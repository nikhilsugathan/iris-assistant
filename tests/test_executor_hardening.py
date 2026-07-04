from __future__ import annotations

from unittest.mock import MagicMock, patch


def _executor():
    import core  # noqa: F401
    from core.executor import ActionExecutor

    executor = ActionExecutor.__new__(ActionExecutor)
    executor.follow_up = None
    executor._log = MagicMock()
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


def test_executor_hardening_is_loaded():
    import core  # noqa: F401
    from core.executor import ActionExecutor

    assert getattr(ActionExecutor, "_iris_executor_open_app_hardening_applied", False)
