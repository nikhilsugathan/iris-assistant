"""
IRIS terminal entry-point smoke test.

Verifies that the terminal wrapper now reuses the shared engine voice helpers
instead of maintaining its own divergent response policy.
"""

from __future__ import annotations

from pathlib import Path
import sys

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from core.engine import EngineResult, IRISEngine
from main import speak_voice_result


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class FakeVoice:
    def __init__(self) -> None:
        self.spoken_sync: list[str] = []
        self.spoken_background: list[str] = []

    def speak(self, text: str) -> None:
        self.spoken_sync.append(text)

    def speak_background(self, text: str):
        self.spoken_background.append(text)
        return None


def main() -> None:
    engine = IRISEngine(text_mode=True)
    fake_voice = FakeVoice()
    engine.voice = fake_voice

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

        print("PASS: IRIS terminal entry smoke test completed.")
    finally:
        engine.shutdown()


if __name__ == "__main__":
    main()
