from __future__ import annotations

from unittest.mock import MagicMock


def _executor():
    import core  # noqa: F401
    from core.executor import ActionExecutor

    executor = ActionExecutor.__new__(ActionExecutor)
    executor._log = MagicMock()
    return executor


def test_success_output_containing_error_word_remains_successful():
    executor = _executor()
    executor._run_command = MagicMock(return_value="Done. Validation complete: 0 errors")

    result, success = executor._execute_with_verify(
        {"action_type": "run_command", "command": "example"}
    )

    assert result.startswith("Done.")
    assert success is True


def test_failed_command_result_remains_failure():
    executor = _executor()
    executor._run_command = MagicMock(return_value="That didn't work. Service unavailable")

    _result, success = executor._execute_with_verify(
        {"action_type": "run_command", "command": "example"}
    )

    assert success is False


def test_executor_verification_patch_is_loaded():
    import core  # noqa: F401
    from core.executor import ActionExecutor

    assert getattr(ActionExecutor, "_iris_executor_verification_hardening_applied", False)
