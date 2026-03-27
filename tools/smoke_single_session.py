"""
Smoke test: single session round-trip
======================================
Simulates one complete text-mode interaction cycle — memory load, brain
routing, and dialog management — without making any real network calls.
Intended for CI use only.
"""

import os
import sys

# Ensure the project root is on sys.path regardless of where we're invoked from
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# ── Imports ───────────────────────────────────────────────────────────
try:
    from config import Config
    from core.memory import Memory
    from core.voice import Voice
    from core.brain import Brain
    from core.council import Council
    from core.dialog_manager import DialogManager
    from core.self_model import SelfModel
    from core.diagnostics import SelfDiagnostics
except ImportError as exc:
    print(f"FAIL  import error: {exc}")
    sys.exit(1)

# ── Session setup ─────────────────────────────────────────────────────
try:
    memory = Memory(Config.MEMORY_FILE)
    voice = Voice(text_mode=True)
    assert voice.io_disabled, "Voice IO must be disabled when text_mode=True"
    brain = Brain(memory)
    council = Council()
    dialog_manager = DialogManager()
    self_model = SelfModel()
    diagnostics = SelfDiagnostics()
except Exception as exc:
    print(f"FAIL  session setup error: {exc}")
    sys.exit(1)

# ── Dialog routing check ──────────────────────────────────────────────
try:
    # Verify the dialog manager can analyze a sample input without
    # raising an exception.  We do not call brain.think() here because
    # that would require a live LLM backend.
    from core.executor import ActionExecutor
    from core.copilot import CoPilot
    executor = ActionExecutor(voice, brain)
    copilot = CoPilot(brain, voice, memory)
    decision = dialog_manager.analyze(
        "hello", executor, copilot, diagnostics, self_model
    )
    assert hasattr(decision, "mode"), "DialogManager.analyze must return an object with a 'mode' attribute"
except Exception as exc:
    print(f"FAIL  dialog routing error: {exc}")
    sys.exit(1)

# ── Memory round-trip ─────────────────────────────────────────────────
try:
    memory.add("user", "hello")
    ctx = memory.get_context(max_turns=1)
    assert ctx and ctx[-1]["content"] == "hello", "Memory round-trip failed"
except Exception as exc:
    print(f"FAIL  memory round-trip error: {exc}")
    sys.exit(1)

print("smoke_single_session: PASS")
