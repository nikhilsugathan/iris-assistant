"""Conservative voice playback override.

This module favors audible, stable TTS playback over aggressive interruption.
It is loaded after the runtime patch layer.
"""

from __future__ import annotations

import os


def apply_voice_stable_override(voice_module) -> None:
    voice_cls = getattr(voice_module, "Voice", None)
    if voice_cls is None or getattr(voice_cls, "_iris_conservative_voice_override", False):
        return

    original_listen_for_interrupt = voice_cls.listen_for_interrupt
    original_start_barge_in_monitor = voice_cls.start_barge_in_monitor

    # Keep Edge streaming enabled when TTS is effectively Edge via auto fallback.
    preferred = str(getattr(voice_module.Config, "TTS_ENGINE", "auto") or "auto").strip().lower()
    if preferred == "auto":
        piper_model = str(getattr(voice_module.Config, "PIPER_MODEL_PATH", "") or "").strip()
        has_piper = bool(piper_model and os.path.exists(piper_model))
        if not has_piper:
            voice_module.Config.TTS_ENGINE = "edge"

    def _interrupt_text_safe(self, text):
        if not text:
            return None
        try:
            if self.should_ignore_transcript(text):
                self._debug_trace("interrupt_rejected", reason="ignore_filter", transcript=text)
                return None
        except Exception:
            pass
        try:
            norm = self._normalize_text(text)
        except Exception:
            norm = str(text or "").lower().strip()
        words = norm.split() if norm else []
        allowed_one_word = {
            "iris", "aletheia", "stop", "wait", "pause", "quiet", "mute", "hold", "enough", "no",
        }
        if len(words) == 1 and words[0] not in allowed_one_word:
            self._debug_trace("interrupt_rejected", reason="single_word_echo_risk", transcript=text, normalized=norm)
            return None
        return text

    def listen_for_interrupt(self, timeout=None, phrase_time_limit=None, on_phrase_captured=None):
        # Do not run any raw-RMS auto-cut by default. Laptop speaker echo can look
        # like speech and stop playback too early. This still listens for real
        # interrupt phrases through the existing STT path, but filters risky echo
        # before main.py receives it.
        text = original_listen_for_interrupt(
            self,
            timeout=0.2 if timeout is None else timeout,
            phrase_time_limit=1.0 if phrase_time_limit is None else phrase_time_limit,
            on_phrase_captured=None,
        )
        return _interrupt_text_safe(self, text)

    def start_barge_in_monitor(self, on_barge_in, warmup_sec=0.45):
        # Preserve caller warmup unless explicitly tuned by env. This avoids
        # thinking-cue or speaker echo cancelling generation too early.
        cap_raw = os.getenv("BARGE_IN_WARMUP_CAP_SEC", "").strip()
        if cap_raw:
            try:
                warmup_sec = min(float(warmup_sec), float(cap_raw))
            except ValueError:
                pass
        return original_start_barge_in_monitor(self, on_barge_in=on_barge_in, warmup_sec=float(warmup_sec))

    voice_cls.listen_for_interrupt = listen_for_interrupt
    voice_cls.start_barge_in_monitor = start_barge_in_monitor
    voice_cls._iris_conservative_voice_override = True
