"""Multilingual pipeline patches for IRIS.

Goals:
- Stop forcing English STT when Groq Whisper can auto-detect language.
- Add language instructions to the LLM for non-English input.
- Keep one consistent Iris TTS voice by default, with a Malayalam-native exception.
"""

from __future__ import annotations

import os
import re
from typing import Optional

_MALAYALAM_SCRIPT_RE = re.compile(r"[\u0D00-\u0D7F]")

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
        re.compile(r"\b(namaskaram|sukham|alle|parayu|nanni|entha|innu|cheyyanam|cheyyam|njan|ivide|undu|sheri|malayalam)\b", re.IGNORECASE),
        "Malayalam or Malayalam-English mixed speech",
        "ml-IN-SobhanaNeural",
    ),
]


def _env_bool(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def malayalam_native_tts_enabled() -> bool:
    # Malayalam pronunciation is poor in the English Iris voice. Keep the global
    # voice locked for other languages, but allow a Malayalam-only native voice.
    return _env_bool("IRIS_MALAYALAM_NATIVE_TTS", True)


def detect_language_style(text: str) -> Optional[tuple[str, str, str]]:
    sample = text or ""
    if _MALAYALAM_SCRIPT_RE.search(sample):
        return "malayalam", "Malayalam", "ml-IN-SobhanaNeural"
    for key, pattern, label, voice in _LANGUAGE_RULES:
        if pattern.search(sample):
            return key, label, voice
    return None


def language_instruction_for(text: str) -> str:
    detected = detect_language_style(text)
    if not detected:
        return ""
    key, label, _voice = detected
    if key == "malayalam":
        if malayalam_native_tts_enabled():
            return (
                "The user is speaking Malayalam or Malayalam-English. Reply naturally in fluent spoken Malayalam when possible. "
                "Use Malayalam script for Malayalam words so TTS can pronounce it correctly. "
                "Use short, simple sentences. Do not use awkward romanized Malayalam unless the user specifically asks for transliteration. "
                "If the user mixes English and Malayalam, mirror that style naturally. Do not explain which language it is."
            )
        return (
            "The user is speaking Malayalam or Malayalam-English, but the active TTS voice is locked to the English Iris voice. "
            "For spoken clarity, reply mostly in English and use only very short Malayalam romanized phrases. "
            "Do not write long Malayalam sentences in romanized form. Do not explain which language it is."
        )
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


def multilingual_tts_voice_switch_enabled() -> bool:
    if _env_bool("IRIS_LOCK_TTS_VOICE", True):
        return False
    return _env_bool("IRIS_MULTILINGUAL_TTS", False)


def _should_switch_tts_voice_for_text(text: str) -> bool:
    detected = detect_language_style(text)
    if not detected:
        return False
    key, _label, _voice = detected
    if key == "malayalam" and malayalam_native_tts_enabled():
        return True
    return multilingual_tts_voice_switch_enabled()


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
        original_tts_status = voice_cls.tts_status

        def _transcribe_groq_multilingual(self, audio, phrase_type: str = "command"):
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
            try:
                lang_raw = str(getattr(voice_module.Config, "STT_LANGUAGE", "auto") or "auto").strip()
                if lang_raw.lower() in {"auto", "multilingual", "detect", ""}:
                    return self.recognizer.recognize_google(audio)
                return self.recognizer.recognize_google(audio, language=lang_raw)
            except Exception as e:
                self._trace_exception("google_transcribe_error", e)
                return None

        def _run_edge_tts_multilingual(self, text, voice, rate, out_file):
            if _should_switch_tts_voice_for_text(text):
                detected_voice = tts_voice_for(text)
                if detected_voice:
                    voice = detected_voice
                    rate = os.getenv("IRIS_MULTILINGUAL_TTS_RATE", "+0%")
                    try:
                        self._debug_trace("tts_language_voice", mode="switched", voice=voice, text=text)
                    except Exception:
                        pass
            else:
                try:
                    self._debug_trace("tts_language_voice", mode="locked", voice=voice, text=text)
                except Exception:
                    pass
            return original_run_edge(self, text, voice, rate, out_file)

        def _stt_status_multilingual(self) -> str:
            base = original_stt_status(self)
            lang_raw = str(getattr(voice_module.Config, "STT_LANGUAGE", "auto") or "auto").strip()
            return f"{base} / language={lang_raw}"

        def _tts_status_multilingual(self) -> str:
            base = original_tts_status(self)
            if malayalam_native_tts_enabled():
                mode = "locked voice + Malayalam native exception"
            else:
                mode = "locked voice" if not multilingual_tts_voice_switch_enabled() else "language voice switching"
            return f"{base} / multilingual={mode}"

        voice_cls._transcribe_groq = _transcribe_groq_multilingual
        voice_cls._transcribe_google = _transcribe_google_multilingual
        voice_cls._run_edge_tts_async = _run_edge_tts_multilingual
        voice_cls.stt_status = _stt_status_multilingual
        voice_cls.tts_status = _tts_status_multilingual
        voice_cls._iris_multilingual_voice_patch_applied = True
