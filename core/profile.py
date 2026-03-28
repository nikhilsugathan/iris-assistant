"""
IRIS User Profile Memory
=======================
Stores durable, user-approved memory separate from transcript:
- preferences ("remember that I like concise answers")
- facts the user asked to remember ("my laptop is called ...")
- goals ("I'm training for a marathon")

This is intentionally simple (JSON file) as a first step toward IRIS-like continuity.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from config import Config
from core.runtime_log import log_runtime


@dataclass
class ProfileUpdate:
    message: str
    changed: bool = False


class UserProfile:
    def __init__(self, path: str | None = None):
        default_path = Path(getattr(Config, "DATA_DIR", Path.cwd())) / "iris_profile.json"
        self.path = Path(path).expanduser() if path else default_path
        self._lock = threading.Lock()
        self._data = {"preferences": {}, "facts": {}, "goals": [], "updated_at": None}
        self._load()

    def _load(self) -> None:
        try:
            if self.path.exists():
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            log_runtime("profile_load_failed", level="WARNING", error=str(exc), path=str(self.path))

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._data["updated_at"] = datetime.now().isoformat(timespec="seconds")
            self.path.write_text(json.dumps(self._data, indent=2, ensure_ascii=True), encoding="utf-8")
        except Exception as exc:
            log_runtime("profile_save_failed", level="WARNING", error=str(exc), path=str(self.path))

    def memory_instructions(self) -> str:
        """A short snippet to inject into system prompt when useful."""
        with self._lock:
            prefs = self._data.get("preferences", {}) or {}
            facts = self._data.get("facts", {}) or {}
            goals = self._data.get("goals", []) or []

        lines: list[str] = []
        if prefs:
            lines.append("User preferences:")
            for key, value in list(prefs.items())[:12]:
                lines.append(f"- {key}: {value}")
        if goals:
            lines.append("User goals:")
            for goal in goals[:8]:
                lines.append(f"- {goal}")
        if facts:
            lines.append("User facts:")
            for key, value in list(facts.items())[:12]:
                lines.append(f"- {key}: {value}")
        return "\n".join(lines).strip()

    def handle_input(self, user_input: str) -> ProfileUpdate:
        """
        Lightweight parser for explicit memory commands.
        Examples:
        - "remember that I like short answers"
        - "remember my laptop name is Nova"
        - "forget my laptop name"
        - "what do you remember about me"
        """
        text = (user_input or "").strip()
        lowered = text.lower()

        if "what do you remember" in lowered or "show my preferences" in lowered:
            snapshot = self.memory_instructions()
            if snapshot:
                return ProfileUpdate(message=snapshot, changed=False)
            return ProfileUpdate(message="I don't have any saved preferences yet.", changed=False)

        if lowered.startswith("forget "):
            key = text[len("forget ") :].strip().strip(".")
            if not key:
                return ProfileUpdate(message="Tell me what to forget.", changed=False)
            with self._lock:
                removed = False
                for bucket in ("preferences", "facts"):
                    if key in (self._data.get(bucket) or {}):
                        self._data[bucket].pop(key, None)
                        removed = True
                if key in (self._data.get("goals") or []):
                    self._data["goals"] = [g for g in self._data.get("goals", []) if g != key]
                    removed = True
                if removed:
                    self._save()
                    log_runtime("profile_forget", key=key)
                    return ProfileUpdate(message=f"Done. I forgot '{key}'.", changed=True)
            return ProfileUpdate(message=f"I don't have '{key}' saved.", changed=False)

        if lowered.startswith("remember "):
            payload = text[len("remember ") :].strip().strip(".")
            if not payload:
                return ProfileUpdate(message="Tell me what to remember.", changed=False)

            # Heuristics: "my X is Y" -> facts; "i like/prefer" -> preferences; otherwise store as fact.
            changed = False
            with self._lock:
                if payload.lower().startswith("that "):
                    payload = payload[5:].strip()
                if " i prefer " in f" {payload.lower()} " or payload.lower().startswith(("i prefer ", "i like ")):
                    self._data.setdefault("preferences", {})
                    self._data["preferences"]["style"] = payload
                    changed = True
                elif payload.lower().startswith(("my ", "i am ", "i'm ")):
                    self._data.setdefault("facts", {})
                    key = payload.split(" is ", 1)[0].strip()
                    value = payload.split(" is ", 1)[1].strip() if " is " in payload else payload
                    self._data["facts"][key] = value
                    changed = True
                elif payload.lower().startswith(("goal: ", "my goal is ", "i want to ")):
                    self._data.setdefault("goals", [])
                    goal = payload.split(":", 1)[-1].strip()
                    if goal and goal not in self._data["goals"]:
                        self._data["goals"].append(goal)
                    changed = True
                else:
                    self._data.setdefault("facts", {})
                    self._data["facts"][payload] = True
                    changed = True

                if changed:
                    self._save()
                    log_runtime("profile_remember", note=payload[:200])
                    return ProfileUpdate(message="Done. I'll remember that.", changed=True)

        return ProfileUpdate(message="If you want me to remember something, say 'remember ...' or 'forget ...'.", changed=False)

