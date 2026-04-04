from __future__ import annotations

import contextlib
import importlib
import sys
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


class _DummyConsole:
    def print(self, *args, **kwargs):
        return None

    def bell(self):
        return None

    def status(self, *args, **kwargs):
        return contextlib.nullcontext()


class _DummySelfModel:
    def __init__(self, admin_unlocked: bool = False):
        self.admin_unlocked = admin_unlocked

    def summary(self) -> str:
        return "Aletheia" if self.admin_unlocked else "IRIS"


ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_make_stub("rich", __path__=[])
_make_stub("rich.console", Console=_DummyConsole)
_make_stub("rich.table", Table=MagicMock)
_make_stub("rich.markup", escape=lambda text: text)

_make_stub("core", __path__=[])
_make_stub("tools", __path__=[])


class _Config:
    SYSTEM_MOTTO = "Intelligence. Redefined."
    WAKE_WORDS = ["legacy"]
    PUBLIC_WAKE_WORD = "phoenix"
    ADMIN_WAKE_WORD = "omega"
    VOICE_DEBUG_TRANSCRIPTS = False


_make_stub("config", Config=_Config)
_make_stub("core.autocorrect", AutoCorrector=MagicMock)
_make_stub("core.brain", Brain=MagicMock)
_make_stub("core.council", Council=MagicMock)
_make_stub("core.copilot", CoPilot=MagicMock)
_make_stub("core.dialog_manager", DialogManager=MagicMock)
_make_stub(
    "core.diagnostics",
    SelfDiagnostics=MagicMock,
    BootDiagnostics=MagicMock,
    get_vram_status=MagicMock(return_value=(0.0, 0.0)),
)
_make_stub("core.executor", ActionExecutor=MagicMock)
_make_stub("core.memory", Memory=MagicMock)
_make_stub("core.self_model", SelfModel=_DummySelfModel)
_make_stub("core.voice", Voice=MagicMock)
_make_stub("core.session_logger", SessionLogger=MagicMock)
_make_stub("core.evolution", EvolutionEngine=MagicMock)
_make_stub("core.autonomist", Autonomist=MagicMock)
_make_stub("tools.researcher", Researcher=MagicMock)
_make_stub("core.logger", get_logger=MagicMock(return_value=MagicMock(debug=MagicMock())))
_make_stub("psutil", cpu_percent=MagicMock(return_value=10.0))

sys.modules.pop("main", None)
main = importlib.import_module("main")


def _make_voice() -> MagicMock:
    voice = MagicMock()
    voice.is_speaking.return_value = False
    voice.listen_for_interrupt.return_value = ""
    voice.listen_for_command.return_value = ""
    voice.should_ignore_transcript.return_value = False
    return voice


def _make_brain() -> MagicMock:
    brain = MagicMock()
    brain._call_groq_simple.return_value = ""
    brain.memory = MagicMock()
    brain.memory.conversation = ["stale"]
    return brain


class TestPhase5StateMachine(unittest.TestCase):
    def test_active_wake_word_switches_with_persona(self):
        public_model = _DummySelfModel(admin_unlocked=False)
        admin_model = _DummySelfModel(admin_unlocked=True)

        self.assertEqual(main._active_wake_words(public_model), ["phoenix"])
        self.assertEqual(main._active_wake_words(admin_model), ["omega"])
        self.assertTrue(main._matches_active_wake_word("phoenix open file", public_model))
        self.assertFalse(main._matches_active_wake_word("omega open file", public_model))
        self.assertTrue(main._matches_active_wake_word("omega open file", admin_model))
        self.assertFalse(main._matches_active_wake_word("phoenix open file", admin_model))

    def test_strip_active_wake_word_uses_only_current_persona_word(self):
        public_model = _DummySelfModel(admin_unlocked=False)
        admin_model = _DummySelfModel(admin_unlocked=True)

        self.assertEqual(main._strip_active_wake_word("phoenix open file", public_model), "open file")
        self.assertEqual(main._strip_active_wake_word("omega open file", admin_model), "open file")
        self.assertEqual(main._strip_active_wake_word("omega open file", public_model), "omega open file")

    def test_exact_exit_routing_terminates_public_and_locks_admin(self):
        voice = _make_voice()
        brain = _make_brain()
        public_model = _DummySelfModel(admin_unlocked=False)
        admin_model = _DummySelfModel(admin_unlocked=True)
        autocorrect = MagicMock()

        public_result = main.handle_user_input(
            "terminate",
            voice,
            autocorrect,
            MagicMock(),
            MagicMock(),
            brain,
            public_model,
            MagicMock(),
            MagicMock(),
            MagicMock(),
            MagicMock(),
            voice_mode=False,
        )
        self.assertEqual(public_result, ("EXIT", True))

        admin_result = main.handle_user_input(
            "terminate",
            voice,
            autocorrect,
            MagicMock(),
            MagicMock(),
            brain,
            admin_model,
            MagicMock(),
            MagicMock(),
            MagicMock(),
            MagicMock(),
            voice_mode=False,
        )
        self.assertEqual(admin_result, ("LOCKED", False))
        self.assertFalse(admin_model.admin_unlocked)
        self.assertEqual(brain.memory.conversation, [])
        brain.memory._save.assert_called()

    def test_exit_detection_is_exact_and_persona_scoped(self):
        public_model = _DummySelfModel(admin_unlocked=False)
        admin_model = _DummySelfModel(admin_unlocked=True)

        self.assertEqual(main._classify_exit_action("terminate", public_model), "EXIT")
        self.assertEqual(main._classify_exit_action("terminate", admin_model), "LOCK")
        self.assertIsNone(main._classify_exit_action("terminated", public_model))
        self.assertIsNone(main._classify_exit_action("germinate", public_model))
        self.assertIsNone(main._classify_exit_action("omega terminate", public_model))
        self.assertIsNone(main._classify_exit_action("phoenix terminate", admin_model))

    def test_followup_window_returns_clean_boolean_for_continue_and_exit(self):
        voice = _make_voice()
        autocorrect = MagicMock()
        brain = _make_brain()
        self_model = _DummySelfModel(admin_unlocked=False)
        common_args = (
            voice,
            autocorrect,
            MagicMock(),
            MagicMock(),
            brain,
            self_model,
            MagicMock(),
            MagicMock(),
            MagicMock(),
            MagicMock(),
            None,
            None,
            None,
        )

        with patch.object(main, "handle_user_input", return_value=("ok", False)):
            should_exit = main._run_voice_followup_window(
                *common_args,
                initial_input="continue",
                max_turns=1,
                missed_limit=1,
            )
        self.assertFalse(should_exit)

        with patch.object(main, "handle_user_input", return_value=("EXIT", True)):
            should_exit = main._run_voice_followup_window(
                *common_args,
                initial_input="terminate",
                max_turns=1,
                missed_limit=1,
            )
        self.assertTrue(should_exit)

    def test_interrupt_followup_uses_configured_wake_words(self):
        self.assertEqual(main._extract_interrupt_followup("phoenix wait open notes"), "open notes")
        self.assertEqual(main._extract_interrupt_followup("omega, stop current playback"), "current playback")
        self.assertEqual(main._extract_interrupt_followup("phoenix: hold on refresh this"), "refresh this")
        self.assertEqual(main._extract_interrupt_followup("iris wait open notes"), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
