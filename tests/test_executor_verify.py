import pytest
import re

def verify_command_success(output: str) -> bool:
    if not output: return False
    # Added "importerror" and "module" to catch Python-specific crashes
    fail_indicators = re.compile(r"\b(error|failed|exception|traceback|importerror|module|couldn\"t|could not|not found|permission denied|access denied|fatal|abort|segmentation fault)\b", re.I)
    return not bool(fail_indicators.search(output))

def test_standard_success():
    assert verify_command_success("Package installed successfully.") is True

def test_string_failure():
    # Now this will match "importerror" or "module"
    assert verify_command_success("ImportError: No module named \"config\"") is False

def test_partial_success_with_crash():
    assert verify_command_success("Compiling... 90% done... segmentation fault") is False

def test_empty_output():
    assert verify_command_success("") is False
