"""
tests/test_hyperscale_sweep.py
==============================
Hyper-Scale Regression Suite — verifies four architectural pillars
introduced in the v5.2.5-STABLE zero-cost sweep:

  Group 1 — Vision anti-hallucination  (Phase 7 short-circuit)
  Group 2 — Groq cloud STT offload     (zero local VRAM)
  Group 3 — UTF-8 enforcement          (text I/O round-trips)
  Group 4 — VRAM & hardware config     (config constant assertions)

Run with:  pytest tests/test_hyperscale_sweep.py -v
"""
from __future__ import annotations

import collections
import json
import os
import sys
import tempfile
import threading
import types
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Stub heavy optional dependencies before any IRIS module is imported.
# This mirrors the isolation pattern in test_concurrency_smoke.py and avoids
# PyAudio / pygame hardware requirements on CI or headless machines.
# ---------------------------------------------------------------------------

def _stub_module(name: str, **attrs) -> types.ModuleType:
    """Return a lightweight ModuleType stub pre-populated with attrs."""
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
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

# Wire pygame.mixer onto the pygame stub so ``from pygame import mixer`` works.
_pygame_stub = sys.modules["pygame"]
if not hasattr(_pygame_stub, "mixer"):
    _pygame_stub.mixer = sys.modules["pygame.mixer"]
if not hasattr(_pygame_stub, "NOEVENT"):
    _pygame_stub.NOEVENT = 0

# speech_recognition needs concrete exception types & class stubs.
_sr_stub = sys.modules["speech_recognition"]
for _attr, _default in [
    ("AudioData",        MagicMock),
    ("Recognizer",       MagicMock),
    ("Microphone",       MagicMock),
    ("UnknownValueError", Exception),
    ("RequestError",     Exception),
    ("WaitTimeoutError", Exception),
]:
    if not hasattr(_sr_stub, _attr):
        setattr(_sr_stub, _attr, _default)

# ---------------------------------------------------------------------------
# IRIS module imports — safe now that stubs are in place.
# ---------------------------------------------------------------------------
import numpy as np  # noqa: E402

from config import Config       # noqa: E402
from core.brain import Brain    # noqa: E402

# The exact hard-coded string emitted by the vision short-circuit.
# Defined here so tests and production code share a single source of truth.
_VISION_FAIL_MSG = "My vision uplink just failed. I can't see your screen right now."


# ---------------------------------------------------------------------------
# Shared factory helpers
# ---------------------------------------------------------------------------

def _make_brain(available_apis=None) -> Brain:
    """Return a Brain instance that bypasses hardware-dependent __init__."""
    b = Brain.__new__(Brain)
    b.memory = MagicMock()
    b.memory.get_context.return_value = []
    b.llm = None
    b._call_ctx = threading.local()
    b.available_apis = (
        available_apis if available_apis is not None else ["gemini"]
    )
    return b


def _patched_brain(try_vision_return) -> Brain:
    """Return a Brain with the entire vision pipeline stubbed.

    _rewrite_generic_response → None   (skips local-rewrite path)
    _is_vision_query           → True  (always enters vision branch)
    _try_vision                → <arg> (caller controls success/fail)
    _classify_query            → MagicMock (asserted NOT called on short-circuit)
    _save_to_memory            → MagicMock (tracked for memory persistence tests)
    """
    b = _make_brain(available_apis=["gemini"])
    b._rewrite_generic_response = MagicMock(return_value=None)
    b._is_vision_query          = MagicMock(return_value=True)
    b._try_vision               = MagicMock(return_value=try_vision_return)
    b._classify_query           = MagicMock(return_value="general")
    b._save_to_memory           = MagicMock()
    return b


def _make_audio_stub(wav_content: bytes = b"RIFF\x00\x00\x00\x00WAVE") -> MagicMock:
    """Return a speech_recognition.AudioData-compatible stub."""
    audio = MagicMock()
    audio.get_wav_data.return_value = wav_content
    return audio


def _make_voice_stub():
    """Return a minimal Voice instance that bypasses hardware __init__."""
    from core.voice import Voice  # imported here to allow stub setup above

    v = Voice.__new__(Voice)
    v._debug_transcripts = False
    v._stt_counts        = collections.Counter()
    v.recognizer         = MagicMock()
    v.recognizer.recognize_google.return_value = "google_fallback"
    # Instance-level overrides so method calls don't touch real hardware.
    v._trace_exception   = MagicMock()
    v._transcribe_google = MagicMock(return_value="google_fallback")
    return v


def _make_groq_module(text_result: str = "hello world"):
    """Build a synthetic ``groq`` module and return (module, create_mock).

    The ``create_mock`` is the ``transcriptions.create`` MagicMock so
    individual tests can assert on call arguments without rebuilding the
    entire mock chain.
    """
    mock_result          = MagicMock()
    mock_result.text     = text_result

    mock_create          = MagicMock(return_value=mock_result)
    mock_transcriptions  = MagicMock()
    mock_transcriptions.create = mock_create

    mock_audio           = MagicMock()
    mock_audio.transcriptions = mock_transcriptions

    mock_instance        = MagicMock()
    mock_instance.audio  = mock_audio

    MockGroqClass        = MagicMock(return_value=mock_instance)

    groq_mod             = types.ModuleType("groq")
    groq_mod.Groq        = MockGroqClass

    return groq_mod, mock_create


# ===========================================================================
# Group 1 — Vision Anti-Hallucination (Phase 7)
# ===========================================================================

class TestVisionAntiHallucination:
    """The Phase 7 vision intercept must never fall through to the text ensemble.

    When _try_vision returns None (screen capture failed / API unavailable),
    think() and stream_think() must both return the exact hardcoded failure
    string and skip _classify_query entirely.  Routing a vision query to a
    text-only LLM would produce a confident hallucination about the screen.
    """

    # ── think() path ─────────────────────────────────────────────────────────

    def test_think_vision_failure_returns_exact_string(self):
        """think() must return the hardcoded fail msg when _try_vision → None."""
        b = _patched_brain(try_vision_return=None)
        result = b.think("what do you see")
        assert result == _VISION_FAIL_MSG

    def test_think_vision_failure_does_not_call_classify_query(self):
        """Text router (_classify_query) must never be entered on vision failure."""
        b = _patched_brain(try_vision_return=None)
        b.think("what am i looking at")
        b._classify_query.assert_not_called()

    def test_think_vision_success_returns_vision_response(self):
        """A successful vision call returns the model response directly."""
        b = _patched_brain(try_vision_return="A terminal window is open.")
        assert b.think("what do you see") == "A terminal window is open."

    def test_think_vision_success_does_not_call_classify_query(self):
        """Successful vision response also short-circuits the text router."""
        b = _patched_brain(try_vision_return="some screen content")
        b.think("describe my screen")
        b._classify_query.assert_not_called()

    def test_think_vision_failure_saves_error_to_memory(self):
        """Failed vision response must still be persisted to conversation memory."""
        b = _patched_brain(try_vision_return=None)
        b.think("what is on my screen")
        calls_str = str(b._save_to_memory.call_args_list)
        assert _VISION_FAIL_MSG in calls_str, (
            f"Expected _VISION_FAIL_MSG in _save_to_memory calls.\nGot: {calls_str}"
        )

    # ── stream_think() path ──────────────────────────────────────────────────

    def test_stream_think_vision_failure_yields_exact_string(self):
        """stream_think() must yield exactly [_VISION_FAIL_MSG] on failure."""
        b = _patched_brain(try_vision_return=None)
        chunks = list(b.stream_think("what do you see"))
        assert chunks == [_VISION_FAIL_MSG], (
            f"Expected [{_VISION_FAIL_MSG!r}], got {chunks!r}"
        )

    def test_stream_think_vision_failure_does_not_call_classify_query(self):
        """stream_think() must not enter text routing on vision failure."""
        b = _patched_brain(try_vision_return=None)
        list(b.stream_think("look at my screen"))
        b._classify_query.assert_not_called()


# ===========================================================================
# Group 2 — Groq Cloud STT Offload
# ===========================================================================

class TestGroqSTTOffload:
    """_transcribe_groq() must call the Groq API with the correct parameters
    and fall back to Google STT gracefully on any failure or missing key.

    The groq package is mocked via sys.modules injection because it is an
    optional runtime dependency (imported dynamically inside the method).
    """

    def test_groq_create_called_with_correct_model(self):
        """transcriptions.create must be invoked with model='whisper-large-v3-turbo'."""
        v            = _make_voice_stub()
        groq_mod, mock_create = _make_groq_module("hello world")

        with patch.dict(sys.modules, {"groq": groq_mod}):
            Config.GROQ_API_KEY = "test-key-abc"
            try:
                v._transcribe_groq(_make_audio_stub())
            finally:
                Config.GROQ_API_KEY = ""

        mock_create.assert_called_once()
        model_arg = mock_create.call_args.kwargs.get("model")
        assert model_arg == "whisper-large-v3-turbo", (
            f"Expected model='whisper-large-v3-turbo', got {model_arg!r}"
        )

    def test_groq_create_receives_wav_file_tuple(self):
        """The ``file`` argument must be a ('audio.wav', <bytes>) tuple."""
        v            = _make_voice_stub()
        dummy_wav    = b"RIFF\x24\x00\x00\x00WAVEfmt "
        groq_mod, mock_create = _make_groq_module()

        with patch.dict(sys.modules, {"groq": groq_mod}):
            Config.GROQ_API_KEY = "test-key-abc"
            try:
                v._transcribe_groq(_make_audio_stub(wav_content=dummy_wav))
            finally:
                Config.GROQ_API_KEY = ""

        file_arg = mock_create.call_args.kwargs.get("file")
        assert isinstance(file_arg, tuple), (
            f"file arg must be a tuple, got {type(file_arg)}"
        )
        assert file_arg[0] == "audio.wav", f"Expected 'audio.wav', got {file_arg[0]!r}"
        assert file_arg[1] == dummy_wav,   "WAV bytes do not match audio stub content"

    def test_groq_language_is_two_char_iso639(self):
        """STT_LANGUAGE='en-US' must be truncated to 'en' (ISO 639-1) for Groq."""
        v            = _make_voice_stub()
        groq_mod, mock_create = _make_groq_module()

        with patch.dict(sys.modules, {"groq": groq_mod}):
            Config.GROQ_API_KEY = "test-key-abc"
            try:
                v._transcribe_groq(_make_audio_stub())
            finally:
                Config.GROQ_API_KEY = ""

        lang_arg = mock_create.call_args.kwargs.get("language")
        assert lang_arg == "en",    f"Expected 'en', got {lang_arg!r}"
        assert len(lang_arg) == 2,  f"Language must be 2 chars (ISO 639-1), got {lang_arg!r}"

    def test_no_groq_key_falls_back_to_google(self):
        """When GROQ_API_KEY is empty, _transcribe_google must be called instead."""
        v            = _make_voice_stub()
        original_key = Config.GROQ_API_KEY
        Config.GROQ_API_KEY = ""
        try:
            result = v._transcribe_groq(_make_audio_stub())
        finally:
            Config.GROQ_API_KEY = original_key

        v._transcribe_google.assert_called_once()
        assert result == "google_fallback"

    def test_groq_api_exception_falls_back_to_google(self):
        """Any exception from the Groq client must fall back to Google silently."""
        v        = _make_voice_stub()
        groq_mod = types.ModuleType("groq")
        groq_mod.Groq = MagicMock(side_effect=RuntimeError("503 Service Unavailable"))

        with patch.dict(sys.modules, {"groq": groq_mod}):
            Config.GROQ_API_KEY = "test-key-abc"
            try:
                result = v._transcribe_groq(_make_audio_stub())
            finally:
                Config.GROQ_API_KEY = ""

        v._transcribe_google.assert_called_once()
        assert result == "google_fallback"

    def test_groq_returns_stripped_transcript(self):
        """Leading/trailing whitespace in result.text must be stripped."""
        v            = _make_voice_stub()
        groq_mod, _  = _make_groq_module("  spacey result  ")

        with patch.dict(sys.modules, {"groq": groq_mod}):
            Config.GROQ_API_KEY = "test-key-abc"
            try:
                result = v._transcribe_groq(_make_audio_stub())
            finally:
                Config.GROQ_API_KEY = ""

        assert result == "spacey result", (
            f"Expected stripped transcript, got {result!r}"
        )


# ===========================================================================
# Group 3 — UTF-8 Enforcement
# ===========================================================================

class TestUTF8Enforcement:
    """Text I/O must round-trip multi-language and supplementary-plane content
    without corruption.  These tests also serve as a smoke-check that the
    Memory module's _load() call uses encoding='utf-8'.
    """

    # German bullet + em-dash + umlaut + rocket emoji (U+1F680 is outside BMP)
    UNICODE_PAYLOAD = "bullet \u2022 dash \u2014 umlaut \u00fc emoji \U0001F680"

    def test_tempfile_unicode_roundtrip(self):
        """Writing and reading a UTF-8 text file must produce byte-perfect equality."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", encoding="utf-8", delete=False
        ) as fh:
            fh.write(self.UNICODE_PAYLOAD)
            tmp_path = fh.name
        try:
            with open(tmp_path, "r", encoding="utf-8") as fh:
                recovered = fh.read()
            assert recovered == self.UNICODE_PAYLOAD, (
                f"UTF-8 round-trip mismatch:\n"
                f"  wrote: {self.UNICODE_PAYLOAD!r}\n"
                f"  read:  {recovered!r}"
            )
        finally:
            os.unlink(tmp_path)

    def test_json_dump_load_unicode(self):
        """JSON serialisation with ensure_ascii=False must be lossless."""
        payload = {"message": self.UNICODE_PAYLOAD, "lang": "de"}
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", encoding="utf-8", delete=False
        ) as fh:
            json.dump(payload, fh, ensure_ascii=False)
            tmp_path = fh.name
        try:
            with open(tmp_path, "r", encoding="utf-8") as fh:
                recovered = json.load(fh)
            assert recovered == payload
        finally:
            os.unlink(tmp_path)

    def test_memory_module_reads_unicode_json(self):
        """Memory._load() must restore unicode conversation turns without corruption.

        This is the critical guard for IRIS's conversation memory: if _load()
        does not use encoding='utf-8', any non-ASCII content in stored history
        would be silently corrupted or raise a UnicodeDecodeError on Windows.
        """
        from core.memory import Memory  # import after stubs are in place

        json_struct = {
            "conversation": [
                {
                    "role":      "user",
                    "content":   self.UNICODE_PAYLOAD,
                    "timestamp": "2025-01-01T00:00:00",
                }
            ],
            "last_updated": "2025-01-01T00:00:00",
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", encoding="utf-8", delete=False
        ) as fh:
            json.dump(json_struct, fh, ensure_ascii=False)
            tmp_path = fh.name

        try:
            mem = Memory(tmp_path)
            assert mem.conversation, "Memory.conversation must be non-empty after load"
            first_turn = mem.conversation[0]
            assert first_turn["content"] == self.UNICODE_PAYLOAD, (
                f"Unicode content corrupted in Memory._load():\n"
                f"  expected: {self.UNICODE_PAYLOAD!r}\n"
                f"  got:      {first_turn['content']!r}"
            )
        finally:
            os.unlink(tmp_path)

    def test_high_plane_emoji_preserved(self):
        """Characters above U+FFFF (supplementary plane) must survive I/O intact."""
        emoji_str = "\U0001F680\U0001F916\U0001F4BB"  # 🚀🤖💻
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", encoding="utf-8", delete=False
        ) as fh:
            fh.write(emoji_str)
            tmp_path = fh.name
        try:
            with open(tmp_path, "r", encoding="utf-8") as fh:
                recovered = fh.read()
            assert recovered == emoji_str, (
                f"Supplementary-plane emoji corrupted:\n"
                f"  expected: {emoji_str!r}\n"
                f"  got:      {recovered!r}"
            )
        finally:
            os.unlink(tmp_path)


# ===========================================================================
# Group 4 — VRAM & Hardware Config
# ===========================================================================

class TestVRAMHardwareConfig:
    """Config constants introduced in the zero-cost architectural sweep.

    These are regression guards: if any constant is accidentally reverted
    (e.g. N_CTX back to 8192, N_GPU_LAYERS back to 99) the corresponding
    test fails immediately, making the regression visible in CI before the
    build is promoted.
    """

    def test_n_ctx_is_16384(self):
        """Context window must be 16 384 tokens (post-Whisper-VRAM reclaim).

        Whisper VRAM (~1.6 GB) freed by the Groq STT migration provides
        headroom to double the LLM context from 8 192 → 16 384 at no cost.
        """
        assert Config.N_CTX == 16384, (
            f"N_CTX regression — expected 16384, got {Config.N_CTX}"
        )

    def test_n_gpu_layers_is_minus_one(self):
        """N_GPU_LAYERS must be -1 (canonical llama-cpp-python all-GPU constant).

        Prior value 99 worked but was an undocumented proxy.  -1 is the
        official llama-cpp-python signal for 'push every layer to GPU'.
        """
        assert Config.N_GPU_LAYERS == -1, (
            f"N_GPU_LAYERS regression — expected -1, got {Config.N_GPU_LAYERS}"
        )

    def test_groq_vision_model_is_llama_32_vision(self):
        """GROQ_VISION_MODEL must be 'meta-llama/llama-4-scout-17b-16e-instruct'.

        Both llama-3.2-11b-vision-preview and llama-3.2-90b-vision-preview were
        decommissioned by Groq in April 2025.  The current active vision model is
        Llama 4 Scout — multimodal, 128 k context, available under the existing
        GROQ_API_KEY with no new credentials required.
        """
        assert Config.GROQ_VISION_MODEL == "meta-llama/llama-4-scout-17b-16e-instruct", (
            f"Groq vision model regression — expected 'meta-llama/llama-4-scout-17b-16e-instruct', "
            f"got {Config.GROQ_VISION_MODEL!r}"
        )

    def test_groq_stt_model_is_whisper_large_v3_turbo(self):
        """GROQ_STT_MODEL must be 'whisper-large-v3-turbo' (cloud Whisper via Groq)."""
        assert Config.GROQ_STT_MODEL == "whisper-large-v3-turbo", (
            f"Groq STT model regression — expected 'whisper-large-v3-turbo', "
            f"got {Config.GROQ_STT_MODEL!r}"
        )

    def test_groq_model_is_llama4_scout(self):
        """GROQ_MODEL must be the fully-qualified Llama 4 Scout model ID used by Groq."""
        assert Config.GROQ_MODEL == "meta-llama/llama-4-scout-17b-16e-instruct", (
            f"Groq LLM model regression — expected 'meta-llama/llama-4-scout-17b-16e-instruct', "
            f"got {Config.GROQ_MODEL!r}"
        )

    def test_use_flash_attn_is_true(self):
        """Flash attention must default to True for RTX 5050 Mobile throughput."""
        assert Config.USE_FLASH_ATTN is True, (
            f"USE_FLASH_ATTN regression — expected True, got {Config.USE_FLASH_ATTN}"
        )
