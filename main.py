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
import difflib
import random
import re
import time
import sys
import threading
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
_WAKE_ACKS_PUBLIC = ["Yes. What's the task?", "Go on.", "What do you need?"]
_WAKE_ACKS_ADMIN  = ["Proceed.", "State the task.", "What's the objective?"]

_FAREWELLS_PUBLIC = ["Session closed.", "Goodbye.", "Standing down."]
_FAREWELLS_ADMIN  = ["Aletheia signing off.", "Admin session terminated.", "Root session closed."]
_SENTENCE_RE = re.compile(r"^\s*(.+?[.!?])(?=(?:\s|$))(.*)$", re.DOTALL)
_INTERRUPT_PREFIX_RE = re.compile(
    r"^\s*(?:(?:iris|aletheia)\s+)?(?:wait|hold on|stop|quiet)\b[\s,.:;-]*(.*)$",
    re.IGNORECASE,
)

def _normalize_command_text(text: str) -> str:
    normalized = re.sub(r"[^a-z0-9\s]", " ", (text or "").lower())
    return re.sub(r"\s+", " ", normalized).strip()

def _strip_wake_words(text: str) -> str:
    cleaned = text or ""
    for wake_word in Config.WAKE_WORDS:
        cleaned = re.sub(rf"\b{re.escape(wake_word)}\b", "", cleaned, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", cleaned).strip()

def _is_interrupt_phrase(text: str) -> bool:
    normalized = _normalize_command_text(text)
    return normalized in {"stop", "wait", "hold on", "hold", "quiet"}

def _has_aletheia_token(text: str) -> bool:
    normalized = _normalize_command_text(text)
    tokens = [token for token in normalized.split() if len(token) >= 5]
    if "aletheia" in tokens:
        return True
    return bool(difflib.get_close_matches("aletheia", tokens, n=1, cutoff=0.55))

def _matches_program_exit(text: str, voice_mode: bool = False) -> bool:
    normalized = _normalize_command_text(text)
    exact = {
        "terminate",
        "shutdown",
        "exit system",
        "terminate system",
        "shutdown system",
        "quit program",
        "exit program",
        "iris exit",
        "exit iris",
        "iris quit",
        "quit iris",
        "iris shutdown",
        "shutdown iris",
        "iris terminate",
        "terminate iris",
    }
    if normalized in exact:
        return True
    if voice_mode and normalized in {"dominate", "terminated", "termination", "germinate"}:
        return True
    return False

def _active_wake_words(self_model: SelfModel) -> list[str]:
    return ["aletheia"] if getattr(self_model, "admin_unlocked", False) else list(Config.WAKE_WORDS)

def _matches_active_wake_word(text: str, self_model: SelfModel) -> bool:
    normalized = _normalize_command_text(text)
    tokens = normalized.split()
    if getattr(self_model, "admin_unlocked", False):
        return _has_aletheia_token(text)
    if any(w.lower() in tokens for w in Config.WAKE_WORDS):
        return True
    return any(difflib.get_close_matches("iris", [token], n=1, cutoff=0.75) for token in tokens if len(token) >= 3)

def _strip_active_wake_word(text: str, self_model: SelfModel) -> str:
    if not text:
        return ""
    if getattr(self_model, "admin_unlocked", False):
        tokens = re.findall(r"[A-Za-z0-9']+", text)
        filtered = []
        removed = False
        for token in tokens:
            lowered = token.lower()
            if not removed and (lowered == "aletheia" or difflib.get_close_matches("aletheia", [lowered], n=1, cutoff=0.55)):
                removed = True
                continue
            filtered.append(token)
        return " ".join(filtered).strip()

    tokens = re.findall(r"[A-Za-z0-9']+", text)
    filtered = []
    removed = False
    for token in tokens:
        lowered = token.lower()
        if not removed and (lowered in {w.lower() for w in Config.WAKE_WORDS} or difflib.get_close_matches("iris", [lowered], n=1, cutoff=0.75)):
            removed = True
            continue
        filtered.append(token)
    return " ".join(filtered).strip()

def _extract_interrupt_followup(text: str) -> str:
    match = _INTERRUPT_PREFIX_RE.match(text or "")
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(1)).strip()

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

def _extract_complete_sentences(buffer: str):
    sentences = []
    remaining = buffer
    while True:
        match = _SENTENCE_RE.match(remaining)
        if not match:
            break
        sentence = match.group(1).strip()
        remaining = match.group(2).lstrip()
        if sentence:
            sentences.append(sentence)
    return sentences, remaining

def _drain_speech_chunks(pending_chunks: list[str], voice: Voice, speech_started: bool) -> bool:
    if not pending_chunks:
        return speech_started
    chunk = " ".join(part.strip() for part in pending_chunks if part and part.strip()).strip()
    pending_chunks.clear()
    if chunk:
        voice.speak(chunk, interrupt=not speech_started)
        voice.record_spoken(chunk)
        return True
    return speech_started

def _stream_reasoning_response(user_input, voice, brain, self_model, decision, council_packet, logger):
    persona_label = "Aletheia" if self_model.admin_unlocked else "IRIS"
    label_color = "red" if self_model.admin_unlocked else "cyan"
    response_parts = []
    speech_buffer = ""
    speech_started = False
    pending_speech_chunks = []

    console.print(f"\n[bold {label_color}]{persona_label}:[/bold {label_color}] ", end="")
    for chunk in brain.stream_think(
        user_input,
        council_packet=council_packet,
        admin_unlocked=self_model.admin_unlocked,
        voice_mode=True,
    ):
        if not chunk:
            continue
        response_parts.append(chunk)
        console.print(chunk, end="", markup=False, highlight=False)
        speech_buffer += chunk
        sentences, speech_buffer = _extract_complete_sentences(speech_buffer)
        for sentence in sentences:
            pending_speech_chunks.append(sentence)
            pending_chars = sum(len(part) for part in pending_speech_chunks)
            if not speech_started:
                should_flush = len(pending_speech_chunks) >= 2 or pending_chars >= 240
            else:
                should_flush = len(pending_speech_chunks) >= 3 or pending_chars >= 320
            if should_flush:
                speech_started = _drain_speech_chunks(pending_speech_chunks, voice, speech_started)

    final_response = "".join(response_parts).strip()
    if pending_speech_chunks:
        speech_started = _drain_speech_chunks(pending_speech_chunks, voice, speech_started)
    if speech_buffer.strip():
        voice.speak(speech_buffer.strip(), interrupt=not speech_started)
        voice.record_spoken(speech_buffer.strip())
        speech_started = True

    console.print("\n")
    self_model.note_response(final_response, source=decision.mode)
    logger.log_turn(persona_label, final_response)
    return final_response

def _run_voice_followup_window(
    voice,
    autocorrect,
    executor,
    copilot,
    brain,
    self_model,
    dialog_manager,
    council,
    diagnostics,
    logger,
    researcher,
    autonomist,
    evolution,
    initial_input: str | None = None,
    max_turns: int = 4,
    missed_limit: int = 3,
) -> bool:
    current_input = (initial_input or "").strip() or None
    missed_follow_ups = 0
    turns_used = 0

    while turns_used < max_turns:
        if current_input is None:
            if voice.is_speaking():
                heard_text = voice.listen_for_interrupt()
            else:
                heard_text = voice.listen_for_command(timeout=6.0, phrase_time_limit=6.0)

            if not heard_text or voice.should_ignore_transcript(heard_text):
                missed_follow_ups += 1
                if missed_follow_ups >= missed_limit:
                    break
                continue

            if voice.is_speaking():
                voice.stop_speaking()

            cleaned = _strip_active_wake_word(heard_text, self_model)
            if _is_interrupt_phrase(cleaned) or not cleaned:
                post_interrupt = _extract_interrupt_followup(heard_text)
                current_input = post_interrupt.strip() or None
                missed_follow_ups = 0
                if current_input is None:
                    continue
            else:
                current_input = cleaned.strip() or None
                if current_input is None:
                    missed_follow_ups += 1
                    if missed_follow_ups >= missed_limit:
                        break
                    continue

        normalized = _normalize_command_text(current_input)
        if normalized in {"thanks", "thank you", "bye", "goodbye"}:
            break
        if _is_interrupt_phrase(normalized):
            current_input = None
            continue

        _, should_exit = handle_user_input(
            current_input,
            voice,
            autocorrect,
            executor,
            copilot,
            brain,
            self_model,
            dialog_manager,
            council,
            diagnostics,
            logger,
            researcher,
            autonomist,
            evolution,
            voice_mode=True,
        )
        turns_used += 1
        current_input = None
        missed_follow_ups = 0
        if should_exit:
            return True

    return False

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

def handle_user_input(user_input, voice, autocorrect, executor, copilot, brain, self_model, dialog_manager, council, diagnostics, logger, researcher=None, autonomist=None, evolution=None, voice_mode=False):
    user_input = (user_input or "").strip()
    if not user_input: return None, False

    logger.log_turn("User", user_input)
    lowered = user_input.lower()
    normalized = _normalize_command_text(user_input)
    persona_label = "Aletheia" if self_model.admin_unlocked else "IRIS"

    if _matches_program_exit(user_input, voice_mode=voice_mode) or normalized in {"terminate", "shutdown", "exit system"}:
        return "EXIT", True

    if lowered.strip() == "authorize protocol aletheia":
        if not self_model.admin_unlocked:
            self_model.admin_unlocked = True
            console.bell()
            resp = _generate_greeting(admin_unlocked=True)
            console.print("\n[bold red][🔒 ROOT ACCESS GRANTED][/bold red]")
            voice.speak(resp)
            voice.record_spoken(resp)
        return "UNLOCKED", False
    elif lowered.strip() in ["lock protocol", "revert to iris"]:
        self_model.admin_unlocked = False
        resp = _generate_greeting(admin_unlocked=False)
        console.print("\n[bold green][🔒 ROOT ACCESS REVOKED][/bold green]")
        voice.speak(resp)
        voice.record_spoken(resp)
        return "LOCKED", False

    corrected, _ = autocorrect.correct_input(user_input)
    user_input = corrected

    decision = dialog_manager.analyze(user_input, executor, copilot, diagnostics, self_model)
    self_model.observe_user_input(user_input, decision)
    streamed_response = False

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
            packet = council.deliberate(user_input, decision, self_model)
            self_model.apply_council(packet.roles)
            if voice_mode:
                response = _stream_reasoning_response(user_input, voice, brain, self_model, decision, packet, logger)
                streamed_response = True
            else:
                with console.status("[cyan]Thinking...[/cyan]", spinner="dots"):
                    response = brain.think(
                        user_input,
                        council_packet=packet,
                        admin_unlocked=self_model.admin_unlocked,
                        voice_mode=voice_mode,
                    )

    if not streamed_response:
        self_model.note_response(response, source=decision.mode)
        label_color = "red" if self_model.admin_unlocked else "cyan"
        logger.log_turn(persona_label, response)
        # Print immediately so text appears before audio starts
        console.print(f"\n[bold {label_color}]{persona_label}:[/bold {label_color}] {response}\n")
        voice.speak(response)
        voice.record_spoken(response)

    return response, False


def _wait_for_engine(brain: Brain, timeout: int = 30) -> bool:
    waited = 0
    while brain.llm is None and waited < timeout:
        time.sleep(0.5)
        waited += 0.5
    return brain.llm is not None


def _wait_for_voice_idle(voice, timeout: float = 2.5) -> None:
    """Wait for any in-progress speech to finish, with a hard timeout."""
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if not voice.is_speaking():
                break
        except Exception:
            break
        time.sleep(0.05)


def _run_session_learning(autonomist, log_path: str, learn_error: list) -> None:
    """Run session learning on a daemon thread and capture errors."""
    try:
        autonomist.learn_from_session(log_path)
    except Exception as e:
        learn_error.append(e)


def _finalize_session(autonomist, logger) -> None:
    """Finalize the session and bound shutdown learning."""
    try:
        logger.finalize()
    except Exception as e:
        console.print(f"[dim yellow]Cleanup error: {e}[/dim yellow]")
        return

    learn_error = []
    learning_thread = threading.Thread(
        target=lambda: _run_session_learning(autonomist, logger.filename, learn_error),
        daemon=True,
        name="iris-shutdown-learning",
    )
    learning_thread.start()
    learning_thread.join(timeout=1.5)

    if learning_thread.is_alive():
        console.print("[dim yellow]Skipping slow shutdown learning to avoid exit stall.[/dim yellow]")
    elif learn_error:
        console.print(f"[dim yellow]Cleanup error: {learn_error[0]}[/dim yellow]")


def _force_exit(code: int = 0) -> None:
    """Hard exit after cleanup — ensures the process always terminates."""
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    os._exit(code)


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
    voice.record_spoken(greeting)

    try:
        while True:
            try:
                v_p, _ = get_vram_status()
                is_safe, temp = diagnostics.check_thermal_integrity()
                if v_p > Config.VRAM_CRITICAL_PERCENT:
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

                    _, should_exit = handle_user_input(user_input, voice, autocorrect, executor, copilot, brain, self_model, dialog_manager, council, diagnostics, logger, researcher, autonomist, evolution, voice_mode=False)
                    if should_exit: break
                    continue

                during_speech = voice.is_speaking()
                active_wake_words = _active_wake_words(self_model)
                if during_speech:
                    heard_text = voice.listen_for_interrupt()
                else:
                    heard_text = voice.listen_for_wake()
                if not heard_text: continue
                if voice.should_ignore_transcript(heard_text):
                    continue

                if voice.is_speaking():
                    voice.stop_speaking()

                lowered_heard = heard_text.lower()
                is_wake = _matches_active_wake_word(heard_text, self_model)
                interrupt_only = during_speech and any(token in lowered_heard for token in ["stop", "wait", "hold on", "quiet"]) and not is_wake

                if during_speech:
                    cleaned = heard_text
                    if is_wake:
                        cleaned = _strip_active_wake_word(cleaned, self_model)

                    if interrupt_only or not cleaned.strip():
                        post_interrupt = _extract_interrupt_followup(cleaned)
                        should_exit = _run_voice_followup_window(
                            voice,
                            autocorrect,
                            executor,
                            copilot,
                            brain,
                            self_model,
                            dialog_manager,
                            council,
                            diagnostics,
                            logger,
                            researcher,
                            autonomist,
                            evolution,
                            initial_input=post_interrupt or None,
                            max_turns=4,
                            missed_limit=3,
                        )
                    else:
                        should_exit = _run_voice_followup_window(
                            voice,
                            autocorrect,
                            executor,
                            copilot,
                            brain,
                            self_model,
                            dialog_manager,
                            council,
                            diagnostics,
                            logger,
                            researcher,
                            autonomist,
                            evolution,
                            initial_input=cleaned,
                            max_turns=4,
                            missed_limit=3,
                        )
                    if should_exit:
                        break
                    continue

                if is_wake:
                    cleaned = _strip_active_wake_word(heard_text, self_model)

                    if not cleaned:
                        label_color = "red" if self_model.admin_unlocked else "cyan"
                        persona_label = "Aletheia" if self_model.admin_unlocked else "IRIS"
                        ack_pool = _WAKE_ACKS_ADMIN if self_model.admin_unlocked else _WAKE_ACKS_PUBLIC
                        wake_ack = random.choice(ack_pool)
                        console.print(f"\n[bold {label_color}]{persona_label}:[/bold {label_color}] {wake_ack}\n")
                        voice.speak(wake_ack)
                        voice.record_spoken(wake_ack)
                    should_exit = _run_voice_followup_window(
                        voice,
                        autocorrect,
                        executor,
                        copilot,
                        brain,
                        self_model,
                        dialog_manager,
                        council,
                        diagnostics,
                        logger,
                        researcher,
                        autonomist,
                        evolution,
                        initial_input=cleaned or None,
                        max_turns=4,
                        missed_limit=3,
                    )
                    if should_exit:
                        break

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
        voice.record_spoken(farewell)
        _wait_for_voice_idle(voice)

        console.print("\n[bold cyan]IRIS:[/bold cyan] Terminating. Finalizing memory...")

        _finalize_session(autonomist, logger)
        _force_exit(0)


if __name__ == "__main__":
    main()
