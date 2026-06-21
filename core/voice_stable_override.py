"""Conservative voice playback override."""

from __future__ import annotations

import os
import threading


def _enabled(name: str, default: str = "true") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def apply_voice_stable_override(voice_module) -> None:
    voice_cls = getattr(voice_module, "Voice", None)
    if voice_cls is None or getattr(voice_cls, "_iris_conservative_voice_override", False):
        return

    original_listen_for_interrupt = voice_cls.listen_for_interrupt
    original_start_barge_in_monitor = voice_cls.start_barge_in_monitor

    preferred = str(getattr(voice_module.Config, "TTS_ENGINE", "auto") or "auto").strip().lower()
    if preferred == "auto":
        piper_model = str(getattr(voice_module.Config, "PIPER_MODEL_PATH", "") or "").strip()
        if not (piper_model and os.path.exists(piper_model)):
            voice_module.Config.TTS_ENGINE = "edge"

    def _safe_text(self, text):
        if not text:
            return None
        try:
            if self.should_ignore_transcript(text):
                self._debug_trace("voice_poll_rejected", reason="ignore_filter", transcript=text)
                return None
        except Exception:
            pass
        try:
            norm = self._normalize_text(text)
        except Exception:
            norm = str(text or "").lower().strip()
        words = norm.split() if norm else []
        one_word_controls = {"iris", "aletheia", "stop", "wait", "pause", "quiet", "mute", "hold", "enough", "no"}
        if len(words) == 1 and words[0] not in one_word_controls:
            self._debug_trace("voice_poll_rejected", reason="single_word_echo_risk", transcript=text, normalized=norm)
            return None
        return text

    def listen_for_interrupt(self, timeout=None, phrase_time_limit=None, on_phrase_captured=None):
        if _enabled("VOICE_STABLE_PLAYBACK", "true"):
            self._debug_trace("voice_poll_skipped", reason="stable_playback_mode")
            return None
        text = original_listen_for_interrupt(
            self,
            timeout=0.2 if timeout is None else timeout,
            phrase_time_limit=1.0 if phrase_time_limit is None else phrase_time_limit,
            on_phrase_captured=None,
        )
        return _safe_text(self, text)

    def start_barge_in_monitor(self, on_barge_in, warmup_sec=0.45):
        if _enabled("VOICE_STABLE_PLAYBACK", "true"):
            return threading.Event()
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
    voice_cls._iris_stable_playback_default = True
