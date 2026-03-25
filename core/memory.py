"""
IRIS Memory Module
==================
Handles persistent conversation history and context.
Stores everything locally in a JSON file on your PC.
"""

import json
import os
import threading
import time
from datetime import datetime
from typing import List, Dict

from config import Config


class Memory:

    def __init__(self, memory_file: str):
        self.memory_file = memory_file
        self.conversation: List[Dict] = []
        self.session_start = datetime.now().strftime("%Y-%m-%d %H:%M")
        self._save_lock = threading.Lock()
        self._save_event = threading.Event()
        self._stop_event = threading.Event()
        self._dirty = False
        self._load()
        self._save_thread = threading.Thread(target=self._save_loop, daemon=True)
        self._save_thread.start()

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
        self.flush()

    def _save_now(self):
        """Persist memory to disk."""
        with self._save_lock:
            try:
                memory_dir = os.path.dirname(self.memory_file)
                if memory_dir:
                    os.makedirs(memory_dir, exist_ok=True)
                with open(self.memory_file, "w", encoding="utf-8") as f:
                    json.dump(
                        {
                            "last_updated": datetime.now().isoformat(),
                            "conversation": self.conversation,
                        },
                        f,
                        indent=2,
                        ensure_ascii=True,
                    )
                self._dirty = False
            except OSError:
                # Memory persistence should never crash the runtime loop.
                pass

    def _save_loop(self) -> None:
        debounce_seconds = max(0.05, int(getattr(Config, "MEMORY_SAVE_DEBOUNCE_MS", 160)) / 1000.0)
        while not self._stop_event.is_set():
            triggered = self._save_event.wait(0.5)
            if not triggered:
                continue

            self._save_event.clear()
            # Collapse bursts of conversation turns into one write.
            time.sleep(debounce_seconds)
            if self._save_event.is_set():
                continue
            if self._dirty:
                self._save_now()

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
        max_entries = max(20, int(getattr(Config, "MAX_MEMORY_TURNS", 8)) * 6)
        if len(self.conversation) > max_entries:
            self.conversation = self.conversation[-max_entries:]
        self._dirty = True
        self._save_event.set()

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
        self._dirty = True
        self.flush()

    def summary(self) -> str:
        """Return a quick stats summary."""
        turns = len([e for e in self.conversation if e["role"] == "user"])
        return f"{turns} stored exchanges. Current session started at {self.session_start}"

    def flush(self):
        if not self._dirty and os.path.exists(self.memory_file):
            return
        self._save_now()

    def close(self):
        self._stop_event.set()
        self._save_event.set()
        if getattr(self, "_save_thread", None) and self._save_thread.is_alive():
            self._save_thread.join(timeout=0.5)
        if self._dirty:
            self._save_now()
