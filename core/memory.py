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
import re
from datetime import datetime
from typing import List, Dict
from config import Config
from core.logger import get_logger

logger = get_logger("Memory")

_GENERIC_ASSISTANT_BOILERPLATE = (
    "how can i assist you today",
    "please let me know your task so i can help you effectively",
)

class Memory:
    def __init__(self, memory_file: str):
        if os.path.isabs(memory_file):
            self.memory_file = memory_file
        else:
            self.memory_file = os.path.join(Config.PROJECT_ROOT, memory_file)
        # Long-term archive lives next to the main memory file.
        _base = os.path.splitext(self.memory_file)[0]
        self._sessions_archive_file = _base + "_sessions_archive.json"
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
            except Exception as _load_err:
                logger.error("[Memory] Conversation load failed (resetting to empty): %s", _load_err)
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
            if self._should_drop_entry(entry):
                continue
            # Only deduplicate short system-local responses (battery, name, etc.)
            if entry.get("source") in ["system-local", "desktop-local"] and len(content) < 100:
                if content not in seen_content:
                    cleaned.append(entry)
                    seen_content.add(content)
            else:
                cleaned.append(entry)
        
        self.conversation = list(reversed(cleaned))

    def _should_drop_entry(self, entry: Dict) -> bool:
        if entry.get("role") != "assistant":
            return False
        normalized = re.sub(r"(?is)<think\b[^>]*>.*?(?:</think>|$)", " ", entry.get("content", "") or "")
        normalized = re.sub(r"(?i)</?think\b[^>]*>?", " ", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip().lower()
        return all(fragment in normalized for fragment in _GENERIC_ASSISTANT_BOILERPLATE)

    def _sanitize_content(self, content: str) -> str:
        """Strip wake-word-only turns, wake-word prefixes, and identity-probing fragments."""
        text = str(content or "").strip()
        if not text:
            return ""
        lowered = text.lower()

        # Build deduplicated set of wake words to check/strip
        wake_words = set()
        for w in getattr(Config, "WAKE_WORDS", []):
            normalized = str(w).strip().lower()
            if normalized:
                wake_words.add(normalized)
        for wake in (
            getattr(Config, "PUBLIC_WAKE_WORD", "iris"),
            getattr(Config, "ADMIN_WAKE_WORD", "aletheia"),
        ):
            normalized = str(wake).strip().lower()
            if normalized:
                wake_words.add(normalized)

        # Drop pure wake-word-only turns (e.g. "iris", "hey iris", "aletheia", "hey aletheia")
        for wake in sorted(wake_words, key=len, reverse=True):
            if re.fullmatch(rf"(?:hey\s+)?{re.escape(wake)}[,!?.:;]*", text, flags=re.IGNORECASE):
                return ""

        # Strip wake-word prefix from content, including punctuated forms ("iris, open file").
        for wake in sorted(wake_words, key=len, reverse=True):
            match = re.match(
                rf"^(?:hey\s+)?{re.escape(wake)}(?:[,!?.:;]+|\s+)\s*(.+)$",
                text,
                flags=re.IGNORECASE,
            )
            if not match:
                continue
            text = match.group(1).strip()
            lowered = text.lower()
            break

        # Drop identity-probing fragments
        identity_probes = {
            "what is your name",
            "who are you",
            "are you iris",
            "are you aletheia",
            "what are you",
        }
        if lowered in identity_probes:
            return ""

        return text

    def add(self, role: str, content: str, source: str = None):
        """Adds a turn, cleans duplicates, and triggers a save."""
        # Ensure role is always 'user' or 'assistant' for API compatibility
        normalized_role = "assistant" if role in ["assistant", "iris"] else "user"

        content = self._sanitize_content(content)
        if not content:
            return

        entry = {
            "role": normalized_role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        }
        if source: entry["source"] = source
        if self._should_drop_entry(entry):
            return

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

    # ── Long-term Session Archive ────────────────────────────────────────────

    def archive_session(self, max_turns: int = 30) -> None:
        """Snapshot the current conversation into the sessions archive so it
        can be recalled in a future session.  Only saves if there are at least
        2 user turns — single-turn sessions are usually noise."""
        user_turns = [e for e in self.conversation if e.get("role") == "user"]
        if len(user_turns) < 2:
            return  # Nothing worth archiving
        # Extract the user messages as topic hints (first 15 words each).
        topic_hints = []
        for e in user_turns[:10]:
            snippet = re.sub(r"\s+", " ", e.get("content", "")).strip()
            if snippet:
                topic_hints.append(" ".join(snippet.split()[:15]))
        entry = {
            "timestamp": datetime.now().isoformat(),
            "session_start": self.session_start,
            "topic_hints": topic_hints,
            "turns": self.conversation[-max_turns:],
        }
        # Load existing archive, append, keep last 20 sessions, save.
        try:
            if os.path.exists(self._sessions_archive_file):
                with open(self._sessions_archive_file, "r", encoding="utf-8") as f:
                    archive = json.load(f)
            else:
                archive = {"sessions": []}
            archive["sessions"].append(entry)
            archive["sessions"] = archive["sessions"][-20:]  # Cap at 20 sessions
            with open(self._sessions_archive_file, "w", encoding="utf-8") as f:
                json.dump(archive, f, indent=2)
        except OSError as e:
            import sys
            print(f"[Memory] archive_session OSError: {e}", file=sys.stderr)

    def load_recent_sessions(self, n: int = 3) -> str:
        """Return a human-readable summary of the last *n* archived sessions,
        suitable for injecting into the system prompt when the user asks IRIS
        to recall a previous conversation."""
        if not os.path.exists(self._sessions_archive_file):
            return ""
        try:
            with open(self._sessions_archive_file, "r", encoding="utf-8") as f:
                archive = json.load(f)
        except Exception as _arc_err:
            logger.warning("[Memory] Session archive load failed: %s", _arc_err)
            return ""
        sessions = archive.get("sessions", [])
        if not sessions:
            return ""
        recent = sessions[-n:]
        lines = []
        for idx, sess in enumerate(reversed(recent), start=1):
            ts = sess.get("session_start") or sess.get("timestamp", "unknown date")
            hints = sess.get("topic_hints", [])
            lines.append(f"Session {idx} ({ts}):")
            # Include the full turns as a condensed Q&A (up to 12 turns)
            for turn in sess.get("turns", [])[:12]:
                role = turn.get("role", "user")
                label = "User" if role == "user" else "IRIS"
                content = re.sub(r"\s+", " ", turn.get("content", "")).strip()
                if content:
                    lines.append(f"  {label}: {content[:200]}")
            if not sess.get("turns"):
                # Fall back to topic hints if no turns stored
                for hint in hints[:5]:
                    lines.append(f"  - {hint}")
            lines.append("")
        return "\n".join(lines).strip()
