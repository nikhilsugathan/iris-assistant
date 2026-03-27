"""
IRIS Main Entry Point (Jarvis-Class Integrated)
==============================================
Version: 3.0.0 "Golden State"
Features: Mood-aware UI, Council Synthesis, Zero-Latency Streaming.
"""

import argparse
from rich.panel import Panel
from rich.text import Text

from config import Config
from core import logger, console
from core.memory import Memory
from core.brain import Brain
from core.voice import Voice
from core.executor import ActionExecutor
from core.council import Council
from core.copilot import CoPilot

def render_status_light(voice, is_thinking=False):
    """Dynamic terminal mood indicator."""
    colors = {"urgent": "red", "calm": "green", "normal": "cyan"}
    color = "yellow" if is_thinking else colors.get(voice.current_mood, "cyan")
    status = Text(f" ● IRIS STATUS: {'THINKING' if is_thinking else voice.current_mood.upper()}", style=f"bold {color}")
    console.print(Panel(status, expand=False, border_style=color))

def handle_user_input(user_input, brain, voice, memory, executor, council, copilot):
    if not user_input.strip(): return None, False
    if any(cmd in user_input.lower() for cmd in ["exit", "shutdown", "goodbye"]):
        voice.speak("System offline. Goodbye.", mood="calm")
        return "Shutting down...", True

    render_status_light(voice, is_thinking=True)
    packet = council.generate_packet(user_input)
    response = brain.think(user_input, voice_engine=voice, council_packet=packet)
    
    memory.add("user", user_input)
    memory.add("iris", response)
    return response, False

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", action="store_true", help="Run in text mode")
    args = parser.parse_args()

    console.print(Panel("[bold cyan]IRIS SYSTEM ONLINE[/bold cyan]", border_style="cyan"))

    # Audit-Verified Initialization Sequence
    memory = Memory(Config.MEMORY_FILE)
    brain = Brain(memory=memory, model=Config.PRIMARY_MODEL)
    voice = Voice(device_index=Config.DEVICE_INDEX, text_mode=args.text)
    executor = ActionExecutor(voice, brain)
    council = Council()
    copilot = CoPilot(brain, voice, memory)

    while True:
        # Audit Fix: Reset exit flag to avoid scope crashes
        should_exit = False 
        
        if args.text:
            user_input = console.input("[bold cyan]You:[/bold cyan] ")
            _, should_exit = handle_user_input(user_input, brain, voice, memory, executor, council, copilot)
        else:
            if voice.listen_for_wake():
                render_status_light(voice)
                user_input = voice.listen_for_command()
                if user_input:
                    console.print(f"[bold cyan]You:[/bold cyan] {user_input}")
                    _, should_exit = handle_user_input(user_input, brain, voice, memory, executor, council, copilot)
        
        if should_exit: break

if __name__ == "__main__":
    main()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", action="store_true", help="Run in text-only mode")
    args = parser.parse_args()

    console.print(Panel("[bold cyan]IRIS SYSTEM ONLINE[/bold cyan]", border_style="cyan"))

    # Audit-Verified Initialization Sequence
    memory = Memory(Config.MEMORY_FILE)
    brain = Brain(memory=memory, model=Config.PRIMARY_MODEL)
    voice = Voice(device_index=Config.DEVICE_INDEX, text_mode=args.text)
    executor = ActionExecutor(voice, brain)
    council = Council()
    copilot = CoPilot(brain, voice, memory)

    while True:
        # Audit Fix: Explicitly reset exit flag to avoid scope crashes
        should_exit = False 
        
        if args.text:
            user_input = console.input("[bold cyan]You:[/bold cyan] ")
            _, should_exit = handle_user_input(user_input, brain, voice, memory, executor, council, copilot)
        else:
            if voice.listen_for_wake():
                render_status_light(voice)
                user_input = voice.listen_for_command()
                if user_input:
                    console.print(f"[bold cyan]You (Voice):[/bold cyan] {user_input}")
                    _, should_exit = handle_user_input(user_input, brain, voice, memory, executor, council, copilot)
        
        if should_exit: break

if __name__ == "__main__":
    main()