"""Speech-text sanitizer for IRIS TTS."""

from __future__ import annotations

import re
import unicodedata

_ALIAS_RE = re.compile(r"\s*:[a-z0-9_+\-]+:\s*", re.IGNORECASE)
_SPACE_RE = re.compile(r"\s+")


def _is_visual_symbol(char: str) -> bool:
    category = unicodedata.category(char)
    if category in {"So", "Sk"}:
        return True
    if char in {"\ufe0e", "\ufe0f", "\u200d", "\u20e3"}:
        return True
    return False


def sanitize_for_tts(text: str) -> str:
    if not text:
        return ""
    cleaned = _ALIAS_RE.sub(" ", text)
    cleaned = "".join(" " if _is_visual_symbol(ch) else ch for ch in cleaned)
    cleaned = _SPACE_RE.sub(" ", cleaned)
    cleaned = re.sub(r"\s+([,.!?;:])", r"\1", cleaned)
    return cleaned.strip()


def apply_tts_sanitizer(voice_module) -> None:
    voice_cls = getattr(voice_module, "Voice", None)
    if voice_cls is None or getattr(voice_cls, "_iris_tts_sanitizer_applied", False):
        return

    original_clean = voice_cls._clean_for_speech

    def _clean_for_speech_sanitized(self, text):
        return sanitize_for_tts(original_clean(self, text))

    voice_cls._clean_for_speech = _clean_for_speech_sanitized
    voice_cls._iris_tts_sanitizer_applied = True
