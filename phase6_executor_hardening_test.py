from __future__ import annotations

import contextlib
import importlib
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


def _make_stub(name: str, **attrs) -> types.ModuleType:
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class _DummyProgress:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def add_task(self, *args, **kwargs):
        return 1

    def update(self, *args, **kwargs):
        return None


class _Config:
    PROJECT_ROOT = str(ROOT)
    PRIMARY_BRAIN = "groq"


_make_stub("rich", __path__=[])
_make_stub("rich.progress", Progress=_DummyProgress, SpinnerColumn=MagicMock, TextColumn=MagicMock)
_make_stub("config", Config=_Config)
_make_stub("core.browser", BrowserAutomation=lambda *args, **kwargs: MagicMock())
_make_stub("core.improv", ImprovEngine=lambda *args, **kwargs: MagicMock())
_make_stub(
    "core.security",
    SecurityGuard=MagicMock(return_value=MagicMock()),
    SAFE="SAFE",
    WARNING="WARNING",
    BLOCKED="BLOCKED",
    NEED_ADMIN="NEED_ADMIN",
)

sys.modules.pop("core.autocorrect", None)
sys.modules.pop("core.tools_registry", None)
sys.modules.pop("core.executor", None)

from core.autocorrect import AutoCorrector
from core.tools_registry import ACTIVE_TOOL_NAMES, ADMIN_TOOL_NAMES
from core.executor import ActionExecutor


def _make_brain() -> MagicMock:
    brain = MagicMock()
    brain._call_api.return_value = json.dumps({
        "action_type": "open_app",
        "description": "open calculator",
        "command": "",
        "filename": "",
        "content": "",
        "app_name": "calculator",
        "search_query": "",
        "url": "",
        "is_dangerous": False,
    })
    return brain


class TestPhase6ExecutorHardening(unittest.TestCase):
    def test_autocorrect_fast_path_skips_trivial_inputs(self):
        autocorrect = AutoCorrector()

        with patch.object(autocorrect, "_correct_word", side_effect=AssertionError("_correct_word should not run")):
            self.assertEqual(autocorrect.correct_input("yes"), ("yes", None))
            self.assertEqual(autocorrect.correct_input("open notepad"), ("open notepad", None))

    def test_pattern_match_handles_bare_file_and_folder_names(self):
        executor = ActionExecutor(voice=MagicMock(), brain=_make_brain())

        folder_plan = executor._pattern_match("create folder nvidia")
        self.assertEqual(folder_plan["action_type"], "create_folder")
        self.assertIn("nvidia", folder_plan["filename"].lower())

        file_plan = executor._pattern_match("create file notes.txt")
        self.assertEqual(file_plan["action_type"], "create_file")
        self.assertTrue(file_plan["filename"].lower().endswith("notes.txt"))

    def test_ai_plan_injects_persona_scoped_tool_schema(self):
        brain = _make_brain()
        executor = ActionExecutor(voice=MagicMock(), brain=brain)

        executor._ai_plan("open calculator", admin_unlocked=False)
        public_prompt = brain._call_api.call_args.args[1]
        self.assertIn("Persona mode: public", public_prompt)
        self.assertIn("Allowed tools for this persona:", public_prompt)
        self.assertIn("- open_app:", public_prompt)
        self.assertNotIn("- run_command:", public_prompt)
        self.assertIn("action_type", public_prompt)
        self.assertIn(" | ".join(sorted(ACTIVE_TOOL_NAMES)), public_prompt)

        brain._call_api.reset_mock()
        executor._ai_plan("run ipconfig", admin_unlocked=True)
        admin_prompt = brain._call_api.call_args.args[1]
        self.assertIn("Persona mode: admin", admin_prompt)
        self.assertIn("- run_command:", admin_prompt)
        self.assertIn(" | ".join(sorted(ADMIN_TOOL_NAMES)), admin_prompt)

    def test_file_operations_return_safe_errors_on_oserror(self):
        executor = ActionExecutor(voice=MagicMock(), brain=_make_brain())

        with patch("core.executor.os.makedirs", side_effect=OSError("denied")):
            result = executor._create_file({"filename": "C:/tmp/test.txt", "content": "hello", "description": "create test"})
        self.assertIn("Couldn't create the file safely", result)

        with patch("core.executor.os.makedirs", side_effect=OSError("denied")):
            result = executor._create_folder({"filename": "C:/tmp/folder"})
        self.assertIn("Couldn't create the folder", result)

        with patch("core.executor.os.makedirs", side_effect=OSError("disk full")):
            result = executor._write_to_file({"filename": "C:/tmp/folder/test.txt", "content": "hello"})
        self.assertIn("Couldn't write to the file safely", result)

    def test_write_to_file_creates_parent_dirs(self):
        executor = ActionExecutor(voice=MagicMock(), brain=_make_brain())

        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "nested" / "notes.txt"
            result = executor._write_to_file({"filename": str(target), "content": "hello"})
            self.assertEqual(result, "Done.")
            self.assertTrue(target.exists())
            self.assertIn("hello", target.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
