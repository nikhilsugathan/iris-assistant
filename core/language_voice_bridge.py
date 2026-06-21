"""Bridge the user's detected input language into the next TTS response.

The multilingual detector can correctly guide the LLM, but the spoken response
may start with wording that is harder for the TTS router to classify. This patch
keeps the last detected user-language style and uses it as the fallback voice for
subsequent speech.
"""

from __future__ import annotations

import os
from typing import Optional

_ACTIVE_STYLE_KEY: Optional[str] = None
_ACTIVE_VOICE_NAME: Optional[str] = None


def _env_bool(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _set_active_language(detected) -> None:
    global _ACTIVE_STYLE_KEY, _ACTIVE_VOICE_NAME
    if not detected:
        return
    key, _label, voice_name = detected
    if key == "malayalam" and not _env_bool("IRIS_MALAYALAM_NATIVE_TTS", False):
        return
    _ACTIVE_STYLE_KEY = key
    _ACTIVE_VOICE_NAME = voice_name


def get_active_language_voice() -> Optional[str]:
    return _ACTIVE_VOICE_NAME


def apply_language_voice_bridge(brain_module, voice_module, multilingual_module) -> None:
    brain_cls = getattr(brain_module, "Brain", None)
    voice_cls = getattr(voice_module, "Voice", None)

    if brain_cls is not None and not getattr(brain_cls, "_iris_language_voice_bridge_applied", False):
        original_generation_settings = brain_cls._generation_settings

        def _generation_settings_language_bridge(self, query_type: str, council_packet=None, voice_mode: bool = False, user_input: str = ""):
            detected = multilingual_module.detect_language_style(user_input)
            if detected:
                _set_active_language(detected)
                try:
                    self._iris_active_language_key = detected[0]
                except Exception:
                    pass
            return original_generation_settings(
                self,
                query_type,
                council_packet=council_packet,
                voice_mode=voice_mode,
                user_input=user_input,
            )

        brain_cls._generation_settings = _generation_settings_language_bridge
        brain_cls._iris_language_voice_bridge_applied = True

    if voice_cls is not None and not getattr(voice_cls, "_iris_language_voice_bridge_applied", False):
        original_run_edge = voice_cls._run_edge_tts_async
        original_tts_status = voice_cls.tts_status

        def _run_edge_tts_language_bridge(self, text, voice, rate, out_file):
            if _env_bool("IRIS_STICKY_LANGUAGE_TTS", True):
                detected = multilingual_module.detect_language_style(text)
                if detected:
                    _set_active_language(detected)
                active_voice = get_active_language_voice()
                if active_voice:
                    voice = active_voice
                    rate = os.getenv("IRIS_MULTILINGUAL_TTS_RATE", "+0%")
                    try:
                        self._iris_language_voice_name = active_voice
                        self._debug_trace("tts_language_voice", mode="input_bridge", voice=voice, text=text)
                    except Exception:
                        pass
            return original_run_edge(self, text, voice, rate, out_file)

        def _tts_status_language_bridge(self) -> str:
            base = original_tts_status(self)
            active = get_active_language_voice() or "none"
            return f"{base} / active_input_voice={active}"

        voice_cls._run_edge_tts_async = _run_edge_tts_language_bridge
        voice_cls.tts_status = _tts_status_language_bridge
        voice_cls._iris_language_voice_bridge_applied = True
