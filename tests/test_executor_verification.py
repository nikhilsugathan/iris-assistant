from __future__ import annotations

import os
import tempfile
from unittest.mock import MagicMock


def _executor():
    import core  # noqa: F401
    from core.executor import ActionExecutor

    executor = ActionExecutor.__new__(ActionExecutor)
    executor._log = MagicMock()
    executor.last_action_path = None
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


def test_file_extension_clarification_is_deferred_not_failed():
    executor = _executor()
    executor._create_file = MagicMock(return_value="Did you mean '.pdf or .py'?")
    executor.waiting_for_clarification = MagicMock(return_value=True)

    result, success = executor._execute_with_verify(
        {"action_type": "create_file", "filename": "example.pf", "content": ""}
    )

    assert "Did you mean" in result
    assert success is True


def test_stale_previous_file_cannot_make_new_file_failure_successful():
    executor = _executor()
    with tempfile.NamedTemporaryFile(delete=False) as handle:
        stale_path = handle.name
    try:
        executor.last_action_path = stale_path
        executor._create_file = MagicMock(return_value="Couldn't create the file safely: denied")
        executor.waiting_for_clarification = MagicMock(return_value=False)

        _result, success = executor._execute_with_verify(
            {"action_type": "create_file", "filename": "new.txt", "content": ""}
        )

        assert os.path.isfile(stale_path)
        assert success is False
    finally:
        try:
            os.remove(stale_path)
        except OSError:
            pass


def test_current_created_file_is_verified_from_result_and_artifact():
    executor = _executor()
    with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as handle:
        created_path = handle.name
    try:
        executor.last_action_path = created_path
        executor._create_file = MagicMock(
            return_value=f"Done. '{os.path.basename(created_path)}' created. Want me to open it?"
        )
        executor.waiting_for_clarification = MagicMock(return_value=False)

        _result, success = executor._execute_with_verify(
            {"action_type": "create_file", "filename": created_path, "content": ""}
        )

        assert success is True
    finally:
        try:
            os.remove(created_path)
        except OSError:
            pass


def test_executor_verification_patch_is_loaded():
    import core  # noqa: F401
    from core.executor import ActionExecutor

    assert getattr(ActionExecutor, "_iris_executor_verification_hardening_applied", False)
    assert getattr(ActionExecutor, "_iris_filesystem_verification_hardening_applied", False)
