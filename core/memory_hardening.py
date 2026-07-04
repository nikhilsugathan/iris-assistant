"""Durability and cleanup hardening for IRIS conversation memory."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime


def apply_memory_hardening(memory_module) -> None:
    memory_cls = getattr(memory_module, "Memory", None)
    if memory_cls is None or getattr(memory_cls, "_iris_memory_hardening_applied", False):
        return

    boilerplate = tuple(getattr(memory_module, "_GENERIC_ASSISTANT_BOILERPLATE", ()))
    atomic_write = memory_module._atomic_json_write

    def _should_drop_entry_hardened(self, entry):
        if entry.get("role") != "assistant":
            return False
        normalized = re.sub(
            r"(?is)<think\b[^>]*>.*?(?:</think>|$)",
            " ",
            entry.get("content", "") or "",
        )
        normalized = re.sub(r"(?i)</?think\b[^>]*>?", " ", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip().lower()
        return any(fragment in normalized for fragment in boilerplate)

    def _save_serialized(self):
        with self._lock:
            payload = {
                "last_updated": datetime.now().isoformat(),
                "conversation": list(self.conversation),
            }
            try:
                atomic_write(self.memory_file, payload)
            except OSError as exc:
                memory_module.logger.exception(
                    "[Memory] could not save to %s: %s",
                    self.memory_file,
                    exc,
                )

    def _archive_session_serialized(self, max_turns: int = 30) -> None:
        with self._lock:
            conversation_snapshot = list(self.conversation)
            user_turns = [entry for entry in conversation_snapshot if entry.get("role") == "user"]
            if len(user_turns) < 2:
                return

            topic_hints = []
            for entry in user_turns[:10]:
                snippet = re.sub(r"\s+", " ", entry.get("content", "") or "").strip()
                if snippet:
                    topic_hints.append(" ".join(snippet.split()[:15]))

            archive_entry = {
                "timestamp": datetime.now().isoformat(),
                "session_start": self.session_start,
                "topic_hints": topic_hints,
                "turns": conversation_snapshot[-max_turns:],
            }

            try:
                if os.path.exists(self._sessions_archive_file):
                    with open(self._sessions_archive_file, "r", encoding="utf-8") as handle:
                        archive = json.load(handle)
                else:
                    archive = {"sessions": []}

                if not isinstance(archive, dict):
                    archive = {"sessions": []}
                sessions = archive.get("sessions")
                if not isinstance(sessions, list):
                    sessions = []
                sessions.append(archive_entry)
                archive["sessions"] = sessions[-20:]
                atomic_write(self._sessions_archive_file, archive)
            except Exception as exc:
                memory_module.logger.exception("[Memory] archive_session failed: %s", exc)
                self._rotate_corrupt_file(self._sessions_archive_file)

    def _load_recent_sessions_serialized(self, n: int = 3) -> str:
        with self._lock:
            if not os.path.exists(self._sessions_archive_file):
                return ""
            try:
                with open(self._sessions_archive_file, "r", encoding="utf-8") as handle:
                    archive = json.load(handle)
            except Exception as exc:
                memory_module.logger.warning("[Memory] Session archive load failed: %s", exc)
                return ""

            sessions = archive.get("sessions", []) if isinstance(archive, dict) else []
            if not sessions:
                return ""
            recent = list(sessions[-max(int(n), 0):]) if n else []

        lines = []
        for index, session in enumerate(reversed(recent), start=1):
            timestamp = session.get("session_start") or session.get("timestamp", "unknown date")
            hints = session.get("topic_hints", [])
            lines.append(f"Session {index} ({timestamp}):")
            turns = session.get("turns", [])
            for turn in turns[:12]:
                role = turn.get("role", "user")
                label = "User" if role == "user" else "IRIS"
                content = re.sub(r"\s+", " ", turn.get("content", "") or "").strip()
                if content:
                    lines.append(f"  {label}: {content[:200]}")
            if not turns:
                for hint in hints[:5]:
                    lines.append(f"  - {hint}")
            lines.append("")
        return "\n".join(lines).strip()

    memory_cls._should_drop_entry = _should_drop_entry_hardened
    memory_cls._save = _save_serialized
    memory_cls.archive_session = _archive_session_serialized
    memory_cls.load_recent_sessions = _load_recent_sessions_serialized
    memory_cls._iris_memory_hardening_applied = True
