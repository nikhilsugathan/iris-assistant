"""
Smoke test: terminal entry-point validation
===========================================
Validates that the core text-mode startup path can import and instantiate
without a live mic, network backend, or interactive input.
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
    from core.dialog_manager import DialogManager
    from core.diagnostics import run_smoke_tests
except ImportError as exc:
    print(f"FAIL  import error: {exc}")
    sys.exit(1)

try:
    memory = Memory(Config.MEMORY_FILE)
    voice = Voice(text_mode=True)
    assert voice.io_disabled, "Voice IO must be disabled when text_mode=True"
    brain = Brain(memory)
    dialog_manager = DialogManager()
    assert dialog_manager is not None
except Exception as exc:
    print(f"FAIL  instantiation error: {exc}")
    sys.exit(1)

results = run_smoke_tests()
failures = [r for r in results if not r.ok and r.severity == "critical"]
if failures:
    for failure in failures:
        print(f"FAIL  {failure.name}: {failure.message}")
    sys.exit(1)

print("smoke_terminal_entry: PASS")
