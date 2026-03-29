import sys
from rich.console import Console
from core.voice import Voice
from config import Config

console = Console()

def run_mic_test():
    console.print("[bold cyan]IRIS Live Mic Diagnostic[/bold cyan]")
    console.print(f"Current Threshold: [yellow]{Config.MIC_ENERGY_THRESHOLD}[/yellow]")
    console.print("[dim]Speak naturally. Press Ctrl+C to exit this test.[/dim]\n")
    
    # Initialize voice in listen-only mode
    voice = Voice()
    
    try:
        while True:
            # Captures and transcribes audio without triggering the brain
            text = voice.listen()
            if text:
                console.print(f"[bold green]Captured:[/bold green] {text}")
            else:
                # Visual feedback that the mic is active but silent
                print(".", end="", flush=True)
    except KeyboardInterrupt:
        console.print("\n[yellow]Mic test stopped.[/yellow]")

if __name__ == "__main__":
    run_mic_test()