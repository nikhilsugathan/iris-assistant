if (!(Test-Path tests)) { New-Item -ItemType Directory -Path tests }
@'
import pytest
import re

def verify_command_success(output: str) -> bool:
    if not output:
        return False
    fail_indicators = re.compile(
        r"\b(error|failed|exception|traceback|couldn\'t|could not|not found|permission denied|access denied|fatal|abort|segmentation fault)\b", 
        re.I
    )
    return not bool(fail_indicators.search(output))

def test_standard_success():
    assert verify_command_success("Package installed successfully.") is True

def test_string_failure():
    assert verify_command_success("ImportError: No module named 'config'") is False

def test_partial_success_with_crash():
    assert verify_command_success("Compiling... 90% done... segmentation fault") is False

def test_empty_output():
    assert verify_command_success("") is False
'@ | Out-File -FilePath tests/test_executor_verify.py -Encoding utf8