"""
IRIS Memory Module v4.7
=======================
Features: 
- Automatic Role Normalization (iris -> assistant)
- Real-time Content De-duplication (Removes system-stat bloat)
- Standardized persistent JSON storage
"""

import json
import os
from datetime import datetime
from typing import List, Dict
from config import Config

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
        """DE-DUPLICATION: Removes repeated system stats to save context window space."""
        seen_content = set()
        cleaned = []
        # Work backwards to keep only the LATEST unique status updates
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
        """Adds a turn, cleans duplicates, and triggers a save."""
        # Ensure role is always 'user' or 'assistant' for API compatibility
        normalized_role = "assistant" if role in ["assistant", "iris"] else "user"
        
        entry = {
            "role": normalized_role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        }
        if source: entry["source"] = source

        self.conversation.append(entry)
        
        # Trim to prevent unbounded memory growth
        if len(self.conversation) > Config.MAX_MEMORY_TURNS:
            self.conversation = self.conversation[-Config.MAX_MEMORY_TURNS:]
        
        # Real-time de-duplication integrated here
        self._self_clean() 
        
        self._save()

    def get_context(self, max_turns: int = None) -> List[Dict]:
        """Retrieve the most recent conversation context."""
        # Default to the Config value if nothing is passed
        limit = max_turns if max_turns is not None else getattr(Config, "MAX_MEMORY_TURNS", 8)
        recent = self.conversation[-limit * 2:]
        return recent

    def summary(self) -> str:
        turns = len([e for e in self.conversation if e["role"] == "user"])
        return f"{turns} exchanges stored (Memory File: {os.path.basename(self.memory_file)})"