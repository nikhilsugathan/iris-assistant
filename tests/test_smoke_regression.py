"""
IRIS v5.0 Smoke & Regression Test Suite
========================================
Covers all 9 bug fixes from the previous session plus core module
integration.  Requires no hardware (mic/GPU), no live API keys, and
no network access.  Every external call is stubbed with unittest.mock.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
import types
import unittest
from dataclasses import dataclass
from typing import List, Dict
from unittest.mock import MagicMock, patch, PropertyMock

# ── Make sure the repo root is importable regardless of CWD ──────────────
REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# ── Stub out hardware-dependent modules before any repo imports ────────────
# This prevents ModuleNotFoundError / ImportError on CI machines that have
# no microphone, GPU, or audio drivers installed.
import unittest.mock as _mock
for _mod in ("pyaudio", "pygame", "pygame.mixer", "pygame.mixer.music"):
    if _mod not in sys.modules:
        sys.modules[_mod] = _mock.MagicMock()

# ---------------------------------------------------------------------------
# Helper: a minimal Brain stub that records calls without hitting any API
# ---------------------------------------------------------------------------

class _StubBrain:
    def __init__(self):
        self.memory = MagicMock()
        self.memory.get_context.return_value = [
            {"role": "user",      "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        self.available_apis = ["groq"]
        self._call_api_calls: list = []

    def _call_api(self, api: str, prompt: str, **_kw) -> str:
        self._call_api_calls.append((api, prompt))
        return f"[stub response from {api}]"

    def think(self, text, **_kw) -> str:
        return f"[think: {text}]"


# ---------------------------------------------------------------------------
# Helper: a minimal Executor stub
# ---------------------------------------------------------------------------

class _StubExecutor:
    def should_handle(self, text: str) -> bool:
        return False

    def waiting_for_permission(self) -> bool:   return False
    def waiting_for_followup(self) -> bool:      return False
    def waiting_for_clarification(self) -> bool: return False
    def waiting_for_plan_choice(self) -> bool:   return False


# ---------------------------------------------------------------------------
# Helper: a minimal Copilot stub
# ---------------------------------------------------------------------------

class _StubCopilot:
    active = False

    def should_activate(self, text: str) -> bool:
        return False

    def respond(self, text: str) -> str:
        return f"[copilot: {text}]"


# ---------------------------------------------------------------------------
# Helper: a minimal Diagnostics stub
# ---------------------------------------------------------------------------

class _StubDiagnostics:
    def should_handle(self, text: str) -> bool:
        return False

    def run(self, *args, **kwargs) -> str:
        return "[diagnostics output]"


# ---------------------------------------------------------------------------
# Helper: a minimal SelfModel stub
# ---------------------------------------------------------------------------

class _StubSelfModel:
    emotional_load = 0.10

    def summary(self) -> str:
        return "stub"

    def note_response(self, *_a, **_kw):
        pass


# ===========================================================================
# FIX 1 — session_logger.py: paths must be anchored to repo root
# ===========================================================================

class TestSessionLoggerPaths(unittest.TestCase):
    """Regression: history/ must live inside the repo root, not the CWD."""

    def _make_logger(self):
        from core.session_logger import SessionLogger, _ROOT
        return SessionLogger(), _ROOT

    def test_root_is_absolute(self):
        from core.session_logger import _ROOT
        self.assertTrue(pathlib.Path(_ROOT).is_absolute(),
                        "_ROOT must be an absolute path")

    def test_root_points_to_repo_root(self):
        from core.session_logger import _ROOT
        # The repo root must contain config.py and main.py
        root = pathlib.Path(_ROOT)
        self.assertTrue((root / "config.py").exists(),
                        "_ROOT must point at the repo root (contains config.py)")
        self.assertTrue((root / "main.py").exists(),
                        "_ROOT must point at the repo root (contains main.py)")

    def test_history_dir_is_absolute(self):
        logger, _ = self._make_logger()
        self.assertTrue(os.path.isabs(logger.history_dir),
                        "history_dir must be an absolute path")

    def test_history_dir_under_repo_root(self):
        logger, _ROOT = self._make_logger()
        self.assertTrue(
            logger.history_dir.startswith(str(_ROOT)),
            "history_dir must be a subdirectory of the repo root"
        )

    def test_filename_is_absolute(self):
        logger, _ = self._make_logger()
        self.assertTrue(os.path.isabs(logger.filename),
                        "filename must be an absolute path")

    def test_filename_under_history_dir(self):
        logger, _ = self._make_logger()
        self.assertTrue(
            logger.filename.startswith(logger.history_dir),
            "filename must be inside history_dir"
        )

    def test_history_dir_is_created(self):
        logger, _ = self._make_logger()
        self.assertTrue(os.path.isdir(logger.history_dir),
                        "history_dir must be created by __init__")

    def test_header_written_to_disk(self):
        logger, _ = self._make_logger()
        self.assertTrue(os.path.exists(logger.filename),
                        "Session file must exist after __init__")
        with open(logger.filename, encoding="utf-8") as fh:
            content = fh.read()
        self.assertIn("IRIS Session Log", content)

    def test_log_turn_appends(self):
        logger, _ = self._make_logger()
        logger.log_turn("User", "hello test")
        with open(logger.filename, encoding="utf-8") as fh:
            content = fh.read()
        self.assertIn("hello test", content)

    def test_finalize_writes_footer(self):
        logger, _ = self._make_logger()
        logger.finalize()
        with open(logger.filename, encoding="utf-8") as fh:
            content = fh.read()
        self.assertIn("Session Terminated", content)

    def test_file_still_exists_after_finalize(self):
        """Regression: autonomist reads the file AFTER finalize() — must still exist."""
        logger, _ = self._make_logger()
        logger.finalize()
        self.assertTrue(os.path.exists(logger.filename),
                        "Session file must still exist after finalize() for autonomist to read")


# ===========================================================================
# FIX 2 — dialog_manager.py: "search" mode added for web-search intents
# ===========================================================================

class TestDialogManagerSearchMode(unittest.TestCase):
    """Regression: WEB_SEARCH_KEYWORDS must trigger mode='search'."""

    def setUp(self):
        from core.dialog_manager import DialogManager
        self.dm = DialogManager()
        self.executor = _StubExecutor()
        self.copilot = _StubCopilot()
        self.diagnostics = _StubDiagnostics()
        self.self_model = _StubSelfModel()

    def _analyze(self, text: str):
        return self.dm.analyze(text, self.executor, self.copilot,
                               self.diagnostics, self.self_model)

    def test_web_search_keywords_class_attribute_exists(self):
        from core.dialog_manager import DialogManager
        self.assertTrue(
            hasattr(DialogManager, "WEB_SEARCH_KEYWORDS"),
            "DialogManager must have WEB_SEARCH_KEYWORDS class attribute"
        )
        self.assertIsInstance(DialogManager.WEB_SEARCH_KEYWORDS, list)
        self.assertGreater(len(DialogManager.WEB_SEARCH_KEYWORDS), 0)

    def test_search_for_triggers_search_mode(self):
        d = self._analyze("search for latest python news")
        self.assertEqual(d.mode, "search",
                         "'search for X' must produce mode='search'")

    def test_look_up_triggers_search_mode(self):
        d = self._analyze("look up the best GPU in 2025")
        self.assertEqual(d.mode, "search",
                         "'look up X' must produce mode='search'")

    def test_google_triggers_search_mode(self):
        d = self._analyze("google who won the 2024 election")
        self.assertEqual(d.mode, "search")

    def test_what_is_the_latest_triggers_search_mode(self):
        d = self._analyze("what is the latest news on SpaceX")
        self.assertEqual(d.mode, "search")

    def test_search_mode_has_correct_depth(self):
        d = self._analyze("search for something interesting")
        self.assertEqual(d.depth, "shallow")

    def test_search_comes_before_action_in_routing(self):
        """Even if executor.should_handle were True, search must win first."""
        executor = MagicMock()
        executor.should_handle.return_value = True
        executor.waiting_for_permission.return_value = False
        executor.waiting_for_followup.return_value = False
        executor.waiting_for_clarification.return_value = False
        executor.waiting_for_plan_choice.return_value = False
        d = self.dm.analyze(
            "search for latest python news",
            executor, self.copilot, self.diagnostics, self.self_model
        )
        self.assertEqual(d.mode, "search",
                         "search routing must precede action routing")

    def test_plain_question_does_not_trigger_search(self):
        d = self._analyze("how are you today")
        self.assertNotEqual(d.mode, "search")

    def test_action_still_works_for_os_triggers(self):
        executor = MagicMock()
        executor.should_handle.return_value = True
        executor.waiting_for_permission.return_value = False
        executor.waiting_for_followup.return_value = False
        executor.waiting_for_clarification.return_value = False
        executor.waiting_for_plan_choice.return_value = False
        d = self.dm.analyze(
            "install python on my machine",
            executor, self.copilot, self.diagnostics, self.self_model
        )
        self.assertEqual(d.mode, "action")


# ===========================================================================
# FIX 3 — executor.py: "search for", "look up", "find" removed from triggers
# ===========================================================================

class TestExecutorActionTriggers(unittest.TestCase):
    """Regression: removed triggers must no longer appear in ACTION_TRIGGERS."""

    @classmethod
    def _read_triggers_from_source(cls) -> list:
        """Parse ACTION_TRIGGERS list from executor.py source."""
        src = (REPO_ROOT / "core" / "executor.py").read_text(encoding="utf-8")
        import re
        m = re.search(r"ACTION_TRIGGERS\s*=\s*\[(.*?)\]", src, re.DOTALL)
        if not m:
            return []
        block = m.group(1)
        return re.findall(r'"([^"]+)"', block)

    def test_search_for_not_in_triggers(self):
        triggers = self._read_triggers_from_source()
        self.assertNotIn("search for", triggers,
                         "'search for' must be removed from ACTION_TRIGGERS")

    def test_look_up_not_in_triggers(self):
        triggers = self._read_triggers_from_source()
        self.assertNotIn("look up", triggers,
                         "'look up' must be removed from ACTION_TRIGGERS")

    def test_find_not_in_triggers(self):
        triggers = self._read_triggers_from_source()
        self.assertNotIn("find", triggers,
                         "'find' must be removed from ACTION_TRIGGERS")

    def test_install_still_in_triggers(self):
        triggers = self._read_triggers_from_source()
        self.assertIn("install", triggers,
                      "'install' must still be in ACTION_TRIGGERS")

    def test_open_still_in_triggers(self):
        triggers = self._read_triggers_from_source()
        self.assertIn("open", triggers,
                      "'open' must still be in ACTION_TRIGGERS")

    def test_create_still_in_triggers(self):
        triggers = self._read_triggers_from_source()
        self.assertIn("create", triggers,
                      "'create' must still be in ACTION_TRIGGERS")

    def test_run_still_in_triggers(self):
        triggers = self._read_triggers_from_source()
        self.assertIn("run", triggers,
                      "'run' must still be in ACTION_TRIGGERS")

    def test_search_for_does_not_appear_in_trigger_block(self):
        src = (REPO_ROOT / "core" / "executor.py").read_text(encoding="utf-8")
        import re
        m = re.search(r"ACTION_TRIGGERS\s*=\s*\[(.*?)\]", src, re.DOTALL)
        self.assertIsNotNone(m, "ACTION_TRIGGERS list must exist in executor.py")
        block = m.group(1)
        self.assertNotIn('"search for"', block)

    def test_look_up_does_not_appear_in_trigger_block(self):
        src = (REPO_ROOT / "core" / "executor.py").read_text(encoding="utf-8")
        import re
        m = re.search(r"ACTION_TRIGGERS\s*=\s*\[(.*?)\]", src, re.DOTALL)
        block = m.group(1) if m else ""
        self.assertNotIn('"look up"', block)

    def test_search_for_does_not_match_executor(self):
        """Functional: ActionExecutor.should_handle must reject web-search text."""
        from core.executor import ActionExecutor
        voice = MagicMock()
        brain = _StubBrain()
        executor = ActionExecutor(voice, brain)
        self.assertFalse(executor.should_handle("search for latest python news"))

    def test_look_up_does_not_match_executor(self):
        from core.executor import ActionExecutor
        voice = MagicMock()
        brain = _StubBrain()
        executor = ActionExecutor(voice, brain)
        self.assertFalse(executor.should_handle("look up the current price of bitcoin"))

    def test_install_still_matches_executor(self):
        from core.executor import ActionExecutor
        executor = ActionExecutor(MagicMock(), _StubBrain())
        self.assertTrue(executor.should_handle("install python"))

    def test_create_still_matches_executor(self):
        from core.executor import ActionExecutor
        executor = ActionExecutor(MagicMock(), _StubBrain())
        self.assertTrue(executor.should_handle("create a file called test.txt"))

# ===========================================================================
# FIX 4 — researcher.py: no nested spinner; PRIMARY_BRAIN lowercased
# ===========================================================================

class TestResearcher(unittest.TestCase):
    """Regression: Researcher must not open a nested Rich console.status."""

    def test_no_console_status_in_module(self):
        """The researcher module must not contain an active console.status() call."""
        researcher_path = REPO_ROOT / "tools" / "researcher.py"
        src = researcher_path.read_text(encoding="utf-8")
        # Strip comments and docstrings before checking — the docstring mentions
        # "console.status spinner" as documentation, which is intentional.
        import ast, tokenize, io
        # Remove all string literals (docstrings) and comments from source
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        code_only = []
        for tok in tokens:
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            code_only.append(tok.string)
        code_str = " ".join(code_only)
        self.assertNotIn(
            "console.status(",
            code_str,
            "tools/researcher.py must not open its own console.status() call in executable code"
        )

    def test_no_rich_console_import(self):
        """researcher.py must not import Console from rich."""
        researcher_path = REPO_ROOT / "tools" / "researcher.py"
        src = researcher_path.read_text(encoding="utf-8")
        self.assertNotIn(
            "from rich.console import Console",
            src,
            "researcher.py must not import Rich Console (no nested spinner needed)"
        )

    def test_primary_brain_is_lowercased(self):
        """_call_api must receive a lowercase provider string."""
        researcher_path = REPO_ROOT / "tools" / "researcher.py"
        src = researcher_path.read_text(encoding="utf-8")
        self.assertIn(
            ".lower()",
            src,
            "researcher.py must call .lower() on PRIMARY_BRAIN before passing to _call_api"
        )

    def test_search_calls_api_with_lowercase_provider(self):
        from tools.researcher import Researcher
        from config import Config

        brain = _StubBrain()
        researcher = Researcher(brain)
        # Set PRIMARY_BRAIN to uppercase to reproduce the original bug
        original = Config.PRIMARY_BRAIN
        Config.PRIMARY_BRAIN = "GROQ"
        try:
            with patch("tools.researcher.DDGS") as mock_ddgs:
                mock_ddgs.return_value.__enter__.return_value.text.return_value = [
                    {"title": "Test", "body": "Test body"}
                ]
                researcher.search("who is Elon Musk")
            # The API call must have been made with "groq" (lowercase), not "GROQ"
            self.assertTrue(
                any(call[0] == "groq" for call in brain._call_api_calls),
                f"_call_api must be called with 'groq' (lowercase), "
                f"got: {brain._call_api_calls}"
            )
        finally:
            Config.PRIMARY_BRAIN = original

    def test_search_returns_fallback_on_no_results(self):
        from tools.researcher import Researcher
        brain = _StubBrain()
        researcher = Researcher(brain)
        with patch("tools.researcher.DDGS") as mock_ddgs:
            mock_ddgs.return_value.__enter__.return_value.text.return_value = []
            result = researcher.search("nothing found query")
        self.assertIn("couldn't find", result.lower())

    def test_search_handles_exception_gracefully(self):
        from tools.researcher import Researcher
        brain = _StubBrain()
        researcher = Researcher(brain)
        with patch("tools.researcher.DDGS", side_effect=Exception("network error")):
            result = researcher.search("broken query")
        self.assertIn("failed", result.lower())


# ===========================================================================
# FIX 5 — brain.py: ollama_deep detection, routing, warmup
# ===========================================================================

class TestBrainOllamaDeep(unittest.TestCase):
    """Regression: ollama_deep must be detectable and correctly routed."""

    def _make_brain_with_apis(self, available: list):
        """Return a Brain instance with a pre-set available_apis list."""
        from core.brain import Brain
        from core.memory import Memory
        mem = Memory(":memory:")   # non-existent file → empty memory, harmless
        with patch.object(Brain, "_detect_apis", return_value=available), \
             patch.object(Brain, "_update_priority"), \
             patch.object(Brain, "_warmup_ollama"):
            brain = Brain.__new__(Brain)
            brain.memory = mem
            brain.available_apis = available
        return brain

    def test_detect_apis_probes_ollama_deep(self):
        from core.brain import Brain
        import inspect
        src = inspect.getsource(Brain._detect_apis)
        self.assertIn("ollama_deep", src,
                      "_detect_apis must probe for ollama_deep")
        self.assertIn("OLLAMA_MODEL_DEEP", src,
                      "_detect_apis must reference OLLAMA_MODEL_DEEP")

    def test_call_ollama_uses_model_map(self):
        from core.brain import Brain
        import inspect
        src = inspect.getsource(Brain._call_ollama)
        self.assertIn("_MODEL_MAP", src,
                      "_call_ollama must use _MODEL_MAP dict for model lookup")
        self.assertIn("ollama_deep", src,
                      "_MODEL_MAP must contain 'ollama_deep' key")
        self.assertIn("OLLAMA_MODEL_DEEP", src,
                      "_MODEL_MAP must map 'ollama_deep' to OLLAMA_MODEL_DEEP")

    def test_call_ollama_deep_uses_deep_model(self):
        """_call_ollama('ollama_deep', ...) must request the deep model, not smart."""
        from core.brain import Brain
        from config import Config

        brain = self._make_brain_with_apis(["ollama_deep"])
        with patch("core.brain.requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"response": "deep answer"}
            mock_post.return_value = mock_resp
            brain._call_ollama("ollama_deep", "test prompt")
            call_kwargs = mock_post.call_args
            payload = call_kwargs[1]["json"] if call_kwargs[1] else call_kwargs[0][1]
            self.assertEqual(
                payload["model"], Config.OLLAMA_MODEL_DEEP,
                f"ollama_deep must use OLLAMA_MODEL_DEEP ({Config.OLLAMA_MODEL_DEEP})"
            )

    def test_call_ollama_fast_still_uses_fast_model(self):
        from core.brain import Brain
        from config import Config

        brain = self._make_brain_with_apis(["ollama_fast"])
        with patch("core.brain.requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"response": "fast answer"}
            mock_post.return_value = mock_resp
            brain._call_ollama("ollama_fast", "test prompt")
            call_kwargs = mock_post.call_args
            payload = call_kwargs[1]["json"] if call_kwargs[1] else call_kwargs[0][1]
            self.assertEqual(payload["model"], Config.OLLAMA_MODEL_FAST)

    def test_call_ollama_smart_still_uses_smart_model(self):
        from core.brain import Brain
        from config import Config

        brain = self._make_brain_with_apis(["ollama_smart"])
        with patch("core.brain.requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"response": "smart answer"}
            mock_post.return_value = mock_resp
            brain._call_ollama("ollama_smart", "test prompt")
            call_kwargs = mock_post.call_args
            payload = call_kwargs[1]["json"] if call_kwargs[1] else call_kwargs[0][1]
            self.assertEqual(payload["model"], Config.OLLAMA_MODEL_SMART)

    def test_warmup_thread_includes_ollama_deep(self):
        from core.brain import Brain
        import inspect
        src = inspect.getsource(Brain.__init__)
        # New guard uses any(k in ...)
        self.assertIn("ollama_deep", src,
                      "Brain.__init__ warmup guard must include ollama_deep")

    def test_unknown_ollama_variant_falls_back_to_smart(self):
        from core.brain import Brain
        from config import Config

        brain = self._make_brain_with_apis(["ollama_smart"])
        with patch("core.brain.requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"response": "fallback answer"}
            mock_post.return_value = mock_resp
            brain._call_ollama("ollama_unknown_variant", "test prompt")
            call_kwargs = mock_post.call_args
            payload = call_kwargs[1]["json"] if call_kwargs[1] else call_kwargs[0][1]
            self.assertEqual(payload["model"], Config.OLLAMA_MODEL_SMART,
                             "Unknown ollama variant must fall back to OLLAMA_MODEL_SMART")


# ===========================================================================
# FIX 6a — main.py: copilot mode has a handler
# ===========================================================================

class TestMainCopilotHandler(unittest.TestCase):
    """Regression: mode='copilot' must NOT fall through to plain brain.think()."""

    def _run_handle(self, text: str, copilot):
        """Call handle_user_input with a copilot that triggers on text."""
        from main import handle_user_input

        brain = _StubBrain()
        logger = MagicMock()
        voice = MagicMock()
        voice.speak = MagicMock()
        autocorrect = MagicMock()
        autocorrect.correct_input.return_value = (text, False)
        executor = _StubExecutor()
        self_model = _StubSelfModel()
        council = MagicMock()
        council.deliberate.return_value = MagicMock()
        diagnostics = _StubDiagnostics()

        from core.dialog_manager import DialogManager
        dm = DialogManager()

        response, should_exit = handle_user_input(
            text, voice, autocorrect, executor, copilot,
            brain, self_model, dm, council, diagnostics, logger
        )
        return response, brain

    def test_copilot_mode_calls_copilot_respond(self):
        copilot = MagicMock()
        copilot.active = True
        copilot.should_activate.return_value = True
        copilot.respond.return_value = "[copilot walked through it]"

        response, brain = self._run_handle(
            "walk me through installing git", copilot
        )
        # copilot.respond must have been called
        copilot.respond.assert_called()

    def test_copilot_mode_does_not_fall_to_brain_think(self):
        """When copilot is active, brain.think must NOT be called."""
        copilot = MagicMock()
        copilot.active = True
        copilot.should_activate.return_value = True
        copilot.respond.return_value = "[copilot response]"

        from main import handle_user_input
        brain = _StubBrain()
        brain.think = MagicMock(return_value="[raw think]")

        logger = MagicMock()
        voice = MagicMock()
        autocorrect = MagicMock()
        autocorrect.correct_input.return_value = ("walk me through git", False)

        from core.dialog_manager import DialogManager
        dm = DialogManager()
        council = MagicMock()
        council.deliberate.return_value = MagicMock()

        handle_user_input(
            "walk me through git", voice, autocorrect, _StubExecutor(),
            copilot, brain, _StubSelfModel(), dm, council,
            _StubDiagnostics(), logger
        )
        brain.think.assert_not_called()


# ===========================================================================
# FIX 6b — main.py: get_context returns List[Dict], must be stringified
# ===========================================================================

class TestMainContextStringification(unittest.TestCase):
    """Regression: get_context() list must be converted to a string before
    being embedded in the logic-engine prompt."""

    def test_context_is_string_in_logic_engine_call(self):
        from main import handle_user_input
        from core.logic_engine import LogicalEngine

        brain = _StubBrain()
        # Confirm memory returns a list (the bug condition)
        brain.memory.get_context.return_value = [
            {"role": "user",      "content": "previous question"},
            {"role": "assistant", "content": "previous answer"},
        ]

        captured_contexts = []
        original_reason = LogicalEngine.reason

        def _spy_reason(self_le, problem, context=""):
            captured_contexts.append(context)
            return "[reasoned]"

        voice = MagicMock(); voice.speak = MagicMock()
        autocorrect = MagicMock()
        autocorrect.correct_input.return_value = ("why does recursion cause stack overflow", False)
        logger = MagicMock()
        council = MagicMock(); council.deliberate.return_value = MagicMock()

        with patch.object(LogicalEngine, "reason", _spy_reason):
            handle_user_input(
                "why does recursion cause stack overflow",
                voice, autocorrect, _StubExecutor(), _StubCopilot(),
                brain, _StubSelfModel(), __import__(
                    "core.dialog_manager", fromlist=["DialogManager"]
                ).DialogManager(),
                council, _StubDiagnostics(), logger
            )

        if captured_contexts:
            ctx = captured_contexts[0]
            self.assertIsInstance(ctx, str,
                                  "context passed to logic_engine.reason() must be a str, not a list")
            self.assertNotIn("{'role'", ctx,
                             "context must not contain raw Python dict repr")


# ===========================================================================
# FIX 6c — main.py: spinner typo (trailing colon) is removed
# ===========================================================================

class TestMainSpinnerTypo(unittest.TestCase):
    """Regression: console.status text must not end with a colon."""

    def test_no_thinking_colon_typo(self):
        main_src = (REPO_ROOT / "main.py").read_text(encoding="utf-8")
        self.assertNotIn(
            '[/cyan]":',
            main_src,
            'Spinner text "[cyan]Thinking...[/cyan]:" must not end with a literal colon'
        )
        # The correct form (no colon) must be present
        self.assertIn(
            '"[cyan]Thinking...[/cyan]"',
            main_src,
            'main.py must contain the corrected spinner "[cyan]Thinking...[/cyan]"'
        )


# ===========================================================================
# FIX 6d — main.py: autonomist.learn_from_session called before finalize
# ===========================================================================

class TestMainShutdownOrder(unittest.TestCase):
    """Regression: autonomist.learn_from_session must be called and must
    come before logger.finalize() in the source text."""

    def test_learn_from_session_present_in_source(self):
        src = (REPO_ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn(
            "autonomist.learn_from_session(logger.filename)",
            src,
            "main.py must call autonomist.learn_from_session(logger.filename)"
        )

    def test_learn_before_finalize_in_source(self):
        src = (REPO_ROOT / "main.py").read_text(encoding="utf-8")
        learn_pos = src.find("autonomist.learn_from_session(logger.filename)")
        finalize_pos = src.find("logger.finalize()")
        self.assertGreater(learn_pos, 0, "learn_from_session call not found")
        self.assertGreater(finalize_pos, 0, "logger.finalize() call not found")
        self.assertLess(
            learn_pos, finalize_pos,
            "autonomist.learn_from_session must appear BEFORE logger.finalize() in main.py"
        )


# ===========================================================================
# Integration: DialogManager full routing table
# ===========================================================================

class TestDialogManagerRouting(unittest.TestCase):
    """Smoke test the entire routing table — every mode must be reachable."""

    def setUp(self):
        from core.dialog_manager import DialogManager
        self.dm = DialogManager()
        self.executor = _StubExecutor()
        self.copilot = _StubCopilot()
        self.diagnostics = _StubDiagnostics()
        self.self_model = _StubSelfModel()

    def _analyze(self, text):
        return self.dm.analyze(text, self.executor, self.copilot,
                               self.diagnostics, self.self_model)

    def test_chat_fallback(self):
        d = self._analyze("how are you today")
        self.assertEqual(d.mode, "chat")

    def test_reflection_mode(self):
        d = self._analyze("why do I keep procrastinating on this")
        self.assertEqual(d.mode, "reflection")

    def test_analysis_mode(self):
        d = self._analyze("why does quicksort outperform bubble sort")
        self.assertEqual(d.mode, "analysis")

    def test_creative_mode(self):
        d = self._analyze("brainstorm ideas for a new product")
        self.assertEqual(d.mode, "creative")

    def test_action_pending_routes_when_executor_waiting(self):
        executor = MagicMock()
        executor.waiting_for_permission.return_value = True
        executor.waiting_for_followup.return_value = False
        executor.waiting_for_clarification.return_value = False
        executor.waiting_for_plan_choice.return_value = False
        d = self.dm.analyze("yes do it", executor, self.copilot,
                             self.diagnostics, self.self_model)
        self.assertEqual(d.mode, "action_pending")

    def test_high_stakes_flag_set(self):
        d = self._analyze("what dose of ibuprofen is safe for a child")
        self.assertTrue(d.high_stakes)

    def test_emotional_flag_set(self):
        d = self._analyze("I feel so lonely and overwhelmed")
        self.assertTrue(d.emotionally_weighted)

    def test_analytical_flag_set(self):
        d = self._analyze("compare the tradeoffs of SQL vs NoSQL")
        self.assertTrue(d.analytical)

    def test_creative_flag_set(self):
        d = self._analyze("brainstorm unusual ways to learn a language")
        self.assertTrue(d.creative)

    def test_reflective_flag_set(self):
        d = self._analyze("what pattern do I keep falling into")
        self.assertTrue(d.reflective)

    def test_decision_has_all_required_fields(self):
        d = self._analyze("hello")
        self.assertIsNotNone(d.mode)
        self.assertIsNotNone(d.depth)
        self.assertIsNotNone(d.tone)
        self.assertIsNotNone(d.reason)


# ===========================================================================
# Integration: Memory module
# ===========================================================================

class TestMemory(unittest.TestCase):
    """Smoke test memory add/get_context/summary."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, dir=tempfile.gettempdir()
        )
        self.tmp.close()
        from core.memory import Memory
        self.mem = Memory(self.tmp.name)

    def tearDown(self):
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def test_add_user_turn(self):
        self.mem.add("user", "hello memory")
        ctx = self.mem.get_context()
        roles = [e["role"] for e in ctx]
        self.assertIn("user", roles)

    def test_add_assistant_turn(self):
        self.mem.add("assistant", "hi there")
        ctx = self.mem.get_context()
        roles = [e["role"] for e in ctx]
        self.assertIn("assistant", roles)

    def test_role_normalization_iris_to_assistant(self):
        self.mem.add("iris", "normalized response")
        ctx = self.mem.get_context()
        for e in ctx:
            self.assertNotEqual(e["role"], "iris",
                                "role 'iris' must be normalized to 'assistant'")

    def test_get_context_returns_list_of_dicts(self):
        self.mem.add("user", "test")
        ctx = self.mem.get_context()
        self.assertIsInstance(ctx, list)
        for item in ctx:
            self.assertIn("role", item)
            self.assertIn("content", item)

    def test_get_context_respects_max_turns(self):
        for i in range(10):
            self.mem.add("user", f"turn {i}")
            self.mem.add("assistant", f"reply {i}")
        ctx = self.mem.get_context(max_turns=3)
        self.assertLessEqual(len(ctx), 6)  # 3 turns × 2 roles

    def test_persistence_across_instances(self):
        from core.memory import Memory
        self.mem.add("user", "persist this")
        mem2 = Memory(self.tmp.name)
        ctx = mem2.get_context()
        contents = [e["content"] for e in ctx]
        self.assertIn("persist this", contents)

    def test_summary_returns_string(self):
        result = self.mem.summary()
        self.assertIsInstance(result, str)


# ===========================================================================
# Integration: SessionLogger used by Autonomist
# ===========================================================================

class TestAutonomistReadsSessionFile(unittest.TestCase):
    """Regression: autonomist.learn_from_session must succeed when file exists
    and the path was written by SessionLogger (absolute path fixture)."""

    def test_learn_skips_gracefully_when_file_missing(self):
        from core.autonomist import Autonomist
        brain = _StubBrain()
        a = Autonomist(brain)
        # Should not raise, just return silently
        a.learn_from_session("/tmp/__nonexistent_iris_session__.md")

    def test_learn_reads_real_session_file(self):
        from core.session_logger import SessionLogger
        from core.autonomist import Autonomist

        # Create a real session log
        logger = SessionLogger()
        logger.log_turn("User", "what is recursion")
        logger.log_turn("IRIS", "A function calling itself until a base case is met.")
        logger.finalize()

        brain = _StubBrain()
        a = Autonomist(brain)
        # Stub _call_api so it returns valid JSON
        brain._call_api = MagicMock(return_value='{"recursion_explained": "yes"}')

        # Must not raise and must call _call_api with the file content
        a.learn_from_session(logger.filename)
        brain._call_api.assert_called()

    def test_kb_path_is_absolute(self):
        from core.autonomist import Autonomist
        brain = _StubBrain()
        a = Autonomist(brain)
        self.assertTrue(os.path.isabs(a.kb_path),
                        "Autonomist.kb_path must be an absolute path")


# ===========================================================================
# Config smoke test
# ===========================================================================

class TestConfig(unittest.TestCase):
    def test_rms_thresholds(self):
        from config import Config
        self.assertEqual(Config.WAKE_RMS_THRESHOLD, 400)
        self.assertEqual(Config.COMMAND_RMS_THRESHOLD, 550)

    def test_brain_priority_contains_ollama_deep(self):
        from config import Config
        self.assertIn("ollama_deep", Config.BRAIN_PRIORITY)

    def test_ollama_model_deep_has_default(self):
        from config import Config
        self.assertTrue(
            hasattr(Config, "OLLAMA_MODEL_DEEP") and Config.OLLAMA_MODEL_DEEP,
            "Config must have a non-empty OLLAMA_MODEL_DEEP"
        )

    def test_primary_brain_default_is_non_empty(self):
        from config import Config
        self.assertTrue(Config.PRIMARY_BRAIN,
                        "Config.PRIMARY_BRAIN must have a non-empty default")

    def test_validate_returns_bool(self):
        from config import Config
        result = Config.validate()
        self.assertIsInstance(result, bool)


if __name__ == "__main__":
    unittest.main(verbosity=2)
