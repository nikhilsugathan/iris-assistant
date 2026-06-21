"""
IRIS Memory Module v4.7
=======================
Features:
- Automatic Role Normalization (iris -> assistant)
- Real-time Content De-duplication (Removes system-stat bloat)
- Atomic persistent JSON storage
"""

import json
import os
import re
import tempfile
import threading
from datetime import datetime
from typing import List, Dict
from config import Config
from core.logger import get_logger

logger = get_logger("Memory")

_GENERIC_ASSISTANT_BOILERPLATE = (
    "how can i assist you today",
    "please let me know your task so i can help you effectively",
)


def _atomic_json_write(path: str, payload: dict) -> None:
    """Write JSON atomically to avoid partially-written memory files."""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


class Memory:
    def __init__(self, memory_file: str):
        if os.path.isabs(memory_file):
            self.memory_file = memory_file
        else:
            self.memory_file = os.path.join(Config.PROJECT_ROOT, memory_file)
        _base = os.path.splitext(self.memory_file)[0]
        self._sessions_archive_file = _base + "_sessions_archive.json"
        self._lock = threading.RLock()
        self.conversation: List[Dict] = []
        self.session_start = datetime.now().strftime("%Y-%m-%d %H:%M")
        self._load()

    def _rotate_corrupt_file(self, path: str) -> None:
        if not os.path.exists(path):
            return
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        corrupt_path = f"{path}.corrupt-{stamp}.json"
        try:
            os.replace(path, corrupt_path)
            logger.error("[Memory] Rotated corrupt file to %s", corrupt_path)
        except OSError as exc:
            logger.exception("[Memory] Failed to rotate corrupt file %s: %s", path, exc)

    def _load(self):
        """Load and normalize existing memory from disk."""
        with self._lock:
            if os.path.exists(self.memory_file):
                try:
                    with open(self.memory_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        raw_conv = data.get("conversation", [])

                        for entry in raw_conv:
                            if entry.get("role") == "iris":
                                entry["role"] = "assistant"

                        self.conversation = raw_conv if isinstance(raw_conv, list) else []
                        self._self_clean()
                except Exception as _load_err:
                    logger.exception("[Memory] Conversation load failed; resetting to empty: %s", _load_err)
                    self._rotate_corrupt_file(self.memory_file)
                    self.conversation = []

    def _save(self):
        """Persist memory to disk with atomic write protection."""
        with self._lock:
            payload = {
                "last_updated": datetime.now().isoformat(),
                "conversation": list(self.conversation),
            }
        try:
            _atomic_json_write(self.memory_file, payload)
        except OSError as e:
            logger.exception("[Memory] could not save to %s: %s", self.memory_file, e)

    def _self_clean(self):
        """DE-DUPLICATION: Removes repeated system stats to save context window space."""
        seen_content = set()
        cleaned = []
        for entry in reversed(self.conversation):
            content = entry.get("content", "")
            if self._should_drop_entry(entry):
                continue
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

        for wake in sorted(wake_words, key=len, reverse=True):
            if re.fullmatch(rf"(?:hey\s+)?{re.escape(wake)}[,!?.:;]*", text, flags=re.IGNORECASE):
                return ""

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
        normalized_role = "assistant" if role in ["assistant", "iris"] else "user"
        content = self._sanitize_content(content)
        if not content:
            return

        with self._lock:
            entry = {
                "role": normalized_role,
                "content": content,
                "timestamp": datetime.now().isoformat(),
            }
            if source:
                entry["source"] = source
            if self._should_drop_entry(entry):
                return

            self.conversation.append(entry)
            if len(self.conversation) > Config.MAX_MEMORY_TURNS:
                self.conversation = self.conversation[-Config.MAX_MEMORY_TURNS:]
            self._self_clean()

        self._save()

    def get_context(self, max_turns: int = None) -> List[Dict]:
        """Retrieve the most recent conversation context."""
        limit = max_turns if max_turns is not None else getattr(Config, "MAX_MEMORY_TURNS", 8)
        with self._lock:
            return list(self.conversation[-limit * 2:])

    def summary(self) -> str:
        with self._lock:
            turns = len([e for e in self.conversation if e.get("role") == "user"])
        return f"{turns} exchanges stored (Memory File: {os.path.basename(self.memory_file)})"

    # ── Long-term Session Archive ────────────────────────────────────────────

    def archive_session(self, max_turns: int = 30) -> None:
        """Snapshot the current conversation into the sessions archive."""
        with self._lock:
            conversation_snapshot = list(self.conversation)
        user_turns = [e for e in conversation_snapshot if e.get("role") == "user"]
        if len(user_turns) < 2:
            return

        topic_hints = []
        for e in user_turns[:10]:
            snippet = re.sub(r"\s+", " ", e.get("content", "")).strip()
            if snippet:
                topic_hints.append(" ".join(snippet.split()[:15]))
        entry = {
            "timestamp": datetime.now().isoformat(),
            "session_start": self.session_start,
            "topic_hints": topic_hints,
            "turns": conversation_snapshot[-max_turns:],
        }

        try:
            if os.path.exists(self._sessions_archive_file):
                with open(self._sessions_archive_file, "r", encoding="utf-8") as f:
                    archive = json.load(f)
            else:
                archive = {"sessions": []}
            if not isinstance(archive, dict):
                archive = {"sessions": []}
            archive.setdefault("sessions", [])
            archive["sessions"].append(entry)
            archive["sessions"] = archive["sessions"][-20:]
            _atomic_json_write(self._sessions_archive_file, archive)
        except Exception as e:
            logger.exception("[Memory] archive_session failed: %s", e)
            self._rotate_corrupt_file(self._sessions_archive_file)

    def load_recent_sessions(self, n: int = 3) -> str:
        """Return a human-readable summary of recent archived sessions."""
        if not os.path.exists(self._sessions_archive_file):
            return ""
        try:
            with open(self._sessions_archive_file, "r", encoding="utf-8") as f:
                archive = json.load(f)
        except Exception as _arc_err:
            logger.warning("[Memory] Session archive load failed: %s", _arc_err)
            return ""
        sessions = archive.get("sessions", []) if isinstance(archive, dict) else []
        if not sessions:
            return ""
        recent = sessions[-n:]
        lines = []
        for idx, sess in enumerate(reversed(recent), start=1):
            ts = sess.get("session_start") or sess.get("timestamp", "unknown date")
            hints = sess.get("topic_hints", [])
            lines.append(f"Session {idx} ({ts}):")
            for turn in sess.get("turns", [])[:12]:
                role = turn.get("role", "user")
                label = "User" if role == "user" else "IRIS"
                content = re.sub(r"\s+", " ", turn.get("content", "")).strip()
                if content:
                    lines.append(f"  {label}: {content[:200]}")
            if not sess.get("turns"):
                for hint in hints[:5]:
                    lines.append(f"  - {hint}")
            lines.append("")
        return "\n".join(lines).strip()
