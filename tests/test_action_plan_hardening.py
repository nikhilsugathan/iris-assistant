from __future__ import annotations

import json
from unittest.mock import MagicMock


def test_plain_text_with_letter_a_does_not_select_plan_a():
    import core  # noqa: F401
    from core.improv import ImprovEngine

    plans = {
        "plan_a": {"description": "open the browser"},
        "plan_b": {"description": "launch calculator"},
        "plan_c": {"description": "install a package"},
    }
    engine = ImprovEngine(brain=None)

    assert engine.select_plan(plans, "banana") is None


def test_public_improv_run_command_is_reassessed_and_blocked():
    import core  # noqa: F401
    from core.executor import ActionExecutor
    from core.improv import ImprovEngine
    from core.security import SecurityGuard

    executor = ActionExecutor.__new__(ActionExecutor)
    executor.pending_plans = {
        "plan_a": {
            "action_type": "run_command",
            "description": "run a harmless example command",
            "command": "echo hello",
            "is_dangerous": False,
            "requires_permission": False,
        },
        "plan_b": {},
        "plan_c": {},
    }
    executor.pending_action = None
    executor.pending_verdict = None
    executor.improv = ImprovEngine(brain=None)
    executor.security = SecurityGuard(brain=None)
    executor._iris_plan_admin_unlocked = False
    executor._log = MagicMock()
    executor._execute_pending = MagicMock(return_value="executed")

    result = executor.handle_plan_choice("plan a")

    assert "Security refusal" in result
    executor._execute_pending.assert_not_called()


def test_admin_improv_run_command_requires_permission_even_when_safe():
    import core  # noqa: F401
    from core.executor import ActionExecutor
    from core.improv import ImprovEngine
    from core.security import SecurityGuard

    executor = ActionExecutor.__new__(ActionExecutor)
    executor.pending_plans = {
        "plan_a": {
            "action_type": "run_command",
            "description": "run an example command",
            "command": "echo hello",
            "is_dangerous": False,
            "requires_permission": False,
        },
        "plan_b": {},
        "plan_c": {},
    }
    executor.pending_action = None
    executor.pending_verdict = None
    executor.improv = ImprovEngine(brain=None)
    executor.security = SecurityGuard(brain=None)
    executor._iris_plan_admin_unlocked = True
    executor._log = MagicMock()
    executor._execute_pending = MagicMock(return_value="executed")

    result = executor.handle_plan_choice("plan a")

    assert "Go ahead?" in result
    executor._execute_pending.assert_not_called()
    assert executor.pending_action["action_type"] == "run_command"


def test_public_ai_plan_rejects_action_outside_allowlist():
    import core  # noqa: F401
    from core.executor import ActionExecutor

    executor = ActionExecutor.__new__(ActionExecutor)
    executor.last_action_path = None
    executor._log = MagicMock()
    executor.brain = MagicMock()
    executor.brain._call_api_with_settings.return_value = json.dumps(
        {
            "action_type": "run_command",
            "description": "run an example command",
            "command": "echo hello",
            "filename": "",
            "content": "",
            "app_name": "",
            "search_query": "",
            "url": "",
            "is_dangerous": False,
        }
    )

    assert executor._ai_plan("do something", admin_unlocked=False) is None


def test_open_app_ai_plan_requires_app_name():
    import core  # noqa: F401
    from core.executor import ActionExecutor

    executor = ActionExecutor.__new__(ActionExecutor)
    executor.last_action_path = None
    executor._log = MagicMock()
    executor.brain = MagicMock()
    executor.brain._call_api_with_settings.return_value = json.dumps(
        {
            "action_type": "open_app",
            "description": "open something",
            "command": "legacy command text",
            "filename": "",
            "content": "",
            "app_name": "",
            "search_query": "",
            "url": "",
            "is_dangerous": False,
        }
    )

    assert executor._ai_plan("open it", admin_unlocked=False) is None


def test_action_plan_hardening_is_loaded():
    import core  # noqa: F401
    from core.executor import ActionExecutor
    from core.improv import ImprovEngine

    assert getattr(ActionExecutor, "_iris_action_plan_hardening_applied", False)
    assert getattr(ImprovEngine, "_iris_plan_selection_hardening_applied", False)
