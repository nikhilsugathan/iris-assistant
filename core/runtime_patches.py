"""
Runtime compatibility patches for IRIS.

These patches keep the existing modules intact while hardening behaviour that is
sensitive to import order, URL validation, and short Edge-TTS interactions.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse


def apply_patch(fullname: str, module) -> None:
    """Apply a targeted patch after a module has been imported."""
    if fullname == "core.brain":
        _patch_brain(module)
    elif fullname == "core.security":
        _patch_security(module)
    elif fullname == "core.voice":
        _patch_voice(module)


def _patch_brain(module) -> None:
    """Provide the module-level logger expected by legacy Brain code paths."""
    if getattr(module, "logger", None) is not None:
        return
    logger_mod = getattr(module, "_logger_mod", None)
    if logger_mod is None:
        return
    module.logger = logger_mod.get_logger("Brain")


def _host_matches(host: str, domain: str) -> bool:
    host = (host or "").strip(".").lower()
    domain = (domain or "").strip(".").lower()
    return bool(host and domain and (host == domain or host.endswith("." + domain)))


def _patch_security(module) -> None:
    """Replace substring URL trust checks with hostname-aware validation."""
    guard_cls = getattr(module, "SecurityGuard", None)
    if guard_cls is None or getattr(guard_cls, "_iris_url_patch_applied", False):
        return

    def _check_url(self, url: str):
        parsed = urlparse(url or "")
        host = (parsed.hostname or "").strip(".").lower()

        if not host:
            return module.WARNING, (
                "I couldn't verify the destination host for this URL. "
                "Do you explicitly want me to proceed?"
            )

        for domain in module.BLOCKED_DOMAINS:
            if _host_matches(host, domain):
                if domain in {"bit.ly", "tinyurl.com"}:
                    return module.WARNING, (
                        f"The URL uses a shortener ({domain}) which hides the real "
                        "destination. I can't verify where it actually leads. "
                        "Do you explicitly want me to proceed to this unknown destination?"
                    )
                return module.BLOCKED, (
                    f"The domain '{domain}' is flagged as potentially unsafe. "
                    "I'm blocking this to protect you."
                )

        if parsed.scheme == "http" and not (
            host in {"localhost", "127.0.0.1"}
            or host.startswith("192.168.")
            or host.startswith("10.")
            or host.startswith("172.16.")
        ):
            return module.WARNING, (
                "This URL uses HTTP instead of HTTPS, meaning the connection is "
                "not encrypted and data could be intercepted. It's safer to find "
                "an HTTPS version. Do you want to proceed anyway?"
            )

        is_trusted = any(_host_matches(host, domain) for domain in module.SAFE_DOWNLOAD_DOMAINS)
        if not is_trusted:
            return module.WARNING, (
                "This URL is from an unverified source, not in my trusted domain list. "
                "I can't guarantee it's safe. Trusted sources include GitHub, Microsoft, "
                "Python.org, PyPI, and similar official sources. Do you want to proceed?"
            )

        return module.SAFE, ""

    guard_cls._check_url = _check_url
    guard_cls._iris_url_patch_applied = True


def _has_local_piper_model(module) -> bool:
    configured = str(getattr(module.Config, "PIPER_MODEL_PATH", "") or "").strip()
    if configured and os.path.exists(configured):
        return True
    models_dir = os.path.join(str(getattr(module.Config, "PROJECT_ROOT", "") or ""), "models")
    try:
        return os.path.isdir(models_dir) and any(name.endswith(".onnx") for name in os.listdir(models_dir))
    except Exception:
        return False


def _edge_tts_effective(module) -> bool:
    preferred = str(getattr(module.Config, "TTS_ENGINE", "auto") or "auto").strip().lower()
    if preferred == "edge":
        return True
    if preferred != "auto":
        return False
    return not _has_local_piper_model(module)


def _patch_voice(module) -> None:
    """Stabilize Edge-TTS turns and make interruption less echo-prone."""
    voice_cls = getattr(module, "Voice", None)
    if voice_cls is None or getattr(voice_cls, "_iris_voice_stability_patch_applied", False):
        return

    # Config says "auto", but when Piper is unavailable the runtime is effectively
    # Edge-TTS. Normalize this early so main.py's Edge-specific streaming logic
    # also activates instead of silently taking the non-Edge batching path.
    if str(getattr(module.Config, "TTS_ENGINE", "auto") or "auto").strip().lower() == "auto" and _edge_tts_effective(module):
        module.Config.TTS_ENGINE = "edge"

    original_listen_for_interrupt = voice_cls.listen_for_interrupt
    original_start_barge_in_monitor = voice_cls.start_barge_in_monitor

    def _start_edge_prefetch(self, clean_text: str, stop_event) -> None:
        if not clean_text:
            return
        if not _edge_tts_effective(module):
            return
        if self._force_io_disabled or getattr(self, "_muted", False):
            return

        with self._static_audio_cache_lock:
            static_path = self._static_audio_cache.get(clean_text)
        if static_path and module.os.path.exists(static_path) and module.os.path.getsize(static_path) > 0:
            return

        with self._tts_prefetch_lock:
            if clean_text in self._tts_prefetch_cache:
                return
            self._tts_prefetch_cache[clean_text] = None

        voice_name = self._active_voice_name
        voice_rate = self._active_voice_rate

        def _early_prefetch(key=clean_text, stop=stop_event, name=voice_name, rate=voice_rate):
            pf = None
            try:
                with module.tempfile.NamedTemporaryFile(
                    suffix=".mp3",
                    delete=False,
                    dir=module.tempfile.gettempdir(),
                ) as tf:
                    pf = tf.name
                ok = self._run_edge_tts_async(key, name, rate, pf)
                if ok and not stop.is_set():
                    with self._tts_prefetch_lock:
                        self._tts_prefetch_cache[key] = pf
                else:
                    with self._tts_prefetch_lock:
                        self._tts_prefetch_cache.pop(key, None)
                    if pf:
                        try:
                            module.os.remove(pf)
                        except Exception as cleanup_err:
                            module.logger.debug(
                                "[Voice] Early prefetch cleanup skipped %s: %s",
                                pf,
                                cleanup_err,
                            )
            except Exception as exc:
                with self._tts_prefetch_lock:
                    self._tts_prefetch_cache.pop(key, None)
                if pf:
                    try:
                        module.os.remove(pf)
                    except Exception as cleanup_err:
                        module.logger.debug(
                            "[Voice] Exception-path early prefetch cleanup skipped %s: %s",
                            pf,
                            cleanup_err,
                        )
                module.logger.debug("[Voice] Early prefetch failed for %r: %s", key, exc)

        module.threading.Thread(
            target=_early_prefetch,
            daemon=True,
            name="tts-early-prefetch-stable",
        ).start()

    def speak(self, text, interrupt=True, on_play_start=None):
        if not text:
            return
        if self._force_io_disabled:
            return
        if self.text_mode and not getattr(module.Config, "SPEAK_IN_TEXT_MODE", False):
            return
        if getattr(self, "_muted", False):
            return

        clean_text = self._clean_for_speech(text)
        if not clean_text:
            return

        with self._tts_lock:
            idle_now = not self.is_speaking()
            needs_new_event = (
                interrupt
                or self._active_stop_event is None
                or self._active_stop_event.is_set()
                or idle_now
            )
            if needs_new_event:
                if interrupt:
                    self.stop_speaking()
                elif self._active_stop_event is not None and not self._active_stop_event.is_set():
                    self._active_stop_event.set()
                self._active_stop_event = module.threading.Event()

            stop_event = self._active_stop_event
            _start_edge_prefetch(self, clean_text, stop_event)
            self._debug_trace(
                "speech_enqueue",
                interrupt=interrupt,
                chars=len(text),
                text=text,
                queue_size=self._utterance_queue.qsize(),
            )
            self._utterance_queue.put((text, stop_event, on_play_start))

    def _fast_tts_cut_monitor(self, stop_event, callback) -> None:
        rms_stream = getattr(self, "_rms_stream", None)
        if rms_stream is None or callback is None:
            return
        threshold = float(
            os.getenv(
                "TTS_BARGE_IN_RMS_THRESHOLD",
                str(max(1600.0, float(getattr(module.Config, "BARGE_IN_RMS_THRESHOLD", 750)) * 2.0)),
            )
        )
        consecutive_required = int(os.getenv("TTS_BARGE_IN_CONSECUTIVE_FRAMES", "3"))
        warmup_sec = float(os.getenv("TTS_BARGE_IN_WARMUP_SEC", "0.18"))
        warmup_until = module.time.monotonic() + warmup_sec
        consecutive = 0
        while not stop_event.is_set() and self.is_speaking():
            try:
                data = rms_stream.read(512, exception_on_overflow=False)
            except Exception:
                return
            if module.time.monotonic() < warmup_until:
                consecutive = 0
                continue
            try:
                arr = module.np.frombuffer(data, dtype=module.np.int16).astype(module.np.float32)
                rms = float(module.np.sqrt(module.np.mean(arr ** 2))) if len(arr) else 0.0
            except Exception:
                rms = 0.0
            if rms >= threshold:
                consecutive += 1
                if consecutive >= consecutive_required:
                    self._debug_trace(
                        "tts_fast_cut_rms_trigger",
                        rms=round(rms, 1),
                        gate=round(threshold, 1),
                        consecutive=consecutive,
                    )
                    stop_event.set()
                    try:
                        callback()
                    except Exception as cb_err:
                        module.logger.debug("[Voice] fast cut callback failed: %s", cb_err)
                    return
            else:
                consecutive = 0

    def listen_for_interrupt(self, timeout=None, phrase_time_limit=None, on_phrase_captured=None):
        # Run a high-threshold raw-RMS cut monitor in parallel with the existing
        # SpeechRecognition interrupt listener. This gives immediate stop behaviour
        # for real nearby speech while avoiding low-level TTS echo false positives.
        fast_stop = module.threading.Event()
        fast_callback = on_phrase_captured or self.stop_speaking
        monitor = module.threading.Thread(
            target=_fast_tts_cut_monitor,
            args=(self, fast_stop, fast_callback),
            daemon=True,
            name="tts-fast-cut-monitor",
        )
        monitor.start()
        try:
            return original_listen_for_interrupt(
                self,
                timeout=0.2 if timeout is None else timeout,
                phrase_time_limit=1.0 if phrase_time_limit is None else phrase_time_limit,
                on_phrase_captured=None,
            )
        finally:
            fast_stop.set()

    def start_barge_in_monitor(self, on_barge_in: callable, warmup_sec: float = 0.45):
        # main.py passes 1.5s to avoid thinking-cue echo, but that makes true
        # interruption feel delayed. Cap it and rely on the stronger RMS threshold
        # to avoid accidental self-cancellation.
        cap = float(os.getenv("BARGE_IN_WARMUP_CAP_SEC", "0.55"))
        return original_start_barge_in_monitor(
            self,
            on_barge_in=on_barge_in,
            warmup_sec=min(float(warmup_sec), cap),
        )

    voice_cls.speak = speak
    voice_cls.listen_for_interrupt = listen_for_interrupt
    voice_cls.start_barge_in_monitor = start_barge_in_monitor
    voice_cls._iris_voice_stability_patch_applied = True
    voice_cls._iris_voice_interrupt_patch_applied = True
