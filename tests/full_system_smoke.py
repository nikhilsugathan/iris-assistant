"""
IRIS Full System Smoke Test
============================
Tests that main.py can be fully initialized and that a basic 'hey iris'
interaction flows end-to-end without a Traceback.

Run from the project root:
    python tests/full_system_smoke.py

No real API keys are required — Brain falls back gracefully when no
backends are reachable.  Voice hardware is disabled via the
IRIS_DISABLE_VOICE_IO env-var so the test runs anywhere (CI, headless
servers, machines without a microphone).
"""

from __future__ import annotations

import os
import sys
import traceback
import unittest.mock

# ── Disable hardware voice I/O before any IRIS import ────────────────────────
os.environ.setdefault("IRIS_DISABLE_VOICE_IO", "1")

# Make sure the project root is on sys.path when running from any directory.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# ── Rich console for test output ─────────────────────────────────────────────
from rich.console import Console

_console = Console()

PASS = "[bold green]✅ PASS[/bold green]"
FAIL = "[bold red]❌ FAIL[/bold red]"

_failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        _console.print(f"  {PASS}  {label}")
    else:
        msg = f"{label}" + (f" — {detail}" if detail else "")
        _console.print(f"  {FAIL}  {msg}")
        _failures.append(msg)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — core/__init__.py exports
# ═══════════════════════════════════════════════════════════════════════════════
_console.rule("[bold cyan]Section 1: core package exports[/bold cyan]")

try:
    from core import logger, console as core_console  # noqa: F401
    check("from core import logger, console", True)
    check("logger is a logging.Logger", hasattr(logger, "info") and callable(logger.info))
    check("console is a rich.Console", hasattr(core_console, "print") and callable(core_console.print))
except Exception as exc:
    check("from core import logger, console", False, str(exc))

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — Module imports (mirrors main.py's import block)
# ═══════════════════════════════════════════════════════════════════════════════
_console.rule("[bold cyan]Section 2: Module imports[/bold cyan]")

try:
    from config import Config
    from core.autocorrect import AutoCorrector
    from core.brain import Brain
    from core.council import Council
    from core.copilot import CoPilot
    from core.dialog_manager import DialogManager
    from core.diagnostics import SelfDiagnostics, BootDiagnostics
    from core.executor import ActionExecutor
    from core.memory import Memory
    from core.self_model import SelfModel
    from core.voice import Voice
    check("All core module imports succeeded", True)
except Exception as exc:
    check("All core module imports succeeded", False, str(exc))
    _console.print("[bold red]Cannot continue — aborting smoke test.[/bold red]")
    sys.exit(1)

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — Instantiation (mirrors main() in main.py)
# ═══════════════════════════════════════════════════════════════════════════════
_console.rule("[bold cyan]Section 3: Object instantiation[/bold cyan]")

try:
    memory = Memory(Config.MEMORY_FILE)
    check("Memory instantiated", True)
except Exception as exc:
    check("Memory instantiated", False, str(exc))
    memory = None

try:
    brain = Brain(memory)
    check("Brain instantiated", True)
except Exception as exc:
    check("Brain instantiated", False, str(exc))
    brain = None

try:
    # text_mode=True + env-var disables all hardware
    voice = Voice(text_mode=True)
    check("Voice instantiated", True)
except Exception as exc:
    check("Voice instantiated", False, str(exc))
    voice = None

try:
    copilot = CoPilot(brain, voice, memory)
    check("CoPilot instantiated", True)
except Exception as exc:
    check("CoPilot instantiated", False, str(exc))
    copilot = None

try:
    executor = ActionExecutor(voice, brain)
    check("ActionExecutor instantiated", True)
except Exception as exc:
    check("ActionExecutor instantiated", False, str(exc))
    executor = None

try:
    autocorrect = AutoCorrector(brain)
    check("AutoCorrector instantiated", True)
except Exception as exc:
    check("AutoCorrector instantiated", False, str(exc))
    autocorrect = None

try:
    self_model = SelfModel()
    check("SelfModel instantiated", True)
except Exception as exc:
    check("SelfModel instantiated", False, str(exc))
    self_model = None

try:
    dialog_manager = DialogManager()
    check("DialogManager instantiated", True)
except Exception as exc:
    check("DialogManager instantiated", False, str(exc))
    dialog_manager = None

try:
    council = Council()
    check("Council instantiated", True)
except Exception as exc:
    check("Council instantiated", False, str(exc))
    council = None

try:
    diagnostics = SelfDiagnostics()
    check("SelfDiagnostics instantiated", True)
except Exception as exc:
    check("SelfDiagnostics instantiated", False, str(exc))
    diagnostics = None

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — Interface contract verification
# ═══════════════════════════════════════════════════════════════════════════════
_console.rule("[bold cyan]Section 4: Interface contract[/bold cyan]")

# -- ActionExecutor callable methods --
if executor is not None:
    required_executor_methods = [
        "waiting_for_followup",
        "handle_followup_response",
        "waiting_for_clarification",
        "handle_clarification_response",
        "waiting_for_plan_choice",
        "handle_plan_choice",
        "waiting_for_permission",
        "handle_permission_response",
        "plan_action",
    ]
    for method_name in required_executor_methods:
        attr = getattr(executor, method_name, None)
        check(
            f"executor.{method_name} is callable",
            callable(attr),
            f"got {type(attr).__name__!r} instead of a method",
        )

# -- Voice attributes and methods --
if voice is not None:
    check("voice.mic_ready attribute exists", hasattr(voice, "mic_ready"))
    check("voice.audio_ready attribute exists", hasattr(voice, "audio_ready"))
    check("voice.speak is callable", callable(getattr(voice, "speak", None)))
    check("voice.stop_speaking is callable", callable(getattr(voice, "stop_speaking", None)))
    check("voice.listen_text is callable", callable(getattr(voice, "listen_text", None)))
    check("voice.listen_for_wake is callable", callable(getattr(voice, "listen_for_wake", None)))
    check("voice.listen_for_command is callable", callable(getattr(voice, "listen_for_command", None)))

# -- Brain attributes and methods --
if brain is not None:
    check("brain.memory attribute exists", hasattr(brain, "memory"))
    check("brain.think is callable", callable(getattr(brain, "think", None)))
    check("brain.available_apis is a list", isinstance(getattr(brain, "available_apis", None), list))

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — End-to-end 'hey iris' interaction
# ═══════════════════════════════════════════════════════════════════════════════
_console.rule("[bold cyan]Section 5: End-to-end greeting simulation[/bold cyan]")

if all(x is not None for x in [voice, executor, copilot, brain, self_model, dialog_manager, council, diagnostics, autocorrect]):
    try:
        # Import handle_user_input directly from main.py
        from main import handle_user_input, strip_wake_word, contains_wake_word

        heard_text = "hey iris"
        check("contains_wake_word('hey iris')", contains_wake_word(heard_text))

        # Use a minimal command so handle_user_input has something to process.
        # Stripping 'hey iris' alone often leaves an empty string, so we fall
        # back to a simple greeting that Brain can always respond to.
        test_input = strip_wake_word(heard_text) or "hello"

        with unittest.mock.patch.object(brain, "think", return_value="I'm here."):
            response, should_exit = handle_user_input(
                test_input,
                voice,
                autocorrect,
                executor,
                copilot,
                brain,
                self_model,
                dialog_manager,
                council,
                diagnostics,
            )

        check("handle_user_input returns a response", isinstance(response, str) and len(response) > 0)
        check("handle_user_input does not request exit", should_exit is False)
        _console.print(f"\n  [dim]Response received:[/dim] [italic]{response!r}[/italic]\n")

    except Exception:
        tb = traceback.format_exc()
        check("handle_user_input completes without Traceback", False, "see traceback above")
        _console.print(f"[red]{tb}[/red]")
else:
    _console.print("[yellow]  Skipping end-to-end test — one or more objects failed to instantiate.[/yellow]")

# ═══════════════════════════════════════════════════════════════════════════════
# FINAL VERDICT
# ═══════════════════════════════════════════════════════════════════════════════
_console.rule()
if not _failures:
    _console.print("\n[bold green]✅ All Systems Nominal[/bold green]\n")
    sys.exit(0)
else:
    _console.print(f"\n[bold red]❌ {len(_failures)} check(s) failed:[/bold red]")
    for f in _failures:
        _console.print(f"   • {f}")
    _console.print()
    sys.exit(1)
