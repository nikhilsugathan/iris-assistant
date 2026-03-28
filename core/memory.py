"""
IRIS Memory Module
====================
Handles persistent conversation history and context.
Stores everything locally in a JSON file on your PC.
"""

import json
import os
import tempfile
from datetime import datetime
from typing import List, Dict

# ── Anchor: memory file must live in the project root ──────────
# This prevents path traversal via Config.MEMORY_FILE or any
# external manipulation of the memory_file argument.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Memory:

    def __init__(self, memory_file: str):
        # Strip any directory component — only the bare filename is accepted.
        # e.g. "../../etc/passwd" becomes "passwd", then is anchored to PROJECT_ROOT.
        basename = os.path.basename(memory_file)
        if not basename:
            basename = "iris_memory.json"
        self.memory_file = os.path.join(_PROJECT_ROOT, basename)

        self.conversation: List[Dict] = []
        self.session_start = datetime.now().strftime("%Y-%m-%d %H:%M")
        self._load()

    def _load(self):
        """Load existing memory from disk."""
        if os.path.exists(self.memory_file):
            try:
                with open(self.memory_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.conversation = data.get("conversation", [])
            except Exception:
                self.conversation = []

    def _save(self):
        """
        Atomic write — crash-safe.

        Writes the new JSON to a temporary file in the same directory,
        then uses os.replace() to atomically swap it into place.
        A crash or power loss during the write can never leave a
        half-written / corrupted memory file.
        """
        data = {
            "last_updated": datetime.now().isoformat(),
            "conversation": self.conversation,
        }
        dir_name = os.path.dirname(self.memory_file)
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                dir=dir_name,
                delete=False,
                suffix=".tmp",
                encoding="utf-8",
            ) as tmp:
                json.dump(data, tmp, indent=2)
                tmp_path = tmp.name
            # Atomic on POSIX; near-atomic (same-volume rename) on Windows
            os.replace(tmp_path, self.memory_file)
        except Exception:
            # Clean up orphaned temp file if the rename failed
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
            raise

    def add(self, role: str, content: str, source: str = None):
        """
        Add a turn to conversation memory.
        role: 'user' or 'assistant'
        source: which AI generated this response (e.g. 'gemini', 'groq')
        """
        entry = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
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
