"""
IRIS Main Entry Point
=====================
Voice standby mode with tighter wake-word handling.
"""

from __future__ import annotations

import argparse
import difflib
import time

from rich.console import Console
from rich.panel import Panel

from config import Config
from core.autocorrect import AutoCorrector
from core.brain import Brain
from core.copilot import CoPilot
from core.executor import ActionExecutor
from core.memory import Memory
from core.voice import Voice

console = Console()

BANNER = r"""
  ██╗██████╗ ██╗███████╗
  ██║██╔══██╗██║██╔════╝
  ██║██████╔╝██║███████╗
  ██║██╔══██╗██║╚════██║
  ██║██║  ██║██║███████║
  ╚═╝╚═╝  ╚═╝╚═╝╚══════╝
  Intelligence. Redefined.
"""


def show_status(memory: Memory, text_mode: bool, voice: Voice) -> None:
    mic_status = "Ready" if getattr(voice, "mic_ready", False) else "Unavailable"
    audio_status = "Ready" if getattr(voice, "audio_ready", False) else "Unavailable"

    console.print(
        Panel(
            "[bold green]Online[/bold green]\n"
            f"[white]Primary Brain  :[/white] [cyan]{Config.PRIMARY_BRAIN}[/cyan]\n"
            f"[white]Fallback Brain :[/white] [cyan]{Config.FALLBACK_BRAIN}[/cyan]\n"
            f"[white]Input Mode     :[/white] [cyan]{'Keyboard' if text_mode else 'Voice standby'}[/cyan]\n"
            f"[white]Microphone     :[/white] [cyan]{mic_status}[/cyan]\n"
            f"[white]Audio Output   :[/white] [cyan]{audio_status}[/cyan]\n"
            f"[white]Wake Words     :[/white] [cyan]{', '.join(Config.WAKE_WORDS)}[/cyan]\n"
            f"[white]Memory         :[/white] [cyan]{memory.summary()}[/cyan]\n",
            title="[bold cyan]IRIS[/bold cyan]",
            border_style="cyan",
        )
    )


def print_response(label: str, text: str) -> None:
    console.print(f"\n[bold cyan]{label}:[/bold cyan] {text}\n")


def contains_wake_word(text: str) -> bool:
    text_l = (text or "").lower().strip()
    wake_words = [w.lower() for w in Config.WAKE_WORDS]

    # exact contains first
    if any(w in text_l for w in wake_words):
        return True

    # tighter fuzzy match on short chunks only
    words = text_l.split()
    chunks = []
    for i in range(len(words)):
        chunks.append(words[i])
        if i + 1 < len(words):
            chunks.append(f"{words[i]} {words[i + 1]}")

    for wake in wake_words:
        for chunk in chunks:
            ratio = difflib.SequenceMatcher(None, chunk, wake).ratio()
            if ratio >= getattr(Config, "WAKE_FUZZY_THRESHOLD", 0.82):
                return True

    return False


def strip_wake_word(text: str) -> str:
    cleaned = text.strip()
    text_l = cleaned.lower()

    for wake in sorted(Config.WAKE_WORDS, key=len, reverse=True):
        wake_l = wake.lower()
        if text_l.startswith(wake_l):
            return cleaned[len(wake):].strip(" ,:.-")

    parts = cleaned.split(maxsplit=1)
    if len(parts) == 2 and contains_wake_word(parts[0]):
        return parts[1].strip()

    return cleaned


def handle_user_input(
    user_input: str,
    voice: Voice,
    autocorrect: AutoCorrector,
    executor: ActionExecutor,
    copilot: CoPilot,
    brain: Brain,
):
    user_input = user_input.strip()
    if not user_input:
        return None, False

    if user_input.lower() in {"exit", "quit", "goodbye iris", "shutdown"}:
        msg = "Shutting down. Try not to break anything while I'm gone."
        print_response("IRIS", msg)
        voice.speak(msg)
        return msg, True

    corrected, correction_note = autocorrect.correct_input(user_input)
    if correction_note:
        console.print(f"[dim]  ✎ {correction_note}[/dim]")
        user_input = corrected

    try:
        voice.stop_speaking()
    except Exception:
        pass

    if executor.waiting_for_followup():
        response = executor.handle_followup_response(user_input)
        if response is not None:
            print_response("IRIS", response)
            voice.speak(response)
            return response, False

    if executor.waiting_for_permission():
        with console.status("[cyan]Executing...[/cyan]", spinner="dots"):
            response = executor.handle_permission_response(user_input)
        print_response("IRIS", response)
        voice.speak(response)
        return response, False

    if copilot.active:
        with console.status("[cyan]Co-Pilot...[/cyan]", spinner="dots"):
            response = copilot.handle_input(user_input)
        if response:
            print_response("IRIS (Co-Pilot)", response)
            voice.speak(response)
        return response, False

    if copilot.should_activate(user_input):
        console.print("[dim]  → Co-Pilot mode activated[/dim]")
        with console.status("[cyan]Planning steps...[/cyan]", spinner="dots"):
            response = copilot.start(user_input)
        print_response("IRIS (Co-Pilot)", response)
        voice.speak(response)
        return response, False

    if executor.should_handle(user_input):
        console.print("[dim]  → Action mode — planning...[/dim]")
        with console.status("[cyan]Planning action...[/cyan]", spinner="dots"):
            response = executor.plan_action(user_input)
        print_response("IRIS (Action)", response)
        voice.speak(response)
        return response, False

    with console.status("[cyan]Thinking...[/cyan]", spinner="dots"):
        response = brain.think(user_input)

    print_response("IRIS", response)
    voice.speak(response)
    return response, False


def main() -> None:
    parser = argparse.ArgumentParser(description="IRIS AI Assistant")
    parser.add_argument("--text", action="store_true", help="Keyboard input mode")
    args = parser.parse_args()

    console.print(BANNER, style="bold cyan")

    memory = Memory(Config.MEMORY_FILE)
    brain = Brain(memory)
    voice = Voice(text_mode=args.text)
    copilot = CoPilot(brain, voice, memory)
    executor = ActionExecutor(voice, brain)
    autocorrect = AutoCorrector(brain)

    show_status(memory, args.text, voice)

    if args.text:
        console.print("[dim]Text mode active. Type 'exit' to shut down.[/dim]\n")
    else:
        console.print("[dim]Standby mode active. Call Iris when you need her.[/dim]")
        console.print(f"[dim]Wake words: {', '.join(Config.WAKE_WORDS)}[/dim]\n")

    # How many follow-up turns Iris listens for after being woken
    CONVERSATION_TURNS = 5

    while True:
        try:
            if args.text:
                user_input = voice.listen_text()
                _, should_exit = handle_user_input(
                    user_input, voice, autocorrect, executor, copilot, brain
                )
                if should_exit:
                    break
                continue

            # ── Standby: wait for wake word ──────────────────────
            heard_text = voice.listen_for_wake()
            if not heard_text:
                continue

            if not contains_wake_word(heard_text):
                continue

            stripped = strip_wake_word(heard_text)

            # Wake word + command in one phrase (e.g. "Iris open notepad")
            if stripped:
                console.print(f"[green]Wake detected:[/green] {heard_text}")
                _, should_exit = handle_user_input(
                    stripped, voice, autocorrect, executor, copilot, brain
                )
                if should_exit:
                    break
            else:
                # Wake word only — acknowledge and listen for command
                ack = getattr(Config, "WAKE_ACKNOWLEDGEMENT", "Yes?")
                print_response("IRIS", ack)
                voice.speak(ack)

                command = voice.listen_for_command()
                if not command:
                    continue

                _, should_exit = handle_user_input(
                    command, voice, autocorrect, executor, copilot, brain
                )
                if should_exit:
                    break

            # ── Conversation mode: keep listening for follow-ups ──
            # No need to say "Iris" again for CONVERSATION_TURNS turns
            for _ in range(CONVERSATION_TURNS):
                console.print("[dim]  (follow-up listening...)[/dim]")
                follow_up = voice.listen_for_command()

                if not follow_up:
                    # Silence — go back to standby
                    console.print("[dim]  → Back to standby[/dim]")
                    break

                # If they say "stop", "bye", "goodbye" — end conversation
                if any(w in follow_up.lower() for w in ["stop", "bye", "goodbye", "that's all", "thanks iris"]):
                    console.print("[dim]  → Conversation ended[/dim]")
                    break

                _, should_exit = handle_user_input(
                    follow_up, voice, autocorrect, executor, copilot, brain
                )
                if should_exit:
                    break

            if should_exit:
                break

        except KeyboardInterrupt:
            console.print("\n\n[bold cyan]IRIS:[/bold cyan] Interrupted. Goodbye!")
            try:
                voice.stop_speaking()
            except Exception:
                pass
            break
        except Exception as e:
            console.print(f"\n[bold red]Error:[/bold red] {e}")
            time.sleep(1)

    try:
        if hasattr(memory, "_save"):
            memory._save()
    except Exception:
        pass


if __name__ == "__main__":
    main()