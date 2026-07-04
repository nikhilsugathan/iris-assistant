"""Durability and cleanup hardening for IRIS conversation memory."""

from __future__ import annotations

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
        # Keep snapshot creation and atomic replace in one critical section.
        # Releasing the lock before the replace allowed an older writer to finish
        # after a newer writer and overwrite the newer conversation state.
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

    memory_cls._should_drop_entry = _should_drop_entry_hardened
    memory_cls._save = _save_serialized
    memory_cls._iris_memory_hardening_applied = True
