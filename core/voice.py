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
from core.logger import get_logger

logger = get_logger("Voice")
console = Console()

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
        self._recent_spoken: collections.deque = collections.deque(maxlen=10)
        self._recent_spoken_lock = threading.Lock()

        self._tts_lock = threading.Lock()
        self._active_stop_event = None
        self._utterance_queue = queue.Queue()
        self._speech_active = False
        self._speech_state_lock = threading.Lock()
        self._speech_worker = threading.Thread(target=self._run_speech_worker, daemon=True)
        self._speech_worker.start()
        
        if not self._force_io_disabled and (not self.text_mode or getattr(Config, "SPEAK_IN_TEXT_MODE", False)):
            try:
                mixer.init()
            except Exception as e:
                logger.error(f"Audio Warning: Could not initialize pygame mixer - {e}")

        if not self._force_io_disabled and not self.text_mode:
            self._init_mic()
            priority = getattr(Config, "WAKE_STT_PRIORITY", "cloud_first")
            if priority == "local_first":
                threading.Thread(target=self._warm_local_stt, daemon=True).start()
            elif priority == "cloud_first" and self._local_whisper_cached():
                # Preload a cached local model so cloud-first mode has stable fallback
                # without kicking off a late download/activation mid-session.
                self._warm_local_stt()
            if getattr(Config, "PIPER_TTS_WARMUP", False):
                threading.Thread(target=self._warm_local_tts, daemon=True).start()

    def _preview_text(self, text: str | None, limit: int = 120) -> str:
        cleaned = re.sub(r"\s+", " ", (text or "")).strip()
        if len(cleaned) <= limit:
            return cleaned
        return cleaned[: limit - 3] + "..."

    def _debug_trace(self, event: str, **fields) -> None:
        if not self._debug_transcripts:
            return
        payload = []
        for key, value in fields.items():
            if isinstance(value, str):
                payload.append(f"{key}={self._preview_text(value)!r}")
            else:
                payload.append(f"{key}={value!r}")
        logger.debug("[VOICE_DEBUG] %s %s", event, " ".join(payload))

    def _init_mic(self):
        """Probes hardware for the Aletheia spec."""
        try:
            self.recognizer = sr.Recognizer()
            self.recognizer.pause_threshold = 0.45
            self.recognizer.phrase_threshold = 0.2
            self.recognizer.non_speaking_duration = 0.25
            self.recognizer.dynamic_energy_threshold = False
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
            with self.mic as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
            self.recognizer.energy_threshold = max(
                self.recognizer.energy_threshold, Config.WAKE_RMS_THRESHOLD
            )
            self.mic_ready = True
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

    def is_speaking(self):
        with self._speech_state_lock:
            queue_pending = not self._utterance_queue.empty()
            speech_active = self._speech_active
        try:
            mixer_busy = mixer.get_init() and mixer.music.get_busy()
        except:
            mixer_busy = False
        return speech_active or queue_pending or mixer_busy

    def stop_speaking(self):
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
        except: pass
        while True:
            try:
                self._utterance_queue.get_nowait()
                self._utterance_queue.task_done()
            except queue.Empty:
                break

    def speak(self, text, interrupt=True):
        if not text: return
        if self._force_io_disabled: return
        if self.text_mode and not getattr(Config, "SPEAK_IN_TEXT_MODE", False): return
        
        with self._tts_lock:
            if interrupt or self._active_stop_event is None or self._active_stop_event.is_set():
                self.stop_speaking()
                self._active_stop_event = threading.Event()
            self._utterance_queue.put((text, self._active_stop_event))

    def _run_speech_worker(self):
        while True:
            text, stop_event = self._utterance_queue.get()
            try:
                if stop_event.is_set():
                    continue
                self._set_speech_active(True)
                self._speak_utterance(text, stop_event)
            except Exception as e:
                logger.error(f"Speech worker failed: {e}")
            finally:
                self._set_speech_active(False)
                self._utterance_queue.task_done()

    def _set_speech_active(self, active):
        with self._speech_state_lock:
            self._speech_active = active

    def _speak_utterance(self, text, stop_event):
        clean_text = self._clean_for_speech(text)
        if not clean_text or stop_event.is_set():
            return
        engine = self._get_piper_engine()
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

        if not stop_event.is_set():
            self._debug_trace(
                "tts_dispatch",
                engine="edge_tts",
                chunk_count=1,
                chars=len(clean_text),
                text=clean_text,
            )
            self._speak_edge_tts(clean_text, stop_event)

    def _stream_piper_chunks(self, engine, chunks, stop_event):
        audio_queue = queue.Queue(maxsize=2)
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
        cleaned = re.sub(r'[*_`#>]+', '', text or '')
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
        if len(sentences) <= 2 and len(text) <= 420:
            return [text]

        chunks = []
        current = []
        current_len = 0
        for sentence in sentences:
            current.append(sentence)
            current_len += len(sentence)
            if len(current) >= 3 or current_len >= 280:
                chunks.append(" ".join(current).strip())
                current = []
                current_len = 0
        if current:
            chunks.append(" ".join(current).strip())
        return chunks or [text]

    def _get_piper_engine(self):
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

    def record_spoken(self, text: str) -> None:
        """Record a phrase IRIS just spoke so it can be suppressed from STT input."""
        normalized = self._normalize_text(text)
        if not normalized:
            return
        with self._recent_spoken_lock:
            self._recent_spoken.append((time.monotonic(), normalized))

    def should_ignore_transcript(self, transcript: str) -> bool:
        normalized = self._normalize_text(transcript)
        if not normalized:
            return True

        tokens = normalized.split()
        if not tokens:
            return True
        if len(tokens) == 1 and (len(tokens[0]) <= 2 or tokens[0] in {"uh", "um", "hmm"}):
            return True

        now = time.monotonic()
        with self._recent_spoken_lock:
            recent_spoken = list(self._recent_spoken)

        for spoken_at, spoken in recent_spoken:
            if now - spoken_at > 12.0:
                continue
            if normalized == spoken:
                return True
            if len(normalized) >= 18 and normalized in spoken:
                return True
            if len(spoken) >= 18 and spoken in normalized:
                return True

            spoken_tokens = set(spoken.split())
            overlap = sum(1 for token in tokens if token in spoken_tokens)
            if len(tokens) >= 4 and overlap / max(len(tokens), 1) >= 0.75:
                return True
        return False

    def listen_for_wake(self, timeout=None, phrase_time_limit=None):
        """Listen for wake word using speech recognition."""
        if not self.mic_ready: 
            import time; time.sleep(0.5); return None
        try:
            self.recognizer.energy_threshold = Config.WAKE_RMS_THRESHOLD
            self._debug_trace(
                "listen_start",
                source="wake",
                configured_gate=Config.WAKE_RMS_THRESHOLD,
                actual_threshold=round(float(self.recognizer.energy_threshold), 2),
                timeout=4 if timeout is None else timeout,
                phrase_time_limit=4 if phrase_time_limit is None else phrase_time_limit,
            )
            with self.mic as source:
                audio = self.recognizer.listen(
                    source,
                    timeout=4 if timeout is None else timeout,
                    phrase_time_limit=4 if phrase_time_limit is None else phrase_time_limit,
                )
            return self._transcribe_audio(audio, phrase_type="wake", source="wake")
        except Exception:
            return None

    def listen_for_command(self, timeout=None, phrase_time_limit=None):
        """Listen for a follow-up command."""
        if not self.mic_ready: return None
        try:
            self.recognizer.energy_threshold = Config.COMMAND_RMS_THRESHOLD
            self._debug_trace(
                "listen_start",
                source="command",
                configured_gate=Config.COMMAND_RMS_THRESHOLD,
                actual_threshold=round(float(self.recognizer.energy_threshold), 2),
                timeout=5 if timeout is None else timeout,
                phrase_time_limit=7 if phrase_time_limit is None else phrase_time_limit,
            )
            with self.mic as source:
                audio = self.recognizer.listen(
                    source,
                    timeout=5 if timeout is None else timeout,
                    phrase_time_limit=7 if phrase_time_limit is None else phrase_time_limit,
                )
            return self._transcribe_audio(audio, phrase_type="command", source="command")
        except Exception:
            return None
        finally:
            self.recognizer.energy_threshold = Config.WAKE_RMS_THRESHOLD

    def listen_for_interrupt(self, timeout=None, phrase_time_limit=None):
        """Listen briefly for a barge-in phrase while IRIS is speaking."""
        if not self.mic_ready:
            return None
        try:
            self.recognizer.energy_threshold = min(
                Config.WAKE_RMS_THRESHOLD,
                Config.COMMAND_RMS_THRESHOLD,
            )
            self._debug_trace(
                "listen_start",
                source="interrupt",
                configured_gate=min(Config.WAKE_RMS_THRESHOLD, Config.COMMAND_RMS_THRESHOLD),
                actual_threshold=round(float(self.recognizer.energy_threshold), 2),
                timeout=1.0 if timeout is None else timeout,
                phrase_time_limit=2.2 if phrase_time_limit is None else phrase_time_limit,
            )
            with self.mic as source:
                audio = self.recognizer.listen(
                    source,
                    timeout=1.0 if timeout is None else timeout,
                    phrase_time_limit=2.2 if phrase_time_limit is None else phrase_time_limit,
                )
            return self._transcribe_audio(audio, phrase_type="command", source="interrupt")
        except Exception:
            return None
        finally:
            self.recognizer.energy_threshold = Config.WAKE_RMS_THRESHOLD

    def _transcribe_audio(self, audio, phrase_type="command", source="command"):
        priority = getattr(Config, "WAKE_STT_PRIORITY", "cloud_first")
        if priority == "local_first":
            try:
                text = self._transcribe_local(audio, phrase_type=phrase_type)
                if phrase_type == "wake" and not self._looks_like_wake_transcript(text or ""):
                    google_text = self._transcribe_google(audio)
                    self._debug_trace(
                        "transcribe",
                        source=source,
                        phrase_type=phrase_type,
                        priority=priority,
                        engine="local_then_google",
                        transcript=(google_text or ""),
                        local_transcript=text or "",
                    )
                    return google_text or None
                self._debug_trace(
                    "transcribe",
                    source=source,
                    phrase_type=phrase_type,
                    priority=priority,
                    engine="local",
                    transcript=text or "",
                )
                return text
            except RuntimeError:
                text = self._transcribe_google(audio)
                self._debug_trace(
                    "transcribe",
                    source=source,
                    phrase_type=phrase_type,
                    priority=priority,
                    engine="google_fallback",
                    transcript=text or "",
                )
                return text
        text = self._transcribe_google(audio)
        if text:
            self._debug_trace(
                "transcribe",
                source=source,
                phrase_type=phrase_type,
                priority=priority,
                engine="google",
                transcript=text,
            )
            return text
        if priority == "cloud_first":
            self._debug_trace(
                "transcribe",
                source=source,
                phrase_type=phrase_type,
                priority=priority,
                engine="google_only_wake_none" if phrase_type == "wake" else "google_only_command_none",
                transcript="",
            )
            return None
        # In cloud_first mode, never trigger a late Whisper load/activation.
        if self._whisper_loading or self._whisper_disabled or self._whisper_model is None:
            self._debug_trace(
                "transcribe",
                source=source,
                phrase_type=phrase_type,
                priority=priority,
                engine="none",
                transcript="",
                whisper_loading=self._whisper_loading,
                whisper_disabled=self._whisper_disabled,
                whisper_ready=self._whisper_model is not None,
            )
            return None
        try:
            text = self._transcribe_local(audio, phrase_type=phrase_type)
            self._debug_trace(
                "transcribe",
                source=source,
                phrase_type=phrase_type,
                priority=priority,
                engine="local_fallback",
                transcript=text or "",
            )
            return text
        except RuntimeError:
            self._debug_trace(
                "transcribe",
                source=source,
                phrase_type=phrase_type,
                priority=priority,
                engine="local_fallback_error",
                transcript="",
            )
            return None

    def _transcribe_google(self, audio):
        try:
            return self.recognizer.recognize_google(audio, language=getattr(Config, "STT_LANGUAGE", "en-US"))
        except Exception:
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
            prompt = "iris" if phrase_type == "wake" else ""
            beam_size = 3 if phrase_type == "wake" else 5
            best_of = 3 if phrase_type == "wake" else 1
            vad_filter = False if phrase_type == "wake" else True
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
            text = " ".join(segment.text.strip() for segment in segments).strip()
            return text or None
        except Exception as e:
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
                from faster_whisper import WhisperModel
                cache_root = getattr(
                    Config,
                    "LOCAL_WHISPER_CACHE_DIR",
                    os.path.join(os.path.dirname(os.path.dirname(__file__)), "models", ".cache"),
                )
                os.makedirs(cache_root, exist_ok=True)
                download_needed = self._reset_incomplete_whisper_downloads(cache_root)
                if not download_needed:
                    download_needed = not self._has_whisper_weights(cache_root)
                if download_needed and not self._whisper_download_announced:
                    console.print("[bold yellow][Voice] Downloading Local Whisper...[/bold yellow]")
                    self._whisper_download_announced = True

                self._whisper_model = WhisperModel(
                    getattr(Config, "LOCAL_WHISPER_MODEL", "base"),
                    device=getattr(Config, "LOCAL_WHISPER_DEVICE", "cpu"),
                    compute_type=getattr(Config, "LOCAL_WHISPER_COMPUTE_TYPE", "int8"),
                    download_root=cache_root,
                )
                if not self._whisper_ready_announced:
                    console.print("[bold green][Voice] Local STT Active[/bold green]")
                    self._whisper_ready_announced = True
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

    def _speak_edge_tts(self, text, stop_event=None):
        temp_file = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
                temp_file = tmp.name

            subprocess.run(
                ["edge-tts", "--voice", Config.VOICE_NAME, "--rate", Config.VOICE_RATE, 
                 "--text", text, "--write-media", temp_file],
                check=False, capture_output=True
            )
            
            if stop_event is not None and stop_event.is_set():
                return

            if os.path.exists(temp_file) and os.path.getsize(temp_file) > 0:
                try:
                    # Final safety check before loading
                    if not mixer.get_init():
                        mixer.init()
                    mixer.music.load(temp_file)
                    mixer.music.play()
                    while mixer.music.get_busy():
                        if stop_event is not None and stop_event.is_set():
                            mixer.music.stop()
                            break
                        time.sleep(0.05)
                except Exception as e:
                    logger.error(f"Playback failed: {e}")
        finally:
            if temp_file and os.path.exists(temp_file):
                try: os.remove(temp_file)
                except: pass
