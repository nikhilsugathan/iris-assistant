"""
IRIS v5.0 — Definitive Stabilization Script (Verified against live source)
Fixes all 12 production bugs. Safe to re-run (idempotent patch_file guards).
Run from project root: python tools/stabilize_v5_final.py
"""
import os, re, sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

def patch_file(path: Path, old: str, new: str, description: str, count: int = 1) -> bool:
    if not path.exists():
        print(f"  ❌ MISSING  [{description}]: {path} not found")
        return False
    content = path.read_text(encoding="utf-8")
    actual = content.count(old)
    if actual == 0:
        print(f"  ⚠  SKIP    [{description}]: already patched or string not found")
        return False
    if actual != count:
        print(f"  ❌ ABORT   [{description}]: expected {count} match(es), found {actual} — unsafe")
        return False
    path.write_text(content.replace(old, new, count), encoding="utf-8")
    print(f"  ✅ PATCHED  [{description}]")
    return True

# ── FIX 1 ─────────────────────────────────────────────────────────────────────
# executor.py: expandvars in _run_command only (context-anchored, avoids _ai_plan)
def fix_executor_expandvars():
    patch_file(
        ROOT / "core/executor.py",
        old=(
            '    def _run_command(self, plan: dict) -> str:\n'
            '        """Run a shell command with defense-in-depth security re-check."""\n'
            '        command = plan.get("command", "")\n'
            '        if not command: return "No command to run."'
        ),
        new=(
            '    def _run_command(self, plan: dict) -> str:\n'
            '        """Run a shell command with defense-in-depth security re-check."""\n'
            '        command = os.path.expandvars(plan.get("command", ""))  # SECURITY: expand env vars before scan\n'
            '        if not command: return "No command to run."'
        ),
        description="Shield: expandvars in _run_command (executor.py)"
    )

# ── FIX 2 ─────────────────────────────────────────────────────────────────────
# executor.py: anchor iris_actions.log to absolute path
def fix_executor_log_path():
    patch_file(
        ROOT / "core/executor.py",
        old='        self.log_file    = "iris_actions.log"',
        new=(
            '        self.log_file    = os.path.join(\n'
            '            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),\n'
            '            "iris_actions.log")'
        ),
        description="Paths: iris_actions.log anchored (executor.py)"
    )

# ── FIX 3 ─────────────────────────────────────────────────────────────────────
# security.py: expandvars in assess() before Layer 1 regex scan
def fix_security_expandvars():
    path = ROOT / "core/security.py"
    # Ensure os is imported
    content = path.read_text(encoding="utf-8")
    if "import os" not in content:
        path.write_text(content.replace("import re\n", "import re\nimport os\n"), encoding="utf-8")
        print("  ✅ PATCHED  [Shield: added os import (security.py)]")
    patch_file(
        path,
        old='        command  = plan.get("command", "")',
        new='        command  = os.path.expandvars(plan.get("command", ""))  # SECURITY: expand before Layer 1 scan',
        description="Shield: expandvars in assess() (security.py)"
    )

# ── FIX 4 ─────────────────────────────────────────────────────────────────────
# config.py: fix PRIMARY_BRAIN case at source, anchor MEMORY_FILE
def fix_config():
    patch_file(
        ROOT / "config.py",
        old='    PRIMARY_BRAIN = "GROQ"',
        new='    PRIMARY_BRAIN = "groq"',
        description="Config: PRIMARY_BRAIN lowercase at source (config.py)"
    )
    patch_file(
        ROOT / "config.py",
        old='    MEMORY_FILE = "iris_memory.json"',
        new=(
            '    MEMORY_FILE = os.path.join(\n'
            '        os.path.dirname(os.path.abspath(__file__)), "iris_memory.json")'
        ),
        description="Paths: MEMORY_FILE anchored (config.py)"
    )

# ── FIX 5 ─────────────────────────────────────────────────────────────────────
# session_logger.py: anchor history/ to absolute path
def fix_session_logger():
    patch_file(
        ROOT / "core/session_logger.py",
        old='        self.history_dir = "history"',
        new=(
            '        _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))\n'
            '        self.history_dir = os.path.join(_root, "history")'
        ),
        description="Paths: history/ anchored (session_logger.py)"
    )

# ── FIX 6 ─────────────────────────────────────────────────────────────────────
# autonomist.py: anchor kb_path AND fix _call_api wrong argument
# Uses __init__ context to avoid hitting the markdown doc-block duplicate
def fix_autonomist():
    patch_file(
        ROOT / "core/autonomist.py",
        old=(
            '    def __init__(self, brain):\n'
            '        self.brain = brain\n'
            '        self.kb_path = "knowledge_base.json"'
        ),
        new=(
            '    def __init__(self, brain):\n'
            '        self.brain = brain\n'
            '        _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))\n'
            '        self.kb_path = os.path.join(_root, "knowledge_base.json")'
        ),
        description="Paths: knowledge_base.json anchored (autonomist.py)"
    )
    # Fix _call_api receiving model name instead of API key
    patch_file(
        ROOT / "core/autonomist.py",
        old='        response = self.brain._call_api(Config.OLLAMA_MODEL_DEEP, learning_prompt)',
        new='        response = self.brain._call_api("ollama_smart", learning_prompt)  # FIX: API key not model name',
        description="Brain: autonomist._call_api uses API key not model name (autonomist.py)"
    )

# ── FIX 7 ─────────────────────────────────────────────────────────────────────
# researcher.py: remove nested console.status (main.py provides the outer one)
def fix_researcher():
    patch_file(
        ROOT / "tools/researcher.py",
        old=(
            '    def search(self, query: str) -> str:\n'
            '        """Fetches live web data and synthesizes it via the Primary Brain."""\n'
            '        with console.status(f"[bold green]Searching for \'{query}\'...[/bold green]"):\n'
            '            try:'
        ),
        new=(
            '    def search(self, query: str) -> str:\n'
            '        """Fetches live web data and synthesizes it via the Primary Brain."""\n'
            '        # FIX: console.status removed — main.py wraps this call with its own spinner\n'
            '        try:'
        ),
        description="UX: nested console.status removed (researcher.py)"
    )
    # Fix indentation of the try block body (dedent by 12→8 spaces)
    path = ROOT / "tools/researcher.py"
    content = path.read_text(encoding="utf-8")
    # The body lines inside the old `with` block had 16-space indent; now need 12
    content = content.replace(
        '                with DDGS() as ddgs:',
        '            with DDGS() as ddgs:'
    ).replace(
        '                if not results:',
        '            if not results:'
    ).replace(
        '                    return "I searched the web but couldn\'t find any relevant information."',
        '                return "I searched the web but couldn\'t find any relevant information."'
    ).replace(
        '                # Format the context for the brain\n'
        '                web_context',
        '            # Format the context for the brain\n'
        '            web_context'
    ).replace(
        '                summary_prompt',
        '            summary_prompt'
    ).replace(
        '                return self.brain._call_api(Config.PRIMARY_BRAIN, summary_prompt)',
        '            return self.brain._call_api(Config.PRIMARY_BRAIN, summary_prompt)'
    ).replace(
        '            except Exception as e:',
        '        except Exception as e:'
    ).replace(
        '                return f"Research failed: {str(e)}"',
        '            return f"Research failed: {str(e)}"'
    )
    path.write_text(content, encoding="utf-8")
    print("  ✅ PATCHED  [UX: researcher.py indentation corrected after try block dedent]")

# ── FIX 8 ─────────────────────────────────────────────────────────────────────
# logic_engine.py: remove nested spinner, fix API key, add empty fallback
def fix_logic_engine():
    patch_file(
        ROOT / "core/logic_engine.py",
        old=(
            '        with console.status("[bold magenta]Engaging Logical Engine...[/bold magenta]"):\n'
            '            # Route specifically to the smart/deep model\n'
            '            model = getattr(Config, "OLLAMA_MODEL_DEEP", "deepseek-r1:8b")\n'
            '            response = self.brain._call_api(model, logic_prompt)\n'
            '\n'
            '        if "<think>" in response:\n'
            '            parts = response.split("</think>")\n'
            '            thinking_trace = parts[0].replace("<think>", "").strip()\n'
            '            final_answer = parts[1].strip() if len(parts) > 1 else ""\n'
            '            \n'
            '            console.print(Panel(\n'
            '                f"[dim]{thinking_trace}[/dim]", \n'
            '                title="[bold magenta]Aletheia Internal Monologue[/bold magenta]", \n'
            '                border_style="magenta"\n'
            '            ))\n'
            '            return final_answer\n'
            '        \n'
            '        return response'
        ),
        new=(
            '        # FIX: no nested spinner — main.py already provides console.status\n'
            '        # FIX: "ollama_smart" is the correct API key, not the raw model name\n'
            '        response = self.brain._call_api("ollama_smart", logic_prompt)\n'
            '\n'
            '        if not response:\n'
            '            return "The reasoning engine returned no response. Check Ollama connectivity."\n'
            '\n'
            '        if "<think>" in response:\n'
            '            parts = response.split("</think>")\n'
            '            thinking_trace = parts[0].replace("<think>", "").strip()\n'
            '            final_answer = parts[1].strip() if len(parts) > 1 else ""\n'
            '\n'
            '            console.print(Panel(\n'
            '                f"[dim]{thinking_trace}[/dim]",\n'
            '                title="[bold magenta]Aletheia Internal Monologue[/bold magenta]",\n'
            '                border_style="magenta"\n'
            '            ))\n'
            '            # FIX: fall back to thinking_trace if model gave no post-</think> text\n'
            '            return final_answer if final_answer else thinking_trace\n'
            '\n'
            '        return response'
        ),
        description="Brain: logic_engine — remove spinner, fix API key, empty fallback"
    )

# ── FIX 9 ─────────────────────────────────────────────────────────────────────
# main.py: wire Researcher + Autonomist + search routing + fixed shutdown
def fix_main():
    path = ROOT / "main.py"
    content = path.read_text(encoding="utf-8")
    changed = False

    # 9a. Add imports
    if "from tools.researcher import Researcher" not in content:
        content = content.replace(
            "from core.session_logger import SessionLogger # New Module Required",
            "from core.session_logger import SessionLogger # New Module Required\n"
            "from tools.researcher import Researcher\n"
            "from core.autonomist import Autonomist"
        )
        print("  ✅ PATCHED  [main.py: Added Researcher + Autonomist imports]")
        changed = True

    # 9b. Extend handle_user_input signature
    old_sig = "def handle_user_input(user_input, voice, autocorrect, executor, copilot, brain, self_model, dialog_manager, council, diagnostics, logger):"
    new_sig = "def handle_user_input(user_input, voice, autocorrect, executor, copilot, brain, self_model, dialog_manager, council, diagnostics, logger, researcher=None, autonomist=None):"
    if old_sig in content:
        content = content.replace(old_sig, new_sig)
        print("  ✅ PATCHED  [main.py: Extended handle_user_input signature]")
        changed = True

    # 9c. Add search routing branch (before the analytical branch)
    if 'decision.mode == "search"' not in content:
        content = content.replace(
            '    elif decision.analytical or decision.depth == "deep":',
            '    elif decision.mode == "search" and researcher:\n'
            '        # ── Live web research ──────────────────────────────────────\n'
            '        with console.status("[bold green]Searching the web...[/bold green]", spinner="dots"):\n'
            '            response = researcher.search(user_input)\n'
            '    elif decision.analytical or decision.depth == "deep":'
        )
        print("  ✅ PATCHED  [main.py: Wired search routing branch]")
        changed = True

    # 9d. Instantiate researcher + autonomist in main()
    if "researcher = Researcher(brain)" not in content:
        content = content.replace(
            "    dialog_manager, council, diagnostics = DialogManager(), Council(), SelfDiagnostics()",
            "    dialog_manager, council, diagnostics = DialogManager(), Council(), SelfDiagnostics()\n"
            "    researcher = Researcher(brain)\n"
            "    autonomist = Autonomist(brain)"
        )
        print("  ✅ PATCHED  [main.py: Instantiated Researcher + Autonomist in main()]")
        changed = True

    # 9e. Update all three call sites to pass researcher + autonomist
    for old_call, label in [
        (
            "handle_user_input(user_input, voice, autocorrect, executor, copilot, brain, self_model, dialog_manager, council, diagnostics, logger)",
            "text-mode call site"
        ),
        (
            'handle_user_input(cleaned or "Yes?", voice, autocorrect, executor, copilot, brain, self_model, dialog_manager, council, diagnostics, logger)',
            "wake-word call site"
        ),
        (
            "handle_user_input(follow_up, voice, autocorrect, executor, copilot, brain, self_model, dialog_manager, council, diagnostics, logger)",
            "momentum-loop call site"
        ),
    ]:
        new_call = old_call.replace(", logger)", ", logger, researcher, autonomist)")
        if old_call in content:
            content = content.replace(old_call, new_call)
            print(f"  ✅ PATCHED  [main.py: Updated {label}]")
            changed = True

    # 9f. Fix shutdown sequence: learn → finalize (not finalize → learn)
    old_shutdown = (
        '    # 4. Shutdown & Finalization\n'
        '    console.print("\\n[bold cyan]IRIS:[/bold cyan] Terminating. Sanitizing memory...")\n'
        '    logger.finalize() # New: Close session log safely\n'
        '    \n'
        '    try:\n'
        '        from tools.cleaner import sanitize_memory\n'
        '        sanitize_memory(Config.MEMORY_FILE)\n'
        '    except Exception: pass\n'
        '    \n'
        '    sys.exit()'
    )
    new_shutdown = (
        '    # 4. Shutdown & Finalization\n'
        '    console.print("\\n[bold cyan]IRIS:[/bold cyan] Running autonomous learning cycle...")\n'
        '    try:\n'
        '        if autonomist:\n'
        '            autonomist.learn_from_session(logger.filename)  # learn BEFORE finalize\n'
        '    except Exception as e:\n'
        '        console.print(f"[yellow][!] Learning skipped: {e}[/yellow]")\n'
        '\n'
        '    console.print("[bold cyan]IRIS:[/bold cyan] Terminating. Sanitizing memory...")\n'
        '    logger.finalize()\n'
        '\n'
        '    try:\n'
        '        from tools.cleaner import sanitize_memory\n'
        '        sanitize_memory(Config.MEMORY_FILE)\n'
        '    except Exception: pass\n'
        '\n'
        '    sys.exit()'
    )
    if old_shutdown in content:
        content = content.replace(old_shutdown, new_shutdown)
        print("  ✅ PATCHED  [main.py: Fixed shutdown — learn_from_session before logger.finalize()]")
        changed = True
    elif "learn_from_session" not in content:
        print("  ❌ MANUAL   [main.py: Shutdown block not matched — apply Fix 9f manually]")

    if changed:
        path.write_text(content, encoding="utf-8")

# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n🔧  IRIS v5.0 — Definitive Stabilization (Final)\n")
    fix_executor_expandvars()
    fix_executor_log_path()
    fix_security_expandvars()
    fix_config()
    fix_session_logger()
    fix_autonomist()
    fix_researcher()
    fix_logic_engine()
    fix_main()
    print("\n" + "─"*60)
    print("VERIFICATION SMOKE TESTS:")
    print("  1. run: %comspec% /c echo test  → IRIS must print BLOCKED")
    print("  2. Search for 2026 NVIDIA drivers → synthesized text response")
    print("  3. shutdown → 'Running autonomous learning cycle...' before exit")
    print("  4. Launch from C:\\ → all files still land in D:\\IRIS\\")
    print("─"*60)