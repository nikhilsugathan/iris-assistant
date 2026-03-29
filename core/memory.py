"""
IRIS Memory Module v4.6
=======================
Features: 
- Automatic Role Normalization (iris -> assistant)
- Content De-duplication (Removes system-stat bloat)
- Standardized persistent JSON storage
"""

import json
import os
from datetime import datetime
from typing import List, Dict

class Memory:
    def __init__(self, memory_file: str):
        self.memory_file = memory_file
        self.conversation: List[Dict] = []
        self.session_start = datetime.now().strftime("%Y-%m-%d %H:%M")
        self._load()

    def _load(self):
        """Load and normalize existing memory from disk."""
        if os.path.exists(self.memory_file):
            try:
                with open(self.memory_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    raw_conv = data.get("conversation", [])
                    
                    # ROLE NORMALIZATION: Convert old 'iris' role to 'assistant'
                    for entry in raw_conv:
                        if entry.get("role") == "iris":
                            entry["role"] = "assistant"
                    
                    self.conversation = raw_conv
                    self._self_clean() # Remove bloat on startup
            except Exception:
                self.conversation = []

    def _save(self):
        """Persist memory to disk with safety guard."""
        try:
            with open(self.memory_file, "w", encoding="utf-8") as f:
                json.dump({
                    "last_updated": datetime.now().isoformat(),
                    "conversation": self.conversation
                }, f, indent=2)
        except OSError as e:
            import sys
            print(f"[Memory] OSError: could not save to '{self.memory_file}': {e}", file=sys.stderr)

    def _self_clean(self):
        """DE-DUPLICATION: Removes repeated system stats to save context."""
        seen_content = set()
        cleaned = []
        # We work backwards to keep only the LATEST unique status updates
        for entry in reversed(self.conversation):
            content = entry.get("content", "")
            # Only deduplicate short system-local responses (battery, name, etc.)
            if entry.get("source") in ["system-local", "desktop-local"] and len(content) < 100:
                if content not in seen_content:
                    cleaned.append(entry)
                    seen_content.add(content)
            else:
                cleaned.append(entry)
        
        self.conversation = list(reversed(cleaned))

    def add(self, role: str, content: str, source: str = None):
        """Adds a turn and triggers a save."""
        # Ensure role is always 'user' or 'assistant' for API compatibility
        normalized_role = "assistant" if role in ["assistant", "iris"] else "user"
        
        entry = {
            "role": normalized_role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        }
        if source: entry["source"] = source

        self.conversation.append(entry)
        self._save()

    def get_context(self, max_turns: int = 20) -> List[Dict]:
        """Returns role + content for LLM API calls."""
        recent = self.conversation[-max_turns * 2:]
        return [{"role": e["role"], "content": e["content"]} for e in recent]

    def summary(self) -> str:
        turns = len([e for e in self.conversation if e["role"] == "user"])
        return f"{turns} exchanges stored (Memory File: {os.path.basename(self.memory_file)})"