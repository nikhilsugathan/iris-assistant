"""
Smoke test: terminal entry-point validation
===========================================
Validates that all modules required to start IRIS in text mode can be
imported and instantiated without errors.  Intended for CI use only —
no network calls are made and no interactive input is required.
"""

import sys
import os
# Ensure the repo root is on sys.path when this script is invoked directly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── Imports ───────────────────────────────────────────────────────────
try:
    from config import Config
    from core.memory import Memory
    from core.voice import Voice
    from core.brain import Brain
    from core.executor import ActionExecutor
    from core.dialog_manager import DialogManager
    from core.diagnostics import run_smoke_tests
except ImportError as exc:
    print(f"FAIL  import error: {exc}")
    sys.exit(1)

# ── Instantiation checks ──────────────────────────────────────────────
try:
    memory = Memory(Config.MEMORY_FILE)
    voice = Voice(text_mode=True)
    assert voice.io_disabled, "Voice IO must be disabled when text_mode=True"
    brain = Brain(memory)
    dialog_manager = DialogManager()
except Exception as exc:
    print(f"FAIL  instantiation error: {exc}")
    sys.exit(1)

# ── Diagnostic smoke suite ────────────────────────────────────────────
results = run_smoke_tests()
failures = [r for r in results if not r.ok and r.severity == "critical"]
if failures:
    for f in failures:
        print(f"FAIL  {f.name}: {f.message}")
    sys.exit(1)

print("smoke_terminal_entry: PASS")
