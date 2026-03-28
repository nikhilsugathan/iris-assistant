"""
IRIS Memory Module
====================
Handles persistent conversation history and context.
Stores everything locally in a JSON file on your PC.
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
        """Load existing memory from disk."""
        if os.path.exists(self.memory_file):
            try:
                with open(self.memory_file, "r") as f:
                    data = json.load(f)
                    self.conversation = data.get("conversation", [])
            except Exception:
                self.conversation = []

    def _save(self):
        """Persist memory to disk."""
        with open(self.memory_file, "w") as f:
            json.dump({
                "last_updated": datetime.now().isoformat(),
                "conversation": self.conversation
            }, f, indent=2)

    def add(self, role: str, content: str, source: str = None):
        """
        Add a turn to conversation memory.
        role: 'user' or 'assistant'
        source: which AI generated this response (e.g. 'gemini', 'groq')
        """
        entry = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        }
        if source:
            entry["source"] = source

        self.conversation.append(entry)
        self._save()

    def get_context(self, max_turns: int = 20) -> List[Dict]:
        """
        Return recent conversation history formatted for LLM API calls.
        Only returns role + content (strips metadata).
        """
        recent = self.conversation[-max_turns * 2:]  # Each turn = 2 entries
        return [{"role": e["role"], "content": e["content"]} for e in recent]

    def get_context_string(self, max_turns: int = 10) -> str:
        """Return conversation history as a readable string for context injection."""
        recent = self.conversation[-max_turns * 2:]
        lines = []
        for entry in recent:
            role = "User" if entry["role"] == "user" else "Iris"
            lines.append(f"{role}: {entry['content']}")
        return "\n".join(lines)

    def clear(self):
        """Wipe memory completely."""
        self.conversation = []
        self._save()

    def summary(self) -> str:
        """Return a quick stats summary."""
        turns = len([e for e in self.conversation if e["role"] == "user"])
        return f"{turns} exchanges since session started at {self.session_start}"
