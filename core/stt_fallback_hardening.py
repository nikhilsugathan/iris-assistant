"""Final STT fallback dispatch for multilingual auto mode."""

from __future__ import annotations


_AUTO_VALUES = {"", "auto", "multilingual", "detect"}


def apply_stt_fallback_hardening(voice_module) -> None:
    voice_cls = getattr(voice_module, "Voice", None)
    if voice_cls is None or getattr(voice_cls, "_iris_stt_fallback_hardening_applied", False):
        return

    previous_transcribe_groq = voice_cls._transcribe_groq

    def _transcribe_groq_hardened(self, audio, phrase_type: str = "command"):
        language = str(
            getattr(voice_module.Config, "STT_LANGUAGE", "auto") or "auto"
        ).strip().lower()
        if language not in _AUTO_VALUES:
            return previous_transcribe_groq(self, audio, phrase_type=phrase_type)

        api_key = getattr(voice_module.Config, "GROQ_API_KEY", "")
        if not api_key:
            return self._transcribe_google(audio)

        try:
            from groq import Groq

            wav_bytes = audio.get_wav_data()
            client = Groq(api_key=api_key)
            model = getattr(
                voice_module.Config,
                "GROQ_STT_MODEL",
                "whisper-large-v3-turbo",
            )
            result = client.audio.transcriptions.create(
                file=("audio.wav", wav_bytes),
                model=model,
            )
            text = (result.text or "").strip()
            return text or None
        except Exception as exc:
            self._trace_exception("groq_stt_error", exc, phrase_type=phrase_type)
            return self._transcribe_google(audio)

    voice_cls._transcribe_groq = _transcribe_groq_hardened
    voice_cls._iris_stt_fallback_hardening_applied = True
