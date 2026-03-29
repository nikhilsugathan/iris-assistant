"""
IRIS Hard Sanitizer v4.7
=======================
Triggered on system shutdown.
- Removes cognitive/connection error loops.
- Prunes history to keep context window lean.
- Redacts potential sensitive tokens.
- De-duplicates system-triggered prompt-response pairs.
"""

import json
import os
import re
from datetime import datetime
from rich.console import Console
from config import Config

console = Console()

def sanitize_memory(file_path=None):
    # Fallback to Config if no path is provided
    if file_path is None:
        file_path = Config.MEMORY_FILE

    if not os.path.exists(file_path):
        return

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            conversation = data.get("conversation", [])

        # 1. REMOVE COGNITIVE ERRORS
        # Filters out "I encountered a cognitive processing error" loops
        error_tokens = ["cognitive processing error", "connection error", "try again"]
        clean_conv = [
            entry for entry in conversation 
            if not any(token in entry.get("content", "").lower() for token in error_tokens)
        ]

        # 2. DE-DUPLICATE SYSTEM PINGS (Fixed for API safety)
        final_conv = []
        seen_system_queries = set()
        
        # Process backwards to prioritize the most recent information
        skip_next_assistant = False
        
        for entry in reversed(clean_conv):
            content = (entry.get("content", "") or "").lower()
            role = entry.get("role")
            
            # Identify redundant assistant status updates
            if role == "assistant" and entry.get("source") in ["system-local", "desktop-local", "clipboard-local"]:
                if content not in seen_system_queries:
                    final_conv.append(entry)
                    seen_system_queries.add(content)
                    skip_next_assistant = False
                else:
                    # Duplicate found. Drop it and flag the user prompt for removal.
                    skip_next_assistant = True
                continue
            
            # Remove the user's prompt that triggered a dropped assistant answer
            if role == "user":
                is_system_prompt = any(q in content for q in ["battery", "computer named", "clipboard"])
                if is_system_prompt and skip_next_assistant:
                    skip_next_assistant = False
                    continue
                
            final_conv.append(entry)

        # 3. SENSITIVE DATA REDACTION (Safety Layer)
        # Masks strings that look like API keys (basic pattern matching)
        key_pattern = r"(sk-[a-zA-Z0-9]{32,}|gsk_[a-zA-Z0-9]{32,})"
        for entry in final_conv:
            if entry.get("content"):
                entry["content"] = re.sub(key_pattern, "[REDACTED_KEY]", entry["content"])

        # 4. TURN PRUNING (Maintain Context Window Health)
        # Keeps the last 100 entries (approx. 50 turns) to prevent context bloat
        MAX_ENTRIES = 100
        final_conv.reverse() # Restore original order before pruning
        if len(final_conv) > MAX_ENTRIES:
            final_conv = final_conv[-MAX_ENTRIES:]

        # 5. SAVE CLEANED DATA
        data["conversation"] = final_conv
        data["last_updated"] = datetime.now().isoformat()
        
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            
        diff = len(conversation) - len(final_conv)
        if diff > 0:
            console.print(f"[bold green]✓ Memory Sanitized:[/bold green] Removed {diff} junk/aged entries.")

    except Exception as e:
        console.print(f"[bold red]Sanitization Failed:[/bold red] {e}")

if __name__ == "__main__":
    sanitize_memory()