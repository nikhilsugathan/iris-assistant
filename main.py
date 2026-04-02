"""
IRIS Main Entry Point v5.1.2 (Ironclad Edition)
=========================================================
- Hardened for RTX 5050 (8GB VRAM)
- Pre-flight Hardware & C++ Engine Initialization
- Integrated Thermal Sentry & VRAM Safety Guard
- Suppressed pygame banner, spoken boot greeting, engine-ready gate
"""

from __future__ import annotations
import os
# Suppress pygame welcome message before any audio libraries load
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"

import argparse
import random
import time
import sys
import psutil
from datetime import datetime

from rich.console import Console
from rich.table import Table
from rich.markup import escape

from config import Config
from core.autocorrect import AutoCorrector
from core.brain import Brain
from core.council import Council
from core.copilot import CoPilot
from core.dialog_manager import DialogManager
from core.diagnostics import SelfDiagnostics, BootDiagnostics, get_vram_status
from core.executor import ActionExecutor
from core.memory import Memory
from core.self_model import SelfModel
from core.voice import Voice
from core.session_logger import SessionLogger
from core.evolution import EvolutionEngine
from tools.researcher import Researcher
from core.autonomist import Autonomist

console = Console()

# ── LOGGING PERSISTENCE ─────────────────────────────────────────────────────
LOGS_DIR = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(LOGS_DIR, exist_ok=True)
CRASH_LOG = os.path.join(LOGS_DIR, "crash.log")

# ── GREETING / FAREWELL POOLS ───────────────────────────────────────────────
_GREETINGS_PUBLIC = ["Online.", "Ready.", "Standing by.", "I'm here."]
_GREETINGS_ADMIN  = ["Aletheia online.", "Root access active.", "Admin session established."]

_FAREWELLS_PUBLIC = ["Session closed.", "Goodbye.", "Standing down."]
_FAREWELLS_ADMIN  = ["Aletheia signing off.", "Admin session terminated.", "Root session closed."]

_FOLLOW_UP_STOP_WORDS = ("stop", "thanks", "bye", "that's all", "exit")

def _generate_greeting(admin_unlocked: bool = False, brain=None) -> str:
    if brain is not None:
        try:
            hour = datetime.now().hour
            tod = "morning" if hour < 12 else "afternoon" if hour < 17 else "evening"
            mode = "You are Aletheia in root/admin mode." if admin_unlocked else "You are Iris in public mode."
            prompt = (
                f"It is {tod}. {mode} "
                f"Give ONE unique, witty, in-character boot-up line. "
                f"Max 10 words. No quotes. No explanation. Just say it. "
                f"Never say 'Standing by', 'Online', 'Ready', or 'I'm here'."
            )
            brain._active_admin_unlocked = admin_unlocked
            result = brain._call_groq_simple(prompt)
            if result and 3 < len(result) < 120:
                return result.strip().strip('"').strip("'")
        except Exception:
            pass
    pool = _GREETINGS_ADMIN if admin_unlocked else _GREETINGS_PUBLIC
    return random.choice(pool)

def _generate_farewell(self_model: SelfModel) -> str:
    admin = getattr(self_model, "admin_unlocked", False)
    pool = _FAREWELLS_ADMIN if admin else _FAREWELLS_PUBLIC
    return random.choice(pool)

# ── BANNER ──────────────────────────────────────────────────────────────────
_RAW_BANNER = rf"""
  ██╗██████╗ ██╗███████╗
  ██║██╔══██╗██║██╔════╝
  ██║██████╔╝██║███████╗
  ██║██╔══██╗██║╚════██║
  ██║██║  ██║██║███████║
  ╚═╝╚═╝  ╚═╝╚═╝╚══════╝
  {Config.SYSTEM_MOTTO}
"""
BANNER = escape(_RAW_BANNER)

# ────────────────────────────────────────────────────────────────────────────

def show_status(voice: Voice, self_model: SelfModel) -> None:
    try:
        v_p, v_f = get_vram_status()
    except:
        v_p, v_f = 0.0, 0.0

    cpu_p = psutil.cpu_percent()
    mic_status = "Ready" if getattr(voice, "mic_ready", False) else "Unavailable"

    color = "red" if self_model.admin_unlocked else "cyan"
    mode_label = "ROOT / ALETHEIA" if self_model.admin_unlocked else "PUBLIC / IRIS"

    table = Table(title=f"IRIS v5.1 Status - {mode_label}", border_style=color, box=None)
    table.add_column("Component", style="white")
    table.add_column("Status / Data", style=color)

    table.add_row("Identity", Config.INNER_CODENAME if self_model.admin_unlocked else "IRIS")
    table.add_row("VRAM Usage", f"{v_p:.1f}% ({v_f:.0f}MB Free)")
    table.add_row("CPU Load", f"{cpu_p}%")
    table.add_row("Microphone", f"{mic_status} (Gate: {Config.WAKE_RMS_THRESHOLD})")
    table.add_row("Self Model", self_model.summary())

    console.print(table)

def handle_user_input(user_input, voice, autocorrect, executor, copilot, brain, self_model, dialog_manager, council, diagnostics, logger, researcher=None, autonomist=None, evolution=None):
    user_input = (user_input or "").strip()
    if not user_input: return None, False

    logger.log_turn("User", user_input)
    lowered = user_input.lower()
    persona_label = "Aletheia" if self_model.admin_unlocked else "IRIS"

    if any(cmd in lowered for cmd in ["terminate", "shutdown", "exit system"]):
        return "EXIT", True

    if lowered.strip() == "authorize protocol aletheia":
        if not self_model.admin_unlocked:
            self_model.admin_unlocked = True
            console.bell()
            resp = _generate_greeting(admin_unlocked=True)
            console.print("\n[bold red][🔒 ROOT ACCESS GRANTED][/bold red]")
            voice.speak(resp)
        return "UNLOCKED", False
    elif lowered.strip() in ["lock protocol", "revert to iris"]:
        self_model.admin_unlocked = False
        resp = _generate_greeting(admin_unlocked=False)
        console.print("\n[bold green][🔒 ROOT ACCESS REVOKED][/bold green]")
        voice.speak(resp)
        return "LOCKED", False

    corrected, _ = autocorrect.correct_input(user_input)
    user_input = corrected

    decision = dialog_manager.analyze(user_input, executor, copilot, diagnostics, self_model)

    if decision.mode == "diagnostics":
        response = diagnostics.run(user_input, brain, voice, executor, copilot, brain.memory, self_model)
    elif decision.mode == "action":
        with console.status("[bold yellow]Formulating action plan...[/bold yellow]", spinner="dots"):
            response = executor.plan_action(user_input, admin_unlocked=self_model.admin_unlocked)
        if evolution and "couldn't figure out how to do that" in response.lower():
            response = evolution.triage_unknown_intent(user_input)
    elif decision.mode == "search" and researcher:
        with console.status("[bold green]Searching web...[/bold green]", spinner="dots"):
            response = researcher.search(user_input)
    elif decision.mode == "copilot" and copilot:
        response = copilot.start(user_input)
    else:
        is_safe, temp = diagnostics.check_thermal_integrity()
        if not is_safe:
            response = f"Reasoning throttled. GPU Core critical at {temp}°C."
            console.print(f"[bold red]THERMAL OVERRIDE:[/bold red] {response}")
        else:
            if decision.depth == "shallow" and decision.mode in ("chat", "action"):
                packet = None
            else:
                packet = council.deliberate(user_input, decision, self_model)
            with console.status("[cyan]Thinking...[/cyan]", spinner="dots"):
                response = brain.think(user_input, council_packet=packet, admin_unlocked=self_model.admin_unlocked)

    self_model.note_response(response, source=decision.mode)
    label_color = "red" if self_model.admin_unlocked else "cyan"
    logger.log_turn(persona_label, response)
    # Print immediately so text appears before audio starts
    console.print(f"\n[bold {label_color}]{persona_label}:[/bold {label_color}] {response}\n")
    voice.speak(response)

    return response, False


def _wait_for_engine(brain: Brain, timeout: int = 30) -> bool:
    waited = 0
    while brain.llm is None and waited < timeout:
        time.sleep(0.5)
        waited += 0.5
    return brain.llm is not None


def main() -> None:
    Config.validate()

    parser = argparse.ArgumentParser()
    parser.add_argument("--text", action="store_true")
    args = parser.parse_args()

    console.print("[bold yellow]Initializing IRIS systems...[/bold yellow]")
    memory = Memory(Config.MEMORY_FILE)
    logger = SessionLogger()

    try:
        brain = Brain(memory)
    except Exception as e:
        console.print(f"[bold red]FATAL: LLM Engine failed to initialize:[/bold red] {e}")
        sys.exit(1)

    voice = Voice(text_mode=args.text)
    self_model = SelfModel()

    copilot, executor = CoPilot(brain, voice, memory), ActionExecutor(voice, brain)
    autocorrect, dialog_manager = AutoCorrector(brain), DialogManager()
    council, diagnostics = Council(), SelfDiagnostics()
    researcher, autonomist = Researcher(brain), Autonomist(brain)
    evolution = EvolutionEngine(brain, researcher)

    # Wait for C++ engine to finish loading before printing banner
    engine_ready = _wait_for_engine(brain, timeout=30)
    if not engine_ready:
        console.print("[bold yellow]⚠ C++ Engine still loading — falling back to cloud APIs.[/bold yellow]")

    # Clean UI render now that engine noise is done
    console.print(BANNER, style="bold cyan")
    show_status(voice, self_model)

    # Boot greeting — spoken + printed
    greeting = _generate_greeting(self_model.admin_unlocked, brain=brain)
    if not args.text:
        console.print(f"\n[bold green]🎤 Voice Mode — listening for: {', '.join(Config.WAKE_WORDS)}[/bold green]")
    else:
        console.print(f"\n[bold green]⌨️  Text Mode — type your command[/bold green]")
    console.print(f"[bold cyan]IRIS:[/bold cyan] {greeting}")
    voice.speak(greeting)

    try:
        while True:
            try:
                v_p, _ = get_vram_status()
                is_safe, temp = diagnostics.check_thermal_integrity()
                if v_p > 96:
                    console.print("[bold red]VRAM CRITICAL - System throttled.[/bold red]")
                if not is_safe:
                    console.print(f"[bold red]THERMAL WARNING - GPU: {temp}°C.[/bold red]")
            except Exception:
                pass

            try:
                if args.text:
                    console.print("[bold magenta]>[/bold magenta] ", end="")
                    user_input = input()
                    if not user_input.strip(): continue

                    _, should_exit = handle_user_input(user_input, voice, autocorrect, executor, copilot, brain, self_model, dialog_manager, council, diagnostics, logger, researcher, autonomist, evolution)
                    if should_exit: break
                    continue

                while voice.is_speaking():
                    time.sleep(0.1)
                heard_text = voice.listen_for_wake()
                if not heard_text: continue

                is_wake = any(w.lower() in heard_text.lower() for w in Config.WAKE_WORDS)
                if is_wake:
                    if voice.is_speaking(): voice.stop_speaking()
                    cleaned = heard_text
                    for w in Config.WAKE_WORDS:
                        cleaned = cleaned.lower().replace(w.lower(), "").strip()

                    _, should_exit = handle_user_input(
                        cleaned or "Yes?", voice, autocorrect, executor, copilot,
                        brain, self_model, dialog_manager, council, diagnostics,
                        logger, researcher, autonomist, evolution
                    )
                    if should_exit: break

                    silence_count = 0
                    while True:
                        while voice.is_speaking():
                            time.sleep(0.1)
                        follow_up = voice.listen_for_command()
                        if not follow_up:
                            silence_count += 1
                            if silence_count >= 2:
                                break
                            continue
                        silence_count = 0
                        if any(w in follow_up.lower() for w in _FOLLOW_UP_STOP_WORDS):
                            break
                        _, should_exit = handle_user_input(
                            follow_up, voice, autocorrect, executor, copilot,
                            brain, self_model, dialog_manager, council, diagnostics,
                            logger, researcher, autonomist, evolution
                        )
                        if should_exit: break
                    if should_exit: break

            except EOFError:
                break
            except Exception as e:
                console.print(f"[bold red]Error:[/bold red] {e}")

    except KeyboardInterrupt:
        pass
    finally:
        farewell = _generate_farewell(self_model)
        console.print(f"\n[bold yellow]Exiting:[/bold yellow] {farewell}")
        voice.speak(farewell)

        console.print("\n[bold cyan]IRIS:[/bold cyan] Terminating. Finalizing memory...")
        try:
            autonomist.learn_from_session(logger.filename)
            logger.finalize()
        except Exception as e:
            console.print(f"[dim yellow]Cleanup error: {e}[/dim yellow]")
        sys.exit(0)


if __name__ == "__main__":
    main()