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
from core.engine import EngineResult, IRISEngine
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
        self.last_transcript_uncertain = False
        self._wake_inputs = ["iris"]
        self._command_inputs = ["please terminate the app"]
        self.spoken: list[str] = []
        self.sync_spoken: list[str] = []
        self.background_spoken: list[str] = []
        self.command_interrupt_flags: list[bool] = []

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

    def listen_for_command(self, interrupt_speech: bool = True) -> str:
        self.command_interrupt_flags.append(bool(interrupt_speech))
        self._emit_state("listening")
        text = self._command_inputs.pop(0) if self._command_inputs else ""
        self.last_listen_status = "heard" if text else "timeout"
        self.last_listen_detail = text
        self._emit_state("idle")
        return text

    def speak(self, text: str) -> None:
        self.spoken.append(text)
        self.sync_spoken.append(text)
        self._emit_state("speaking")
        self._emit_state("idle")

    def speak_background(self, text: str):
        self.spoken.append(text)
        self.background_spoken.append(text)
        self._emit_state("speaking")
        self._emit_state("idle")
        return None

    def speak_quick_ack(self, text: str):
        return self.speak_background(text)

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
    normal_engine = None
    repeat_engine = None
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
        assert_true(
            fake_voice.command_interrupt_flags == [True],
            "Wake acknowledgement handoff should interrupt any overlapping quick acknowledgement before command capture.",
        )

        normal_engine = IRISEngine(text_mode=True)
        normal_voice = FakeVoice()
        normal_engine.voice = normal_voice
        normal_engine.begin_slow_voice_ack = lambda user_input, enabled=True: None  # type: ignore[method-assign]
        normal_engine.finish_slow_voice_ack = lambda token, stop_audio=True: None  # type: ignore[method-assign]
        normal_engine.process_user_input = lambda command_text, speak_response=False, input_source="voice": EngineResult(  # type: ignore[method-assign]
            label=Config.PUBLIC_NAME,
            response="Queued response.",
            should_exit=False,
            mode="action",
        )
        follow_up_calls: list[bool] = []
        normal_engine.listen_for_voice_command = lambda interrupt_speech=True: follow_up_calls.append(bool(interrupt_speech)) or ""  # type: ignore[method-assign]
        normal_engine.should_end_followup = lambda text: False  # type: ignore[method-assign]
        normal_engine.executor.waiting_for_followup = lambda: False  # type: ignore[method-assign]
        normal_engine.executor.waiting_for_clarification = lambda: False  # type: ignore[method-assign]
        normal_engine.executor.waiting_for_plan_choice = lambda: False  # type: ignore[method-assign]
        normal_engine.executor.waiting_for_presence_check = lambda: False  # type: ignore[method-assign]
        normal_engine.executor.waiting_for_permission = lambda: False  # type: ignore[method-assign]
        normal_engine.copilot.active = False

        normal_worker = VoiceStandbyWorker(normal_engine, should_pause=lambda: False)
        handled = normal_worker._handle_command("queued response", "queued response", follow_up_turns=4)
        assert_true(handled, "Normal standby handling should keep the voice worker alive.")
        assert_true(
            normal_voice.sync_spoken == [],
            "Non-interactive voice results should not block the standby worker with synchronous speech.",
        )
        assert_true(
            normal_voice.background_spoken == ["Queued response."],
            "Non-interactive voice results should be queued in background speech.",
        )
        assert_true(
            follow_up_calls == [],
            "Normal voice results should return to wake standby instead of forcing an empty follow-up listen loop.",
        )

        repeat_engine = IRISEngine(text_mode=True)
        repeat_voice = FakeVoice()
        repeat_engine.voice = repeat_voice
        repeat_results = iter(
            [
                EngineResult(
                    label=Config.PUBLIC_NAME,
                    response="Tell me what you want me to do.",
                    should_exit=False,
                    mode="voice-repeat",
                ),
                EngineResult(
                    label=Config.PUBLIC_NAME,
                    response="Opening Notepad.",
                    should_exit=False,
                    mode="action",
                ),
            ]
        )
        repeat_engine.process_voice_turn = lambda command_text, input_source="voice", enable_slow_ack=True: next(repeat_results)  # type: ignore[method-assign]
        repeat_follow_up_calls: list[bool] = []
        repeat_engine.listen_for_voice_command = lambda interrupt_speech=True: repeat_follow_up_calls.append(bool(interrupt_speech)) or "open notepad"  # type: ignore[method-assign]
        repeat_engine.should_end_followup = lambda text: False  # type: ignore[method-assign]
        repeat_engine.should_hold_voice_followup_open = lambda: False  # type: ignore[method-assign]
        repeat_engine.executor.waiting_for_followup = lambda: False  # type: ignore[method-assign]
        repeat_engine.executor.waiting_for_clarification = lambda: False  # type: ignore[method-assign]
        repeat_engine.executor.waiting_for_plan_choice = lambda: False  # type: ignore[method-assign]
        repeat_engine.executor.waiting_for_presence_check = lambda: False  # type: ignore[method-assign]
        repeat_engine.executor.waiting_for_permission = lambda: False  # type: ignore[method-assign]
        repeat_engine.copilot.active = False

        repeat_worker = VoiceStandbyWorker(repeat_engine, should_pause=lambda: False)
        repeat_handled = repeat_worker._handle_command("hello", "hello", follow_up_turns=4)
        assert_true(repeat_handled, "Voice repeat standby handling should keep the worker alive.")
        assert_true(
            repeat_voice.sync_spoken == ["Tell me what you want me to do."],
            "Voice-repeat results should speak synchronously before listening again.",
        )
        assert_true(
            repeat_voice.background_spoken == ["Opening Notepad."],
            "Follow-up command after a repeat prompt should return to background speech on success.",
        )
        assert_true(
            repeat_follow_up_calls == [True],
            "Voice-repeat handling should capture one follow-up command without requiring a new wake phrase.",
        )

        print("PASS: IRIS voice standby smoke test completed.")
    finally:
        engine.shutdown()
        try:
            if normal_engine is not None:
                normal_engine.shutdown()
        except Exception:
            pass
        try:
            if repeat_engine is not None:
                repeat_engine.shutdown()
        except Exception:
            pass
        if owns_app:
            app.quit()


if __name__ == "__main__":
    main()
