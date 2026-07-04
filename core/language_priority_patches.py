"""First-cue language priority for mixed-language input.

Distinctive language cues win by their position in the user's text. Ambiguous
words that are also common English are treated as weak cues and cannot switch a
conversation by themselves.
"""

from __future__ import annotations

import re
from typing import Optional

_MALAYALAM_SCRIPT_RE = re.compile(r"[\u0D00-\u0D7F]")

_STRONG_RULES = [
    (
        "spanish",
        re.compile(
            r"\b("
            r"hola|amor|mi\s+amor|papi|gracias|buenos|buenas|dime|necesito|quiero|puedes|"
            r"como|cómo|que|qué|por\s+favor|vale|español|espanol|spanish|"
            r"banco|banko|bebé|bebe|bebes|bebis|estas|estás"
            r")\b",
            re.IGNORECASE,
        ),
        "Spanish",
        "es-ES-ElviraNeural",
    ),
    (
        "german",
        re.compile(
            r"\b(hallo|guten|morgen|abend|danke|bitte|kannst|können|wie|warum|ich|du|aufgabe|weiter|ja|nein|deutsch|german|was\s+ist)\b",
            re.IGNORECASE,
        ),
        "German",
        "de-DE-KatjaNeural",
    ),
    (
        "french",
        re.compile(
            r"\b(bonjour|bonjor|salut|merci|s'il|sil|vous|plaît|plait|peux|pouvez|quoi|pourquoi|oui|non|bonsoir|français|francais|french|comment\s+(?:ça|ca))\b",
            re.IGNORECASE,
        ),
        "French",
        "fr-FR-DeniseNeural",
    ),
    (
        "italian",
        re.compile(
            r"\b(ciao|buongiorno|grazie|prego|puoi|cosa|perché|perche|italiano|italian|come\s+stai)\b",
            re.IGNORECASE,
        ),
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

_WEAK_RULES = [
    (
        "spanish",
        re.compile(r"\b(el|la|los|las|un|una|sí|si)\b", re.IGNORECASE),
        "Spanish",
        "es-ES-ElviraNeural",
    ),
    (
        "german",
        re.compile(r"\b(was)\b", re.IGNORECASE),
        "German",
        "de-DE-KatjaNeural",
    ),
    (
        "french",
        re.compile(r"\b(comment)\b", re.IGNORECASE),
        "French",
        "fr-FR-DeniseNeural",
    ),
    (
        "italian",
        re.compile(r"\b(come|sì|si)\b", re.IGNORECASE),
        "Italian",
        "it-IT-ElsaNeural",
    ),
]

_ENGLISH_COLLISION_CUES = {"was", "comment", "come", "si", "sí", "sì"}


def _first_match(rules, sample: str):
    best = None
    for key, pattern, label, voice in rules:
        match = pattern.search(sample)
        if not match:
            continue
        candidate = (match.start(), -(match.end() - match.start()), key, label, voice, match.group(0))
        if best is None or candidate < best:
            best = candidate
    return best


def detect_first_language_style(text: str) -> Optional[tuple[str, str, str]]:
    sample = text or ""
    if _MALAYALAM_SCRIPT_RE.search(sample):
        return "malayalam", "Malayalam", "ml-IN-SobhanaNeural"

    strong = _first_match(_STRONG_RULES, sample)
    if strong is not None:
        _start, _neg_len, key, label, voice, _cue = strong
        return key, label, voice

    weak_matches = []
    for key, pattern, label, voice in _WEAK_RULES:
        matches = list(pattern.finditer(sample))
        for match in matches:
            weak_matches.append((match.start(), key, label, voice, match.group(0).lower()))

    if not weak_matches:
        return None

    languages = {item[1] for item in weak_matches}
    if len(languages) != 1:
        return None

    weak_matches.sort(key=lambda item: item[0])
    _start, key, label, voice, cue = weak_matches[0]
    word_count = len(re.findall(r"\b\w+\b", sample, flags=re.UNICODE))
    if len(weak_matches) >= 2:
        return key, label, voice
    if word_count <= 2 and cue not in _ENGLISH_COLLISION_CUES:
        return key, label, voice
    return None


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
