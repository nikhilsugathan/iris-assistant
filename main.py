"""
IRIS Main Entry Point
=====================
Terminal entry point backed by the shared IRIS runtime engine.
"""

from __future__ import annotations

import argparse
import time

from rich.console import Console
from rich.panel import Panel

from config import Config
from core.engine import IRISEngine

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


def show_status(engine: IRISEngine, text_mode: bool) -> None:
    snapshot = engine.status_snapshot()
    mic_status = "Ready" if snapshot.get("mic_ready") else "Unavailable"
    audio_status = "Ready" if snapshot.get("audio_ready") else "Unavailable"
    overdrive = "Active" if snapshot.get("overdrive_active") else "Off"

    console.print(
        Panel(
            "[bold green]Online[/bold green]\n"
            f"[white]Primary Brain  :[/white] [cyan]{snapshot.get('primary_brain')}[/cyan]\n"
            f"[white]Fallback Brain :[/white] [cyan]{snapshot.get('fallback_brain')}[/cyan]\n"
            f"[white]Cognitive Core :[/white] [cyan]Adaptive council online[/cyan]\n"
            f"[white]Input Mode     :[/white] [cyan]{'Keyboard' if text_mode else 'Voice standby'}[/cyan]\n"
            f"[white]Microphone     :[/white] [cyan]{mic_status}[/cyan]\n"
            f"[white]Audio Output   :[/white] [cyan]{audio_status}[/cyan]\n"
            f"[white]Wake Words     :[/white] [cyan]{', '.join(snapshot.get('wake_words', []))}[/cyan]\n"
            f"[white]Overdrive      :[/white] [cyan]{overdrive}[/cyan]\n"
            f"[white]Self Model     :[/white] [cyan]{snapshot.get('self_model')}[/cyan]\n"
            f"[white]Memory         :[/white] [cyan]{snapshot.get('memory')}[/cyan]\n",
            title=f"[bold cyan]{snapshot.get('system_name', Config.SYSTEM_NAME)}[/bold cyan]",
            border_style="cyan",
        )
    )


def print_response(label: str, text: str) -> None:
    if not text:
        return
    console.print(f"\n[bold cyan]{label}:[/bold cyan] {text}\n")


def drain_background_updates(engine: IRISEngine) -> None:
    for update in engine.drain_background_updates():
        message = str(update.get("message") or "").strip()
        if not message:
            continue
        label = str(update.get("label") or f"{Config.PUBLIC_NAME} (Action)")
        print_response(label, message)


def speak_voice_result(engine: IRISEngine, result) -> None:
    if not result.response or getattr(result, "exit_immediately", False) or getattr(result, "speech_started", False):
        return
    if engine.should_hold_voice_followup_open():
        engine.voice.speak(result.response)
    else:
        engine.voice.speak_background(result.response)


def main() -> None:
    parser = argparse.ArgumentParser(description="IRIS AI Assistant")
    parser.add_argument("--text", action="store_true", help="Keyboard input mode")
    args = parser.parse_args()

    console.print(BANNER, style="bold cyan")

    engine = IRISEngine(text_mode=args.text)
    voice = engine.voice
    show_status(engine, args.text)

    if args.text:
        console.print("[dim]Text mode active. Type 'exit' to shut down.[/dim]\n")
    else:
        console.print("[dim]Standby mode active. Call Iris when you need her.[/dim]")
        console.print(f"[dim]Wake words: {', '.join(Config.WAKE_WORDS)}[/dim]\n")

    conversation_turns = max(1, int(getattr(Config, "VOICE_FOLLOWUP_TURNS", 4)))

    try:
        while True:
            drain_background_updates(engine)
            if args.text:
                user_input = voice.listen_text()
                result = engine.process_user_input(user_input, speak_response=True, input_source="text")
                print_response(result.label, result.response)
                drain_background_updates(engine)
                if result.should_exit:
                    break
                continue

            heard_text = voice.listen_for_wake()
            if not heard_text:
                continue

            if not engine.contains_wake_word(heard_text):
                continue

            stripped = engine.strip_wake_word(heard_text)

            if stripped:
                console.print(f"[green]Wake detected:[/green] {heard_text}")
                result = engine.process_voice_turn(stripped, input_source="voice", enable_slow_ack=True)
                speak_voice_result(engine, result)
                print_response(result.label, result.response)
                drain_background_updates(engine)
                if result.should_exit:
                    break
                if not engine.should_hold_voice_followup_open():
                    console.print("[dim]  → Back to standby[/dim]")
                    continue
            else:
                ack = getattr(Config, "WAKE_ACKNOWLEDGEMENT", "I'm here.")
                print_response(Config.PUBLIC_NAME, ack)
                voice.speak_quick_ack(ack)

                command = engine.listen_for_voice_command(interrupt_speech=False)
                if not command:
                    if getattr(voice, "last_listen_status", "") == "transcription_failed":
                        print_response("System", voice.describe_last_listen_feedback())
                    continue

                result = engine.process_voice_turn(command, input_source="voice", enable_slow_ack=True)
                speak_voice_result(engine, result)
                print_response(result.label, result.response)
                drain_background_updates(engine)
                if result.should_exit:
                    break
                if not engine.should_hold_voice_followup_open():
                    console.print("[dim]  → Back to standby[/dim]")
                    continue

            for _ in range(conversation_turns):
                console.print("[dim]  (follow-up listening...)[/dim]")
                follow_up = engine.listen_for_voice_command()

                if not follow_up:
                    console.print("[dim]  → Back to standby[/dim]")
                    break

                if engine.should_end_followup(follow_up):
                    console.print("[dim]  → Conversation ended[/dim]")
                    break

                result = engine.process_voice_turn(follow_up, input_source="voice", enable_slow_ack=True)
                speak_voice_result(engine, result)
                print_response(result.label, result.response)
                drain_background_updates(engine)
                if result.should_exit:
                    return
                if not engine.should_hold_voice_followup_open():
                    console.print("[dim]  → Back to standby[/dim]")
                    break
    except KeyboardInterrupt:
        console.print("\n\n[bold cyan]IRIS:[/bold cyan] Interrupted. Goodbye!")
        try:
            voice.stop_speaking()
        except Exception:
            pass
    except Exception as exc:
        console.print(f"\n[bold red]Error:[/bold red] {exc}")
        time.sleep(1)
    finally:
        engine.shutdown()


if __name__ == "__main__":
    main()
