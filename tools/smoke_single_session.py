"""
IRIS single-session smoke test.

This script exercises the core milestone path without requiring a microphone,
speaker, or live browser interaction:

- wake-word parsing
- chat response flow
- action execution with verification
- hard-blocked safety path
"""

from __future__ import annotations

from pathlib import Path
import sys

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from core.engine import IRISEngine


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class FakeDesktop:
    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []
        self.current_window_title = "SmokePad"

    def type_text(self, text: str, interval: float = 0.02):
        self.events.append(("type_text", text))

    def press_hotkey(self, keys: list[str]):
        self.events.append(("press_hotkey", tuple(keys)))

    def click_at(self, x: int, y: int, button: str = "left", clicks: int = 1):
        self.events.append(("click_at", (x, y, button, clicks)))

    def get_active_window_title(self) -> str:
        return self.current_window_title

    def focus_window(self, title_query: str):
        self.current_window_title = title_query
        self.events.append(("focus_window", title_query))
        class Result:
            message = f"Focused '{title_query}'."
        return Result()


def main() -> None:
    smoke_dir = WORKSPACE / "build" / "smoke"
    smoke_dir.mkdir(parents=True, exist_ok=True)
    smoke_file = smoke_dir / "iris_smoke_note.txt"
    sensitive_smoke_file = smoke_dir / "smoke_token.env"
    actions_log = smoke_dir / "iris_actions.log"
    audit_log = smoke_dir / "iris_audit.log"
    if smoke_file.exists():
        smoke_file.unlink()
    if sensitive_smoke_file.exists():
        sensitive_smoke_file.unlink()
    if actions_log.exists():
        actions_log.unlink()
    if audit_log.exists():
        audit_log.unlink()

    engine = IRISEngine(text_mode=True)
    spoken_messages: list[str] = []
    fake_desktop = FakeDesktop()

    original_speak = engine.voice.speak
    original_think = engine.brain.think
    original_pattern_match = engine.executor._pattern_match

    def fake_speak(text: str) -> None:
        spoken_messages.append(text)

    def fake_think(user_input: str, council_packet=None) -> str:
        return "Smoke response ready."

    def fake_pattern_match(user_input: str):
        if user_input == "run smoke action":
            return {
                "action_type": "create_file",
                "description": "create a smoke note",
                "filename": str(smoke_file),
                "content": "IRIS smoke test artifact\n",
                "is_dangerous": False,
            }
        if user_input == "run smoke blocked action":
            return {
                "action_type": "run_command",
                "description": "launch a blocked command",
                "command": "msfconsole",
                "is_dangerous": True,
            }
        if user_input == "run smoke warning action":
            return {
                "action_type": "open_app",
                "description": "open a Pastebin URL",
                "app_name": "chrome",
                "url": "https://pastebin.com/raw/example",
                "is_dangerous": False,
            }
        if user_input.startswith("run smoke auto folder "):
            suffix = user_input.rsplit(" ", 1)[-1]
            return {
                "action_type": "create_folder",
                "description": f"create smoke folder {suffix}",
                "filename": str(smoke_dir / f"auto_{suffix}"),
                "is_dangerous": False,
            }
        if user_input == "run smoke type action":
            return {
                "action_type": "type_text",
                "description": "type smoke text into the focused app",
                "text_to_type": "IRIS desktop smoke",
                "is_dangerous": False,
            }
        if user_input == "run smoke chain step 1":
            return {
                "action_type": "create_file",
                "description": "create a sensitive smoke env file",
                "filename": str(sensitive_smoke_file),
                "content": "token=smoke-secret\n",
                "is_dangerous": False,
            }
        if user_input == "run smoke chain step 2":
            return {
                "action_type": "search_web",
                "description": "search the web for smoke token.env follow-up",
                "search_query": "inspect smoke_token.env",
                "is_dangerous": False,
            }
        return original_pattern_match(user_input)

    try:
        engine.executor.log_file = str(actions_log)
        engine.executor.audit_file = str(audit_log)
        engine.executor._desktop = fake_desktop
        engine.voice.speak = fake_speak
        engine.brain.think = fake_think
        engine.executor._pattern_match = fake_pattern_match

        assert_true(engine.contains_wake_word("iris status check"), "Wake-word detection failed.")
        assert_true(
            engine.strip_wake_word("iris status check") == "status check",
            "Wake-word stripping failed.",
        )

        chat_result = engine.process_user_input("give me a smoke response", speak_response=True)
        assert_true(chat_result.response == "Smoke response ready.", "Chat flow returned the wrong response.")
        assert_true(spoken_messages[-1] == "Smoke response ready.", "Chat response was not routed to speech.")

        action_result = engine.process_user_input("run smoke action", speak_response=True)
        assert_true(smoke_file.exists(), "Smoke action did not create the expected file.")
        assert_true(
            "created" in action_result.response.lower(),
            "Smoke action did not report a verified creation result.",
        )
        assert_true(spoken_messages[-1] == action_result.response, "Action result was not routed to speech.")

        followup_result = engine.process_user_input("no", speak_response=True)
        assert_true(followup_result.response == "No problem.", "Follow-up handling did not close cleanly.")
        assert_true(spoken_messages[-1] == "No problem.", "Follow-up response was not routed to speech.")

        blocked_result = engine.process_user_input("run smoke blocked action", speak_response=True)
        assert_true(
            "blocked by the safety contract" in blocked_result.response.lower(),
            "Blocked action did not return the expected safety-contract message.",
        )
        assert_true(
            not engine.executor.waiting_for_permission(),
            "Blocked action should not leave IRIS waiting for permission.",
        )

        warning_result = engine.process_user_input("run smoke warning action", speak_response=True)
        assert_true(
            engine.executor.waiting_for_permission(),
            "Warning-grade action should wait for confirmation.",
        )
        assert_true(
            "pastebin" in warning_result.response.lower(),
            "Warning-grade Pastebin action did not return the expected message.",
        )
        cancel_result = engine.process_user_input("no", speak_response=True)
        assert_true(cancel_result.response == "Cancelled.", "Warning action did not cancel cleanly.")

        desktop_warning = engine.process_user_input("run smoke type action", speak_response=True)
        assert_true(
            engine.executor.waiting_for_permission(),
            "Desktop typing action should wait for confirmation.",
        )
        assert_true(
            "currently focused app" in desktop_warning.response.lower(),
            "Desktop typing action did not return the expected confirmation warning.",
        )
        desktop_result = engine.process_user_input("yes", speak_response=True)
        assert_true(desktop_result.response == "Done.", "Desktop typing action did not execute cleanly.")
        assert_true(
            ("type_text", "IRIS desktop smoke") in fake_desktop.events,
            "Desktop typing action did not reach the desktop controller.",
        )

        desktop_memory_prompt = engine.process_user_input("run smoke type action", speak_response=True)
        assert_true(
            engine.executor.waiting_for_permission(),
            "Desktop typing action should still require permission before session approval is remembered.",
        )
        desktop_memory_result = engine.process_user_input("always for this session", speak_response=True)
        assert_true(
            desktop_memory_result.response == "Done.",
            "Desktop typing action did not execute after session approval memory was granted.",
        )
        fake_desktop.current_window_title = "Different Window"
        desktop_other_window = engine.process_user_input("run smoke type action", speak_response=True)
        assert_true(
            engine.executor.waiting_for_permission(),
            "Desktop session approval should not be reused when the focused window changes.",
        )
        engine.process_user_input("no", speak_response=True)
        fake_desktop.current_window_title = "SmokePad"
        desktop_auto = engine.process_user_input("run smoke type action", speak_response=True)
        assert_true(
            desktop_auto.response == "Done.",
            "Desktop session approval was not reused for the same focused window.",
        )
        assert_true(
            not engine.executor.waiting_for_permission(),
            "Remembered desktop approval should execute without leaving IRIS waiting for permission.",
        )

        focus_result = engine.process_user_input("focus Claude", speak_response=True)
        assert_true(
            focus_result.response == "Focused 'Claude'.",
            "Named window focus did not return the expected result.",
        )
        assert_true(
            ("focus_window", "Claude") in fake_desktop.events,
            "Named window focus did not reach the desktop controller.",
        )

        chain_step_one = engine.process_user_input("run smoke chain step 1", speak_response=True)
        assert_true(sensitive_smoke_file.exists(), "Sensitive smoke chain file was not created.")
        assert_true(
            "created" in chain_step_one.response.lower(),
            "Sensitive smoke chain setup action did not report success.",
        )
        chain_step_two = engine.process_user_input("run smoke chain step 2", speak_response=True)
        assert_true(
            engine.executor.waiting_for_permission(),
            "Sensitive file -> network chain should escalate to a confirmation warning.",
        )
        assert_true(
            "sensitive path" in chain_step_two.response.lower() or "browser or network-capable action" in chain_step_two.response.lower(),
            "Action-chain escalation warning did not surface.",
        )
        chain_cancel = engine.process_user_input("no", speak_response=True)
        assert_true(chain_cancel.response == "Cancelled.", "Escalated action chain did not cancel cleanly.")

        engine.executor.auto_action_timestamps = []
        for idx in range(1, 5):
            auto_result = engine.process_user_input(f"run smoke auto folder {idx}", speak_response=True)
        assert_true(
            "still with you" in auto_result.response.lower(),
            "Rapid AUTO sequence did not trigger the presence check.",
        )
        presence_result = engine.process_user_input("yes", speak_response=True)
        assert_true(
            presence_result.response == "All right. Continuing.",
            "Presence check confirmation did not clear cleanly.",
        )

        overdrive_on = engine.process_user_input("activate overdrive", speak_response=True)
        assert_true(engine.overdrive_active, "Overdrive activation command did not enable Overdrive.")
        assert_true(
            "overdrive is active" in overdrive_on.response.lower(),
            "Overdrive activation did not return the expected response.",
        )
        overdrive_status = engine.process_user_input("overdrive status", speak_response=True)
        assert_true(
            "overdrive is active" in overdrive_status.response.lower(),
            "Overdrive status command did not report the live state.",
        )
        overdrive_off = engine.process_user_input("deactivate overdrive", speak_response=True)
        assert_true(not engine.overdrive_active, "Overdrive deactivation command did not disable Overdrive.")
        assert_true(
            "overdrive is off" in overdrive_off.response.lower(),
            "Overdrive deactivation did not return the expected response.",
        )

        security = engine.executor.security
        assert_true(
            security.assess({"action_type": "run_command", "command": "msfconsole"})[0] == "BLOCKED",
            "Metasploit-style commands must be blocked.",
        )
        assert_true(
            security.assess({"action_type": "run_command", "command": "format c:"})[0] == "BLOCKED",
            "Disk-format commands must be blocked.",
        )
        assert_true(
            security.assess({"action_type": "run_command", "command": "winget install Git.Git"})[0] == "NEED_ADMIN",
            "Winget installs must require admin approval.",
        )
        assert_true(audit_log.exists(), "Audit log was not created during smoke test.")
        audit_text = audit_log.read_text(encoding="utf-8")
        assert_true(
            "BLOCKED | run_command | msfconsole | SOURCE(text)" in audit_text,
            "Audit log did not capture the blocked-attempt event.",
        )
        assert_true(
            "CONFIRM_ONCE_CANCELLED" in audit_text,
            "Audit log did not capture the cancelled warning event.",
        )
        assert_true(
            "CONFIRM_ONCE_SESSION_APPROVED" in audit_text and "SESSION_APPROVAL_REUSED" in audit_text,
            "Audit log did not capture the session approval memory lifecycle.",
        )
        assert_true(
            "PRESENCE_CHECK_CONFIRMED" in audit_text,
            "Audit log did not capture the rapid-sequence presence confirmation.",
        )
        assert_true(
            "OVERDRIVE_ACTIVATED" in audit_text and "OVERDRIVE_DEACTIVATED" in audit_text,
            "Audit log did not capture the Overdrive activation lifecycle.",
        )

        print("PASS: IRIS single-session smoke test completed.")
        print(f"Artifact: {smoke_file}")
    finally:
        engine.voice.speak = original_speak
        engine.brain.think = original_think
        engine.executor._pattern_match = original_pattern_match
        engine.shutdown()


if __name__ == "__main__":
    main()
