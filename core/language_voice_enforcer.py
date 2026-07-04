"""Final sticky-language TTS enforcement."""

from __future__ import annotations

import os
import threading

from .language_voice_bridge import get_active_language_style, get_active_language_voice


def _env_bool(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _remove_output(path: str) -> None:
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def apply_language_voice_enforcer(voice_module, multilingual_module) -> None:
    voice_cls = getattr(voice_module, "Voice", None)
    if voice_cls is None or getattr(voice_cls, "_iris_language_voice_enforcer_applied", False):
        return

    detector = multilingual_module.detect_language_style
    detector_ctx = threading.local()

    def _guarded_detector(text: str):
        if getattr(detector_ctx, "suppress_response_detection", False):
            return None
        return detector(text)

    multilingual_module.detect_language_style = _guarded_detector
    original_run_edge = voice_cls._run_edge_tts_async

    def _run_edge_tts_input_authoritative(self, text, voice, rate, out_file, *args, **kwargs):
        active_voice = get_active_language_voice()
        active_style = get_active_language_style()
        if not active_voice or not _env_bool("IRIS_STICKY_LANGUAGE_TTS", True):
            return original_run_edge(self, text, voice, rate, out_file, *args, **kwargs)

        previous = getattr(detector_ctx, "suppress_response_detection", False)
        detector_ctx.suppress_response_detection = True
        try:
            self._iris_forced_input_language_key = active_style
            self._iris_forced_input_voice_name = active_voice
            self._iris_language_voice_key = active_style
            self._iris_language_voice_name = active_voice
            result = original_run_edge(
                self,
                text,
                active_voice,
                os.getenv("IRIS_MULTILINGUAL_TTS_RATE", "+0%"),
                out_file,
                *args,
                **kwargs,
            )
            if get_active_language_voice() != active_voice:
                _remove_output(out_file)
                try:
                    self._debug_trace(
                        "tts_language_voice",
                        mode="stale_audio_removed",
                        voice=active_voice,
                        text=text,
                    )
                except Exception:
                    pass
                return False
            return result
        finally:
            detector_ctx.suppress_response_detection = previous

    voice_cls._run_edge_tts_async = _run_edge_tts_input_authoritative
    voice_cls._iris_language_voice_enforcer_applied = True
