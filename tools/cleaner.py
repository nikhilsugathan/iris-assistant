import json
import os
from datetime import datetime
from rich.console import Console

console = Console()

def sanitize_memory(file_path="iris_memory.json"):
    if not os.path.exists(file_path):
        return

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            conversation = data.get("conversation", [])

        # 1. REMOVE COGNITIVE ERRORS
        # Filters out the "I encountered a cognitive processing error" loops
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
            content = entry.get("content", "").lower()
            role = entry.get("role")
            
            # Identify if this is the assistant's answer to a system ping
            if role == "assistant" and entry.get("source") in ["system-local", "desktop-local", "clipboard-local"]:
                # We haven't seen this specific status yet, keep it.
                if content not in seen_system_queries:
                    final_conv.append(entry)
                    seen_system_queries.add(content)
                    skip_next_assistant = False
                else:
                    # It's a duplicate. We drop it, AND we must drop the user's prompt that triggered it.
                    skip_next_assistant = True
                continue
            
            # Identify the user's prompt
            if role == "user":
                is_system_prompt = any(q in content for q in ["battery status", "computer named", "on my clipboard"])
                if is_system_prompt and skip_next_assistant:
                    # Drop the user prompt that matches the dropped assistant answer
                    skip_next_assistant = False
                    continue
                
            final_conv.append(entry)

        # Restore original order
        final_conv.reverse()

        # 3. SAVE CLEANED DATA
        data["conversation"] = final_conv
        data["last_updated"] = datetime.now().isoformat()
        
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            
        diff = len(conversation) - len(final_conv)
        if diff > 0:
            console.print(f"[bold green]✓ Memory Sanitized:[/bold green] Removed {diff} junk entries.")

    except Exception as e:
        console.print(f"[bold red]Sanitization Failed:[/bold red] {e}")

if __name__ == "__main__":
    sanitize_memory()