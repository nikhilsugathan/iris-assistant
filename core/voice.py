import subprocess
import os
import time
import threading
import tempfile
import queue
import re
import difflib
import collections
import numpy as np
import speech_recognition as sr
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "hide")
from pygame import mixer
from rich.console import Console
from config import Config
from core import logger as _logger_mod
import contextlib as _contextlib

@_contextlib.contextmanager
def _quiet_stderr():
    """Suppress C-library stderr (ALSA/JACK probe noise) during audio init.

    Redirects file-descriptor 2 to /dev/null so C-library noise from
    PortAudio/ALSA/JACK device enumeration never reaches docker logs.
    Python-level logging still works because the logging module writes
    through its own file objects, not fd 2 directly.
    """
    devnull_fd = os.open(os.devnull, os.O_WRONLY)
    saved_fd = os.dup(2)
    os.dup2(devnull_fd, 2)
    try:
        yield
    finally:
        os.dup2(saved_fd, 2)
        os.close(saved_fd)
        os.close(devnull_fd)

get_logger = _logger_mod.get_logger
get_trace_logger = getattr(_logger_mod, "get_trace_logger", _logger_mod.get_logger)

logger = get_logger("Voice")
trace_logger = get_trace_logger("Voice")
console = Console()

class _EdgeTTSEventLoop:
    """
    Persistent asyncio event loop for Edge-TTS.
    Creating a new loop per call on Windows adds ~300-500ms overhead (TLS
    handshake, ProactorEventLoop setup). One long-lived loop eliminates that.
    """
    def __init__(self):
        import asyncio, sys
        # ProactorEventLoop (Windows IOCP) is ~2x faster for network I/O
        # than SelectorEventLoop.  On other platforms use default.
        if sys.platform == "win32":
            self._loop = asyncio.ProactorEventLoop()
        else:
            self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever, daemon=True, name="edge-tts-loop"
        )
        self._thread.start()

    def run(self, coro, timeout: float = 30.0):
        import concurrent.futures
        fut = concurrent.futures.Future()

        async def _wrap():
            try:
                fut.set_result(await coro)
            except Exception as exc:
                if not fut.done():
                    fut.set_exception(exc)

        self._loop.call_soon_threadsafe(
            lambda: self._loop.create_task(_wrap())
        )
        return fut.result(timeout=timeout)


class Voice:
    _QUEUE_SENTINEL = object()
    _CHUNK_MIN_CHARS = 120

    def __init__(self, text_mode=False):
        self.text_mode = text_mode
        self._debug_transcripts = os.getenv("VOICE_DEBUG_TRANSCRIPTS", "false").lower() == "true"
        self._force_io_disabled = os.getenv("IRIS_DISABLE_VOICE_IO", "false").lower() == "true"
        self.io_disabled = text_mode or self._force_io_disabled
        self.mic_ready = False
        self.recognizer = None
        self.mic = None
        self.mic_device_index = None
        self.mic_name = None
        # Active TTS voice — swapped on persona change (Iris ↔ Aletheia).
        self._active_voice_name: str = getattr(Config, "IRIS_VOICE_NAME", Config.VOICE_NAME)
        self._active_voice_rate: str = getattr(Config, "IRIS_VOICE_RATE", Config.VOICE_RATE)
        self._piper_engine = None
        self._piper_disabled = False
        self._piper_lock = threading.Lock()
        self._resolved_piper_model_path = None
        self._piper_ready_announced = False
        self._whisper_model = None
        self._whisper_disabled = False
        self._whisper_lock = threading.Lock()
        self._whisper_loading = False
        self._whisper_ready_announced = False
        self._whisper_download_announced = False
        self._whisper_runtime_device = None
        self._whisper_runtime_compute_type = None
        self._whisper_inference_failures = 0
        self._recent_spoken: collections.deque = collections.deque(maxlen=10)
        self._recent_spoken_lock = threading.Lock()
        self._session_started_at = time.monotonic()
        self._stt_counts = collections.Counter()

        self._tts_lock = threading.Lock()
        self._active_stop_event = None
        self._utterance_queue = queue.Queue()
        self._speech_active = False
        self._speech_state_lock = threading.Lock()
        # Lookahead prefetch: while chunk N plays, generate chunk N+1 in background.
        # Maps clean_text → temp_file_path (str) when ready, or None while in-flight.
        self._tts_prefetch_cache: dict = {}
        self._tts_prefetch_lock = threading.Lock()
        # Static audio cache: pre-generated files for known short phrases (wake
        # acks, farewells, etc.).  These are reused every call — never deleted
        # mid-session.  Eliminates TTS network round-trip for common phrases.
        self._static_audio_cache: dict = {}
        self._static_audio_cache_lock = threading.Lock()
        # Persistent asyncio event loop for Edge-TTS (lazy-initialised on first use).
        self._edge_tts_loop: "_EdgeTTSEventLoop | None" = None
        self._edge_tts_loop_lock = threading.Lock()
        # C-05: flag that lets the speech worker exit its loop cleanly on shutdown.
        # Without this, the blocking queue.get() holds the daemon thread open until
        # Windows force-kills it, which can leave the audio session in a bad state.
        self._speech_running = True
        self._speech_worker = threading.Thread(target=self._run_speech_worker, daemon=True)
        self._speech_worker.start()

        # Mute flag — when True, speak() discards all TTS silently.
        # Set via mute() / unmute().  Voice still listens while muted.
        self._muted: bool = False

        # Generation cancel event — set by barge-in monitor when the user
        # speaks while IRIS is thinking (LLM streaming, before TTS starts).
        # _stream_reasoning_response checks this inside the chunk loop.
        self._generation_cancel: threading.Event = threading.Event()

        # Persistent mic stream — opened once and kept alive so Windows never
        # drops the mic indicator between listen() calls.
        self._persistent_source = None
        self._mic_open = False
        # Persistent raw-audio stream for barge-in RMS monitoring.
        # Opened once alongside the SR mic stream so the Windows taskbar
        # mic indicator stays lit permanently — no create/destroy cycle per
        # generation means no icon flapping.
        self._rms_pa = None
        self._rms_stream = None

        if not self._force_io_disabled and (not self.text_mode or getattr(Config, "SPEAK_IN_TEXT_MODE", False)):
            try:
                with _quiet_stderr():
                    mixer.init(44100, -16, 2, 4096)
            except Exception as e:
                logger.error(f"Audio Warning: Could not initialize pygame mixer - {e}")

        if not self._force_io_disabled and not self.text_mode:
            self._init_mic()
            # STT is now served by the Groq Whisper API — no local model warmup
            # or VRAM allocation at startup.  Key is validated per-transcription.
            _groq_key   = getattr(Config, "GROQ_API_KEY", "")
            _groq_model = getattr(Config, "GROQ_STT_MODEL", "whisper-large-v3-turbo")
            if _groq_key:
                console.print(
                    f"[bold green][Voice] STT Backend: Groq ({_groq_model})[/bold green]"
                )
            else:
                console.print(
                    "[yellow][Voice] GROQ_API_KEY absent — STT will fall back to Google[/yellow]"
                )
            if getattr(Config, "TTS_ENGINE", "auto") != "edge" and getattr(Config, "PIPER_TTS_WARMUP", False):
                threading.Thread(target=self._warm_local_tts, daemon=True).start()

    def _preview_text(self, text: str | None, limit: int = 120) -> str:
        cleaned = re.sub(r"\s+", " ", (text or "")).strip()
        if len(cleaned) <= limit:
            return cleaned
        return cleaned[: limit - 3] + "..."

    def _debug_trace(self, event: str, **fields) -> None:
        payload = []
        for key, value in fields.items():
            if isinstance(value, str):
                payload.append(f"{key}={self._preview_text(value)!r}")
            else:
                payload.append(f"{key}={value!r}")
        trace_logger.info("[VOICE_TRACE] %s %s", event, " ".join(payload))
        if not self._debug_transcripts:
            return
        logger.debug("[VOICE_DEBUG] %s %s", event, " ".join(payload))

    def _trace_exception(self, event: str, exc: Exception, **fields) -> None:
        fields = dict(fields)
        fields["error"] = str(exc)
        fields["error_type"] = exc.__class__.__name__
        self._debug_trace(event, **fields)

    @staticmethod
    def _clamp_threshold(value: float, configured_gate: float, floor_ratio: float = 0.6, ceiling_ratio: float = 1.35) -> float:
        floor = max(120.0, float(configured_gate) * floor_ratio)
        # Min-gap reduced from 25 → 10: the old 25-RMS guard was overriding
        # the command listener's intended ceiling_ratio=1.05 (315) and forcing
        # the ceiling to 325, so commands always ran 8% above the configured
        # gate after a wake-word listen.  A 10-RMS minimum gap is sufficient
        # to keep floor < ceiling while letting ceiling_ratio win.
        ceiling = max(floor + 10.0, float(configured_gate) * ceiling_ratio)
        return min(max(float(value), floor), ceiling)

    def stt_status(self) -> str:
        if getattr(Config, "GROQ_API_KEY", ""):
            model = getattr(Config, "GROQ_STT_MODEL", "whisper-large-v3-turbo")
            return f"STT Backend: Groq ({model})"
        return "Google fallback"

    def tts_status(self) -> str:
        preferred = getattr(Config, "TTS_ENGINE", "auto")
        if preferred == "edge":
            return "Edge-TTS"
        if preferred == "piper":
            return "Piper"
        if self._piper_disabled:
            return "Edge-TTS (fallback)"
        return "Piper/Edge auto"

    def runtime_summary(self) -> dict:
        return {
            "uptime_s": round(time.monotonic() - self._session_started_at, 2),
            "mic_ready": self.mic_ready,
            "mic_name": self.mic_name or "",
            "wake_threshold": getattr(Config, "WAKE_RMS_THRESHOLD", None),
            "command_threshold": getattr(Config, "COMMAND_RMS_THRESHOLD", None),
            "stt_status": self.stt_status(),
            "tts_status": self.tts_status(),
            "stt_counts": dict(self._stt_counts),
            "whisper_failures": self._whisper_inference_failures,
            "piper_disabled": self._piper_disabled,
        }

    @_quiet_stderr()
    def _init_mic(self):
        """Probes hardware for the Aletheia spec."""
        try:
            self.recognizer = sr.Recognizer()
            self.recognizer.pause_threshold = 0.45
            self.recognizer.phrase_threshold = 0.2
            self.recognizer.non_speaking_duration = 0.25
            # Dynamic energy: auto-adapts to ambient noise level like a consumer
            # voice assistant. The ratio (1.8) means speech must be 1.8× louder
            # than the measured ambient floor before it's treated as speech.
            # Damping of 0.08 means the threshold tracks noise changes quickly.
            self.recognizer.dynamic_energy_threshold = False  # HF-2: prevent ambient drift that erodes energy_threshold below noise floor
            # S-01: dynamic_energy_adjustment_damping and dynamic_energy_ratio are
            # dead parameters now that dynamic_energy_threshold is permanently False.
            # They were only used by the library's auto-calibration loop and by
            # adjust_for_ambient_noise().  Both are disabled — do not restore them.
            self.recognizer.energy_threshold = Config.WAKE_RMS_THRESHOLD
            default_index, default_name = self._get_default_input_device()
            configured_index = getattr(Config, "MIC_DEVICE_INDEX", None)
            preferred_name = getattr(Config, "PREFERRED_MIC_NAME", "").strip()
            preferred_index = self._find_mic_index_by_name_hint(preferred_name) if preferred_name else None
            device_index = (
                configured_index
                if configured_index is not None
                else preferred_index
                if preferred_index is not None
                else default_index
            )
            self.mic = sr.Microphone(device_index=device_index)
            self.mic_device_index = device_index
            self.mic_name = self._lookup_mic_name(device_index) or default_name or "Default input"
            # R-01: adjust_for_ambient_noise() removed.  With dynamic_energy_threshold
            # permanently False (HF-2), this call ran the same exponential-damping
            # formula as the disabled auto-calibration — contradicting the very fix it
            # followed.  Energy threshold is now anchored exclusively via _clamp_threshold
            # inside each listen method, which enforces mode-specific bounds on every
            # call.  No one-time startup calibration is needed or safe here.
            self.mic_ready = True
            # Keep the stream open so Windows never drops the mic indicator
            # between listen() calls — fixes the "IRIS goes deaf" symptom.
            try:
                self.mic.__enter__()
                self._mic_open = True
            except Exception as _me:
                logger.warning(f"[Voice] Persistent mic open failed: {_me}")
                self._mic_open = False
            # Open the persistent RMS monitor stream immediately after the SR
            # stream is confirmed live.  Both streams share the same device under
            # WASAPI shared mode.  Doing this here (not in __init__) ensures
            # mic_device_index is resolved before the RMS stream is opened.
            self._open_rms_stream()
            self._debug_trace(
                "mic_init",
                configured_gate=Config.WAKE_RMS_THRESHOLD,
                actual_threshold=round(float(self.recognizer.energy_threshold), 2),
                mic_device_index=self.mic_device_index,
                mic_name=self.mic_name or "",
                preferred_mic_name=preferred_name,
            )
        except Exception as e:
            logger.error(f"Microphone init failed: {e}")
            self.mic_ready = False
            self.mic_device_index = None
            self.mic_name = None

    def _open_rms_stream(self):
        """Open a persistent PyAudio input stream for barge-in RMS monitoring.

        Kept separate from the SR Microphone stream so two consumers can read
        the same device simultaneously under Windows WASAPI shared mode.
        Opened once at startup — never destroyed mid-session — so the Windows
        taskbar mic indicator stays lit permanently instead of flapping on
        every generation cycle.
        """
        try:
            pyaudio_cls = sr.Microphone.get_pyaudio().PyAudio
            self._rms_pa = pyaudio_cls()
            self._rms_stream = self._rms_pa.open(
                format=self._rms_pa.get_format_from_width(2),  # int16
                channels=1,
                rate=16000,
                input=True,
                input_device_index=self.mic_device_index,
                frames_per_buffer=512,
            )
            logger.debug("[Voice] Persistent RMS monitor stream opened.")
        except Exception as _rms_e:
            logger.warning(
                f"[Voice] Persistent RMS stream failed — barge-in monitor disabled: {_rms_e}"
            )
            self._rms_pa = None
            self._rms_stream = None

    def _get_default_input_device(self):
        try:
            pyaudio_module = sr.Microphone.get_pyaudio()
            audio = pyaudio_module.PyAudio()
            try:
                info = audio.get_default_input_device_info() or {}
            finally:
                audio.terminate()
        except Exception:
            return None, None
        index = info.get("index")
        name = info.get("name")
        try:
            index = int(index) if index is not None else None
        except Exception:
            index = None
        return index, str(name).strip() if name else None

    def _lookup_mic_name(self, device_index):
        if device_index is None:
            return None
        try:
            names = sr.Microphone.list_microphone_names()
            if 0 <= int(device_index) < len(names):
                return str(names[int(device_index)]).strip()
        except Exception:
            return None
        return None

    def _find_mic_index_by_name_hint(self, name_hint: str):
        hint = str(name_hint or "").strip().lower()
        if not hint:
            return None
        try:
            for idx, name in enumerate(sr.Microphone.list_microphone_names()):
                if hint in str(name).lower():
                    return idx
        except Exception:
            return None
        return None

    def _get_mic_source(self):
        """Return the persistent open mic source, reopening the PyAudio stream
        if it has died (e.g. after a system suspend or device unplug).
        Using a persistent stream means Windows never drops the mic indicator
        between listen() calls."""
        if self.mic is None:
            return None
        # Happy path: stream is alive.
        # IMPORTANT: never call __exit__/__enter__ just because is_active() returns
        # False momentarily.  Many USB/Bluetooth devices briefly report inactive
        # between reads.  Reopening the stream on each poll cycle is what causes
        # the Windows taskbar mic icon to flash.  As long as the stream *object*
        # exists (i.e. mic.stream is not None), treat it as open.
        if self._mic_open:
            try:
                stream = getattr(self.mic, "stream", None)
                if stream is not None:
                    # Stream object present → return immediately.
                    # Do NOT test is_active() — that poll triggers reopen churn.
                    return self.mic
            except Exception:
                pass
        # Stream is dead — close cleanly then reopen
        if self._mic_open:
            try:
                self.mic.__exit__(None, None, None)
            except Exception:
                pass
            self._mic_open = False
        try:
            self.mic.__enter__()
            self._mic_open = True
            logger.debug("[Voice] Persistent mic stream reopened.")
            return self.mic
        except Exception as e:
            logger.error(f"[Voice] Failed to get mic source: {e}")
            return None

    def close_mic(self):
        """Gracefully close the persistent mic stream (call on shutdown)."""
        # C-05: signal the speech worker to exit its poll loop.
        self._speech_running = False
        if self._mic_open and self.mic is not None:
            try:
                self.mic.__exit__(None, None, None)
            except Exception:
                pass
            self._mic_open = False
            self._persistent_source = None
        # Tear down the persistent RMS monitor stream.
        if self._rms_stream is not None:
            try:
                self._rms_stream.stop_stream()
                self._rms_stream.close()
            except Exception:
                pass
            self._rms_stream = None
        if self._rms_pa is not None:
            try:
                self._rms_pa.terminate()
            except Exception:
                pass
            self._rms_pa = None

    def is_speaking(self):
        with self._speech_state_lock:
            queue_pending = not self._utterance_queue.empty()
            speech_active = self._speech_active
        try:
            mixer_busy = mixer.get_init() and mixer.music.get_busy()
        except Exception:
            mixer_busy = False
        return speech_active or queue_pending or mixer_busy

    def is_audio_playing(self) -> bool:
        """True only while the mixer is actively outputting audio.
        Unlike is_speaking(), this is False during TTS generation gaps and
        after the final audio chunk finishes.  Use this to skip interrupt
        listening on laptop setups where the mic picks up speaker output."""
        try:
            return bool(mixer.get_init() and mixer.music.get_busy())
        except Exception:
            return False

    def stop_speaking(self):
        self._debug_trace(
            "speech_stop_requested",
            queue_pending=not self._utterance_queue.empty(),
            active_stop=bool(self._active_stop_event and not self._active_stop_event.is_set()),
        )
        stop_event = self._active_stop_event
        if stop_event is not None:
            stop_event.set()
        if self._piper_engine is not None:
            try:
                self._piper_engine.stop()
            except Exception:
                pass
        try:
            if mixer.get_init():
                mixer.music.stop()
                mixer.music.unload()
        except Exception as _mxe:
            logger.debug("[Voice] Mixer stop/unload skipped: %s", _mxe)
        while True:
            try:
                self._utterance_queue.get_nowait()
                self._utterance_queue.task_done()
            except queue.Empty:
                break
        # Discard any pre-generated audio files from the lookahead cache.
        with self._tts_prefetch_lock:
            for _pf_path in self._tts_prefetch_cache.values():
                if isinstance(_pf_path, str):
                    try:
                        os.remove(_pf_path)
                    except Exception as _rme:
                        logger.debug("[Voice] Prefetch cleanup skipped %s: %s", _pf_path, _rme)
            self._tts_prefetch_cache.clear()

    # ── Mute ─────────────────────────────────────────────────────────────────

    def mute(self) -> None:
        """Silence Iris immediately and suppress all TTS until unmuted.
        She still listens and processes commands — she just won't speak."""
        self._muted = True
        self.stop_speaking()
        self._debug_trace("muted")

    def unmute(self) -> None:
        """Re-enable Iris's voice after a mute."""
        self._muted = False
        self._debug_trace("unmuted")

    def is_muted(self) -> bool:
        return getattr(self, "_muted", False)

    def is_static_cached(self, text: str) -> bool:
        """Return True if *text* has a pre-generated static audio file ready on
        disk.  Used to gate thinking-cue playback so the speech worker is never
        blocked waiting for a live Edge-TTS network call when the prewarm missed."""
        clean_text = self._clean_for_speech(text)
        if not clean_text:
            return False
        with self._static_audio_cache_lock:
            cached_path = self._static_audio_cache.get(clean_text)
        return (
            cached_path is not None
            and os.path.exists(cached_path)
            and os.path.getsize(cached_path) > 0
        )

    # ── Generation cancel (barge-in during thinking) ─────────────────────────

    def cancel_generation(self) -> None:
        """Signal ongoing LLM generation to abort and stop any queued speech.
        Called when the user speaks while IRIS is still thinking."""
        self._generation_cancel.set()
        self.stop_speaking()
        self._debug_trace("generation_cancelled")

    def reset_generation_cancel(self) -> None:
        """Clear the generation cancel flag before each new response cycle."""
        self._generation_cancel.clear()

    def start_barge_in_monitor(self, on_barge_in: callable, warmup_sec: float = 0.45) -> threading.Event:
        """Monitor mic RMS via the persistent input stream (_rms_stream) and
        call on_barge_in() if the user speaks while the LLM is generating.
        Returns a stop_event — set it to terminate the monitor.

        Reuses the persistent stream opened in _open_rms_stream() so no
        PyAudio instance is created or destroyed per generation.  This
        eliminates the Windows taskbar mic-icon flapping caused by the
        previous create/destroy cycle on every LLM call.

        `warmup_sec`: RMS checks are suppressed for this many seconds after
        the monitor starts.  Absorbs the tail of the user's own previous
        speech that is still decaying in the mic buffer.
        """
        stop = threading.Event()
        rms_stream = self._rms_stream  # snapshot — None if _open_rms_stream failed
        if rms_stream is None:
            # RMS stream unavailable (hardware error at startup) — return an
            # inert event so the caller's finally: _barge_in_stop.set() is safe.
            return stop

        # Barge-in threshold: BARGE_IN_RMS_THRESHOLD (default 750) comfortably
        # clears mechanical keyboard clicks (~400-600 RMS peak) and fan noise
        # (≈300-450 RMS).  Falls back to max(550, WAKE*1.1) when unset so
        # existing deployments that haven't added the env key are unaffected.
        threshold = float(
            getattr(Config, "BARGE_IN_RMS_THRESHOLD", None)
            or max(550.0, float(getattr(Config, "WAKE_RMS_THRESHOLD", 400)) * 1.1)
        )

        # Debounce: require N consecutive frames above threshold before firing.
        # A mechanical keyclick is a single-frame transient (~32 ms at 512
        # samples / 16 kHz).  Sustained speech stays above threshold for many
        # consecutive frames.  N=3 (~96 ms) blocks clicks while passing voice.
        _CONSECUTIVE_REQUIRED = 3

        def _monitor():
            # Warmup: drain frames for `warmup_sec` without checking RMS.
            _warmup_until = time.monotonic() + warmup_sec
            _consecutive = 0  # frames consecutively above threshold
            while not stop.is_set():
                try:
                    data = rms_stream.read(512, exception_on_overflow=False)
                except Exception:
                    break  # stream error — exit silently; monitor disabled
                if time.monotonic() < _warmup_until:
                    _consecutive = 0  # reset during warmup
                    continue
                arr = np.frombuffer(data, dtype=np.int16).astype(np.float32)
                rms = float(np.sqrt(np.mean(arr ** 2))) if len(arr) > 0 else 0.0
                if rms > threshold:
                    _consecutive += 1
                    if _consecutive >= _CONSECUTIVE_REQUIRED:
                        self._debug_trace(
                            "barge_in_rms_trigger",
                            rms=round(rms, 1),
                            gate=round(threshold, 1),
                            consecutive=_consecutive,
                        )
                        stop.set()
                        try:
                            on_barge_in()
                        except Exception as _cb_err:
                            logger.debug(f"[Voice] barge-in callback error: {_cb_err}")
                        break
                else:
                    _consecutive = 0  # transient — reset counter
            # Stream intentionally NOT closed here — it is persistent.

        t = threading.Thread(target=_monitor, daemon=True, name="barge-in-monitor")
        t.start()
        return stop

    # ─────────────────────────────────────────────────────────────────────────

    def speak(self, text, interrupt=True, on_play_start=None):
        if not text: return
        if self._force_io_disabled: return
        if self.text_mode and not getattr(Config, "SPEAK_IN_TEXT_MODE", False): return
        if getattr(self, "_muted", False): return  # silenced — discard TTS

        with self._tts_lock:
            if interrupt or self._active_stop_event is None or self._active_stop_event.is_set():
                self.stop_speaking()
                self._active_stop_event = threading.Event()
            self._debug_trace(
                "speech_enqueue",
                interrupt=interrupt,
                chars=len(text),
                text=text,
                queue_size=self._utterance_queue.qsize(),
            )
            self._utterance_queue.put((text, self._active_stop_event, on_play_start))
            # ── Early prefetch: start TTS generation in the background the
            # instant speak() is called — for BOTH the first sentence and
            # follow-on sentences.  Previously this only fired while speech was
            # already active (self._speech_active), which meant the first sentence
            # waited for the speech worker to call _speak_edge_tts inline (~7-8 s
            # round-trip from India).  By firing here unconditionally we overlap
            # TTS network I/O with whatever the caller does next (print to console,
            # dispatch next LLM chunk, etc.), cutting perceived first-word latency.
            if (
                getattr(Config, "TTS_ENGINE", "auto") == "edge"
                and self._active_stop_event is not None
                and not self._active_stop_event.is_set()
            ):
                _prefetch_text = self._clean_for_speech(text)
                if _prefetch_text:
                    with self._tts_prefetch_lock:
                        if _prefetch_text not in self._tts_prefetch_cache:
                            self._tts_prefetch_cache[_prefetch_text] = None
                            _stop_ev = self._active_stop_event

                            def _early_prefetch(key=_prefetch_text, stop=_stop_ev):
                                if self._force_io_disabled:
                                    return
                                try:
                                    import tempfile
                                    with tempfile.NamedTemporaryFile(
                                        suffix=".mp3", delete=False,
                                        dir=tempfile.gettempdir()
                                    ) as tf:
                                        pf = tf.name
                                    ok = self._run_edge_tts_async(
                                        key,
                                        self._active_voice_name,
                                        self._active_voice_rate,
                                        pf,
                                    )
                                    if ok and not stop.is_set():
                                        with self._tts_prefetch_lock:
                                            self._tts_prefetch_cache[key] = pf
                                    else:
                                        with self._tts_prefetch_lock:
                                            self._tts_prefetch_cache.pop(key, None)
                                        try:
                                            os.remove(pf)
                                        except Exception as _rme:
                                            logger.debug("[Voice] Inline prefetch cleanup skipped %s: %s", pf, _rme)
                                except Exception:
                                    with self._tts_prefetch_lock:
                                        self._tts_prefetch_cache.pop(key, None)

                            threading.Thread(
                                target=_early_prefetch,
                                daemon=True,
                                name="tts-early-prefetch",
                            ).start()

    def start_prefetch(self, text: str) -> None:
        """Fire an Edge-TTS prefetch for *text* without enqueueing it for playback.

        Call this as early as possible — the moment a sentence is fully assembled
        from the LLM stream — so the network round-trip to Edge-TTS overlaps with
        the remaining LLM generation time.  voice.speak() will later detect that
        the cache entry is already in-flight and will not start a duplicate request.

        No-ops when TTS engine is not Edge-TTS, when muted, or when text is empty.
        """
        if not text:
            return
        if getattr(Config, "TTS_ENGINE", "auto") != "edge":
            return
        if getattr(self, "_muted", False):
            return
        if self._force_io_disabled:
            return
        clean_text = self._clean_for_speech(text)
        if not clean_text:
            return
        with self._tts_prefetch_lock:
            if clean_text in self._tts_prefetch_cache:
                return   # already in-flight or ready
            self._tts_prefetch_cache[clean_text] = None  # mark in-flight

        # Capture active voice settings now (they could change later).
        _voice_name = self._active_voice_name
        _voice_rate = self._active_voice_rate

        def _do_prefetch(key=clean_text):
            pf = None
            try:
                import tempfile
                with tempfile.NamedTemporaryFile(
                    suffix=".mp3", delete=False, dir=tempfile.gettempdir()
                ) as tf:
                    pf = tf.name
                ok = self._run_edge_tts_async(key, _voice_name, _voice_rate, pf)
                if ok:
                    with self._tts_prefetch_lock:
                        self._tts_prefetch_cache[key] = pf
                else:
                    with self._tts_prefetch_lock:
                        self._tts_prefetch_cache.pop(key, None)
                    try:
                        os.remove(pf)
                    except Exception as _rme:
                        logger.debug("[Voice] Pre-prefetch cleanup skipped %s: %s", pf, _rme)
            except Exception as _exc:
                with self._tts_prefetch_lock:
                    self._tts_prefetch_cache.pop(key, None)
                if pf is not None:
                    try:
                        os.remove(pf)
                    except Exception as _rme:
                        logger.debug("[Voice] Exception-path prefetch cleanup skipped %s: %s", pf, _rme)
                logger.warning("[Voice] _do_prefetch failed for key=%r: %s", key, _exc)

        threading.Thread(target=_do_prefetch, daemon=True, name="tts-pre-prefetch").start()

    def _run_speech_worker(self):
        while self._speech_running:
            try:
                _item = self._utterance_queue.get(timeout=1.0)
            except queue.Empty:
                # No item yet — loop back and re-check _speech_running so the
                # thread can exit cleanly when close_mic() signals shutdown.
                continue
            text = _item[0]
            stop_event = _item[1]
            on_play_start = _item[2] if len(_item) > 2 else None
            started_at = time.monotonic()
            try:
                if stop_event.is_set():
                    self._debug_trace("speech_skip_cancelled", chars=len(text), text=text)
                    continue

                # Edge-TTS coalescing: only merge tiny follow-on fragments,
                # and ONLY when the current text is NOT already in the prefetch
                # cache.  If a prefetch is in-flight or ready, merging would
                # create a new un-cached string and throw away the pre-warmed
                # audio, forcing a fresh 4-second network round-trip.
                if getattr(Config, "TTS_ENGINE", "auto") == "edge" and not stop_event.is_set():
                    _clean_check = self._clean_for_speech(text)
                    with self._tts_prefetch_lock:
                        _already_prefetched = _clean_check in self._tts_prefetch_cache
                    if not _already_prefetched:
                        # No prefetch is ready — merging small fragments reduces
                        # total network calls, so coalesce conservatively.
                        merge_limit = 120 if len(text) <= 50 else len(text)
                        total_chars = len(text)
                        extra_texts = []
                        while True:
                            try:
                                _n_item = self._utterance_queue.get_nowait()
                                n_text, n_stop = _n_item[0], _n_item[1]
                                if n_stop is stop_event:
                                    projected = total_chars + 1 + len(n_text)
                                    if projected <= merge_limit:
                                        extra_texts.append(n_text)
                                        total_chars = projected
                                    else:
                                        self._utterance_queue.put(_n_item)
                                        self._utterance_queue.task_done()
                                        break
                                else:
                                    # Different batch — re-queue and stop draining
                                    self._utterance_queue.put(_n_item)
                                    self._utterance_queue.task_done()
                                    break
                            except queue.Empty:
                                break
                        if extra_texts:
                            text = text + " " + " ".join(extra_texts)
                            for _ in extra_texts:
                                self._utterance_queue.task_done()

                # Mark speech as active BEFORE TTS generation starts so that
                # is_speaking() returns True during the network round-trip.
                # Previously this was only set inside _play_edge_tts_file (after
                # playback began), leaving an 8-second window where the mic
                # opened and transcribed Iris's own TTS as a command.
                self._set_speech_active(True)
                self._debug_trace("speech_start", chars=len(text), text=text)
                self._speak_utterance(text, stop_event, on_play_start=on_play_start)
            except Exception as e:
                logger.error(f"Speech worker failed: {e}")
                self._trace_exception("speech_error", e, chars=len(text), text=text)
            finally:
                # Only drop speech_active to False when there is no immediately
                # following chunk that shares the same stop_event (i.e. same
                # utterance batch).  Dropping between back-to-back chunks opens
                # a ~50 ms window where the barge-in monitor sees silence and
                # reopens the mic, which causes the voice to "break up".
                _stay_active = False
                try:
                    with self._utterance_queue.mutex:
                        _q = list(self._utterance_queue.queue)
                    if _q and _q[0][1] is stop_event and not stop_event.is_set():
                        _stay_active = True
                except Exception:
                    pass
                if not _stay_active:
                    self._set_speech_active(False)
                self._debug_trace(
                    "speech_end",
                    chars=len(text),
                    elapsed_ms=round((time.monotonic() - started_at) * 1000, 1),
                    stopped=stop_event.is_set(),
                )
                self._utterance_queue.task_done()

    def _set_speech_active(self, active):
        with self._speech_state_lock:
            self._speech_active = active

    def _speak_utterance(self, text, stop_event, on_play_start=None):
        clean_text = self._clean_for_speech(text)
        if not clean_text or stop_event.is_set():
            self._debug_trace("tts_skip", reason="empty_or_stopped", chars=len(text or ""), text=text or "")
            return
        preferred_tts = getattr(Config, "TTS_ENGINE", "auto")
        engine = None if preferred_tts == "edge" else self._get_piper_engine()
        if engine is not None:
            try:
                chunks = self._split_speech_chunks(clean_text)
                self._debug_trace(
                    "tts_dispatch",
                    engine="piper",
                    chunk_count=len(chunks),
                    chars=len(clean_text),
                    text=clean_text,
                )
                # Fire the text-sync callback as soon as audio begins.
                if on_play_start:
                    on_play_start()
                # _speech_active is already True (set by _run_speech_worker).
                if len(chunks) == 1:
                    engine.speak(chunks[0])
                else:
                    self._stream_piper_chunks(engine, chunks, stop_event)
                return
            except Exception as e:
                self._piper_disabled = True
                self._piper_engine = None
                logger.error(f"Piper TTS Engine Failed: {e}")
                logger.warning("Falling back to Edge-TTS...")
                self._trace_exception("tts_piper_error", e, chars=len(clean_text), text=clean_text)

        if not stop_event.is_set():
            self._debug_trace(
                "tts_dispatch",
                engine="edge_tts",
                chunk_count=1,
                chars=len(clean_text),
                text=clean_text,
            )
            # ── Static cache: pre-generated at boot for known phrases ──────────
            # Zero network delay — just load the file and play.
            with self._static_audio_cache_lock:
                _static_path = self._static_audio_cache.get(clean_text)
            if _static_path and os.path.exists(_static_path) and os.path.getsize(_static_path) > 0:
                self._debug_trace("tts_static_hit", chars=len(clean_text), text=clean_text)
                self._play_edge_tts_file(_static_path, stop_event, trigger_prefetch=False, on_play_start=on_play_start)
                return
            # ── Lookahead / early prefetch: generated by speak() in background ─
            # speak() now fires prefetch unconditionally (not just when already
            # playing).  By the time the worker reaches here the audio is often
            # already fully generated — saves the entire TTS round-trip latency.
            # We wait up to TTS_NETWORK_TIMEOUT_SEC + 50 % to give the background
            # thread maximum time before falling through to inline generation.
            _tts_timeout = float(getattr(Config, "TTS_NETWORK_TIMEOUT_SEC", 8))
            _max_wait = _tts_timeout * 1.5
            _prefetched_file = None
            with self._tts_prefetch_lock:
                _cached = self._tts_prefetch_cache.get(clean_text)
            if _cached is None and clean_text in self._tts_prefetch_cache:
                # Generation is in-flight; wait patiently for it.
                _waited = 0.0
                while _waited < _max_wait:
                    time.sleep(0.05)
                    _waited += 0.05
                    with self._tts_prefetch_lock:
                        _cached = self._tts_prefetch_cache.get(clean_text)
                    if _cached is not None:
                        break
                    if stop_event.is_set():
                        break
            if isinstance(_cached, str) and os.path.exists(_cached) and os.path.getsize(_cached) > 0:
                with self._tts_prefetch_lock:
                    _prefetched_file = self._tts_prefetch_cache.pop(clean_text, None)
                if _prefetched_file:
                    self._debug_trace("tts_prefetch_hit", chars=len(clean_text), text=clean_text)
                    try:
                        self._play_edge_tts_file(_prefetched_file, stop_event, trigger_prefetch=True, on_play_start=on_play_start)
                    finally:
                        try:
                            os.remove(_prefetched_file)
                        except Exception as _rme:
                            logger.debug("[Voice] Prefetch-hit cleanup skipped %s: %s", _prefetched_file, _rme)
                    return
            else:
                # Remove stale/failed cache entry if present.
                with self._tts_prefetch_lock:
                    self._tts_prefetch_cache.pop(clean_text, None)
            self._speak_edge_tts(clean_text, stop_event, on_play_start=on_play_start)

    def _stream_piper_chunks(self, engine, chunks, stop_event):
        audio_queue = queue.Queue(maxsize=5)
        producer_error = []

        def produce():
            try:
                for chunk in chunks:
                    if stop_event.is_set():
                        return
                    audio_bytes = engine.synthesize(chunk)
                    if stop_event.is_set():
                        return
                    while not stop_event.is_set():
                        try:
                            audio_queue.put(audio_bytes, timeout=0.1)
                            break
                        except queue.Full:
                            continue
            except Exception as e:
                producer_error.append(e)
            finally:
                while True:
                    try:
                        audio_queue.put(self._QUEUE_SENTINEL, timeout=0.1)
                        break
                    except queue.Full:
                        if stop_event.is_set():
                            break

        def consume():
            while True:
                if stop_event.is_set():
                    return
                try:
                    item = audio_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                if item is self._QUEUE_SENTINEL:
                    return
                engine.play_audio(item)

        producer = threading.Thread(target=produce, daemon=True)
        consumer = threading.Thread(target=consume, daemon=True)
        producer.start()
        consumer.start()
        producer.join()
        consumer.join()

        if producer_error:
            raise producer_error[0]

    def _clean_for_speech(self, text):
        cleaned = text or ''
        # ── Stage 1: Fix CP1252 mojibake FIRST (â€™, Ã©, etc.) ──────────────────
        # Same round-trip as Brain._fix_mojibake; kept here so voice.py doesn't
        # need to import brain.py.
        if '\u00e2' in cleaned or '\u00c3' in cleaned:
            try:
                cleaned = cleaned.encode('cp1252').decode('utf-8')
            except (UnicodeDecodeError, UnicodeEncodeError):
                pass
        cleaned = cleaned.replace('\u00c2\u00b0', '\u00b0').replace('Â°', '°')
        # ── Stage 2: Normalize Unicode punctuation → ASCII for TTS ──────────────
        # Edge-TTS sometimes mispronounces curly quotes, em dashes, etc.
        cleaned = (cleaned
            .replace('\u2019', "'").replace('\u2018', "'")    # curly single quotes
            .replace('\u201c', '"').replace('\u201d', '"')    # curly double quotes
            .replace('\u2014', ' - ').replace('\u2013', ' - ')  # em/en dash → spoken pause
            .replace('\u2026', '...')                           # ellipsis
            .replace('\u00e2\u20ac\u2122', "'")                # residual â€™
            .replace('\u00e2\u20ac', ' - ')                    # generic â€ prefix
        )
        # ── Stage 3: Temperature symbols → spoken form ──────────────────────────
        cleaned = re.sub(r'(\d+)\s*°C', r'\1 degrees Celsius', cleaned)
        cleaned = re.sub(r'(\d+)\s*°F', r'\1 degrees Fahrenheit', cleaned)
        cleaned = re.sub(r'(\d+)\s*°K', r'\1 Kelvin', cleaned)
        cleaned = re.sub(r'°', ' degrees', cleaned)
        # ── Stage 4: Strip markdown ──────────────────────────────────────────────
        # 4a: Fenced code blocks (```lang\n...\n``` or ~~~\n...\n~~~).
        # Replace the entire block with a brief spoken note so TTS doesn't
        # read raw Python/JSON/etc. verbatim.  The re.DOTALL flag makes '.'
        # match newlines so multi-line blocks are caught in one pass.
        cleaned = re.sub(
            r'```[\w]*\n.*?```|~~~[\w]*\n.*?~~~',
            ' …code example… ',
            cleaned,
            flags=re.DOTALL,
        )
        # 4b: Dangling opening fence with no closing triple-backtick
        # (model cut off mid-block or context ended early).
        cleaned = re.sub(r'```[\w]*\n.*$', ' …code example… ', cleaned, flags=re.DOTALL)
        # 4c: Inline code spans — strip backticks, keep the token text.
        # e.g. `os.makedirs` → os.makedirs  (readable as a word)
        cleaned = re.sub(r'`([^`\n]+)`', r'\1', cleaned)
        # 4d: Remaining markdown syntax characters
        cleaned = re.sub(r'[*_`#>]+', '', cleaned)
        cleaned = re.sub(r'\[(.*?)\]\((.*?)\)', r'\1', cleaned)
        cleaned = re.sub(r'\s+', ' ', cleaned)
        return cleaned.strip()

    def _split_speech_chunks(self, text):
        if not text:
            return []
        if len(text) < self._CHUNK_MIN_CHARS:
            return [text]

        sentences = re.split(r'(?<=[.!?])\s+', text)
        sentences = [sentence.strip() for sentence in sentences if sentence.strip()]
        if len(sentences) <= 4 and len(text) <= 600:
            return [text]

        chunks = []
        current = []
        current_len = 0
        for sentence in sentences:
            current.append(sentence)
            current_len += len(sentence)
            if len(current) >= 5 or current_len >= 480:
                chunks.append(" ".join(current).strip())
                current = []
                current_len = 0
        if current:
            chunks.append(" ".join(current).strip())
        return chunks or [text]

    def _get_piper_engine(self):
        if getattr(Config, "TTS_ENGINE", "auto") == "edge":
            return None
        if self._piper_disabled:
            return None
        if self._piper_engine is not None:
            return self._piper_engine

        with self._piper_lock:
            if self._piper_engine is not None:
                return self._piper_engine

            piper_model = self._resolve_piper_model_path()
            if not piper_model:
                return None

            try:
                from core.piper_tts import PiperTTSEngine
                self._piper_engine = PiperTTSEngine(
                    model_path=piper_model,
                    piper_exe=getattr(Config, "PIPER_EXE_PATH", "piper"),
                )
                if not self._piper_ready_announced:
                    console.print(f"[bold green][Voice] Local TTS Active ({os.path.basename(piper_model)})[/bold green]")
                    self._piper_ready_announced = True
                return self._piper_engine
            except Exception as e:
                self._piper_disabled = True
                logger.error(f"Piper TTS setup failed: {e}")
                logger.warning("Falling back to Edge-TTS...")
                return None

    def _resolve_piper_model_path(self):
        if self._resolved_piper_model_path is not None:
            return self._resolved_piper_model_path

        configured = getattr(Config, "PIPER_MODEL_PATH", "")
        candidates = []
        if configured:
            candidates.append(configured)

        project_root = os.path.dirname(os.path.dirname(__file__))
        models_dir = os.path.join(project_root, "models")
        if os.path.isdir(models_dir):
            for name in sorted(os.listdir(models_dir)):
                if name.endswith(".onnx"):
                    candidates.append(os.path.join(models_dir, name))

        for candidate in candidates:
            if candidate and os.path.exists(candidate):
                self._resolved_piper_model_path = candidate
                if configured and candidate != configured:
                    logger.warning(f"Configured Piper model missing; using fallback model: {candidate}")
                return self._resolved_piper_model_path

        if configured:
            logger.warning(f"Configured Piper model not found: {configured}")
        self._resolved_piper_model_path = ""
        return None

    def _warm_local_tts(self):
        engine = self._get_piper_engine()
        if engine is None:
            return
        try:
            engine.synthesize("Ready.")
        except Exception as e:
            logger.warning(f"Local TTS warm-up failed: {e}")

    def _normalize_text(self, text: str) -> str:
        text = re.sub(r"[^a-z0-9\s]", " ", (text or "").lower())
        return re.sub(r"\s+", " ", text).strip()

    def _looks_like_wake_transcript(self, text: str) -> bool:
        normalized = self._normalize_text(text)
        if not normalized:
            return False
        tokens = normalized.split()
        if not tokens:
            return False
        wake_words = {w.lower() for w in getattr(Config, "WAKE_WORDS", [])}
        wake_words.add("aletheia")
        # Let short control phrases through the wake filter so the runtime can
        # handle "terminate" or "initiate protocol" without forcing the user to
        # repeat the wake word.
        if any(token in {"terminate", "shutdown", "exit", "quit", "goodbye", "bye"} for token in tokens):
            return True
        if "protocol" in tokens and any(token in {"initiate", "authorize", "activate", "unlock", "open"} for token in tokens):
            return True
        if any(token in wake_words for token in tokens):
            return True
        if any(
            difflib.get_close_matches(wake_word, tokens, n=1, cutoff=0.78)
            for wake_word in wake_words
        ):
            return True
        compact = normalized.replace(" ", "")
        return bool(
            difflib.get_close_matches("iris", [compact], n=1, cutoff=0.72)
            or difflib.get_close_matches("aletheia", [compact], n=1, cutoff=0.6)
        )

    def set_active_voice(self, voice_name: str, voice_rate: str) -> None:
        """Switch the Edge-TTS voice used for all subsequent speech.
        Called when persona changes (Iris ↔ Aletheia).  The static audio cache
        is keyed on text only, so entries pre-generated with the old voice are
        cleared to prevent Aletheia speaking in Iris's voice (or vice versa).
        """
        if voice_name == self._active_voice_name and voice_rate == self._active_voice_rate:
            return
        self._active_voice_name = voice_name
        self._active_voice_rate = voice_rate
        # Flush cached audio — stale entries belong to the previous persona's voice.
        with self._static_audio_cache_lock:
            self._static_audio_cache.clear()
        with self._tts_prefetch_lock:
            for _cached_pf in self._tts_prefetch_cache.values():
                if _cached_pf is not None:
                    try:
                        os.remove(_cached_pf)
                    except Exception as _rme:
                        logger.debug("[Voice] Voice-switch prefetch cleanup skipped %s: %s", _cached_pf, _rme)
            self._tts_prefetch_cache.clear()
        self._debug_trace("voice_switch", voice=voice_name, rate=voice_rate)

    def record_spoken(self, text: str) -> None:
        """Record a phrase IRIS just spoke so it can be suppressed from STT input."""
        normalized = self._normalize_text(text)
        if not normalized:
            return
        with self._recent_spoken_lock:
            self._recent_spoken.append((time.monotonic(), normalized))
        self._debug_trace("speech_recorded", chars=len(normalized), text=normalized)

    def last_spoken_text(self, max_age: float = 5.0) -> str:
        now = time.monotonic()
        with self._recent_spoken_lock:
            recent_spoken = list(self._recent_spoken)
        for spoken_at, spoken in reversed(recent_spoken):
            if now - spoken_at <= max_age:
                return spoken
        return ""

    # Regex for known Whisper hallucination patterns on synthetic TTS audio.
    # When Whisper processes speaker-bleed from Edge-TTS it hallucinates URN/XML
    # namespace strings and outputs musical note characters for non-speech audio.
    # These are never valid voice commands and must be rejected before any other check.
    _WHISPER_HALLUCINATION_RE = re.compile(
        # Bare "urn" — the root artefact, sometimes transcribed alone
        r'^\s*urn\s*$'
        # Colon-prefix variants:  urn:  urn:com  urn:schemas
        r'|(?:urn:[a-z]|urn:com\b|urn:schemas'
        # Dot-prefix variants (Whisper renders same hallucination with dots):
        # urn.com  urn.schemas  urn.schemas-microsoft-com.h
        r'|urn\.[a-z]'
        # Space-separated variant: "urn com"
        r'|\burn\s+com\b'
        # XML namespace remnants
        r'|schemas[-.]microsoft'
        # Music / non-speech audio artefacts
        r'|[𝅘𝅥♪🎵♫♬])',
        re.UNICODE | re.IGNORECASE,
    )

    # Whisper frequently hallucinates these YouTube/podcast closing phrases when it
    # transcribes TTS speaker-bleed during the dead-zone window.  They are never
    # valid voice commands and should be silently dropped.
    _TTS_ECHO_PHRASES_RE = re.compile(
        r'thank you (?:so much )?for (?:having me|watching|listening|joining)'
        r'|thanks for watching'
        r'|please (?:like and )?subscribe'
        r'|like and subscribe'
        r'|don\'?t forget to subscribe'
        r'|see you (?:in the next|next time)'
        r'|i\'?ll see you (?:in the next|next time)'
        r'|click (?:the )?(?:like|subscribe) button'
        r'|subtitles? by\b'
        r'|transcribed? by\b'
        r'|this (?:video|episode) (?:was )?brought to you by',
        re.IGNORECASE,
    )

    def should_ignore_transcript(self, transcript: str) -> bool:
        # Block Whisper artefacts on raw transcript before any normalisation
        # (normalisation strips the special characters that identify music notes).
        if transcript and self._WHISPER_HALLUCINATION_RE.search(transcript):
            self._debug_trace("transcript_ignored", reason="whisper_hallucination", transcript=transcript)
            return True

        # Reject transcripts that end with a hyphen — Whisper uses trailing "-"
        # to indicate it captured audio that was cut off mid-word (e.g. the user
        # was still speaking when phrase_time_limit fired).  "Alithya Exe-" would
        # otherwise strip the wake word and dispatch the fragment "Exe" to the LLM.
        if transcript and transcript.rstrip().endswith('-'):
            self._debug_trace("transcript_ignored", reason="truncated_speech", transcript=transcript)
            return True

        if transcript and self._TTS_ECHO_PHRASES_RE.search(transcript):
            self._debug_trace("transcript_ignored", reason="tts_echo_phrase", transcript=transcript)
            return True

        normalized = self._normalize_text(transcript)
        if not normalized:
            self._debug_trace("transcript_ignored", reason="empty", transcript=transcript or "")
            return True

        tokens = normalized.split()
        if not tokens:
            self._debug_trace("transcript_ignored", reason="no_tokens", transcript=transcript or "")
            return True
        if len(tokens) == 1 and (len(tokens[0]) <= 2 or tokens[0] in {"uh", "um", "hmm"}):
            self._debug_trace("transcript_ignored", reason="filler", transcript=normalized)
            return True

        # Reject transcripts made entirely of single-character tokens:
        # "a a a a", "b b b", "i i i" — Whisper noise on garbled/quiet audio.
        # Real speech always has at least one word of ≥2 characters.
        if all(len(t) == 1 for t in tokens):
            self._debug_trace("transcript_ignored", reason="single_chars", transcript=normalized)
            return True

        now = time.monotonic()
        with self._recent_spoken_lock:
            recent_spoken = list(self._recent_spoken)

        for spoken_at, spoken in recent_spoken:
            if now - spoken_at > 12.0:
                continue
            if normalized == spoken:
                self._debug_trace("transcript_ignored", reason="exact_echo", transcript=normalized, spoken=spoken)
                return True
            if len(normalized) >= 18 and normalized in spoken:
                self._debug_trace("transcript_ignored", reason="transcript_in_spoken", transcript=normalized, spoken=spoken)
                return True
            if len(spoken) >= 18 and spoken in normalized:
                self._debug_trace("transcript_ignored", reason="spoken_in_transcript", transcript=normalized, spoken=spoken)
                return True

            spoken_tokens = set(spoken.split())
            overlap = sum(1 for token in tokens if token in spoken_tokens)
            if len(tokens) >= 4 and overlap / max(len(tokens), 1) >= 0.75:
                self._debug_trace(
                    "transcript_ignored",
                    reason="token_overlap",
                    transcript=normalized,
                    spoken=spoken,
                    overlap=round(overlap / max(len(tokens), 1), 2),
                )
                return True
        return False

    def listen_for_wake(self, timeout=None, phrase_time_limit=None):
        """Listen for wake word using speech recognition."""
        if not self.mic_ready:
            time.sleep(0.5)
            return None
        started_at = time.monotonic()
        # R-02: save energy_threshold so the finally block can restore it.
        # listen_for_command and listen_for_interrupt already do this; wake was
        # the only mode missing the save/restore, leaving the threshold at whatever
        # the clamp set it to if an exception interrupted the loop.
        original_energy = self.recognizer.energy_threshold
        try:
            # floor_ratio=0.85, ceiling_ratio=1.0: keep threshold in [340, 400].
            # Without floor_ratio the default 0.6 floor allows drift to 240, making
            # the wake loop over-sensitive and triggering on ambient noise.
            # Without ceiling_ratio=1.0 the default 1.35 allows drift to 540 after
            # loud TTS, making the mic functionally deaf to normal speech.
            self.recognizer.dynamic_energy_threshold = False  # HF-2: explicit per-call guard
            self.recognizer.energy_threshold = self._clamp_threshold(
                self.recognizer.energy_threshold,
                Config.WAKE_RMS_THRESHOLD,
                floor_ratio=0.85,
                ceiling_ratio=1.0,
            )
            self._debug_trace(
                "listen_start",
                source="wake",
                configured_gate=Config.WAKE_RMS_THRESHOLD,
                actual_threshold=round(float(self.recognizer.energy_threshold), 2),
                timeout=4 if timeout is None else timeout,
                phrase_time_limit=6 if phrase_time_limit is None else phrase_time_limit,
            )
            source = self._get_mic_source()
            if source is None:
                return None
            audio = self.recognizer.listen(
                source,
                timeout=4 if timeout is None else timeout,
                # 4→6s: allows full sentences like "what did you say iris?"
                # or "iris, what was that?" without cutting off mid-phrase.
                # The recognizer still stops early on natural speech pauses
                # (pause_threshold=0.45), so short wake words aren't delayed.
                phrase_time_limit=6 if phrase_time_limit is None else phrase_time_limit,
            )
            text = self._transcribe_audio(audio, phrase_type="wake", source="wake")
            self._debug_trace(
                "listen_end",
                source="wake",
                elapsed_ms=round((time.monotonic() - started_at) * 1000, 1),
                transcript=text or "",
            )
            return text
        except Exception as e:
            if "Stream closed" in str(e) or "-9988" in str(e):
                self._mic_open = False  # Tells _get_mic_source to rebuild the hardware link
            self._trace_exception("listen_error", e, source="wake")
            return None
        finally:
            # R-02: restore energy_threshold so exceptions mid-loop don't leave
            # the recognizer at a stale clamped value for the next iteration.
            self.recognizer.energy_threshold = self._clamp_threshold(
                original_energy,
                Config.WAKE_RMS_THRESHOLD,
                floor_ratio=0.85,
                ceiling_ratio=1.0,
            )

    def listen_for_command(self, timeout=None, phrase_time_limit=None):
        """Listen for a follow-up command."""
        if not self.mic_ready: return None
        started_at = time.monotonic()
        original_pause = self.recognizer.pause_threshold
        original_phrase = self.recognizer.phrase_threshold
        original_non_speaking = self.recognizer.non_speaking_duration
        try:
            # Pin energy_threshold tightly to the command gate.
            # floor_ratio=1.0: threshold can NEVER go below the configured gate (300).
            # Previous floor_ratio=0.90 allowed drift to 270 (300×0.9), which let
            # single-word Whisper noise like "rifle" trigger as commands.
            # ceiling_ratio=1.05: allows up to 315 so the mic isn't stone-deaf after
            # loud TTS, but recovers quickly back toward 300.
            self.recognizer.dynamic_energy_threshold = False  # HF-2: explicit per-call guard
            self.recognizer.energy_threshold = self._clamp_threshold(
                self.recognizer.energy_threshold,
                Config.COMMAND_RMS_THRESHOLD,
                floor_ratio=1.0,
                ceiling_ratio=1.05,
            )
            # pause_threshold: silence required before Whisper processes audio.
            # 0.72 → 0.55 was too aggressive: natural mid-sentence pauses of ~0.5s
            # were triggering early STT submission, cutting off the user.
            # 0.55 → 0.65 → 0.90: user still being cut off mid-sentence at 0.65
            # (natural breath holds are ~0.7-0.8s for many speakers).
            # 0.90 → 0.80: HF-2 fix — with dynamic_energy disabled the threshold
            # now stays anchored, so 0.80s closes the mic reliably in the desired
            # 0.8–1.0s window without needing the extra 100ms buffer.
            self.recognizer.pause_threshold = 0.80
            self.recognizer.phrase_threshold = 0.25
            self.recognizer.non_speaking_duration = 0.20  # was 0.30; tighter pre-speech buffer
            self._debug_trace(
                "listen_start",
                source="command",
                configured_gate=Config.COMMAND_RMS_THRESHOLD,
                actual_threshold=round(float(self.recognizer.energy_threshold), 2),
                timeout=5 if timeout is None else timeout,
                phrase_time_limit=7.5 if phrase_time_limit is None else phrase_time_limit,
            )
            source = self._get_mic_source()
            if source is None:
                return None
            audio = self.recognizer.listen(
                source,
                timeout=5 if timeout is None else timeout,
                phrase_time_limit=7.5 if phrase_time_limit is None else phrase_time_limit,
            )
            text = self._transcribe_audio(audio, phrase_type="command", source="command")
            self._debug_trace(
                "listen_end",
                source="command",
                elapsed_ms=round((time.monotonic() - started_at) * 1000, 1),
                transcript=text or "",
            )
            return text
        except Exception as e:
            self._trace_exception("listen_error", e, source="command")
            return None
        finally:
            self.recognizer.pause_threshold = original_pause
            self.recognizer.phrase_threshold = original_phrase
            self.recognizer.non_speaking_duration = original_non_speaking
            # Restore threshold after command listen — same floor=1.0 so post-listen
            # drift stays anchored at the configured gate, not below it.
            self.recognizer.energy_threshold = self._clamp_threshold(
                self.recognizer.energy_threshold,
                Config.COMMAND_RMS_THRESHOLD,
                floor_ratio=1.0,
                ceiling_ratio=1.05,
            )

    def listen_for_interrupt(self, timeout=None, phrase_time_limit=None,
                             on_phrase_captured=None):
        """Listen briefly for a barge-in phrase while IRIS is speaking.

        on_phrase_captured: optional zero-argument callable fired the instant
        audio is captured (before Whisper round-trip).  Use this to cut TTS
        playback immediately — speech stops at phrase-capture speed (~100-400 ms)
        rather than after the Whisper transcription returns (~1-2 s).
        """
        if not self.mic_ready:
            return None
        started_at = time.monotonic()
        original_pause = self.recognizer.pause_threshold
        original_phrase = self.recognizer.phrase_threshold
        original_non_speaking = self.recognizer.non_speaking_duration
        try:
            # HF-2 fix: hard-pin interrupt gate to WAKE_RMS_THRESHOLD (400).
            # The old min(400, 550, 180)=180 gate, halved by floor_ratio=0.5,
            # produced an effective floor of ~90 RMS — below ambient noise on
            # most laptops.  Micro-noises at 100–150 RMS triggered barge-in
            # and killed TTS mid-sentence.  Anchoring to 400 keeps the interrupt
            # poller at the same sensitivity as the wake-word loop, which is
            # already tuned to reject ambient noise while catching conversational
            # speech at ~200+ RMS during TTS playback.
            interrupt_gate = Config.WAKE_RMS_THRESHOLD  # hard 400; 180 default was eroding to ~90 effective
            self.recognizer.dynamic_energy_threshold = False  # HF-2: explicit per-call guard
            self.recognizer.energy_threshold = self._clamp_threshold(
                interrupt_gate,
                interrupt_gate,
                floor_ratio=0.5,
                ceiling_ratio=1.0,
            )
            self.recognizer.pause_threshold = 0.08
            self.recognizer.phrase_threshold = 0.08
            self.recognizer.non_speaking_duration = 0.05
            # phrase_time_limit: 0.3 → 1.5s.
            # HF-2 fix: 0.3s was too short — a single syllable like "I-ris"
            # spans ~400ms and was being clipped before Whisper could score it,
            # causing the transcript to be empty or garbled.  1.5s is sufficient
            # to capture one complete word while still polling fast enough for
            # low-latency barge-in detection.
            _eff_timeout = 0.3 if timeout is None else timeout
            _eff_ptl = 1.5 if phrase_time_limit is None else phrase_time_limit
            self._debug_trace(
                "listen_start",
                source="interrupt",
                configured_gate=interrupt_gate,
                actual_threshold=round(float(self.recognizer.energy_threshold), 2),
                timeout=_eff_timeout,
                phrase_time_limit=_eff_ptl,
            )
            source = self._get_mic_source()
            if source is None:
                return None
            audio = self.recognizer.listen(
                source,
                timeout=_eff_timeout,
                phrase_time_limit=_eff_ptl,
            )
            # ── Fast-cut: audio physically captured — stop TTS NOW, before
            # waiting for the Whisper round-trip.  This brings interrupt
            # latency from ~2 s (post-Whisper) down to ~100-400 ms
            # (post-capture).  The echo check below may still discard the
            # transcript as speaker bleed-through, but the audio cut is safe
            # regardless — the user just spoke into the mic.
            if on_phrase_captured is not None:
                try:
                    on_phrase_captured()
                except Exception as _pc_err:
                    logger.debug("[Voice] on_phrase_captured callback error: %s", _pc_err)
            # phrase_type="interrupt" triggers greedy, no-VAD transcription
            text = self._transcribe_audio(audio, phrase_type="interrupt", source="interrupt")
            # Short-clip TTS-echo guard.  The generic should_ignore_transcript
            # check requires ≥4 tokens at 0.75 overlap — calibrated for full
            # command clips.  Interrupt clips are ≤1.5s (1–3 words).
            #
            # Two historical failure modes fixed:
            #
            # 1. Age window too short (was 8 s): Whisper latency (1-3 s) plus
            #    multiple 0.3s timeout polls before any audio is captured means
            #    the echo transcript can arrive 10-15 s after record_spoken.
            #    Extended to 20 s to absorb the full pipeline delay.
            #
            # 2. Single-word false-positive risk: lowering the gate to len>=1
            #    causes common words like "it", "ok", "yes" to be suppressed
            #    after any IRIS response (they appear in almost all sentences).
            #    Fix: single-word transcripts are only echo-checked when IRIS
            #    is still actively speaking (is_speaking() = True — includes
            #    queued chunks and the gap between chunks).  Multi-word clips
            #    are checked regardless (Whisper latency means the audio may
            #    have ended before the transcript arrives).
            if text:
                _norm = self._normalize_text(text)
                _toks = _norm.split() if _norm else []
                # Single-word: gate on is_speaking() to avoid false positives
                # on common words.  Multi-word: always check (age window is
                # the sole staleness gate for multi-word echo).
                _do_echo_check = len(_toks) >= 2 or (len(_toks) == 1 and self.is_speaking())
                if _do_echo_check:
                    _now = time.monotonic()
                    with self._recent_spoken_lock:
                        _recent = list(self._recent_spoken)
                    for _ts, _spoken in _recent:
                        if _now - _ts > 20.0:
                            continue
                        _overlap = (
                            sum(1 for t in _toks if t in set(_spoken.split()))
                            / max(len(_toks), 1)
                        )
                        if _overlap >= 0.60:
                            self._debug_trace(
                                "transcript_ignored",
                                reason="interrupt_echo",
                                transcript=_norm,
                                spoken=_spoken,
                                overlap=round(_overlap, 2),
                            )
                            text = None
                            break
            self._debug_trace(
                "listen_end",
                source="interrupt",
                elapsed_ms=round((time.monotonic() - started_at) * 1000, 1),
                transcript=text or "",
            )
            return text
        except Exception as e:
            self._trace_exception("listen_error", e, source="interrupt")
            return None
        finally:
            self.recognizer.pause_threshold = original_pause
            self.recognizer.phrase_threshold = original_phrase
            self.recognizer.non_speaking_duration = original_non_speaking
            self.recognizer.energy_threshold = self._clamp_threshold(
                self.recognizer.energy_threshold,
                Config.WAKE_RMS_THRESHOLD,
            )

    def _transcribe_audio(self, audio, phrase_type="command", source="command"):
        """Route audio to Groq STT (primary) with Google as automatic fallback.

        Wake-word gate: if phrase_type is "wake" and the transcript doesn't
        match a wake phrase, return None so ambient speech never triggers IRIS.
        """
        started_at = time.monotonic()
        text = self._transcribe_groq(audio, phrase_type=phrase_type)

        # Wake-word gate — suppress non-wake transcripts during wake listening.
        if phrase_type == "wake" and text and not self._looks_like_wake_transcript(text):
            self._debug_trace(
                "transcribe",
                source=source,
                phrase_type=phrase_type,
                engine="groq_nonwake",
                transcript=text,
                latency_ms=round((time.monotonic() - started_at) * 1000, 1),
            )
            self._stt_counts["groq_nonwake"] += 1
            return None

        engine = "groq" if text is not None else "none"
        self._stt_counts[engine] += 1
        self._debug_trace(
            "transcribe",
            source=source,
            phrase_type=phrase_type,
            engine=engine,
            transcript=text or "",
            latency_ms=round((time.monotonic() - started_at) * 1000, 1),
        )
        return text

    def _transcribe_groq(self, audio, phrase_type: str = "command") -> "str | None":
        """Transcribe audio using the Groq Whisper API (zero local VRAM cost).

        Primary STT path.  Falls back to Google STT automatically when:
          - GROQ_API_KEY is absent
          - The ``groq`` package is not installed
          - Any API / network error occurs

        Args:
            audio:        speech_recognition.AudioData captured by listen().
            phrase_type:  "wake", "command", or "interrupt" — for trace logging.

        Returns:
            Stripped transcript string, or None on silence / API failure.
        """
        api_key = getattr(Config, "GROQ_API_KEY", "")
        if not api_key:
            return self._transcribe_google(audio)
        try:
            from groq import Groq  # dynamic import — optional dep, gracefully absent
            wav_bytes = audio.get_wav_data()
            client    = Groq(api_key=api_key)
            model     = getattr(Config, "GROQ_STT_MODEL", "whisper-large-v3-turbo")
            # Groq expects ISO 639-1 (2-char) language code; STT_LANGUAGE is IETF.
            lang      = (getattr(Config, "STT_LANGUAGE", "en-US") or "en")[:2]
            result    = client.audio.transcriptions.create(
                file=("audio.wav", wav_bytes),
                model=model,
                language=lang,
            )
            text = (result.text or "").strip()
            return text or None
        except Exception as exc:
            self._trace_exception("groq_stt_error", exc, phrase_type=phrase_type)
            # Transparent fallback — IRIS stays responsive even during API outages.
            return self._transcribe_google(audio)

    def _transcribe_google(self, audio):
        try:
            return self.recognizer.recognize_google(audio, language=getattr(Config, "STT_LANGUAGE", "en-US"))
        except Exception as e:
            self._trace_exception("google_transcribe_error", e)
            return None

    def _transcribe_local(self, audio, phrase_type="command"):
        if self._whisper_loading and self._whisper_model is None:
            raise RuntimeError("Local Whisper model still loading")
        model = self._get_whisper_model()
        if model is None:
            raise RuntimeError("Local Whisper model unavailable")

        try:
            samples = np.frombuffer(
                audio.get_raw_data(convert_rate=Config.MIC_SAMPLE_RATE, convert_width=2),
                dtype=np.int16,
            ).astype(np.float32) / 32768.0
            # Transcription settings vary by use case:
            # - wake: accurate recognition of specific keywords, no VAD
            # - interrupt: greedy/fastest possible — we only need to confirm
            #   speech was heard so IRIS can stop talking immediately
            # - command: accurate free-form transcription, no keyword bias,
            #   no VAD (VAD on short clips can accidentally cut off real speech)
            if phrase_type == "wake":
                prompt = "iris aletheia alithia initiate protocol authorize terminate exit"
                beam_size = 3
                best_of = 3
                vad_filter = False
            elif phrase_type == "interrupt":
                # Speed is critical here — use greedy decoding, skip VAD, no
                # keyword bias that might skew a short barge-in fragment.
                prompt = ""
                beam_size = 1
                best_of = 1
                vad_filter = False
            else:  # "command" — free-form conversation
                # Initial prompt primes Whisper with the style/context of speech
                # it should expect.  Without this, Whisper frequently hallucinates
                # completely wrong phrases on ambiguous audio (e.g. "i just bought
                # this elephant" instead of "what do an elephant and a human have
                # in common").  The prompt acts as fake prior text that nudges the
                # model toward natural conversational English and away from
                # training-data artifacts like URLs, product listings, etc.
                prompt = (
                    "Conversation with AI voice assistant IRIS. "
                    "Natural spoken English, questions and commands."
                )
                beam_size = 5
                best_of = 1
                # Skip VAD on command clips — the SpeechRecognition energy
                # detector already confirmed speech is present; a second VAD
                # pass on short audio can falsely filter real speech.
                vad_filter = False
            segments, _ = model.transcribe(
                samples,
                beam_size=beam_size,
                best_of=best_of,
                temperature=0.0,
                language=getattr(Config, "LOCAL_WHISPER_LANGUAGE_HINT", "en") or None,
                vad_filter=vad_filter,
                condition_on_previous_text=False,
                initial_prompt=prompt,
            )
            # faster-whisper returns a generator — materialise so we can inspect.
            segments = list(segments)

            # no_speech_prob: probability that the audio frame contains NO human
            # speech.  If EVERY segment scores above 0.6, the model itself is not
            # confident this is real speech — treat it as noise and return None.
            # This catches hallucinations on silent/TTS-echo audio (especially
            # during 0.3s interrupt clips) where Whisper fabricates words even
            # though the energy gate already let it through.
            #
            # Threshold reasoning:
            #   0.6  — Whisper's internal default for VAD; using the same value
            #           ensures we're no more aggressive than --vad_filter would be.
            #   interrupt clips especially benefit: 0.3s of TTS echo routinely
            #   scores no_speech_prob ≈ 0.7–0.95 even when "a word" appears.
            if segments:
                max_speech_confidence = max(
                    1.0 - seg.no_speech_prob for seg in segments
                )
                if max_speech_confidence < 0.4:  # equiv. no_speech_prob > 0.6 on all
                    self._debug_trace(
                        "transcript_rejected_no_speech",
                        phrase_type=phrase_type,
                        max_speech_confidence=round(max_speech_confidence, 3),
                        raw_text=" ".join(s.text.strip() for s in segments),
                    )
                    self._whisper_inference_failures = 0
                    return None

            text = " ".join(segment.text.strip() for segment in segments).strip()
            self._whisper_inference_failures = 0
            return text or None
        except Exception as e:
            self._whisper_inference_failures += 1
            backend = f"{self._whisper_runtime_device or 'unknown'}/{self._whisper_runtime_compute_type or 'unknown'}"
            self._trace_exception(
                "local_stt_error",
                e,
                phrase_type=phrase_type,
                backend=backend,
                failures=self._whisper_inference_failures,
            )
            if (self._whisper_runtime_device, self._whisper_runtime_compute_type) != ("cpu", "int8"):
                try:
                    self._reload_whisper_model("cpu", "int8")
                    retry_model = self._get_whisper_model()
                    segments, _ = retry_model.transcribe(
                        samples,
                        beam_size=beam_size,
                        best_of=best_of,
                        temperature=0.0,
                        language=getattr(Config, "LOCAL_WHISPER_LANGUAGE_HINT", "en") or None,
                        vad_filter=vad_filter,
                        condition_on_previous_text=False,
                        initial_prompt=prompt,
                    )
                    segments = list(segments)
                    if segments:
                        max_speech_confidence = max(1.0 - seg.no_speech_prob for seg in segments)
                        if max_speech_confidence < 0.4:
                            self._whisper_inference_failures = 0
                            return None
                    text = " ".join(segment.text.strip() for segment in segments).strip()
                    self._whisper_inference_failures = 0
                    self._debug_trace(
                        "local_stt_recovered",
                        phrase_type=phrase_type,
                        backend=f"{self._whisper_runtime_device}/{self._whisper_runtime_compute_type}",
                        transcript=text or "",
                    )
                    return text or None
                except Exception as retry_error:
                    e = retry_error
                    self._trace_exception(
                        "local_stt_recovery_failed",
                        retry_error,
                        phrase_type=phrase_type,
                        backend=f"{self._whisper_runtime_device or 'unknown'}/{self._whisper_runtime_compute_type or 'unknown'}",
                    )
            if self._whisper_inference_failures >= 3:
                self._whisper_disabled = True
            logger.error(f"Local STT failed: {e}")
            raise RuntimeError("Local Whisper transcription failed") from e

    def _warm_local_stt(self):
        try:
            self._get_whisper_model()
        except BaseException as exc:
            if isinstance(exc, KeyboardInterrupt):
                logger.info("Local STT warmup interrupted during shutdown.")
            else:
                logger.warning(f"Local STT warmup aborted: {exc}")

    def _whisper_cache_root(self):
        return getattr(
            Config,
            "LOCAL_WHISPER_CACHE_DIR",
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "models", ".cache"),
        )

    def _instantiate_whisper_model(self, cache_root, device, compute_type):
        # Silence HuggingFace Hub cosmetic warnings before importing.
        # HF_HUB_DISABLE_SYMLINKS_WARNING: Windows Developer Mode is not required
        # for IRIS — symlinks just degrade to copies, which is fine.
        # TOKENIZERS_PARALLELISM: not relevant here, avoids a deadlock warning.
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        import warnings
        warnings.filterwarnings(
            "ignore",
            message=".*symlinks.*",
            category=UserWarning,
        )
        from faster_whisper import WhisperModel
        return WhisperModel(
            getattr(Config, "LOCAL_WHISPER_MODEL", "base"),
            device=device,
            compute_type=compute_type,
            download_root=cache_root,
        )

    def _reload_whisper_model(self, device, compute_type):
        cache_root = self._whisper_cache_root()
        self._whisper_model = self._instantiate_whisper_model(cache_root, device, compute_type)
        self._whisper_runtime_device = device
        self._whisper_runtime_compute_type = compute_type
        self._whisper_disabled = False
        console.print(f"[bold yellow][Voice] Local STT fallback -> {device}/{compute_type}[/bold yellow]")
        self._debug_trace("whisper_backend_switch", device=device, compute_type=compute_type)
        return self._whisper_model

    def _local_whisper_cached(self):
        cache_root = getattr(
            Config,
            "LOCAL_WHISPER_CACHE_DIR",
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "models", ".cache"),
        )
        try:
            os.makedirs(cache_root, exist_ok=True)
        except OSError:
            return False
        return self._has_whisper_weights(cache_root)

    def _get_whisper_model(self):
        if self._whisper_disabled:
            return None
        if self._whisper_model is not None:
            return self._whisper_model

        with self._whisper_lock:
            if self._whisper_model is not None:
                return self._whisper_model

            try:
                self._whisper_loading = True
                cache_root = self._whisper_cache_root()
                os.makedirs(cache_root, exist_ok=True)
                download_needed = self._reset_incomplete_whisper_downloads(cache_root)
                if not download_needed:
                    download_needed = not self._has_whisper_weights(cache_root)
                if download_needed and not self._whisper_download_announced:
                    console.print("[bold yellow][Voice] Downloading Local Whisper...[/bold yellow]")
                    self._whisper_download_announced = True

                requested_device = getattr(Config, "LOCAL_WHISPER_DEVICE", "cpu")
                requested_compute = getattr(Config, "LOCAL_WHISPER_COMPUTE_TYPE", "int8")
                fallback_candidates = [(requested_device, requested_compute)]
                if (requested_device, requested_compute) != ("cpu", "int8"):
                    fallback_candidates.append(("cpu", "int8"))
                last_error = None
                for device, compute_type in fallback_candidates:
                    try:
                        self._whisper_model = self._instantiate_whisper_model(cache_root, device, compute_type)
                        self._whisper_runtime_device = device
                        self._whisper_runtime_compute_type = compute_type
                        break
                    except Exception as e:
                        last_error = e
                        self._trace_exception(
                            "whisper_load_error",
                            e,
                            device=device,
                            compute_type=compute_type,
                        )
                        self._whisper_model = None
                if self._whisper_model is None:
                    raise last_error or RuntimeError("Unable to initialize local Whisper")
                if not self._whisper_ready_announced:
                    console.print(
                        f"[bold green][Voice] Local STT Active ({self._whisper_runtime_device}/{self._whisper_runtime_compute_type})[/bold green]"
                    )
                    self._whisper_ready_announced = True
                self._debug_trace(
                    "whisper_ready",
                    device=self._whisper_runtime_device or "",
                    compute_type=self._whisper_runtime_compute_type or "",
                )
                return self._whisper_model
            except Exception as e:
                self._whisper_disabled = True
                logger.warning(f"Local STT unavailable, falling back to Google STT: {e}")
                return None
            finally:
                self._whisper_loading = False

    def _reset_incomplete_whisper_downloads(self, cache_root):
        removed = False
        for root, _, files in os.walk(cache_root):
            for name in files:
                if not name.endswith(".incomplete"):
                    continue
                try:
                    os.remove(os.path.join(root, name))
                    removed = True
                except OSError:
                    continue
        return removed

    def _has_whisper_weights(self, cache_root):
        model_name = getattr(Config, "LOCAL_WHISPER_MODEL", "base").replace("/", "--")
        repo_dir = os.path.join(cache_root, f"models--Systran--faster-whisper-{model_name}")
        snapshots_dir = os.path.join(repo_dir, "snapshots")
        if not os.path.isdir(snapshots_dir):
            return False
        for root, _, files in os.walk(snapshots_dir):
            if any(name.endswith((".bin", ".safetensors")) for name in files):
                return True
        return False

    def prime_audio_cache(self, phrases: list) -> None:
        """
        Pre-generate TTS audio for all given phrases CONCURRENTLY on the persistent
        event loop (max 5 parallel connections).  30 phrases that took ~21 s
        sequentially now finish in ~3-5 s, so wake acks are ready before the user
        can even say the wake word the first time.
        """
        if self._force_io_disabled:
            return
        if getattr(Config, "TTS_ENGINE", "auto") != "edge":
            return
        try:
            import edge_tts as _edge
        except ImportError:
            return
        phrases = [p for p in phrases if p and isinstance(p, str)]
        if not phrases:
            return

        # Deduplicate and collect clean texts that aren't already cached/in-flight.
        clean_list: list = []
        for phrase in phrases:
            clean = self._clean_for_speech(phrase)
            if not clean:
                continue
            with self._static_audio_cache_lock:
                if clean not in self._static_audio_cache:
                    self._static_audio_cache[clean] = None   # mark in-flight
                    clean_list.append(clean)
        if not clean_list:
            return

        async def _gen_one(clean: str, sem) -> None:
            async with sem:
                pf = None
                try:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
                        pf = tmp.name
                    communicate = _edge.Communicate(
                        clean, voice=Config.VOICE_NAME, rate=Config.VOICE_RATE
                    )
                    with open(pf, "wb") as f:
                        async for chunk in communicate.stream():
                            if chunk["type"] == "audio":
                                f.write(chunk["data"])
                    if os.path.exists(pf) and os.path.getsize(pf) > 0:
                        with self._static_audio_cache_lock:
                            self._static_audio_cache[clean] = pf
                        self._debug_trace("tts_prime_done", chars=len(clean), text=clean)
                    else:
                        with self._static_audio_cache_lock:
                            self._static_audio_cache.pop(clean, None)
                        if pf and os.path.exists(pf):
                            try:
                                os.remove(pf)
                            except Exception as _rme:
                                logger.debug("[Voice] prime_cache stale-file cleanup skipped %s: %s", pf, _rme)
                except Exception as exc:
                    logger.debug(f"[TTS] prime_cache error for {clean!r}: {exc}")
                    with self._static_audio_cache_lock:
                        self._static_audio_cache.pop(clean, None)
                    if pf and os.path.exists(pf):
                        try:
                            os.remove(pf)
                        except Exception as _rme:
                            logger.debug("[Voice] prime_cache error-path cleanup skipped %s: %s", pf, _rme)

        async def _gen_all() -> None:
            import asyncio
            sem = asyncio.Semaphore(5)   # max 5 concurrent TTS connections
            await asyncio.gather(*(_gen_one(c, sem) for c in clean_list), return_exceptions=True)

        def _run_prime() -> None:
            try:
                self._get_edge_tts_loop().run(_gen_all(), timeout=120.0)
            except Exception as exc:
                logger.debug(f"[TTS] prime batch error: {exc}")

        threading.Thread(target=_run_prime, daemon=True, name="tts-prime").start()

    def _try_prefetch_next(self, current_stop_event) -> None:
        """While the current audio plays, pre-generate TTS for the next queued item."""
        try:
            with self._utterance_queue.mutex:
                q_snapshot = list(self._utterance_queue.queue)
        except Exception:
            return
        if not q_snapshot:
            return
        _nxt_item = q_snapshot[0]
        nxt_text = _nxt_item[0]
        nxt_stop = _nxt_item[1]
        if nxt_stop is not current_stop_event or nxt_stop.is_set():
            return
        clean_nxt = self._clean_for_speech(nxt_text)
        if not clean_nxt:
            return
        with self._tts_prefetch_lock:
            if clean_nxt in self._tts_prefetch_cache:
                return  # already in-flight or ready
            self._tts_prefetch_cache[clean_nxt] = None  # mark in-flight

        def _generate_prefetch(text_key=clean_nxt):
            pf = None
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
                    pf = tmp.name
                # Use active persona voice, not the global default.
                # Using Config.VOICE_NAME here was a bug: prefetched audio would
                # always be generated in Iris's voice even when Aletheia was speaking.
                ok = self._run_edge_tts_async(
                    text_key,
                    self._active_voice_name,
                    self._active_voice_rate,
                    pf,
                )
                with self._tts_prefetch_lock:
                    if ok and os.path.exists(pf) and os.path.getsize(pf) > 0:
                        self._tts_prefetch_cache[text_key] = pf
                    else:
                        self._tts_prefetch_cache.pop(text_key, None)
                        if pf and os.path.exists(pf):
                            try:
                                os.remove(pf)
                            except Exception as _rme:
                                logger.debug("[Voice] Prefetch failed-write cleanup skipped %s: %s", pf, _rme)
            except Exception as exc:
                logger.debug(f"[TTS] prefetch error: {exc}")
                with self._tts_prefetch_lock:
                    self._tts_prefetch_cache.pop(text_key, None)

        threading.Thread(target=_generate_prefetch, daemon=True, name="tts-prefetch").start()

    def _play_edge_tts_file(self, temp_file: str, stop_event, trigger_prefetch: bool = False, on_play_start=None) -> None:
        """Play a pre-generated MP3 file and optionally trigger lookahead prefetch.
        Note: _speech_active is managed by _run_speech_worker, not here."""
        try:
            if not mixer.get_init():
                mixer.init(44100, -16, 2, 4096)
            mixer.music.load(temp_file)
            mixer.music.play()
            # Fire the text-sync callback the instant audio starts playing so
            # the console text and the voice are synchronised.
            if on_play_start:
                try:
                    on_play_start()
                except Exception:
                    pass
            _prefetch_triggered = False
            while mixer.music.get_busy():
                if stop_event is not None and stop_event.is_set():
                    mixer.music.stop()
                    break
                if trigger_prefetch and not _prefetch_triggered and stop_event is not None:
                    self._try_prefetch_next(stop_event)
                    _prefetch_triggered = True
                time.sleep(0.01)
        except Exception as e:
            logger.error(f"Playback failed: {e}")

    def _get_edge_tts_loop(self) -> "_EdgeTTSEventLoop":
        """Return the shared persistent asyncio event loop for Edge-TTS."""
        if self._edge_tts_loop is not None:
            return self._edge_tts_loop
        with self._edge_tts_loop_lock:
            if self._edge_tts_loop is None:
                self._edge_tts_loop = _EdgeTTSEventLoop()
        return self._edge_tts_loop

    def _run_edge_tts_async(self, text: str, voice: str, rate: str, output_path: str,
                            timeout: float = None, stop_event=None) -> bool:
        """Generate audio via the edge-tts Python library using a persistent event loop.

        `timeout` caps the maximum wait in seconds.  Defaults to
        TTS_NETWORK_TIMEOUT_SEC config (8 s).  A TimeoutError causes a warning
        and returns False so the caller can try a CLI fallback.

        `stop_event` is checked on every streamed chunk so an interrupted call
        aborts immediately rather than running to the full 8-second timeout.
        Without this check, stopping IRIS mid-speech blocks the speech worker
        for up to 8 s while the in-flight network stream drains.
        """
        import concurrent.futures
        try:
            import edge_tts as _edge_tts_lib
        except ImportError:
            return False

        _timeout = float(getattr(Config, "TTS_NETWORK_TIMEOUT_SEC", 8)) if timeout is None else timeout

        async def _generate():
            communicate = _edge_tts_lib.Communicate(text, voice=voice, rate=rate)
            with open(output_path, "wb") as f:
                async for chunk in communicate.stream():
                    # Bail out immediately if the speech worker was stopped
                    # (e.g. barge-in or explicit stop_speaking call) so we don't
                    # drain an 8-second network stream after the user interrupted.
                    if stop_event is not None and stop_event.is_set():
                        return
                    if chunk["type"] == "audio":
                        f.write(chunk["data"])

        _MAX_ATTEMPTS = 3
        for _attempt in range(_MAX_ATTEMPTS):
            try:
                self._get_edge_tts_loop().run(_generate(), timeout=_timeout)
                return True
            except concurrent.futures.TimeoutError:
                logger.warning(
                    f"[TTS] Edge-TTS timeout after {_timeout:.0f}s for {len(text)} chars "
                    f"— check internet connectivity"
                )
                return False
            except Exception as exc:
                # Two known transient Microsoft service errors — retry both:
                #   NoAudioReceived: connection accepted but zero audio chunks returned.
                #   503 WSServerHandshakeError: WebSocket handshake rejected (overload).
                # Both resolve on retry with 1 s / 2 s backoff.
                _exc_str = str(exc)
                _is_transient = (
                    type(exc).__name__ == "NoAudioReceived"
                    or "503" in _exc_str
                    or "Invalid response status" in _exc_str
                )
                if _is_transient and _attempt < _MAX_ATTEMPTS - 1:
                    _wait = float(_attempt + 1)
                    logger.warning(
                        "[TTS] edge-tts transient error (attempt %d/%d, %s) — retrying in %.0fs",
                        _attempt + 1, _MAX_ATTEMPTS, type(exc).__name__, _wait,
                    )
                    time.sleep(_wait)
                    continue
                logger.error(f"[TTS] edge-tts Python library failed: {exc}")
                return False
        return False

    def _speak_edge_tts(self, text, stop_event=None, on_play_start=None):
        temp_file = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
                temp_file = tmp.name

            # Prefer the Python library (no subprocess spawn cost ~200-400ms on Windows).
            # Fall back to the CLI subprocess if the library call fails.
            # Use the active persona voice (Iris or Aletheia), not the global default.
            rate = self._active_voice_rate
            voice_name = self._active_voice_name
            _tts_timeout = float(getattr(Config, "TTS_NETWORK_TIMEOUT_SEC", 8))
            ok = self._run_edge_tts_async(text, voice_name, rate, temp_file,
                                          timeout=_tts_timeout, stop_event=stop_event)
            if not ok:
                # Try CLI subprocess as secondary fallback.
                result = subprocess.run(
                    ["edge-tts", "--voice", voice_name, "--rate", rate,
                     "--text", text, "--write-media", temp_file],
                    check=False, capture_output=True,
                    encoding="utf-8", errors="replace",
                    timeout=_tts_timeout,
                    # CREATE_NO_WINDOW: hides the CMD flash on Windows and
                    # reduces idle CPU cost from console-session overhead.
                    # getattr fallback: evaluates to 0 on Linux where the
                    # constant does not exist, avoiding AttributeError.
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                if result.returncode != 0:
                    # encoding="utf-8" makes stderr a str already — no .decode() needed.
                    err = result.stderr.strip()
                    logger.error(f"[TTS] edge-tts CLI failed (rc={result.returncode}): {err or '(no stderr)'}")

            if stop_event is not None and stop_event.is_set():
                return

            if os.path.exists(temp_file) and os.path.getsize(temp_file) > 0:
                # Play and trigger lookahead prefetch for the next queued item.
                self._play_edge_tts_file(temp_file, stop_event, trigger_prefetch=True, on_play_start=on_play_start)
        finally:
            if temp_file and os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except Exception as _rme:
                    logger.debug("[Voice] TTS temp-file cleanup skipped %s: %s", temp_file, _rme)
