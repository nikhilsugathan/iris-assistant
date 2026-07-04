from __future__ import annotations

import json
import os
import tempfile
import threading


def test_generic_boilerplate_is_dropped_individually():
    import core  # noqa: F401
    from core.memory import Memory

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as handle:
        path = handle.name
    try:
        memory = Memory(path)
        memory.add("assistant", "Hello! How can I assist you today?")
        assert memory.conversation == []
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def test_concurrent_memory_adds_persist_all_turns():
    import core  # noqa: F401
    from core.memory import Memory

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as handle:
        path = handle.name

    memory = Memory(path)
    workers = 4
    turns_per_worker = 20

    def writer(worker_id: int) -> None:
        for index in range(turns_per_worker):
            memory.add("user", f"worker-{worker_id}-turn-{index}")

    threads = [
        threading.Thread(target=writer, args=(worker_id,))
        for worker_id in range(workers)
    ]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        assert all(not thread.is_alive() for thread in threads)
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)

        persisted = {
            entry["content"]
            for entry in payload.get("conversation", [])
            if entry.get("role") == "user"
        }
        expected = {
            f"worker-{worker_id}-turn-{index}"
            for worker_id in range(workers)
            for index in range(turns_per_worker)
        }
        assert expected <= persisted
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
