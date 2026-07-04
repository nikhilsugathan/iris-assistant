from __future__ import annotations

from unittest.mock import MagicMock


def _copilot():
    import core  # noqa: F401
    from core.copilot import CoPilot

    brain = MagicMock()
    brain._call_api.return_value = (
        "1. Open the settings page.\n"
        "2. Select the account tab.\n"
        "3. Save the changes."
    )
    brain.think.return_value = "fallback"
    return CoPilot(brain, voice=MagicMock(), memory=MagicMock()), brain


def test_active_start_delegates_to_existing_walkthrough():
    copilot, brain = _copilot()

    first = copilot.start("walk me through account settings")
    second = copilot.start("next")

    assert "Step 1 of 3" in first
    assert "Step 2 of 3" in second
    assert copilot.current_step == 1
    assert brain._call_api.call_count == 1


def test_question_during_active_session_helps_current_step_without_reset():
    copilot, brain = _copilot()
    copilot.start("walk me through account settings")
    copilot.start("next")
    brain._call_api.return_value = "Use the Account tab in the left navigation. Say next when ready."

    response = copilot.start("where is that tab?")

    assert "Account tab" in response
    assert copilot.current_step == 1
    assert copilot.active is True


def test_negative_continue_phrase_pauses_instead_of_advancing():
    copilot, _brain = _copilot()
    copilot.start("walk me through account settings")

    response = copilot.start("don't continue")

    assert response.startswith("Paused at step 1")
    assert copilot.active is False
    assert copilot.current_step == 0


def test_unrelated_word_containing_ok_does_not_advance():
    copilot, brain = _copilot()
    copilot.start("walk me through account settings")
    brain._call_api.return_value = "Focus on the current step. Say next when ready."

    response = copilot.start("broken")

    assert "current step" in response
    assert copilot.current_step == 0


def test_final_next_completes_walkthrough():
    copilot, brain = _copilot()
    copilot.start("walk me through account settings")
    copilot.start("next")
    copilot.start("next")
    brain._call_api.return_value = "Account settings complete. Nicely done."

    response = copilot.start("next")

    assert "complete" in response.lower()
    assert copilot.active is False
