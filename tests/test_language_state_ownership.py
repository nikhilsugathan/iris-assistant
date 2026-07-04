from __future__ import annotations

import os
import tempfile
from unittest.mock import patch

os.environ["IRIS_DISABLE_VOICE_IO"] = "true"
os.environ["STT_LANGUAGE"] = "auto"
os.environ["IRIS_STICKY_LANGUAGE_TTS"] = "true"
os.environ["IRIS_MALAYALAM_NATIVE_TTS"] = "false"


class DummyMemory:
    def add(self, *args, **kwargs):
        pass

    def get_context(self, *args, **kwargs):
        return []


class FakeCommunicate:
    def __init__(self, text: str, voice: str, rate: str):
        self.text = text
        self.voice = voice
        self.rate = rate

    async def stream(self):
        yield {"type": "audio", "data": b"audio"}


def test_generated_foreign_text_does_not_establish_sticky_language():
    import core  # noqa: F401
    from core.language_voice_bridge import get_active_language_voice, reset_active_language
    from core.voice import Voice

    reset_active_language()
    voice = Voice(text_mode=True)

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as handle:
        output_path = handle.name
    try:
        with patch("edge_tts.Communicate", FakeCommunicate):
            assert voice._run_edge_tts_async(
                "Hola, buenos días.",
                voice._active_voice_name,
                voice._active_voice_rate,
                output_path,
            ) is True
        assert get_active_language_voice() is None
    finally:
        try:
            os.remove(output_path)
        except OSError:
            pass


def test_fast_user_input_establishes_sticky_language_before_local_reply():
    import core  # noqa: F401
    from core.brain import Brain
    from core.language_voice_bridge import get_active_language_voice, reset_active_language

    reset_active_language()
    brain = Brain(DummyMemory())
    reply = brain._rewrite_generic_response("dime")

    assert reply
    assert get_active_language_voice() == "es-ES-ElviraNeural"
