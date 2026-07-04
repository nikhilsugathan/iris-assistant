from __future__ import annotations

import os
import tempfile
from unittest.mock import patch

os.environ["IRIS_DISABLE_VOICE_IO"] = "true"
os.environ["STT_LANGUAGE"] = "auto"
os.environ["IRIS_STICKY_LANGUAGE_TTS"] = "true"
os.environ["IRIS_MULTILINGUAL_TTS"] = "true"
os.environ["IRIS_LOCK_TTS_VOICE"] = "false"
os.environ["IRIS_MALAYALAM_NATIVE_TTS"] = "false"


class DummyMemory:
    def add(self, *args, **kwargs):
        pass

    def get_context(self, *args, **kwargs):
        return []


class FakeCommunicate:
    calls: list[tuple[str, str, str]] = []

    def __init__(self, text: str, voice: str, rate: str):
        self.text = text
        self.voice = voice
        self.rate = rate
        self.__class__.calls.append((text, voice, rate))

    async def stream(self):
        yield {"type": "audio", "data": b"fake-audio"}


def _synthesize(voice, text: str) -> tuple[str, str, str]:
    FakeCommunicate.calls.clear()
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as handle:
        output_path = handle.name
    try:
        with patch("edge_tts.Communicate", FakeCommunicate):
            ok = voice._run_edge_tts_async(
                text,
                voice._active_voice_name,
                voice._active_voice_rate,
                output_path,
            )
        assert ok is True
        assert FakeCommunicate.calls
        return FakeCommunicate.calls[-1]
    finally:
        try:
            os.remove(output_path)
        except OSError:
            pass


def test_first_language_cue_wins_for_mixed_input():
    import core  # noqa: F401
    from core.multilingual_patches import detect_language_style

    detected = detect_language_style("bonjour papi")
    assert detected is not None
    assert detected[0] == "french"


def test_user_input_language_is_authoritative_for_tts_response():
    import core  # noqa: F401
    from core.brain import Brain
    from core.language_voice_bridge import reset_active_language
    from core.voice import Voice

    reset_active_language()
    brain = Brain(DummyMemory())
    voice = Voice(text_mode=True)

    brain._generation_settings("general", user_input="bonjour mon ami")
    _text, selected_voice, _rate = _synthesize(voice, "Hola amiga, todo bien.")

    assert selected_voice == "fr-FR-DeniseNeural"


def test_explicit_english_switch_restores_default_iris_voice():
    import core  # noqa: F401
    from config import Config
    from core.brain import Brain
    from core.language_voice_bridge import reset_active_language
    from core.voice import Voice

    reset_active_language()
    brain = Brain(DummyMemory())
    voice = Voice(text_mode=True)

    brain._generation_settings("general", user_input="hola amiga")
    assert _synthesize(voice, "Todo bien.")[1] == "es-ES-ElviraNeural"

    brain._generation_settings("general", user_input="switch to English")
    assert _synthesize(voice, "Back in English.")[1] == Config.IRIS_VOICE_NAME


def test_language_voice_patches_are_loaded():
    from core.brain import Brain
    from core.memory import Memory
    from core.voice import Voice

    assert getattr(Brain, "_iris_language_voice_bridge_applied", False)
    assert getattr(Voice, "_iris_language_voice_bridge_applied", False)
    assert getattr(Voice, "_iris_language_voice_enforcer_applied", False)
    assert getattr(Voice, "_iris_local_whisper_multilingual_patch_applied", False)
    assert getattr(Memory, "_iris_memory_hardening_applied", False)
