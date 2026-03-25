"""
IRIS memory persistence smoke test.

Verifies that debounced background saving still writes conversation history to
disk and that shutdown flushing preserves the latest turns.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import time

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from core.memory import Memory


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    smoke_dir = WORKSPACE / "build" / "smoke"
    smoke_dir.mkdir(parents=True, exist_ok=True)
    memory_path = smoke_dir / "iris_memory_smoke.json"
    if memory_path.exists():
        memory_path.unlink()

    memory = Memory(str(memory_path))
    try:
        memory.add("user", "memory smoke request")
        memory.add("assistant", "memory smoke response", source="local")
        time.sleep(0.35)
        assert_true(memory_path.exists(), "Memory file was not written after the debounce interval.")

        payload = json.loads(memory_path.read_text(encoding="utf-8"))
        conversation = payload.get("conversation", [])
        assert_true(len(conversation) >= 2, "Debounced memory save did not persist the conversation turns.")

        memory.add("user", "shutdown flush request")
        memory.close()

        payload = json.loads(memory_path.read_text(encoding="utf-8"))
        conversation = payload.get("conversation", [])
        assert_true(
            any(item.get("content") == "shutdown flush request" for item in conversation),
            "Memory shutdown flush did not preserve the latest turn.",
        )

        print("PASS: IRIS memory persistence smoke test completed.")
    finally:
        try:
            memory.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
