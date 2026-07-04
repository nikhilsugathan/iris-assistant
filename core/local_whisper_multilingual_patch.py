"""Multilingual defaults for the optional local Whisper fallback path."""

from __future__ import annotations


_AUTO_VALUES = {"", "auto", "multilingual", "detect", "none"}


def _language_hint(config) -> str | None:
    raw = str(getattr(config, "LOCAL_WHISPER_LANGUAGE_HINT", "auto") or "auto").strip()
    return None if raw.lower() in _AUTO_VALUES else raw[:2].lower()


def apply_local_whisper_multilingual_patch(voice_module) -> None:
    voice_cls = getattr(voice_module, "Voice", None)
    if voice_cls is None or getattr(voice_cls, "_iris_local_whisper_multilingual_patch_applied", False):
        return

    original_transcribe_local = voice_cls._transcribe_local

    def _transcribe_local_multilingual(self, audio, phrase_type="command"):
        original_hint = getattr(voice_module.Config, "LOCAL_WHISPER_LANGUAGE_HINT", "auto")
        try:
            # The existing local implementation reads Config at transcription time.
            # Blank maps to None and lets multilingual Whisper detect the language.
            voice_module.Config.LOCAL_WHISPER_LANGUAGE_HINT = _language_hint(voice_module.Config)
            return original_transcribe_local(self, audio, phrase_type=phrase_type)
        finally:
            voice_module.Config.LOCAL_WHISPER_LANGUAGE_HINT = original_hint

    voice_cls._transcribe_local = _transcribe_local_multilingual
    voice_cls._iris_local_whisper_multilingual_patch_applied = True
