"""First-cue language priority for mixed-language input.

This keeps multilingual conversations predictable:
- Pick the first language cue in the user's text, not the first language in our rule list.
- Handle common typos such as "bonjor".
- Let short mixed-language greetings use the local fast path instead of an LLM call.
"""

from __future__ import annotations

import re
from typing import Optional

_MALAYALAM_SCRIPT_RE = re.compile(r"[\u0D00-\u0D7F]")

_PRIORITY_RULES = [
    (
        "spanish",
        re.compile(
            r"\b("
            r"hola|amor|mi\s+amor|papi|gracias|buenos|buenas|dime|necesito|quiero|puedes|"
            r"como|cómo|que|qué|por\s+favor|vale|sí|si|español|espanol|spanish|"
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
        re.compile(r"\b(bonjour|bonjor|salut|merci|s'il|sil|vous|plaît|plait|peux|pouvez|quoi|comment|pourquoi|oui|non|bonsoir|français|francais|french)\b", re.IGNORECASE),
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


def detect_first_language_style(text: str) -> Optional[tuple[str, str, str]]:
    sample = text or ""
    if _MALAYALAM_SCRIPT_RE.search(sample):
        return "malayalam", "Malayalam", "ml-IN-SobhanaNeural"

    best = None
    for key, pattern, label, voice in _PRIORITY_RULES:
        match = pattern.search(sample)
        if not match:
            continue
        candidate = (match.start(), -(match.end() - match.start()), key, label, voice)
        if best is None or candidate < best:
            best = candidate
    if best is None:
        return None
    _start, _neg_len, key, label, voice = best
    return key, label, voice


def _style_key_for_text(text: str) -> str:
    detected = detect_first_language_style(text)
    if not detected:
        return "english"
    key = detected[0]
    return "indic" if key == "hindi" else key


def apply_language_priority_patches(multilingual_module, performance_module=None) -> None:
    multilingual_module.detect_language_style = detect_first_language_style

    def _tts_voice_for_first_language(text: str) -> Optional[str]:
        detected = detect_first_language_style(text)
        return detected[2] if detected else None

    multilingual_module.tts_voice_for = _tts_voice_for_first_language

    if performance_module is not None:
        performance_module._detect_style = _style_key_for_text

        def _is_fast_smalltalk_first_language(normalized: str) -> bool:
            if not normalized or len(normalized.split()) > 4:
                return False
            known = {
                "hi", "hello", "hey", "yo", "good morning", "good evening", "good night",
                "thanks", "thank you", "ok", "okay", "yes", "no", "are you there", "you there",
                "namaste", "namaskar", "pranam", "namaskaram", "hola", "mi amor", "buenos dias",
                "buenas noches", "bonjour", "bonjor", "bonjor papi", "salut", "hallo", "guten morgen", "guten abend",
                "ciao", "buongiorno", "gracias", "danke", "merci", "grazie", "nanni", "dime",
            }
            if normalized in known:
                return True
            return _style_key_for_text(normalized) != "english"

        performance_module._is_fast_smalltalk = _is_fast_smalltalk_first_language
