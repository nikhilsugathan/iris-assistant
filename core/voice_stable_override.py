"""Conservative voice playback override."""

from __future__ import annotations

import os
import threading


def _mode() -> str:
    raw = os.getenv("VOICE_PLAYBACK_MODE", "balanced").strip().lower()
    if raw in {"stable", "safe", "no_interrupt", "no-interrupt"}:
        return "stable"
    if raw in {"realtime", "barge", "barge_in", "barge-in"}:
        return "realtime"
    return "balanced"


def apply_voice_stable_override(voice_module) -> None:
    voice_cls = getattr(voice_module, "Voice", None)
    if voice_cls is None or getattr(voice_cls, "_iris_conservative_voice_override", False):
        return

    original_listen_for_interrupt = voice_cls.listen_for_interrupt
    original_start_barge_in_monitor = voice_cls.start_barge_in_monitor
    original_open_rms_stream = voice_cls._open_rms_stream
    original_runtime_summary = voice_cls.runtime_summary

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
        if not words:
            return None

        control_words = {"iris", "aletheia", "stop", "wait", "pause", "quiet", "mute", "hold", "enough", "no", "cancel"}
        control_phrases = {"iris stop", "iris wait", "iris pause", "iris quiet", "iris mute", "aletheia stop", "aletheia wait", "stop talking", "be quiet", "hold on"}

        if len(words) == 1 and words[0] not in control_words:
            self._debug_trace("voice_poll_rejected", reason="single_word_echo_risk", transcript=text, normalized=norm)
            return None
        if len(words) <= 3:
            has_control = any(word in control_words for word in words) or norm in control_phrases
            if not has_control:
                self._debug_trace("voice_poll_rejected", reason="short_non_control_echo_risk", transcript=text, normalized=norm)
                return None
        return text

    def _open_rms_stream(self):
        if _mode() != "realtime":
            self._rms_pa = None
            self._rms_stream = None
            self._debug_trace("rms_stream_skipped", mode=_mode())
            return None
        return original_open_rms_stream(self)

    def listen_for_interrupt(self, timeout=None, phrase_time_limit=None, on_phrase_captured=None):
        playback_mode = _mode()
        if playback_mode == "stable":
            self._debug_trace("voice_poll_skipped", reason="stable_playback_mode")
            return None
        text = original_listen_for_interrupt(
            self,
            timeout=0.35 if timeout is None else timeout,
            phrase_time_limit=1.25 if phrase_time_limit is None else phrase_time_limit,
            on_phrase_captured=None,
        )
        return _safe_text(self, text)

    def start_barge_in_monitor(self, on_barge_in, warmup_sec=0.45):
        playback_mode = _mode()
        if playback_mode in {"stable", "balanced"}:
            return threading.Event()
        cap_raw = os.getenv("BARGE_IN_WARMUP_CAP_SEC", "").strip()
        if cap_raw:
            try:
                warmup_sec = min(float(warmup_sec), float(cap_raw))
            except ValueError:
                pass
        return original_start_barge_in_monitor(self, on_barge_in=on_barge_in, warmup_sec=float(warmup_sec))

    def runtime_summary(self):
        data = original_runtime_summary(self)
        data["voice_playback_mode"] = _mode()
        data["rms_stream_enabled"] = bool(getattr(self, "_rms_stream", None))
        return data

    voice_cls._open_rms_stream = _open_rms_stream
    voice_cls.listen_for_interrupt = listen_for_interrupt
    voice_cls.start_barge_in_monitor = start_barge_in_monitor
    voice_cls.runtime_summary = runtime_summary
    voice_cls._iris_conservative_voice_override = True
    voice_cls._iris_stable_playback_default = False
    voice_cls._iris_balanced_interrupt_default = True
    voice_cls._iris_single_input_default = True
