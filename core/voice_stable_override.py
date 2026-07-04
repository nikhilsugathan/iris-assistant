"""Conservative voice playback and locked-persona TTS race hardening."""

from __future__ import annotations

import os
import threading
from collections import OrderedDict


def _mode() -> str:
    raw = os.getenv("VOICE_PLAYBACK_MODE", "balanced").strip().lower()
    if raw in {"stable", "safe", "no_interrupt", "no-interrupt"}:
        return "stable"
    if raw in {"realtime", "barge", "barge_in", "barge-in"}:
        return "realtime"
    return "balanced"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _persona_voice_locked() -> bool:
    return _env_bool("IRIS_LOCK_TTS_VOICE", True)


def _recognized_multilingual_cue(text: str) -> bool:
    try:
        from .multilingual_patches import detect_language_style

        return detect_language_style(text or "") is not None
    except Exception:
        return False


def _remove_output(path: str) -> None:
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def apply_voice_stable_override(voice_module) -> None:
    voice_cls = getattr(voice_module, "Voice", None)
    if voice_cls is None or getattr(voice_cls, "_iris_conservative_voice_override", False):
        return

    original_listen_for_interrupt = voice_cls.listen_for_interrupt
    original_start_barge_in_monitor = voice_cls.start_barge_in_monitor
    original_open_rms_stream = voice_cls._open_rms_stream
    original_runtime_summary = voice_cls.runtime_summary
    original_speak = voice_cls.speak
    original_start_prefetch = voice_cls.start_prefetch
    original_set_active_voice = voice_cls.set_active_voice
    original_run_edge = voice_cls._run_edge_tts_async

    preferred = str(getattr(voice_module.Config, "TTS_ENGINE", "auto") or "auto").strip().lower()
    if preferred == "auto":
        piper_model = str(getattr(voice_module.Config, "PIPER_MODEL_PATH", "") or "").strip()
        if not (piper_model and os.path.exists(piper_model)):
            voice_module.Config.TTS_ENGINE = "edge"

    def _ensure_persona_state(self) -> None:
        if hasattr(self, "_iris_persona_voice_state_lock"):
            return
        self._iris_persona_voice_state_lock = threading.RLock()
        self._iris_persona_voice_revision = 0
        self._iris_expected_tts_voice = OrderedDict()

    def _remember_expected_voice(self, text: str) -> None:
        if not _persona_voice_locked():
            return
        _ensure_persona_state(self)
        try:
            key = self._clean_for_speech(text)
        except Exception:
            key = str(text or "").strip()
        if not key:
            return
        with self._iris_persona_voice_state_lock:
            expected = (
                self._active_voice_name,
                self._active_voice_rate,
                self._iris_persona_voice_revision,
            )
            self._iris_expected_tts_voice[key] = expected
            self._iris_expected_tts_voice.move_to_end(key)
            while len(self._iris_expected_tts_voice) > 256:
                self._iris_expected_tts_voice.popitem(last=False)

    def _expected_voice(self, text: str):
        if not _persona_voice_locked():
            return None
        _ensure_persona_state(self)
        try:
            key = self._clean_for_speech(text)
        except Exception:
            key = str(text or "").strip()
        with self._iris_persona_voice_state_lock:
            return self._iris_expected_tts_voice.get(key)

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
        multilingual_cue = _recognized_multilingual_cue(norm)

        if len(words) == 1 and words[0] not in control_words and not multilingual_cue:
            self._debug_trace("voice_poll_rejected", reason="single_word_echo_risk", transcript=text, normalized=norm)
            return None
        if len(words) <= 3:
            has_control = any(word in control_words for word in words) or norm in control_phrases
            if not has_control and not multilingual_cue:
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

    def speak(self, text, interrupt=True, on_play_start=None):
        _remember_expected_voice(self, text)
        return original_speak(self, text, interrupt=interrupt, on_play_start=on_play_start)

    def start_prefetch(self, text: str) -> None:
        _remember_expected_voice(self, text)
        return original_start_prefetch(self, text)

    def set_active_voice(self, voice_name: str, voice_rate: str) -> None:
        _ensure_persona_state(self)
        changed = voice_name != self._active_voice_name or voice_rate != self._active_voice_rate
        result = original_set_active_voice(self, voice_name, voice_rate)
        if changed:
            with self._iris_persona_voice_state_lock:
                self._iris_persona_voice_revision += 1
        return result

    def _run_edge_tts_persona_guard(self, text, voice, rate, out_file, *args, **kwargs):
        expected = _expected_voice(self, text)
        if not expected:
            return original_run_edge(self, text, voice, rate, out_file, *args, **kwargs)

        expected_voice, expected_rate, expected_revision = expected
        with self._iris_persona_voice_state_lock:
            current_revision = self._iris_persona_voice_revision
        if expected_revision != current_revision:
            _remove_output(out_file)
            try:
                self._debug_trace(
                    "tts_persona_voice",
                    mode="stale_prefetch_rejected_before_generation",
                    expected_revision=expected_revision,
                    current_revision=current_revision,
                    text=text,
                )
            except Exception:
                pass
            return False

        result = original_run_edge(
            self,
            text,
            expected_voice,
            expected_rate,
            out_file,
            *args,
            **kwargs,
        )

        with self._iris_persona_voice_state_lock:
            current_revision = self._iris_persona_voice_revision
        if expected_revision != current_revision:
            _remove_output(out_file)
            try:
                self._debug_trace(
                    "tts_persona_voice",
                    mode="stale_prefetch_rejected_after_generation",
                    expected_revision=expected_revision,
                    current_revision=current_revision,
                    text=text,
                )
            except Exception:
                pass
            return False
        return result

    def runtime_summary(self):
        data = original_runtime_summary(self)
        _ensure_persona_state(self)
        data["voice_playback_mode"] = _mode()
        data["rms_stream_enabled"] = bool(getattr(self, "_rms_stream", None))
        data["persona_voice_revision"] = self._iris_persona_voice_revision
        data["persona_voice_lock"] = _persona_voice_locked()
        return data

    voice_cls._open_rms_stream = _open_rms_stream
    voice_cls.listen_for_interrupt = listen_for_interrupt
    voice_cls.start_barge_in_monitor = start_barge_in_monitor
    voice_cls.speak = speak
    voice_cls.start_prefetch = start_prefetch
    voice_cls.set_active_voice = set_active_voice
    voice_cls._run_edge_tts_async = _run_edge_tts_persona_guard
    voice_cls.runtime_summary = runtime_summary
    voice_cls._iris_conservative_voice_override = True
    voice_cls._iris_stable_playback_default = False
    voice_cls._iris_balanced_interrupt_default = True
    voice_cls._iris_single_input_default = True
    voice_cls._iris_persona_voice_race_hardening_applied = True
