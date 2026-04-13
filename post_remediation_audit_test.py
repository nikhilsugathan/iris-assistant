from __future__ import annotations

import sys
import tempfile
import types
import unittest
import json
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


class _DummyPanel:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_make_stub("rich", __path__=[])
_make_stub("rich.console", Console=_DummyConsole)
_make_stub("rich.panel", Panel=_DummyPanel)


class _Config:
    PROJECT_ROOT = str(ROOT)
    MAX_MEMORY_TURNS = 200
    WAKE_WORDS = ["phoenix"]
    PUBLIC_WAKE_WORD = "phoenix"
    ADMIN_WAKE_WORD = "omega"
    LOCAL_MODEL_PATH = ""
    N_GPU_LAYERS = 0
    N_CTX = 512
    OLLAMA_BASE_URL = "http://localhost:11434"
    OLLAMA_MODEL_FAST = "phi3.5"
    OLLAMA_MODEL_SMART = "deepseek-r1:8b"
    BRAIN_PRIORITY = ["llama_cpp", "groq", "ollama_smart", "claude", "gemini"]
    PRIMARY_BRAIN = "groq"
    FALLBACK_BRAIN = "gemini"
    USE_ENSEMBLE = False
    WEB_KEYWORDS = ["search"]
    CODE_KEYWORDS = ["code"]
    IRIS_PERSONA = "You are IRIS."
    ALETHEIA_PERSONA = "You are Aletheia."
    GROQ_MODEL = "g"
    GEMINI_MODEL = "g"
    CLAUDE_MODEL = "c"
    PERPLEXITY_MODEL = "p"
    GROQ_API_KEY = ""
    GEMINI_API_KEY = ""
    CLAUDE_API_KEY = ""
    PERPLEXITY_API_KEY = ""
    DANGER_PATTERNS = [
        r"\beval\b",
        r"\bexec\b",
        r"shutil\.rmtree",
        r"os\.system",
        r"subprocess\.run.*shell\s*=\s*True",
        r"\.unlink\(",
    ]


_make_stub("config", Config=_Config)

sys.modules.pop("core.brain", None)
sys.modules.pop("core.memory", None)
sys.modules.pop("core.evolution", None)

from core.brain import Brain
from core.memory import Memory
import core.evolution as evolution_module
from core.evolution import EvolutionEngine


class TestPostRemediationAudit(unittest.TestCase):
    def test_general_and_code_routes_include_local_fallbacks(self):
        memory = MagicMock()
        memory.get_context.return_value = []
        fake_get = MagicMock()
        fake_get.status_code = 200
        fake_get.json.return_value = {"models": []}
        with patch("core.brain.requests.get", return_value=fake_get):
            brain = Brain(memory)

        self.assertEqual(
            brain._get_apis_for_query("general"),
            ["groq", "gemini", "claude", "llama_cpp", "ollama_smart", "ollama_fast"],
        )
        self.assertEqual(
            brain._get_apis_for_query("code"),
            ["groq", "llama_cpp", "claude", "ollama_smart", "ollama_fast"],
        )

    def test_ollama_generate_prompt_preserves_persona_and_context(self):
        memory = MagicMock()
        memory.get_context.return_value = [{"role": "assistant", "content": "Previous reply"}]
        fake_get = MagicMock()
        fake_get.status_code = 200
        fake_get.json.return_value = {"models": []}
        with patch("core.brain.requests.get", return_value=fake_get):
            brain = Brain(memory)

        fake_response = MagicMock()
        fake_response.json.return_value = {"response": "ok"}
        with patch("core.brain.requests.post", return_value=fake_response) as post:
            response = brain._call_ollama(
                "ollama_smart",
                "How are you?",
                {"context_turns": 1, "temperature": 0.4, "max_tokens": 42},
                admin_unlocked=True,
            )

        self.assertEqual(response, "ok")
        payload = post.call_args.kwargs["json"]
        self.assertIn("System: You are Aletheia.", payload["prompt"])
        self.assertIn("Assistant: Previous reply", payload["prompt"])
        self.assertIn("User: How are you?", payload["prompt"])
        self.assertEqual(payload["options"]["temperature"], 0.4)
        self.assertEqual(payload["options"]["num_predict"], 42)

    def test_memory_sanitization_handles_none_and_punctuated_wake_words(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            memory = Memory(str(Path(temp_dir) / "memory.json"))
            self.assertEqual(memory._sanitize_content(None), "")
            self.assertEqual(memory._sanitize_content("phoenix, open file"), "open file")
            self.assertEqual(memory._sanitize_content("hey omega! run scan"), "run scan")
            self.assertEqual(memory._sanitize_content("phoenix."), "")

    def test_memory_drops_generic_assistant_boilerplate_on_load(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "memory.json"
            target.write_text(
                json.dumps(
                    {
                        "conversation": [
                            {"role": "user", "content": "audible"},
                            {
                                "role": "assistant",
                                "content": "Hello! How can I assist you today? Please let me know your task so I can help you effectively.<think>secret</think>",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            memory = Memory(str(target))
            self.assertEqual(memory.conversation, [{"role": "user", "content": "audible"}])

    def test_postprocess_strips_generic_boilerplate_and_dangling_think_blocks(self):
        memory = MagicMock()
        memory.get_context.return_value = []
        fake_get = MagicMock()
        fake_get.status_code = 200
        fake_get.json.return_value = {"models": []}
        with patch("core.brain.requests.get", return_value=fake_get):
            brain = Brain(memory)

        text = (
            "Hello! How can I assist you today? "
            "Please let me know your task so I can help you effectively.<think>secret plan"
        )
        self.assertEqual(brain._postprocess(text), "")

    def test_approve_tool_rescans_pending_code_before_write(self):
        engine = EvolutionEngine(brain=MagicMock(), researcher=None)
        engine._pending_tool_code = "def custom_bad():\n    eval('1 + 1')\n"

        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "custom_tools.py"
            with patch.object(evolution_module, "CUSTOM_TOOLS_PATH", str(target)):
                result = engine.approve_tool()

        self.assertIn("rejected due to safety patterns", result.lower())
        self.assertIsNone(engine._pending_tool_code)
        self.assertFalse(target.exists())

    def test_triage_unknown_intent_handles_empty_draft_response(self):
        brain = MagicMock()
        brain._call_api.return_value = None
        engine = EvolutionEngine(brain=brain, researcher=None)

        result = engine.triage_unknown_intent("write a helper", admin_unlocked=True)

        self.assertIn("Tool drafting failed", result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
