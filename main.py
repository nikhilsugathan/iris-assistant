"""
IRIS Main Entry Point v5.1 (C++ Engine + Survival Layer)
=========================================================
- Hardened for RTX 5050 (8GB VRAM)
- Integrated Session Logging & VRAM Safety Monitor
- Production Gates: Wake (400) / Command (550)
- v5.1: C++ LLM Engine (llama-cpp-python) + Piper TTS streaming audio
"""

from __future__ import annotations
import argparse
import time
import sys
import os
import traceback
from datetime import datetime

from rich.console import Console
from rich.panel import Panel

from config import Config
from core.autocorrect import AutoCorrector
from core.brain import Brain
from core.council import Council
from core.copilot import CoPilot
from core.dialog_manager import DialogManager
from core.diagnostics import SelfDiagnostics, BootDiagnostics, get_vram_status
from core.executor import ActionExecutor
from core.logic_engine import LogicalEngine
from core.memory import Memory
from core.self_model import SelfModel
from core.voice import Voice
from core.session_logger import SessionLogger
from core.evolution import EvolutionEngine
from tools.researcher import Researcher       # FIX: was missing
from core.autonomist import Autonomist         # FIX: was missing

console = Console()

CRASH_LOG = os.path.join(os.path.dirname(__file__), "logs", "crash.log")

BANNER = f"""
  ██████████████████████ ████████████████
  ████▄████▄████████▄████▄████████▄████▄
  ████▄████████████▄████▄████████▄███████
  ████▄████▄████▄████████▄████████████▄████
  ████▄████▄████████████▄████▄████████████
  ▀▀▀▀▀▀▀▀ ▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀
  {Config.SYSTEM_MOTTO}
"""

def show_status(voice: Voice, self_model: SelfModel) -> None:
    """Displays hardware and logic gates for the Aletheia spec."""
    v_p, _ = get_vram_status()
    mic_status = "Ready" if getattr(voice, "mic_ready", False) else "Unavailable"
    
    console.print(
        Panel(
            f"[bold green]Online[/bold green] | [bold red]{'PRIVACY' if getattr(voice, 'privacy_mode', False) else 'NORMAL'}[/bold red] | [bold yellow]VRAM: {v_p:.1f}%[/bold yellow]\n"
            f"[white]Codename       :[/white] [cyan]{Config.INNER_CODENAME}[/cyan]\n"
            f"[white]Primary Brain  :[/white] [cyan]{Config.PRIMARY_BRAIN}[/cyan]\n"
            f"[white]Microphone     :[/white] [cyan]{mic_status} (W: {Config.WAKE_RMS_THRESHOLD} / C: {Config.COMMAND_RMS_THRESHOLD})[/cyan]\n"
            f"[white]Self Model     :[/white] [cyan]{self_model.summary()}[/cyan]\n",
            title="[bold cyan]IRIS v5.0[/bold cyan]",
            border_style="cyan",
        )
    )

def handle_user_input(user_input, voice, autocorrect, executor, copilot, brain, self_model, dialog_manager, council, diagnostics, logger, researcher=None, autonomist=None, evolution=None):
    """Processes input and records turns to the session log."""
    user_input = (user_input or "").strip()
    if not user_input: return None, False

    # Log user turn
    logger.log_turn("User", user_input)

    # ── Initialise the reasoning engine for this turn ──────────────────────
    logic_engine = LogicalEngine(brain)
    
    lowered = user_input.lower()
    if any(cmd in lowered for cmd in ["terminate", "shutdown", "exit system"]):
        return "EXIT", True

    if any(cmd in lowered for cmd in ["privacy mode", "stop eavesdropping"]):
        voice.toggle_privacy()
        return "Privacy Toggled", False

    # ── Evolution Engine: approve/reject pending tool ──────────────
    if evolution:
        if "approve tool" in lowered:
            response = evolution.approve_tool()
            console.print(f"\n[bold cyan]IRIS:[/bold cyan] {response}\n")
            logger.log_turn("IRIS", response)
            voice.speak(response)
            return response, False
        if "reject tool" in lowered:
            response = evolution.reject_tool()
            console.print(f"\n[bold cyan]IRIS:[/bold cyan] {response}\n")
            logger.log_turn("IRIS", response)
            voice.speak(response)
            return response, False

    corrected, _ = autocorrect.correct_input(user_input)
    user_input = corrected

    decision = dialog_manager.analyze(user_input, executor, copilot, diagnostics, self_model)
    
    # --- ROUTING LOGIC ---
    if decision.mode == "diagnostics":
        response = diagnostics.run(user_input, brain, voice, executor, copilot, brain.memory, self_model)
    elif decision.mode == "action":
        # Spinner for when she is figuring out HOW to do the task
        with console.status("[bold yellow]Formulating action plan...[/bold yellow]", spinner="dots"):
            response = executor.plan_action(user_input)
        # Route unhandled intents to Evolution Engine
        if evolution and response and "couldn't figure out how to do that" in response.lower():
            response = evolution.triage_unknown_intent(user_input)
    elif decision.mode == "search" and researcher:
        # FIX: was missing entirely — web search was completely dead
        with console.status("[bold green]Searching the web...[/bold green]", spinner="dots"):
            response = researcher.search(user_input)
    elif decision.mode == "action_pending":
        # Spinner for when you say "Yes" and she actually executes the command
        with console.status("[bold yellow]Executing system action... Please wait.[/bold yellow]", spinner="dots"):
            if getattr(executor, "waiting_for_permission", lambda: False)():
                response = executor.handle_permission_response(user_input)
            elif getattr(executor, "waiting_for_followup", lambda: False)():
                response = executor.handle_followup_response(user_input)
            elif getattr(executor, "waiting_for_clarification", lambda: False)():
                response = executor.handle_clarification_response(user_input)
            elif getattr(executor, "waiting_for_plan_choice", lambda: False)():
                response = executor.handle_plan_choice(user_input)
            else:
                response = "Action state cleared."
    elif decision.analytical or decision.depth == "deep":
        # ── Deep reasoning path — route through Chain-of-Thought engine ──
        context = brain.memory.get_context() if hasattr(brain, "memory") and hasattr(brain.memory, "get_context") else ""
        with console.status("[bold magenta]Reasoning...[/bold magenta]", spinner="dots"):
            response = logic_engine.reason(user_input, context=context)
    else:
        packet = council.deliberate(user_input, decision, self_model)
        with console.status("[cyan]Thinking...[/cyan]:"): 
            response = brain.think(user_input, council_packet=packet)

    # Update self-model and log IRIS turn
    self_model.note_response(response, source=decision.mode)
    console.print(f"\n[bold cyan]IRIS:[/bold cyan] {response}\n")
    logger.log_turn("IRIS", response)
    
    voice.speak(response)
    return response, False

def main() -> None:
    # 1. Pre-flight & Config Validation
    Config.validate()
    try:
        BootDiagnostics().run_preflight()
    except Exception: pass

    parser = argparse.ArgumentParser()
    parser.add_argument("--text", action="store_true")
    args = parser.parse_args()

    # 2. Module Initialization
    memory = Memory(Config.MEMORY_FILE)
    logger = SessionLogger()
    brain, voice = Brain(memory), Voice(text_mode=args.text)
    copilot, executor = CoPilot(brain, voice, memory), ActionExecutor(voice, brain)
    autocorrect, self_model = AutoCorrector(brain), SelfModel()
    dialog_manager, council, diagnostics = DialogManager(), Council(), SelfDiagnostics()
    researcher  = Researcher(brain)   # FIX: was never instantiated
    autonomist  = Autonomist(brain)   # FIX: was never instantiated
    evolution   = EvolutionEngine(brain, researcher)

    console.print(BANNER, style="bold cyan")
    show_status(voice, self_model)

    CONVERSATION_TURNS = 5

    try:
        while True:
            try:
                # 3. VRAM Safety Guard for RTX 5050
                v_p, v_f = get_vram_status()
                if v_p > 96:
                    voice.speak("VRAM is critically over-extended. Close background processes to avoid a crash.")

                if args.text:
                    user_input = input("You: ")
                    _, should_exit = handle_user_input(user_input, voice, autocorrect, executor, copilot, brain, self_model, dialog_manager, council, diagnostics, logger, researcher, autonomist, evolution)
                    if should_exit: break
                    continue

                heard_text = voice.listen_for_wake()
                if not heard_text: continue

                # --- BARGE-IN / INTERRUPT LOGIC ---
                is_wake = any(w.lower() in heard_text.lower() for w in Config.WAKE_WORDS)
                if is_wake:
                    if voice.is_speaking():
                        voice.stop_speaking()
                        console.print("[bold yellow]  (Interrupt detected! Stopping speech...)[/bold yellow]")
                    
                    cleaned = heard_text
                    for w in Config.WAKE_WORDS: 
                        cleaned = cleaned.lower().replace(w.lower(), "").strip()
                    
                    _, should_exit = handle_user_input(cleaned or "Yes?", voice, autocorrect, executor, copilot, brain, self_model, dialog_manager, council, diagnostics, logger, researcher, autonomist, evolution)
                    if should_exit: break

                    # MOMENTUM LOOP
                    for _ in range(CONVERSATION_TURNS):
                        follow_up = voice.listen_for_command()
                        if not follow_up or any(w in follow_up.lower() for w in ["stop", "thanks", "bye"]):
                            break
                        _, should_exit = handle_user_input(follow_up, voice, autocorrect, executor, copilot, brain, self_model, dialog_manager, council, diagnostics, logger, researcher, autonomist, evolution)
                        if should_exit: break
                    
                    if should_exit: break

            except KeyboardInterrupt:
                break
            except Exception as e:
                console.print(f"[red]System Error:[/red] {e}")
                time.sleep(1)

    except KeyboardInterrupt:
        console.print("[bold yellow]Session ended by user.[/bold yellow]")
    except Exception as e:
        tb = traceback.format_exc()
        os.makedirs(os.path.join(os.path.dirname(__file__), "logs"), exist_ok=True)
        with open(CRASH_LOG, "a", encoding="utf-8") as f:
            f.write(f"\n{'='*60}\nCRASH at {datetime.now().isoformat()}\n{tb}\n")
        console.print("[bold red]IRIS crashed. Traceback written to logs/crash.log[/bold red]")
        console.print(f"[red]{tb}[/red]")
        raise
    finally:
        console.print("[dim]Session closed.[/dim]")

    # 4. Shutdown & Finalization — FIX: learn BEFORE finalize so file is still open
    console.print("\n[bold cyan]IRIS:[/bold cyan] Running autonomous learning cycle...")
    try:
        autonomist.learn_from_session(logger.filename)
    except Exception as e:
        console.print(f"[yellow][!] Learning skipped: {e}[/yellow]")

    console.print("[bold cyan]IRIS:[/bold cyan] Terminating. Sanitizing memory...")
    logger.finalize()
    
    try:
        from tools.cleaner import sanitize_memory
        sanitize_memory(Config.MEMORY_FILE)
    except Exception: pass
    
    sys.exit()

if __name__ == "__main__":
    main()