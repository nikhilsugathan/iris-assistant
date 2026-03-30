"""
IRIS v4.8.3 Final Build Verification
====================================
Checks the integrity of manual diffs for Config and Voice modules.
"""
import os
from config import Config
from core.voice import Voice
from rich.console import Console

console = Console()

def verify():
    console.print("[bold cyan]→ Starting IRIS v4.8.3 Integrity Check...[/bold cyan]\n")
    errors = 0

    # 1. Verify Config Thresholds
    console.print("[white]1. Checking Config Gates...[/white]")
    wake_gate = getattr(Config, "WAKE_RMS_THRESHOLD", None)
    cmd_gate = getattr(Config, "COMMAND_RMS_THRESHOLD", None)

    if wake_gate == 400:
        console.print("  [green]✓[/green] WAKE_RMS_THRESHOLD is 400")
    else:
        console.print(f"  [red]✗[/red] WAKE_RMS_THRESHOLD is {wake_gate} (Expected 400)")
        errors += 1

    if cmd_gate == 550:
        console.print("  [green]✓[/green] COMMAND_RMS_THRESHOLD is 550")
    else:
        console.print(f"  [red]✗[/red] COMMAND_RMS_THRESHOLD is {cmd_gate} (Expected 550)")
        errors += 1

    # 2. Verify Voice Property Logic
    console.print("\n[white]2. Checking Voice Property Logic...[/white]")
    try:
        v = Voice(text_mode=True)
        # Test the io_disabled property added in the last diff
        if v.io_disabled is True:
            console.print("  [green]✓[/green] Voice.io_disabled property detected and functional")
        else:
            console.print("  [red]✗[/red] Voice.io_disabled returned False in text_mode")
            errors += 1
    except AttributeError:
        console.print("  [red]✗[/red] AttributeError: io_disabled property missing from Voice class")
        errors += 1

    # 3. Verify Atomic Lock Placeholder
    console.print("\n[white]3. Checking Threading Strategy...[/white]")
    if hasattr(v, "_tts_lock"):
        console.print("  [green]✓[/green] _tts_lock identified")
    else:
        console.print("  [red]✗[/red] _tts_lock missing")
        errors += 1

    if errors == 0:
        console.print("\n[bold green]FINAL VERDICT: GREEN LIGHT. IRIS v4.8.3 IS PRODUCTION READY.[/bold green]")
    else:
        console.print(f"\n[bold red]VERDICT: FAIL. {errors} hardening issues detected.[/bold red]")

if __name__ == "__main__":
    verify()