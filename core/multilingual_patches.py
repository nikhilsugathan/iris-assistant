"""Multilingual pipeline patches for IRIS.

Goals:
- Stop forcing English STT when Groq Whisper can auto-detect language.
- Add language instructions to the LLM for non-English input.
- Route Edge-TTS to matching voices for multilingual responses.
"""

from __future__ import annotations

import os
import re
from typing import Optional

_LANGUAGE_RULES = [
    (
        "spanish",
        re.compile(r"\b(hola|amor|mi amor|gracias|buenos|buenas|dime|necesito|quiero|puedes|como|cómo|que|qué|por favor|vale|sí|si)\b", re.IGNORECASE),
        "Spanish",
        "es-ES-ElviraNeural",
    ),
    (
        "german",
        re.compile(r"\b(hallo|guten|morgen|abend|danke|bitte|kannst|können|was|wie|warum|ich|du|aufgabe|weiter|ja|nein)\b", re.IGNORECASE),
        "German",
        "de-DE-KatjaNeural",
    ),
    (
        "french",
        re.compile(r"\b(bonjour|salut|merci|s'il|sil|vous|plaît|plait|peux|pouvez|quoi|comment|pourquoi|oui|non|bonsoir)\b", re.IGNORECASE),
        "French",
        "fr-FR-DeniseNeural",
    ),
    (
        "italian",
        re.compile(r"\b(ciao|buongiorno|grazie|prego|puoi|cosa|come|perché|perche|sì|si|no)\b", re.IGNORECASE),
        "Italian",
        "it-IT-ElsaNeural",
    ),
    (
        "hindi",
        re.compile(r"\b(namaste|namaskar|pranam|shukriya|dhanyavad|kya|kaise|karna|batao|bolo|aaj|haan|nahi|theek|accha)\b", re.IGNORECASE),
        "Hindi/Hinglish",
        "hi-IN-SwaraNeural",
    ),
    (
        "malayalam",
        re.compile(r"\b(namaskaram|sukham|alle|parayu|nanni|entha|innu|cheyyanam|cheyyam|njan|ivide|undu|sheri)\b", re.IGNORECASE),
        "Malayalam or Malayalam-English mixed speech",
        "ml-IN-SobhanaNeural",
    ),
]


def _env_bool(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def detect_language_style(text: str) -> Optional[tuple[str, str, str]]:
    sample = text or ""
    for key, pattern, label, voice in _LANGUAGE_RULES:
        if pattern.search(sample):
            return key, label, voice
    return None


def language_instruction_for(text: str) -> str:
    detected = detect_language_style(text)
    if not detected:
        return ""
    _key, label, _voice = detected
    return (
        f"The user is speaking in {label}. Reply naturally and fluently in that same language/style. "
        "Do not explain which language it is. Do not translate unless asked. "
        "If the user mixes English with that language, mirror the same mixed style naturally."
    )


def tts_voice_for(text: str) -> Optional[str]:
    detected = detect_language_style(text)
    if detected:
        return detected[2]
    return None


def apply_multilingual_patches(brain_module, voice_module) -> None:
    brain_cls = getattr(brain_module, "Brain", None)
    voice_cls = getattr(voice_module, "Voice", None)

    if brain_cls is not None and not getattr(brain_cls, "_iris_multilingual_patch_applied", False):
        original_generation_settings = brain_cls._generation_settings

        def _generation_settings_multilingual(self, query_type: str, council_packet=None, voice_mode: bool = False, user_input: str = ""):
            settings = original_generation_settings(
                self,
                query_type,
                council_packet=council_packet,
                voice_mode=voice_mode,
                user_input=user_input,
            )
            instruction = language_instruction_for(user_input)
            if instruction:
                existing = str(settings.get("extra_system", "") or "").strip()
                settings["extra_system"] = f"{existing}\n\n{instruction}".strip() if existing else instruction
                try:
                    brain_module.trace_logger.info("[MULTILINGUAL] prompt_language_instruction applied=true instruction=%s", instruction)
                except Exception:
                    pass
            return settings

        brain_cls._generation_settings = _generation_settings_multilingual
        brain_cls._iris_multilingual_patch_applied = True

    if voice_cls is not None and not getattr(voice_cls, "_iris_multilingual_voice_patch_applied", False):
        original_transcribe_groq = voice_cls._transcribe_groq
        original_transcribe_google = voice_cls._transcribe_google
        original_run_edge = voice_cls._run_edge_tts_async
        original_stt_status = voice_cls.stt_status

        def _transcribe_groq_multilingual(self, audio, phrase_type: str = "command"):
            # Native implementation forces Config.STT_LANGUAGE into Groq. When set
            # to auto/multilingual, omit the language parameter so Whisper detects it.
            lang_raw = str(getattr(voice_module.Config, "STT_LANGUAGE", "auto") or "auto").strip().lower()
            if lang_raw not in {"auto", "multilingual", "detect", ""}:
                return original_transcribe_groq(self, audio, phrase_type=phrase_type)
            api_key = getattr(voice_module.Config, "GROQ_API_KEY", "")
            if not api_key:
                return original_transcribe_google(self, audio)
            try:
                from groq import Groq

                wav_bytes = audio.get_wav_data()
                client = Groq(api_key=api_key)
                model = getattr(voice_module.Config, "GROQ_STT_MODEL", "whisper-large-v3-turbo")
                result = client.audio.transcriptions.create(
                    file=("audio.wav", wav_bytes),
                    model=model,
                )
                text = (result.text or "").strip()
                return text or None
            except Exception as exc:
                self._trace_exception("groq_stt_error", exc, phrase_type=phrase_type)
                return original_transcribe_google(self, audio)

        def _transcribe_google_multilingual(self, audio):
            # Google fallback is not our primary multilingual path. If STT_LANGUAGE
            # is auto, try default recognition; if a specific locale is configured,
            # honor it.
            try:
                lang_raw = str(getattr(voice_module.Config, "STT_LANGUAGE", "auto") or "auto").strip()
                if lang_raw.lower() in {"auto", "multilingual", "detect", ""}:
                    return self.recognizer.recognize_google(audio)
                return self.recognizer.recognize_google(audio, language=lang_raw)
            except Exception as e:
                self._trace_exception("google_transcribe_error", e)
                return None

        def _run_edge_tts_multilingual(self, text, voice, rate, out_file):
            if _env_bool("IRIS_MULTILINGUAL_TTS", True):
                detected_voice = tts_voice_for(text)
                if detected_voice:
                    voice = detected_voice
                    # Keep native-language voices closer to natural speed.
                    rate = os.getenv("IRIS_MULTILINGUAL_TTS_RATE", "+0%")
                    try:
                        self._debug_trace("tts_language_voice", voice=voice, text=text)
                    except Exception:
                        pass
            return original_run_edge(self, text, voice, rate, out_file)

        def _stt_status_multilingual(self) -> str:
            base = original_stt_status(self)
            lang_raw = str(getattr(voice_module.Config, "STT_LANGUAGE", "auto") or "auto").strip()
            return f"{base} / language={lang_raw}"

        voice_cls._transcribe_groq = _transcribe_groq_multilingual
        voice_cls._transcribe_google = _transcribe_google_multilingual
        voice_cls._run_edge_tts_async = _run_edge_tts_multilingual
        voice_cls.stt_status = _stt_status_multilingual
        voice_cls._iris_multilingual_voice_patch_applied = True
