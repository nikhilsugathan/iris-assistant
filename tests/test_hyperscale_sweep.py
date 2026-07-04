"""Core architecture regression tests for IRIS v5.2.5-STABLE."""

from __future__ import annotations

import collections
import json
import os
import sys
import tempfile
import threading
import types
from unittest.mock import MagicMock, patch


def _stub_module(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    return mod


_STUB_NAMES = [
    "pygame",
    "pygame.mixer",
    "pygame.display",
    "pyaudio",
    "speech_recognition",
    "mss",
    "mss.mss",
    "PIL",
    "PIL.Image",
    "faster_whisper",
]
for _dep in _STUB_NAMES:
    sys.modules.setdefault(_dep, _stub_module(_dep))

_pygame_stub = sys.modules["pygame"]
if not hasattr(_pygame_stub, "mixer"):
    _pygame_stub.mixer = sys.modules["pygame.mixer"]
if not hasattr(_pygame_stub, "NOEVENT"):
    _pygame_stub.NOEVENT = 0

_sr_stub = sys.modules["speech_recognition"]
for _attr, _default in [
    ("AudioData", MagicMock),
    ("Recognizer", MagicMock),
    ("Microphone", MagicMock),
    ("UnknownValueError", Exception),
    ("RequestError", Exception),
    ("WaitTimeoutError", Exception),
]:
    if not hasattr(_sr_stub, _attr):
        setattr(_sr_stub, _attr, _default)

import numpy as np  # noqa: E402,F401

from config import Config  # noqa: E402
from core.brain import Brain  # noqa: E402


_VISION_FAIL_MSG = "My vision uplink just failed. I can't see your screen right now."


def _make_brain(available_apis=None) -> Brain:
    brain = Brain.__new__(Brain)
    brain.memory = MagicMock()
    brain.memory.get_context.return_value = []
    brain.llm = None
    brain._call_ctx = threading.local()
    brain.available_apis = available_apis if available_apis is not None else ["gemini"]
    return brain


def _patched_brain(try_vision_return) -> Brain:
    brain = _make_brain(available_apis=["gemini"])
    brain._rewrite_generic_response = MagicMock(return_value=None)
    brain._is_vision_query = MagicMock(return_value=True)
    brain._try_vision = MagicMock(return_value=try_vision_return)
    brain._classify_query = MagicMock(return_value="general")
    brain._save_to_memory = MagicMock()
    return brain


def _make_audio_stub(wav_content: bytes = b"RIFF\x00\x00\x00\x00WAVE") -> MagicMock:
    audio = MagicMock()
    audio.get_wav_data.return_value = wav_content
    return audio


def _make_voice_stub():
    from core.voice import Voice

    voice = Voice.__new__(Voice)
    voice._debug_transcripts = False
    voice._stt_counts = collections.Counter()
    voice.recognizer = MagicMock()
    voice.recognizer.recognize_google.return_value = "google_fallback"
    voice._trace_exception = MagicMock()
    voice._transcribe_google = MagicMock(return_value="google_fallback")
    return voice


def _make_groq_module(text_result: str = "hello world"):
    mock_result = MagicMock()
    mock_result.text = text_result
    mock_create = MagicMock(return_value=mock_result)
    mock_transcriptions = MagicMock()
    mock_transcriptions.create = mock_create
    mock_audio = MagicMock()
    mock_audio.transcriptions = mock_transcriptions
    mock_instance = MagicMock()
    mock_instance.audio = mock_audio
    mock_class = MagicMock(return_value=mock_instance)
    groq_mod = types.ModuleType("groq")
    groq_mod.Groq = mock_class
    return groq_mod, mock_create


class TestVisionAntiHallucination:
    def test_think_vision_failure_returns_exact_string(self):
        brain = _patched_brain(try_vision_return=None)
        assert brain.think("what do you see") == _VISION_FAIL_MSG

    def test_think_vision_failure_does_not_call_text_router(self):
        brain = _patched_brain(try_vision_return=None)
        brain.think("what am i looking at")
        brain._classify_query.assert_not_called()

    def test_think_vision_success_returns_direct_response(self):
        brain = _patched_brain(try_vision_return="A terminal window is open.")
        assert brain.think("describe my screen") == "A terminal window is open."
        brain._classify_query.assert_not_called()

    def test_stream_vision_failure_short_circuits(self):
        brain = _patched_brain(try_vision_return=None)
        assert list(brain.stream_think("look at my screen")) == [_VISION_FAIL_MSG]
        brain._classify_query.assert_not_called()


class TestGroqSTTOffload:
    def test_groq_create_uses_configured_model_and_wav_tuple(self):
        voice = _make_voice_stub()
        wav = b"RIFF\x24\x00\x00\x00WAVEfmt "
        groq_mod, mock_create = _make_groq_module("hello world")
        original_key = Config.GROQ_API_KEY
        original_language = Config.STT_LANGUAGE
        try:
            Config.GROQ_API_KEY = "test-key-abc"
            Config.STT_LANGUAGE = "auto"
            with patch.dict(sys.modules, {"groq": groq_mod}):
                voice._transcribe_groq(_make_audio_stub(wav_content=wav))
        finally:
            Config.GROQ_API_KEY = original_key
            Config.STT_LANGUAGE = original_language

        kwargs = mock_create.call_args.kwargs
        assert kwargs["model"] == "whisper-large-v3-turbo"
        assert kwargs["file"] == ("audio.wav", wav)

    def test_auto_language_omits_groq_language_hint(self):
        voice = _make_voice_stub()
        groq_mod, mock_create = _make_groq_module()
        original_key = Config.GROQ_API_KEY
        original_language = Config.STT_LANGUAGE
        try:
            Config.GROQ_API_KEY = "test-key-abc"
            Config.STT_LANGUAGE = "auto"
            with patch.dict(sys.modules, {"groq": groq_mod}):
                voice._transcribe_groq(_make_audio_stub())
        finally:
            Config.GROQ_API_KEY = original_key
            Config.STT_LANGUAGE = original_language

        assert "language" not in mock_create.call_args.kwargs

    def test_explicit_language_uses_two_char_iso639_hint(self):
        voice = _make_voice_stub()
        groq_mod, mock_create = _make_groq_module()
        original_key = Config.GROQ_API_KEY
        original_language = Config.STT_LANGUAGE
        try:
            Config.GROQ_API_KEY = "test-key-abc"
            Config.STT_LANGUAGE = "de-DE"
            with patch.dict(sys.modules, {"groq": groq_mod}):
                voice._transcribe_groq(_make_audio_stub())
        finally:
            Config.GROQ_API_KEY = original_key
            Config.STT_LANGUAGE = original_language

        assert mock_create.call_args.kwargs["language"] == "de"

    def test_no_groq_key_falls_back_to_google(self):
        voice = _make_voice_stub()
        original_key = Config.GROQ_API_KEY
        Config.GROQ_API_KEY = ""
        try:
            result = voice._transcribe_groq(_make_audio_stub())
        finally:
            Config.GROQ_API_KEY = original_key
        voice._transcribe_google.assert_called_once()
        assert result == "google_fallback"

    def test_groq_api_exception_falls_back_to_google(self):
        voice = _make_voice_stub()
        groq_mod = types.ModuleType("groq")
        groq_mod.Groq = MagicMock(side_effect=RuntimeError("service unavailable"))
        original_key = Config.GROQ_API_KEY
        try:
            Config.GROQ_API_KEY = "test-key-abc"
            with patch.dict(sys.modules, {"groq": groq_mod}):
                result = voice._transcribe_groq(_make_audio_stub())
        finally:
            Config.GROQ_API_KEY = original_key
        voice._transcribe_google.assert_called_once()
        assert result == "google_fallback"

    def test_groq_returns_stripped_transcript(self):
        voice = _make_voice_stub()
        groq_mod, _ = _make_groq_module("  spacey result  ")
        original_key = Config.GROQ_API_KEY
        try:
            Config.GROQ_API_KEY = "test-key-abc"
            with patch.dict(sys.modules, {"groq": groq_mod}):
                result = voice._transcribe_groq(_make_audio_stub())
        finally:
            Config.GROQ_API_KEY = original_key
        assert result == "spacey result"


class TestUTF8Enforcement:
    UNICODE_PAYLOAD = "bullet \u2022 dash \u2014 umlaut \u00fc emoji \U0001F680"

    def test_tempfile_unicode_roundtrip(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", encoding="utf-8", delete=False) as fh:
            fh.write(self.UNICODE_PAYLOAD)
            tmp_path = fh.name
        try:
            with open(tmp_path, "r", encoding="utf-8") as fh:
                assert fh.read() == self.UNICODE_PAYLOAD
        finally:
            os.unlink(tmp_path)

    def test_json_dump_load_unicode(self):
        payload = {"message": self.UNICODE_PAYLOAD, "lang": "de"}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", encoding="utf-8", delete=False) as fh:
            json.dump(payload, fh, ensure_ascii=False)
            tmp_path = fh.name
        try:
            with open(tmp_path, "r", encoding="utf-8") as fh:
                assert json.load(fh) == payload
        finally:
            os.unlink(tmp_path)

    def test_memory_reads_unicode_json(self):
        from core.memory import Memory

        payload = {
            "conversation": [
                {
                    "role": "user",
                    "content": self.UNICODE_PAYLOAD,
                    "timestamp": "2025-01-01T00:00:00",
                }
            ],
            "last_updated": "2025-01-01T00:00:00",
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", encoding="utf-8", delete=False) as fh:
            json.dump(payload, fh, ensure_ascii=False)
            tmp_path = fh.name
        try:
            memory = Memory(tmp_path)
            assert memory.conversation[0]["content"] == self.UNICODE_PAYLOAD
        finally:
            os.unlink(tmp_path)


class TestRuntimeConfig:
    def test_multilingual_stt_defaults_to_auto(self):
        assert Config.STT_LANGUAGE == "auto"

    def test_cloud_stt_model_is_whisper_large_v3_turbo(self):
        assert Config.GROQ_STT_MODEL == "whisper-large-v3-turbo"

    def test_local_language_hint_defaults_to_auto(self):
        assert Config.LOCAL_WHISPER_LANGUAGE_HINT == "auto"

    def test_context_and_gpu_defaults(self):
        assert Config.N_CTX == 16384
        assert Config.N_GPU_LAYERS == -1
        assert Config.USE_FLASH_ATTN is True
