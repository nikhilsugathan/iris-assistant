from __future__ import annotations

import json
from unittest.mock import MagicMock, patch


_EXECUTOR_DISPATCH_ACTIONS = {
    "manage_package",
    "run_command",
    "create_file",
    "create_folder",
    "write_to_file",
    "open_app",
    "search_web",
    "delete_item",
    "play_music",
    "unsupported",
}


def _executor():
    import core  # noqa: F401
    from core.executor import ActionExecutor

    executor = ActionExecutor.__new__(ActionExecutor)
    executor.last_action_path = None
    executor._log = MagicMock()
    executor.brain = MagicMock()
    return executor


def test_planner_allowlists_only_expose_dispatchable_actions():
    from core.tools_registry import ACTIVE_TOOL_NAMES, ADMIN_TOOL_NAMES, IMPLEMENTED_TOOL_NAMES

    assert ACTIVE_TOOL_NAMES <= IMPLEMENTED_TOOL_NAMES
    assert ADMIN_TOOL_NAMES <= IMPLEMENTED_TOOL_NAMES
    assert IMPLEMENTED_TOOL_NAMES == _EXECUTOR_DISPATCH_ACTIONS


def test_planned_unimplemented_window_tools_are_not_advertised():
    from core.tools_registry import ADMIN_TOOL_NAMES, TOOLS

    assert "focus_window" in TOOLS
    assert "click_at" in TOOLS
    assert "focus_window" not in ADMIN_TOOL_NAMES
    assert "click_at" not in ADMIN_TOOL_NAMES


def test_manage_package_ai_plan_accepts_command_contract():
    executor = _executor()
    executor.brain._call_api_with_settings.return_value = json.dumps(
        {
            "action_type": "manage_package",
            "description": "install a package",
            "command": "winget install Example.Package",
            "filename": "",
            "content": "",
            "app_name": "",
            "search_query": "",
            "url": "",
            "is_dangerous": False,
        }
    )

    plan = executor._ai_plan("install the package", admin_unlocked=True)

    assert plan is not None
    assert plan["action_type"] == "manage_package"
    assert plan["command"] == "winget install Example.Package"


def test_spotify_launch_does_not_use_subprocess_shell():
    executor = _executor()
    with patch("core.executor_hardening.platform.system", return_value="Windows"), patch(
        "core.executor_hardening.os.startfile", create=True
    ) as startfile, patch("core.executor_hardening.subprocess.Popen") as popen:
        result = executor._play_music(
            {
                "action_type": "play_music",
                "search_query": "test & song",
                "platform": "spotify",
            }
        )

    assert result == "Done."
    startfile.assert_called_once_with("spotify:search:test+%26+song")
    popen.assert_not_called()


def test_web_search_encodes_query_data():
    executor = _executor()
    with patch("core.executor_hardening.webbrowser.open") as browser_open:
        result = executor._search_web(
            {
                "action_type": "search_web",
                "search_query": "iris & security review",
            }
        )

    assert result == "Done."
    browser_open.assert_called_once_with(
        "https://www.google.com/search?q=iris+%26+security+review"
    )
