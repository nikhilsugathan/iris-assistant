"""
Runtime compatibility patches for IRIS.

These patches keep the existing modules intact while hardening behaviour that is
sensitive to import order, URL validation, and short Edge-TTS interactions.
"""

from __future__ import annotations

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
        url_lower = (url or "").lower()

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


def _patch_voice(module) -> None:
    """Stabilize short Edge-TTS turns by registering prefetch before queueing audio.

    The original order queued text first and only then registered the prefetch.
    On short interactions, the speech worker could consume the queue before the
    prefetch marker existed, causing duplicate TTS work or a stale stop-event
    reuse. This patched speak() creates a fresh stop event after idle turns and
    marks Edge-TTS prefetch as in-flight before the worker sees the utterance.
    """
    voice_cls = getattr(module, "Voice", None)
    if voice_cls is None or getattr(voice_cls, "_iris_voice_stability_patch_applied", False):
        return

    def _start_edge_prefetch(self, clean_text: str, stop_event) -> None:
        if not clean_text:
            return
        if getattr(module.Config, "TTS_ENGINE", "auto") != "edge":
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
                    # Natural completion never set the old event. Mark it closed so
                    # a new light interaction cannot inherit stale cancellation state.
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

    voice_cls.speak = speak
    voice_cls._iris_voice_stability_patch_applied = True
