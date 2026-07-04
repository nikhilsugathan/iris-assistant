from __future__ import annotations

import os
from types import SimpleNamespace


class DummyConfig:
    TTS_ENGINE = "edge"
    PIPER_MODEL_PATH = ""


def _patched_voice_class():
    from core.voice_stable_override import apply_voice_stable_override

    class DummyVoice:
        def __init__(self):
            self._active_voice_name = "IrisVoice"
            self._active_voice_rate = "+1%"
            self._rms_stream = None
            self.interrupt_text = None
            self.edge_calls = []
            self.trace = []

        def listen_for_interrupt(self, timeout=None, phrase_time_limit=None, on_phrase_captured=None):
            return self.interrupt_text

        def start_barge_in_monitor(self, on_barge_in, warmup_sec=0.45):
            return "original-monitor"

        def _open_rms_stream(self):
            self._rms_stream = object()
            return self._rms_stream

        def runtime_summary(self):
            return {}

        def speak(self, text, interrupt=True, on_play_start=None):
            return text

        def start_prefetch(self, text):
            return None

        def set_active_voice(self, voice_name, voice_rate):
            self._active_voice_name = voice_name
            self._active_voice_rate = voice_rate

        def _run_edge_tts_async(self, text, voice, rate, out_file, *args, **kwargs):
            self.edge_calls.append((text, voice, rate, out_file))
            with open(out_file, "wb") as handle:
                handle.write(b"audio")
            return True

        def _clean_for_speech(self, text):
            return str(text or "").strip()

        def should_ignore_transcript(self, text):
            return str(text or "").strip().lower() == "urn"

        def _normalize_text(self, text):
            return " ".join(str(text or "").lower().split())

        def _debug_trace(self, event, **fields):
            self.trace.append((event, fields))

    module = SimpleNamespace(Voice=DummyVoice, Config=DummyConfig)
    apply_voice_stable_override(module)
    return DummyVoice


def test_balanced_interrupt_filter_allows_short_multilingual_cues(monkeypatch):
    monkeypatch.setenv("VOICE_PLAYBACK_MODE", "balanced")
    Voice = _patched_voice_class()
    voice = Voice()

    for cue in ("hola", "dime", "mi amor", "merci", "danke"):
        voice.interrupt_text = cue
        assert voice.listen_for_interrupt() == cue


def test_balanced_interrupt_filter_keeps_unknown_short_noise_blocked(monkeypatch):
    monkeypatch.setenv("VOICE_PLAYBACK_MODE", "balanced")
    Voice = _patched_voice_class()
    voice = Voice()

    for noise in ("urn", "rifle", "aloft"):
        voice.interrupt_text = noise
        assert voice.listen_for_interrupt() is None


def test_locked_persona_voice_is_forced_for_expected_text(tmp_path, monkeypatch):
    monkeypatch.setenv("IRIS_LOCK_TTS_VOICE", "true")
    Voice = _patched_voice_class()
    voice = Voice()
    voice.speak("hello")

    output = tmp_path / "voice.mp3"
    assert voice._run_edge_tts_async("hello", "WrongVoice", "+9%", str(output)) is True

    assert voice.edge_calls[-1][1] == "IrisVoice"
    assert voice.edge_calls[-1][2] == "+1%"
    assert output.exists()


def test_prefetch_from_old_persona_is_rejected_after_voice_switch(tmp_path, monkeypatch):
    monkeypatch.setenv("IRIS_LOCK_TTS_VOICE", "true")
    Voice = _patched_voice_class()
    voice = Voice()
    voice.start_prefetch("shared phrase")
    voice.set_active_voice("AletheiaVoice", "+0%")

    output = tmp_path / "stale.mp3"
    result = voice._run_edge_tts_async(
        "shared phrase",
        "AletheiaVoice",
        "+0%",
        str(output),
    )

    assert result is False
    assert voice.edge_calls == []
    assert not output.exists()


def test_runtime_summary_reports_persona_voice_lock(monkeypatch):
    monkeypatch.setenv("IRIS_LOCK_TTS_VOICE", "true")
    Voice = _patched_voice_class()
    voice = Voice()

    summary = voice.runtime_summary()

    assert summary["persona_voice_lock"] is True
    assert summary["persona_voice_revision"] == 0
