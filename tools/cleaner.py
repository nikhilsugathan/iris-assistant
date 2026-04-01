"""
IRIS Hard Sanitizer & Auto-Sync v4.8.3
=====================================
- C1 Fix: Hard 20s timeout on Git Push prevents indefinite shutdown hangs.
"""
import json, os, re, subprocess
from datetime import datetime
from rich.console import Console
from config import Config

console = Console()

def sync_to_git():
    if not getattr(Config, 'ENABLE_AUTO_SYNC', False):
        console.print("[bold yellow]Auto-sync disabled. Skipping git commit/push.[/bold yellow]")
        return

    try:
        console.print("[bold cyan]→ Syncing to GitHub...[/bold cyan]")
        # Local Ops
        subprocess.run(["git", "add", "."], check=True, timeout=5)
        msg = f"AUTO: State Sync {datetime.now().strftime('%H:%M')}"
        subprocess.run(["git", "commit", "-m", msg], check=True, timeout=5)
        
        # C1 FIX: Hard Timeout for Network Ops
        subprocess.run(["git", "push", "origin", "main"], check=True, capture_output=True, timeout=20)
        console.print("[bold green]✓ Cloud Backup Successful.[/bold green]")
    except subprocess.TimeoutExpired:
        console.print("[bold yellow]! Sync Timeout:[/bold yellow] Network unreachable. Force-exiting.")
    except Exception as e:
        console.print(f"[bold red]! Sync Failed:[/bold red] {e}")

def sanitize_memory(file_path):
    if not os.path.exists(file_path): return
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Redaction logic...
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        sync_to_git()
    except Exception as e:
        console.print(f"[bold red]Sanitization Error:[/bold red] {e}")