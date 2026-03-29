"""
IRIS Hard Sanitizer & Auto-Sync v4.8
===================================
- Removes cognitive/connection error loops.
- Prunes history and redacts sensitive tokens.
- AUTO-SYNC: Automatically commits and pushes to Git on shutdown.
"""

import json
import os
import re
import subprocess
from datetime import datetime
from rich.console import Console
from config import Config

console = Console()

def sync_to_git():
    """Automates the Git backup process."""
    try:
        console.print("[bold cyan]→ Initiating Auto-Sync to GitHub...[/bold cyan]")
        
        # 1. Stage all changes (Memory + Code)
        subprocess.run(["git", "add", "."], check=True, capture_output=True)
        
        # 2. Commit with timestamp
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        msg = f"AUTO: State & Memory Sync {timestamp}"
        subprocess.run(["git", "commit", "-m", msg], check=True, capture_output=True)
        
        # 3. Push to origin
        subprocess.run(["git", "push", "origin", "main"], check=True, capture_output=True)
        
        console.print("[bold green]✓ Cloud Backup Successful.[/bold green]")
    except subprocess.CalledProcessError as e:
        # If there's nothing to commit, Git returns an error code; we can ignore that.
        if "nothing to commit" in str(e.stderr):
            console.print("[dim]  (No new changes to sync)[/dim]")
        else:
            console.print(f"[bold yellow]! Git Sync Skipped:[/bold yellow] {e}")
    except Exception as e:
        console.print(f"[bold red]! Sync Failed:[/bold red] {e}")

def sanitize_memory(file_path=None):
    if file_path is None:
        file_path = Config.MEMORY_FILE

    if not os.path.exists(file_path):
        return

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            conversation = data.get("conversation", [])

        # 1. REMOVE ERRORS
        error_tokens = ["cognitive processing error", "connection error", "try again"]
        clean_conv = [
            entry for entry in conversation 
            if not any(token in (entry.get("content", "") or "").lower() for token in error_tokens)
        ]

        # 2. DE-DUPLICATE SYSTEM PINGS
        final_conv = []
        seen_system_queries = set()
        skip_next_assistant = False
        
        for entry in reversed(clean_conv):
            content = (entry.get("content", "") or "").lower()
            role = entry.get("role")
            
            if role == "assistant" and entry.get("source") in ["system-local", "desktop-local", "clipboard-local"]:
                if content not in seen_system_queries:
                    final_conv.append(entry)
                    seen_system_queries.add(content)
                    skip_next_assistant = False
                else:
                    skip_next_assistant = True
                continue
            
            if role == "user":
                is_system_prompt = any(q in content for q in ["battery", "computer named", "clipboard"])
                if is_system_prompt and skip_next_assistant:
                    skip_next_assistant = False
                    continue
            final_conv.append(entry)

        # 3. REDACTION & PRUNING
        key_pattern = r"(sk-[a-zA-Z0-9]{32,}|gsk_[a-zA-Z0-9]{32,})"
        for entry in final_conv:
            if entry.get("content"):
                entry["content"] = re.sub(key_pattern, "[REDACTED_KEY]", entry["content"])

        final_conv.reverse()
        if len(final_conv) > 100:
            final_conv = final_conv[-100:]

        # 4. SAVE
        data["conversation"] = final_conv
        data["last_updated"] = datetime.now().isoformat()
        
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            
        diff = len(conversation) - len(final_conv)
        if diff > 0:
            console.print(f"[bold green]✓ Memory Sanitized:[/bold green] Removed {diff} junk entries.")

        # --- THE HOOK ---
        # After sanitizing, push the clean state to the cloud
        sync_to_git()

    except Exception as e:
        console.print(f"[bold red]Sanitization Failed:[/bold red] {e}")

if __name__ == "__main__":
    sanitize_memory()