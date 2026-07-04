from __future__ import annotations

import os
import tempfile
from unittest.mock import patch

os.environ["IRIS_DISABLE_VOICE_IO"] = "true"
os.environ["STT_LANGUAGE"] = "auto"
os.environ["IRIS_STICKY_LANGUAGE_TTS"] = "false"
os.environ["IRIS_MULTILINGUAL_TTS"] = "false"
os.environ["IRIS_LOCK_TTS_VOICE"] = "true"
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


def test_default_iris_voice_is_preserved_across_languages():
    import core  # noqa: F401
    from config import Config
    from core.brain import Brain
    from core.language_voice_bridge import reset_active_language
    from core.voice import Voice

    reset_active_language()
    brain = Brain(DummyMemory())
    voice = Voice(text_mode=True)

    brain._generation_settings("general", user_input="bonjour mon ami")
    assert _synthesize(voice, "Bonjour. Comment ça va?")[1] == Config.IRIS_VOICE_NAME

    brain._generation_settings("general", user_input="hola amiga")
    assert _synthesize(voice, "Todo bien, mi amor.")[1] == Config.IRIS_VOICE_NAME

    brain._generation_settings("general", user_input="guten morgen")
    assert _synthesize(voice, "Guten Morgen. Was steht an?")[1] == Config.IRIS_VOICE_NAME


def test_locked_language_mode_preserves_aletheia_persona_voice():
    import core  # noqa: F401
    from config import Config
    from core.brain import Brain
    from core.language_voice_bridge import reset_active_language
    from core.voice import Voice

    reset_active_language()
    brain = Brain(DummyMemory())
    voice = Voice(text_mode=True)
    voice.set_active_voice(Config.ALETHEIA_VOICE_NAME, Config.ALETHEIA_VOICE_RATE)

    brain._generation_settings("general", user_input="hola amiga")
    assert _synthesize(voice, "Todo bien.")[1] == Config.ALETHEIA_VOICE_NAME


def test_explicit_opt_in_enables_language_specific_voice():
    import core  # noqa: F401
    from core.brain import Brain
    from core.language_voice_bridge import reset_active_language
    from core.voice import Voice

    with patch.dict(
        os.environ,
        {
            "IRIS_LOCK_TTS_VOICE": "false",
            "IRIS_MULTILINGUAL_TTS": "true",
            "IRIS_STICKY_LANGUAGE_TTS": "true",
        },
    ):
        reset_active_language()
        brain = Brain(DummyMemory())
        voice = Voice(text_mode=True)

        brain._generation_settings("general", user_input="hola amiga")
        assert _synthesize(voice, "Todo bien.")[1] == "es-ES-ElviraNeural"


def test_explicit_english_switch_restores_default_voice_in_opt_in_mode():
    import core  # noqa: F401
    from config import Config
    from core.brain import Brain
    from core.language_voice_bridge import reset_active_language
    from core.voice import Voice

    with patch.dict(
        os.environ,
        {
            "IRIS_LOCK_TTS_VOICE": "false",
            "IRIS_MULTILINGUAL_TTS": "true",
            "IRIS_STICKY_LANGUAGE_TTS": "true",
        },
    ):
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
