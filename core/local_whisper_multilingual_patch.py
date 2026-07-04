"""Multilingual defaults for cloud and optional local STT fallback paths."""

from __future__ import annotations

from .stt_fallback_hardening import apply_stt_fallback_hardening


_AUTO_VALUES = {"", "auto", "multilingual", "detect", "none"}


def _language_hint(config) -> str | None:
    raw = str(getattr(config, "LOCAL_WHISPER_LANGUAGE_HINT", "auto") or "auto").strip()
    return None if raw.lower() in _AUTO_VALUES else raw[:2].lower()


def apply_local_whisper_multilingual_patch(voice_module) -> None:
    # This stage is already loaded after multilingual STT patching, so it is also
    # the safe final point to correct Groq-to-Google fallback dispatch.
    apply_stt_fallback_hardening(voice_module)

    voice_cls = getattr(voice_module, "Voice", None)
    if voice_cls is None or getattr(voice_cls, "_iris_local_whisper_multilingual_patch_applied", False):
        return

    original_transcribe_local = voice_cls._transcribe_local

    def _transcribe_local_multilingual(self, audio, phrase_type="command"):
        original_hint = getattr(voice_module.Config, "LOCAL_WHISPER_LANGUAGE_HINT", "auto")
        try:
            voice_module.Config.LOCAL_WHISPER_LANGUAGE_HINT = _language_hint(voice_module.Config)
            return original_transcribe_local(self, audio, phrase_type=phrase_type)
        finally:
            voice_module.Config.LOCAL_WHISPER_LANGUAGE_HINT = original_hint

    voice_cls._transcribe_local = _transcribe_local_multilingual
    voice_cls._iris_local_whisper_multilingual_patch_applied = True
