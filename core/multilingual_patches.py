"""Multilingual pipeline patches for IRIS.

Goals:
- Let Groq Whisper auto-detect spoken language.
- Add same-language/style instructions to the LLM.
- Keep the same Iris TTS speaker across languages by default.
- Retain optional per-language TTS voices behind explicit configuration.
"""

from __future__ import annotations

import os
import random
import re
from typing import Optional

_MALAYALAM_SCRIPT_RE = re.compile(r"[\u0D00-\u0D7F]")

_LANGUAGE_RULES = [
    (
        "spanish",
        re.compile(
            r"\b("
            r"hola|amor|mi amor|gracias|buenos|buenas|dime|necesito|quiero|puedes|"
            r"como|cómo|que|qué|por favor|vale|sí|si|español|espanol|spanish|"
            r"el|la|los|las|un|una|banco|banko|bebé|bebe|bebes|bebis|estas|estás"
            r")\b",
            re.IGNORECASE,
        ),
        "Spanish",
        "es-ES-ElviraNeural",
    ),
    (
        "german",
        re.compile(r"\b(hallo|guten|morgen|abend|danke|bitte|kannst|können|was|wie|warum|ich|du|aufgabe|weiter|ja|nein|deutsch|german)\b", re.IGNORECASE),
        "German",
        "de-DE-KatjaNeural",
    ),
    (
        "french",
        re.compile(r"\b(bonjour|salut|merci|s'il|sil|vous|plaît|plait|peux|pouvez|quoi|comment|pourquoi|oui|non|bonsoir|français|francais|french)\b", re.IGNORECASE),
        "French",
        "fr-FR-DeniseNeural",
    ),
    (
        "italian",
        re.compile(r"\b(ciao|buongiorno|grazie|prego|puoi|cosa|come|perché|perche|sì|si|italiano|italian)\b", re.IGNORECASE),
        "Italian",
        "it-IT-ElsaNeural",
    ),
    (
        "hindi",
        re.compile(r"\b(namaste|namaskar|pranam|shukriya|dhanyavad|kya|kaise|karna|batao|bolo|aaj|haan|nahi|theek|accha|hindi|hinglish)\b", re.IGNORECASE),
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

_WAKE_OR_SYSTEM_LINES = {
    "right here what's on your mind", "oh it's you lucky me", "you have my undivided slightly smug attention",
    "listening make it interesting", "i'm all ears well technically all microphone but you get it", "talk to me",
    "hit me with it", "i'm in what disaster are we solving today", "what are we getting into",
    "already thinking ahead of you what is it", "present and mildly curious", "say the word",
    "oh you called this better be good", "what have you got for me", "go ahead i'm listening", "you rang",
    "until next time", "good session signing off", "later stay curious", "closing out take care",
    "done for now you've got this", "standing down come back whenever", "session closed",
    "aletheia standing down", "root session terminated", "all systems nominal",
    "looking good from where i'm standing", "okay", "sure", "back", "i'm back what were you saying",
}

_STYLE_LINES = {
    "english": {
        "wake": ["I'm listening. Make it useful.", "Go on. I'm already suspiciously ready.", "Speak. Let's make this efficient."],
        "farewell": ["Done for now. Try not to break reality without me.", "Standing down. Call me when the chaos gets interesting.", "Session closed. Nicely survived."],
    },
    "spanish": {
        "wake": ["Dime, mi amor. ¿Qué hacemos?", "Te escucho. Dame la misión.", "Aquí estoy. Vamos con estilo."],
        "farewell": ["Hasta luego, mi amor. No rompas nada sin mí.", "Cierro sesión. El drama queda pausado.", "Listo. Me llamas si el caos vuelve."],
    },
    "german": {
        "wake": ["Ich höre. Was ist der Plan?", "Sag mir die Aufgabe. Wir machen das sauber.", "Bereit. Was lösen wir?"],
        "farewell": ["Bis später. Bitte nichts anzünden.", "Sitzung beendet. Sehr ordentlich.", "Ich bin raus. Ruf mich, wenn es brennt."],
    },
    "french": {
        "wake": ["Je t'écoute. Quelle est la mission?", "Dis-moi. On fait ça proprement.", "Je suis là. On commence?"],
        "farewell": ["À plus tard. Garde un peu de chaos pour moi.", "Session terminée. Très élégant.", "Je disparais. Appelle-moi si besoin."],
    },
    "italian": {
        "wake": ["Dimmi. Da dove cominciamo?", "Ti ascolto. Qual è la missione?", "Eccomi. Facciamolo bene."],
        "farewell": ["A dopo. Non fare disastri senza di me.", "Sessione chiusa. Molto elegante.", "Mi ritiro. Chiamami se serve."],
    },
    "hindi": {
        "wake": ["Bolo. Aaj kya solve karna hai?", "Haan, batao. Mission kya hai?", "Sun rahi hoon. Chalo smart kaam karte hain."],
        "farewell": ["Theek hai. Baad mein milte hain.", "Session khatam. Drama pause pe hai.", "Main standby mein hoon. Zarurat ho toh bulao."],
    },
    "malayalam": {
        "wake": ["പറയൂ. എന്താണ് ചെയ്യേണ്ടത്?", "ഞാൻ കേൾക്കുന്നു. പ്ലാൻ എന്താണ്?", "നമുക്ക് തുടങ്ങാം. എന്ത് സഹായം വേണം?"],
        "farewell": ["ശരി. പിന്നെ കാണാം.", "സെഷൻ കഴിഞ്ഞു. ആവശ്യം വന്നാൽ വിളിക്കൂ.", "ഞാൻ ഇവിടെ തന്നെ ഉണ്ടാകും."],
    },
}

_STYLE_LABELS = {key: label for key, _pattern, label, _voice in _LANGUAGE_RULES}
_STYLE_VOICES = {key: voice for key, _pattern, _label, voice in _LANGUAGE_RULES}


def _env_bool(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _normalize_line(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9'\s]", " ", (text or "").lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def malayalam_native_tts_enabled() -> bool:
    return _env_bool("IRIS_MALAYALAM_NATIVE_TTS", False)


def sticky_language_tts_enabled() -> bool:
    return _env_bool("IRIS_STICKY_LANGUAGE_TTS", False)


def multilingual_tts_voice_switch_enabled() -> bool:
    # The lock is authoritative. Sticky state must never bypass it.
    if _env_bool("IRIS_LOCK_TTS_VOICE", True):
        return False
    return _env_bool("IRIS_MULTILINGUAL_TTS", False)


def detect_language_style(text: str) -> Optional[tuple[str, str, str]]:
    sample = text or ""
    if _MALAYALAM_SCRIPT_RE.search(sample):
        return "malayalam", "Malayalam", "ml-IN-SobhanaNeural"
    for key, pattern, label, voice in _LANGUAGE_RULES:
        if pattern.search(sample):
            return key, label, voice
    return None


def _style_tuple_for_key(key: str) -> Optional[tuple[str, str, str]]:
    label = _STYLE_LABELS.get(key)
    voice = _STYLE_VOICES.get(key)
    if label and voice:
        return key, label, voice
    return None


def _instruction_for_detected(detected: tuple[str, str, str], *, persistent: bool = False) -> str:
    key, label, _voice = detected
    prefix = "Continue using" if persistent else "The user is speaking in"
    if key == "malayalam":
        if malayalam_native_tts_enabled():
            return (
                "The user is speaking Malayalam or Malayalam-English. Reply naturally in fluent spoken Malayalam when possible. "
                "Use Malayalam script for Malayalam words so TTS can pronounce it correctly. "
                "Use short, simple sentences. Do not use awkward romanized Malayalam unless the user specifically asks for transliteration. "
                "If the user mixes English and Malayalam, mirror that style naturally. Do not explain which language it is."
            )
        return (
            "The user is speaking Malayalam or Malayalam-English, but Malayalam native TTS is disabled. "
            "For spoken clarity, reply mostly in English and use only very short Malayalam romanized phrases. "
            "Do not write long Malayalam sentences in romanized form. Do not explain which language it is."
        )
    if key == "spanish":
        return (
            f"{prefix} Spanish, including imperfect or broken Spanish. Reply naturally and fluently in Spanish or Spanish-English mixed style. "
            "If the user's Spanish is broken, lightly understand the intent and correct/help playfully, but do not switch into a full English explanation unless asked. "
            "Do not explain which language it is. Do not translate unless asked."
        )
    return (
        f"{prefix} {label}. Reply naturally and fluently in that same language/style. "
        "Do not explain which language it is. Do not translate unless asked. "
        "If the user mixes English with that language, mirror the same mixed style naturally."
    )


def language_instruction_for(text: str) -> str:
    detected = detect_language_style(text)
    if not detected:
        return ""
    return _instruction_for_detected(detected)


def tts_voice_for(text: str) -> Optional[str]:
    detected = detect_language_style(text)
    if detected:
        return detected[2]
    return None


def _voice_for_style(key: str) -> Optional[str]:
    return _STYLE_VOICES.get(key)


def _detect_system_line_kind(text: str) -> Optional[str]:
    normalized = _normalize_line(text)
    if normalized not in _WAKE_OR_SYSTEM_LINES:
        return None
    if any(token in normalized for token in ["until", "later", "closing", "done for now", "standing down", "session closed", "terminated"]):
        return "farewell"
    return "wake"


def _system_line_for(style: str, kind: str) -> str:
    style_lines = _STYLE_LINES.get(style) or _STYLE_LINES["english"]
    return random.choice(style_lines.get(kind) or _STYLE_LINES["english"][kind])


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
            detected = detect_language_style(user_input)
            if detected:
                self._iris_active_language_key = detected[0]
                instruction = _instruction_for_detected(detected)
            else:
                active_key = getattr(self, "_iris_active_language_key", None)
                active_detected = _style_tuple_for_key(active_key) if active_key else None
                instruction = _instruction_for_detected(active_detected, persistent=True) if active_detected else ""
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
        original_init = voice_cls.__init__
        original_speak = voice_cls.speak
        original_transcribe_groq = voice_cls._transcribe_groq
        original_transcribe_google = voice_cls._transcribe_google
        original_run_edge = voice_cls._run_edge_tts_async
        original_stt_status = voice_cls.stt_status
        original_tts_status = voice_cls.tts_status

        def _init_multilingual(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            self._iris_language_voice_key = None
            self._iris_language_voice_name = None
            self._iris_default_voice_name = getattr(self, "_active_voice_name", None)
            self._iris_default_voice_rate = getattr(self, "_active_voice_rate", None)

        def _select_utterance_voice(self, text: str, interrupt: bool = True) -> None:
            detected = detect_language_style(text)
            if detected:
                key, _label, voice_name = detected
                self._iris_language_voice_key = key
                if multilingual_tts_voice_switch_enabled() and (key != "malayalam" or malayalam_native_tts_enabled()):
                    self._iris_language_voice_name = voice_name
                else:
                    self._iris_language_voice_name = None
                return
            if interrupt and _detect_system_line_kind(text) is None and not sticky_language_tts_enabled():
                self._iris_language_voice_key = None
                self._iris_language_voice_name = None

        def _stylize_system_line(self, text: str) -> str:
            if not _env_bool("IRIS_UNIQUE_SYSTEM_LINES", True):
                return text
            kind = _detect_system_line_kind(text)
            if not kind:
                return text
            style = getattr(self, "_iris_language_voice_key", None) or "english"
            return _system_line_for(style, kind)

        def _speak_multilingual(self, text, interrupt=True, on_play_start=None):
            text = _stylize_system_line(self, text)
            _select_utterance_voice(self, text, interrupt=interrupt)
            return original_speak(self, text, interrupt=interrupt, on_play_start=on_play_start)

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
            detected = detect_language_style(text)
            switching = multilingual_tts_voice_switch_enabled()
            if detected:
                key, _label, voice_name = detected
                self._iris_language_voice_key = key
                if switching and (key != "malayalam" or malayalam_native_tts_enabled()):
                    self._iris_language_voice_name = voice_name
                elif not switching:
                    self._iris_language_voice_name = None

            if switching:
                selected_voice = getattr(self, "_iris_language_voice_name", None)
                if selected_voice:
                    voice = selected_voice
                    rate = os.getenv("IRIS_MULTILINGUAL_TTS_RATE", "+0%")
                    try:
                        self._debug_trace("tts_language_voice", mode="language_switch", voice=voice, text=text)
                    except Exception:
                        pass
            else:
                try:
                    self._debug_trace("tts_language_voice", mode="locked_iris_voice", voice=voice, text=text)
                except Exception:
                    pass
            return original_run_edge(self, text, voice, rate, out_file)

        def _stt_status_multilingual(self) -> str:
            base = original_stt_status(self)
            lang_raw = str(getattr(voice_module.Config, "STT_LANGUAGE", "auto") or "auto").strip()
            return f"{base} / language={lang_raw}"

        def _tts_status_multilingual(self) -> str:
            base = original_tts_status(self)
            if not multilingual_tts_voice_switch_enabled():
                mode = "locked Iris voice"
            elif sticky_language_tts_enabled():
                mode = "sticky language voice"
            else:
                mode = "language voice switching"
            return f"{base} / multilingual={mode}"

        voice_cls.__init__ = _init_multilingual
        voice_cls.speak = _speak_multilingual
        voice_cls._transcribe_groq = _transcribe_groq_multilingual
        voice_cls._transcribe_google = _transcribe_google_multilingual
        voice_cls._run_edge_tts_async = _run_edge_tts_multilingual
        voice_cls.stt_status = _stt_status_multilingual
        voice_cls.tts_status = _tts_status_multilingual
        voice_cls._iris_multilingual_voice_patch_applied = True
