from core.executor import ActionExecutor


class DummyExecutor(ActionExecutor):
    def __init__(self):
        # bypass super init which expects real voice/brain
        self.last_action_path = None

    def _run_command(self, plan):
        # Return values will be set externally in tests by attaching attribute
        return getattr(self, "_fake_result", "")


def test_run_command_success_and_failure():
    e = DummyExecutor()

    # success case
    e._fake_result = "All done. Installed successfully."
    result, success = e._execute_with_verify({"action_type": "run_command"})
    assert success is True

    # failure case (stderr-like tuple)
    e._fake_result = ("", "ERROR: permission denied")
    result, success = e._execute_with_verify({"action_type": "run_command"})
    assert success is False

    # empty output
    e._fake_result = ""
    result, success = e._execute_with_verify({"action_type": "run_command"})
    assert success is False

    # failure indicated by "failed" keyword
    e._fake_result = "Process failed with exit code 1."
    result, success = e._execute_with_verify({"action_type": "run_command"})
    assert success is False

    # failure indicated by "traceback"
    e._fake_result = "Traceback (most recent call last): ..."
    result, success = e._execute_with_verify({"action_type": "run_command"})
    assert success is False

    # failure indicated by "not found"
    e._fake_result = "command not found"
    result, success = e._execute_with_verify({"action_type": "run_command"})
    assert success is False

    # install_package success
    e._fake_result = "Done. Successfully installed requests-2.31.0."
    result, success = e._execute_with_verify({"action_type": "install_package"})
    assert success is True

    # install_package failure via dict
    e._fake_result = {"stdout": "", "stderr": "Exception: package not found"}
    result, success = e._execute_with_verify({"action_type": "install_package"})
    assert success is False
