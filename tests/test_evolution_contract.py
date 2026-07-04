from __future__ import annotations

from unittest.mock import MagicMock, patch


def _engine():
    from core.evolution import EvolutionEngine

    brain = MagicMock()
    brain._call_api.return_value = "def custom_example():\n    return 'candidate'"
    researcher = MagicMock()
    researcher.search.return_value = "reference snippet"
    return EvolutionEngine(brain, researcher), brain, researcher


def test_public_mode_cannot_draft_evolution_tool():
    engine, brain, researcher = _engine()

    result = engine.triage_unknown_intent("make a new capability", admin_unlocked=False)

    assert "Aletheia-level" in result
    brain._call_api.assert_not_called()
    researcher.search.assert_not_called()


def test_admin_draft_is_explicitly_not_integrated():
    engine, _brain, _researcher = _engine()

    result = engine.triage_unknown_intent("example", admin_unlocked=True)

    assert "not enabled" in result.lower()
    assert "not integrated" in result.lower()
    assert engine._pending_tool_code


def test_approve_tool_does_not_write_or_reload_generated_code():
    engine, _brain, _researcher = _engine()
    engine._pending_tool_code = "def custom_example():\n    return 'candidate'"

    with patch("builtins.open") as file_open, patch("importlib.reload") as reload_module:
        result = engine.approve_tool()

    assert "disabled" in result.lower()
    assert "unexecuted" in result.lower()
    file_open.assert_not_called()
    reload_module.assert_not_called()


def test_dangerous_candidate_is_rejected():
    engine, brain, _researcher = _engine()
    brain._call_api.return_value = "import os\ndef custom_bad():\n    return os.system('example')"

    result = engine.triage_unknown_intent("bad example", admin_unlocked=True)

    assert "rejected" in result.lower()
    assert engine._pending_tool_code is None
