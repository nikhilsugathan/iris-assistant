"""
IRIS Hard Sanitizer & Auto-Sync v4.8.3
=====================================
- Auto-sync is disabled by default.
- When enabled, only allowlisted project files are staged.
"""
import json
import os
import re
import subprocess
from datetime import datetime
from rich.console import Console
from config import Config

console = Console()

_ALLOWED_SYNC_PATHS = [
    "README.md",
    "requirements.txt",
    "config.py",
    "main.py",
    "core",
    "tools",
    "tests",
    "launch_iris.bat",
]

_BLOCKED_SYNC_PATTERNS = re.compile(
    r"(^|/)(\.env|logs|history|models|browser_data|exports|\.cache)(/|$)"
    r"|iris_memory"
    r"|knowledge_base\.json"
    r"|sessions_archive"
    r"|\.gguf$|\.bin$|\.log$|\.tmp$",
    re.IGNORECASE,
)


def _run_git(args, timeout=10):
    return subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _safe_sync_paths():
    existing = []
    for path in _ALLOWED_SYNC_PATHS:
        if os.path.exists(path) and not _BLOCKED_SYNC_PATTERNS.search(path.replace("\\", "/")):
            existing.append(path)
    return existing


def sync_to_git():
    if not getattr(Config, "ENABLE_AUTO_SYNC", False):
        console.print("[bold yellow]Auto-sync disabled. Skipping git commit/push.[/bold yellow]")
        return

    try:
        console.print("[bold cyan]→ Syncing allowlisted project files to GitHub...[/bold cyan]")
        paths = _safe_sync_paths()
        if not paths:
            console.print("[bold yellow]! Sync skipped:[/bold yellow] no allowlisted paths found.")
            return

        _run_git(["add", "--", *paths], timeout=5)
        diff = subprocess.run(["git", "diff", "--cached", "--quiet"], timeout=5)
        if diff.returncode == 0:
            console.print("[dim]No staged changes to sync.[/dim]")
            return

        msg = f"AUTO: State Sync {datetime.now().strftime('%H:%M')}"
        _run_git(["commit", "-m", msg], timeout=10)
        _run_git(["push", "origin", "main"], timeout=20)
        console.print("[bold green]✓ Cloud Backup Successful.[/bold green]")
    except subprocess.TimeoutExpired:
        console.print("[bold yellow]! Sync Timeout:[/bold yellow] Network unreachable. Force-exiting.")
    except Exception as e:
        console.print(f"[bold red]! Sync Failed:[/bold red] {e}")


def sanitize_memory(file_path):
    if not os.path.exists(file_path):
        return
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        sync_to_git()
    except Exception as e:
        console.print(f"[bold red]Sanitization Error:[/bold red] {e}")
