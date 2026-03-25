"""
IRIS terminal entry-point smoke test.

Verifies that the terminal wrapper now reuses the shared engine voice helpers
instead of maintaining its own divergent response policy.
"""

from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from core.engine import EngineResult, IRISEngine
from config import Config
from main import speak_voice_result


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class FakeVoice:
    def __init__(self) -> None:
        self.audio_ready = True
        self.spoken_sync: list[str] = []
        self.spoken_background: list[str] = []
        self.sequence_chunks: list[tuple[int, str, bool]] = []
        self._sequence_id = 0

    def speak(self, text: str) -> None:
        self.spoken_sync.append(text)

    def speak_background(self, text: str):
        self.spoken_background.append(text)
        return None

    def begin_background_speech_sequence(self, cancel_pending: bool = True) -> int:
        self._sequence_id += 1
        return self._sequence_id

    def queue_background_speech(self, text: str, generation_id: int, backend_priority: str | None = None, interrupt_current: bool = False):
        self.sequence_chunks.append((generation_id, text, bool(interrupt_current)))
        return None


def main() -> None:
    engine = IRISEngine(text_mode=True)
    fake_voice = FakeVoice()
    engine.voice = fake_voice
    original_streaming = Config.OLLAMA_STREAM_VOICE_RESPONSES
    Config.OLLAMA_STREAM_VOICE_RESPONSES = True

    try:
        result = EngineResult(label="IRIS", response="Queued terminal response.")
        speak_voice_result(engine, result)
        assert_true(
            fake_voice.spoken_sync == [],
            "Terminal wrapper should not block on synchronous speech when no follow-up state is active.",
        )
        assert_true(
            fake_voice.spoken_background == ["Queued terminal response."],
            "Terminal wrapper should queue background speech for non-interactive responses.",
        )

        fake_voice.spoken_sync.clear()
        fake_voice.spoken_background.clear()
        engine.executor.pending_action = {"action_type": "run_command", "command": "echo smoke"}
        engine.executor.pending_verdict = "WARNING"

        speak_voice_result(engine, EngineResult(label="IRIS", response="Go ahead, or cancel?"))
        assert_true(
            fake_voice.spoken_sync == ["Go ahead, or cancel?"],
            "Terminal wrapper should keep synchronous speech when a live confirmation state is pending.",
        )
        assert_true(
            fake_voice.spoken_background == [],
            "Terminal wrapper should not background a response that needs an immediate follow-up answer.",
        )

        fake_voice.spoken_sync.clear()
        fake_voice.spoken_background.clear()
        fake_voice.sequence_chunks.clear()
        engine.executor.pending_action = None
        engine.executor.pending_verdict = None

        engine.autocorrect.correct_input = lambda text: (text, 1.0)  # type: ignore[method-assign]
        engine.dialog_manager.analyze = lambda *args, **kwargs: SimpleNamespace(mode="chat")  # type: ignore[method-assign]
        engine.council.deliberate = lambda *args, **kwargs: SimpleNamespace(roles=[], preferred_apis=[], extra_system="", allow_long_response=False)  # type: ignore[method-assign]

        def fake_streaming_think(user_input: str, council_packet=None, stream_callback=None) -> str:
            if stream_callback:
                stream_callback("First streamed sentence.")
                stream_callback("Second streamed sentence.")
            return "First streamed sentence. Second streamed sentence."

        engine.brain.think_with_stream = fake_streaming_think  # type: ignore[method-assign]
        streamed = engine.process_user_input("give me the streamed answer", speak_response=False, input_source="voice")
        assert_true(streamed.speech_started, "Voice streaming should mark the result as already spoken.")
        assert_true(
            fake_voice.sequence_chunks == [
                (1, "First streamed sentence.", True),
            ],
            "Voice streaming should queue the allowed sentence budget into one speech sequence.",
        )

        speak_voice_result(engine, streamed)
        assert_true(
            fake_voice.spoken_sync == [] and fake_voice.spoken_background == [],
            "Terminal wrapper should not re-speak a response that already started streaming.",
        )

        print("PASS: IRIS terminal entry smoke test completed.")
    finally:
        Config.OLLAMA_STREAM_VOICE_RESPONSES = original_streaming
        engine.shutdown()


if __name__ == "__main__":
    main()
