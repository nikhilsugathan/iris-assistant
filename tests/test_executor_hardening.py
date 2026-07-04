from __future__ import annotations

from unittest.mock import MagicMock, patch


def _executor():
    import core  # noqa: F401
    from core.executor import ActionExecutor

    executor = ActionExecutor.__new__(ActionExecutor)
    executor.follow_up = None
    executor.pending_action = None
    executor.pending_verdict = None
    executor._clarification_options = []
    executor._log = MagicMock()
    executor._execute_pending = MagicMock(return_value="executed")
    return executor


def test_open_app_ignores_legacy_shell_command_for_known_app():
    executor = _executor()
    with patch("core.executor_hardening.subprocess.Popen") as popen:
        result = executor._open_app(
            {
                "action_type": "open_app",
                "app_name": "notepad",
                "command": "legacy shell launch text",
            }
        )

    assert result == "Done."
    args, kwargs = popen.call_args
    assert args[0] == ["notepad.exe"]
    assert kwargs.get("shell") is not True


def test_open_app_rejects_command_only_plan():
    executor = _executor()
    with patch("core.executor_hardening.subprocess.Popen") as popen:
        result = executor._open_app(
            {
                "action_type": "open_app",
                "app_name": "",
                "command": "arbitrary shell instruction",
            }
        )

    assert "shell command" in result.lower()
    popen.assert_not_called()


def test_unknown_app_target_is_launched_without_shell():
    executor = _executor()
    target = "custom-app-name"
    with patch("core.executor_hardening.subprocess.Popen") as popen:
        result = executor._open_app(
            {
                "action_type": "open_app",
                "app_name": target,
                "command": "",
            }
        )

    assert result == "Done."
    args, kwargs = popen.call_args
    assert args[0] == [target]
    assert kwargs.get("shell") is not True


def test_open_app_followup_uses_hardened_launcher():
    executor = _executor()
    executor.follow_up = {"action": "open_app", "app": "calculator"}

    with patch("core.executor_hardening.subprocess.Popen") as popen:
        result = executor.handle_followup_response("yes")

    assert result == "Done."
    args, kwargs = popen.call_args
    assert args[0] == ["calc.exe"]
    assert kwargs.get("shell") is not True


def test_negative_permission_response_wins_over_affirmative_word():
    from core.security import WARNING

    executor = _executor()
    executor.pending_action = {"action_type": "run_command", "command": "example"}
    executor.pending_verdict = WARNING

    result = executor.handle_permission_response("no, that is not correct")

    assert result == "Cancelled."
    executor._execute_pending.assert_not_called()
    assert executor.pending_action is None
    assert executor.pending_verdict is None


def test_substring_is_not_treated_as_confirmation():
    from core.security import WARNING

    executor = _executor()
    executor.pending_action = {"action_type": "run_command", "command": "example"}
    executor.pending_verdict = WARNING

    result = executor.handle_permission_response("broken")

    assert result == "Go ahead, or cancel?"
    executor._execute_pending.assert_not_called()
    assert executor.pending_action is not None


def test_explicit_affirmative_confirmation_executes_pending_action():
    from core.security import WARNING

    executor = _executor()
    executor.pending_action = {"action_type": "run_command", "command": "example"}
    executor.pending_verdict = WARNING

    result = executor.handle_permission_response("please go ahead")

    assert result == "executed"
    executor._execute_pending.assert_called_once()


def test_negative_override_phrase_does_not_override():
    from core.security import WARNING

    executor = _executor()
    executor.pending_action = {"action_type": "run_command", "command": "example"}
    executor.pending_verdict = WARNING

    result = executor.handle_permission_response("don't override")

    assert result == "Cancelled."
    executor._execute_pending.assert_not_called()


def test_ambiguous_followup_keeps_followup_pending():
    executor = _executor()
    followup = {"action": "open_app", "app": "calculator"}
    executor.follow_up = followup

    result = executor.handle_followup_response("maybe later")

    assert result == "Yes, or no?"
    assert executor.follow_up == followup


def test_extension_substring_does_not_select_python():
    executor = _executor()
    executor.pending_action = {"action_type": "create_file", "filename": "example.pf", "content": ""}
    executor._clarification_options = [".pdf", ".py"]

    result = executor.handle_clarification_response("copy that")

    assert result == "Say .pdf or .py, or cancel."
    executor._execute_pending.assert_not_called()
    assert executor._clarification_options == [".pdf", ".py"]


def test_python_alias_selects_py_only_when_offered():
    executor = _executor()
    executor.pending_action = {"action_type": "create_file", "filename": "example.pf", "content": ""}
    executor._clarification_options = [".pdf", ".py"]

    result = executor.handle_clarification_response("python")

    assert result == "executed"
    assert executor.pending_action["filename"].endswith(".py")
    assert executor._clarification_options == []
    executor._execute_pending.assert_called_once()


def test_ambiguous_extension_choice_remains_pending():
    executor = _executor()
    executor.pending_action = {"action_type": "create_file", "filename": "example.pf", "content": ""}
    executor._clarification_options = [".pdf", ".py"]

    result = executor.handle_clarification_response("pdf or python")

    assert result == "Say .pdf or .py, or cancel."
    executor._execute_pending.assert_not_called()
    assert executor._clarification_options == [".pdf", ".py"]


def test_clarification_cancel_clears_pending_state():
    executor = _executor()
    executor.pending_action = {"action_type": "create_file", "filename": "example.pf", "content": ""}
    executor.pending_verdict = "SAFE"
    executor._clarification_options = [".pdf", ".py"]

    result = executor.handle_clarification_response("no, cancel")

    assert result == "Cancelled."
    assert executor.pending_action is None
    assert executor.pending_verdict is None
    assert executor._clarification_options == []


def test_executor_hardening_is_loaded():
    import core  # noqa: F401
    from core.executor import ActionExecutor

    assert getattr(ActionExecutor, "_iris_executor_open_app_hardening_applied", False)
    assert getattr(ActionExecutor, "_iris_executor_confirmation_hardening_applied", False)
    assert getattr(ActionExecutor, "_iris_executor_clarification_hardening_applied", False)
