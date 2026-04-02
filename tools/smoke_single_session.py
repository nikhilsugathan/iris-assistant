"""
Smoke test: single session round-trip
=====================================
Simulates one lightweight text-mode interaction setup without calling any
remote APIs or requiring voice IO.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from config import Config
    from core.memory import Memory
    from core.voice import Voice
    from core.brain import Brain
    from core.council import Council
    from core.dialog_manager import DialogManager
    from core.self_model import SelfModel
    from core.diagnostics import SelfDiagnostics
    from core.executor import ActionExecutor
    from core.copilot import CoPilot
except ImportError as exc:
    print(f"FAIL  import error: {exc}")
    sys.exit(1)

try:
    memory = Memory(Config.MEMORY_FILE)
    voice = Voice(text_mode=True)
    assert voice.io_disabled, "Voice IO must be disabled when text_mode=True"
    brain = Brain(memory)
    council = Council()
    dialog_manager = DialogManager()
    self_model = SelfModel()
    diagnostics = SelfDiagnostics()
    executor = ActionExecutor(voice, brain)
    copilot = CoPilot(brain, voice, memory)
    assert council is not None and executor is not None and copilot is not None
except Exception as exc:
    print(f"FAIL  session setup error: {exc}")
    sys.exit(1)

try:
    decision = dialog_manager.analyze("hello", executor, copilot, diagnostics, self_model)
    assert hasattr(decision, "mode"), "DialogManager.analyze must return an object with a 'mode' attribute"
except Exception as exc:
    print(f"FAIL  dialog routing error: {exc}")
    sys.exit(1)

try:
    memory.add("user", "hello")
    ctx = memory.get_context(max_turns=1)
    assert ctx and ctx[-1]["content"] == "hello", "Memory round-trip failed"
except Exception as exc:
    print(f"FAIL  memory round-trip error: {exc}")
    sys.exit(1)

print("smoke_single_session: PASS")
