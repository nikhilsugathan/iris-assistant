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


def test_concurrent_archive_calls_do_not_lose_sessions():
    import core  # noqa: F401
    from core.memory import Memory

    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "memory.json")
        memory = Memory(path)
        memory.add("user", "first archive turn")
        memory.add("assistant", "first response")
        memory.add("user", "second archive turn")
        memory.add("assistant", "second response")

        workers = 8
        threads = [threading.Thread(target=memory.archive_session) for _ in range(workers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        assert all(not thread.is_alive() for thread in threads)
        with open(memory._sessions_archive_file, "r", encoding="utf-8") as handle:
            archive = json.load(handle)

        assert len(archive["sessions"]) == workers
        assert all(session.get("turns") for session in archive["sessions"])


def test_recent_session_read_returns_archived_turns():
    import core  # noqa: F401
    from core.memory import Memory

    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "memory.json")
        memory = Memory(path)
        memory.add("user", "remember the blue deployment")
        memory.add("assistant", "I will track the deployment context.")
        memory.add("user", "the second point is rollback")
        memory.archive_session()

        recent = memory.load_recent_sessions(n=1)

        assert "remember the blue deployment" in recent
        assert "the second point is rollback" in recent
