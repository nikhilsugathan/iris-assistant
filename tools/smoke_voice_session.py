"""
IRIS voice-standby smoke test.

Exercises the wake-word and spoken-command flow without requiring a live
microphone.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from PySide6 import QtWidgets

from config import Config
from core.engine import IRISEngine
from iris_gui import VoiceStandbyWorker


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class FakeVoice:
    def __init__(self) -> None:
        self.audio_ready = True
        self.mic_ready = True
        self.current_state = "idle"
        self.last_listen_status = "idle"
        self.last_listen_detail = ""
        self._wake_inputs = ["iris"]
        self._command_inputs = ["please terminate the app"]
        self.spoken: list[str] = []

    def set_state_callback(self, callback) -> None:
        self._state_callback = callback

    def _emit_state(self, state: str) -> None:
        self.current_state = state
        callback = getattr(self, "_state_callback", None)
        if callback:
            callback(state)

    def listen_for_wake(self) -> str:
        self._emit_state("listening")
        text = self._wake_inputs.pop(0) if self._wake_inputs else ""
        self.last_listen_status = "heard" if text else "timeout"
        self.last_listen_detail = text
        self._emit_state("idle")
        return text

    def listen_for_command(self) -> str:
        self._emit_state("listening")
        text = self._command_inputs.pop(0) if self._command_inputs else ""
        self.last_listen_status = "heard" if text else "timeout"
        self.last_listen_detail = text
        self._emit_state("idle")
        return text

    def speak(self, text: str) -> None:
        self.spoken.append(text)
        self._emit_state("speaking")
        self._emit_state("idle")

    def speak_background(self, text: str):
        self.spoken.append(text)
        self._emit_state("speaking")
        self._emit_state("idle")
        return None

    def stop_speaking(self) -> None:
        self._emit_state("idle")

    def stop(self) -> None:
        self.stop_speaking()

    def describe_last_listen_feedback(self) -> str:
        return "Voice standby feedback."

    def short_last_listen_feedback(self) -> str:
        return "Didn't catch that."


def main() -> None:
    app = QtWidgets.QApplication.instance()
    owns_app = app is None
    if app is None:
        app = QtWidgets.QApplication([])

    engine = IRISEngine(text_mode=True)
    fake_voice = FakeVoice()
    engine.voice = fake_voice

    events: list[dict] = []
    worker = VoiceStandbyWorker(engine, should_pause=lambda: False)
    worker.event.connect(events.append)

    try:
        worker.run()
        app.processEvents()

        event_types = [event.get("type") for event in events]
        assert_true("ack" in event_types, "Wake acknowledgement event was not emitted.")
        assert_true("heard" in event_types, "Spoken command event was not emitted.")
        assert_true("result" in event_types, "Voice command result event was not emitted.")
        assert_true("shutdown" in event_types, "Terminate command did not trigger the shutdown event.")

        result_event = next(event for event in events if event.get("type") == "result")
        result = result_event.get("result")
        assert_true(result is not None and result.should_exit, "Voice terminate command did not request shutdown.")
        assert_true(getattr(result, "exit_immediately", False), "Voice terminate command should exit immediately.")
        assert_true(
            result.response == "Terminating now.",
            "Voice terminate command did not return the expected response.",
        )
        shutdown_event = next(event for event in events if event.get("type") == "shutdown")
        assert_true(bool(shutdown_event.get("immediate")), "Voice shutdown event should be marked immediate.")
        assert_true(
            fake_voice.spoken == [Config.WAKE_ACKNOWLEDGEMENT],
            "Immediate terminate should not speak a farewell after the wake acknowledgement.",
        )

        print("PASS: IRIS voice standby smoke test completed.")
    finally:
        engine.shutdown()
        if owns_app:
            app.quit()


if __name__ == "__main__":
    main()
