"""
IRIS Main Entry Point v4.7
==========================
- Hardened Voice Standby & Privacy Mode
- Continuous Conversation Momentum
- Auto-Sanitizing Memory Shutdown
- Barge-in Support (Interrupt while speaking)
"""

from __future__ import annotations

import argparse
import time
import sys

from rich.console import Console
from rich.panel import Panel

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

try:
    from core.runtime_log import log_runtime
except ImportError:
    def log_runtime(t, m, l="INFO"): pass

console = Console()

BANNER = f"""
  ██╗██████╗ ██╗███████╗
  ██║██╔══██╗██║██╔════╝
  ██║██████╔╝██║███████╗
  ██║██╔══██╗██║╚════██║
  ██║██║  ██║██║███████║
  ╚═╝╚═╝  ╚═╝╚═╝╚══════╝
  {Config.SYSTEM_MOTTO}
"""

def show_status(memory: Memory, text_mode: bool, voice: Voice, self_model: SelfModel) -> None:
    mic_status = "Ready" if getattr(voice, "mic_ready", False) else "Unavailable"
    if getattr(voice, "engine", None):
        base_threshold = getattr(Config, "WAKE_RMS_THRESHOLD", 500)
        threshold = base_threshold + 2500 if getattr(voice, "privacy_mode", False) else base_threshold
    else:
        threshold = "N/A"
    
    console.print(
        Panel(
            f"[bold green]Online[/bold green] | [bold red]{'PRIVACY' if getattr(voice, 'privacy_mode', False) else 'NORMAL'}[/bold red]\n"
            f"[white]Primary Brain  :[/white] [cyan]{Config.PRIMARY_BRAIN}[/cyan]\n"
            f"[white]Input Mode     :[/white] [cyan]{'Keyboard' if text_mode else 'Voice Standby'}[/cyan]\n"
            f"[white]Microphone     :[/white] [cyan]{mic_status} (RMS Gate: {threshold})[/cyan]\n"
            f"[white]Self Model     :[/white] [cyan]{self_model.summary()}[/cyan]\n",
            title=f"[bold cyan]{Config.SYSTEM_NAME}[/bold cyan]",
            border_style="cyan",
        )
    )

def update_self_model_logic(self_model: SelfModel, response: str, source: str) -> None:
    lowered = (response or "").lower()
    if any(token in lowered for token in ["failed", "error", "couldn't"]):
        self_model.note_failure(response)
        return
    self_model.note_response(response, source=source)

def handle_user_input(user_input, voice, autocorrect, executor, copilot, brain, self_model, dialog_manager, council, diagnostics):
    user_input = (user_input or "").strip()
    if not user_input: return None, False

    lowered = user_input.lower()
    if any(cmd in lowered for cmd in ["terminate", "shutdown", "exit system"]):
        return "EXIT", True

    if any(cmd in lowered for cmd in ["privacy mode", "stop eavesdropping"]):
        voice.toggle_privacy()
        return "Privacy Toggled", False

    corrected, _ = autocorrect.correct_input(user_input)
    user_input = corrected

    decision = dialog_manager.analyze(user_input, executor, copilot, diagnostics, self_model)
    
    if decision.mode == "diagnostics":
        response = diagnostics.run(user_input, brain, voice, executor, copilot, brain.memory, self_model)
    elif decision.mode == "action":
        response = executor.plan_action(user_input)
    else:
        packet = council.deliberate(user_input, decision, self_model)
        with console.status("[cyan]Thinking...[/cyan]"):
            response = brain.think(user_input, council_packet=packet)

    update_self_model_logic(self_model, response, decision.mode)
    console.print(f"\n[bold cyan]IRIS:[/bold cyan] {response}\n")
    voice.speak(response)
    return response, False

def main() -> None:
    try:
        BootDiagnostics().run_preflight()
    except Exception: pass

    parser = argparse.ArgumentParser()
    parser.add_argument("--text", action="store_true")
    args = parser.parse_args()

    memory = Memory(Config.MEMORY_FILE)
    brain, voice = Brain(memory), Voice(text_mode=args.text)
    copilot, executor = CoPilot(brain, voice, memory), ActionExecutor(voice, brain)
    autocorrect, self_model = AutoCorrector(brain), SelfModel()
    dialog_manager, council, diagnostics = DialogManager(), Council(), SelfDiagnostics()

    console.print(BANNER, style="bold cyan")
    show_status(memory, args.text, voice, self_model)

    CONVERSATION_TURNS = 5 

    while True:
        try:
            if args.text:
                user_input = input("You: ")
                _, should_exit = handle_user_input(user_input, voice, autocorrect, executor, copilot, brain, self_model, dialog_manager, council, diagnostics)
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
                
                console.print(f"[dim]  (Wake STT heard: '{heard_text}')[/dim]")
                
                cleaned = heard_text
                for w in Config.WAKE_WORDS: 
                    cleaned = cleaned.lower().replace(w.lower(), "").strip()
                
                _, should_exit = handle_user_input(cleaned or "Yes?", voice, autocorrect, executor, copilot, brain, self_model, dialog_manager, council, diagnostics)
                if should_exit: break

                # MOMENTUM LOOP
                for _ in range(CONVERSATION_TURNS):
                    console.print("[dim]  (listening...)[/dim]")
                    follow_up = voice.listen_for_command()
                    if not follow_up or any(w in follow_up.lower() for w in ["stop", "thanks", "bye"]):
                        break
                    _, should_exit = handle_user_input(follow_up, voice, autocorrect, executor, copilot, brain, self_model, dialog_manager, council, diagnostics)
                    if should_exit: break
                
                if should_exit: break

        except KeyboardInterrupt: break
        except Exception as e:
            console.print(f"[red]System Error:[/red] {e}")
            time.sleep(1)

    console.print("\n[bold cyan]IRIS:[/bold cyan] Terminating. Sanitizing memory...")
    try:
        from tools.cleaner import sanitize_memory
        sanitize_memory(Config.MEMORY_FILE)
        console.print("[bold green]✓ Cleanup complete. Goodbye.[/bold green]")
    except Exception as e:
        console.print(f"[bold yellow]Warning:[/bold yellow] Memory cleanup skipped: {e}")
    
    sys.exit()

if __name__ == "__main__":
    main()