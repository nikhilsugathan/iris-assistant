"""IRIS boot sequence timeout doctor.

Run from project root:
    python tools\doctor_boot_sequence.py

This checks the expensive startup stages separately and reports which one blocks.
It does not launch the full IRIS loop.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import queue
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _run_stage(name: str, output: mp.Queue) -> None:
    started = time.monotonic()
    try:
        os.environ.setdefault("IRIS_DISABLE_VOICE_IO", "true")
        os.environ.setdefault("SPEAK_IN_TEXT_MODE", "false")
        import core  # noqa: F401
        from config import Config

        if name == "config_validate":
            Config.validate()
        elif name == "memory_init":
            from core.memory import Memory
            Memory(Config.MEMORY_FILE)
        elif name == "memory_archive_save":
            from core.memory import Memory
            memory = Memory(Config.MEMORY_FILE)
            memory.archive_session()
            memory.conversation.clear()
            memory._save()
        elif name == "session_logger":
            from core.session_logger import SessionLogger
            SessionLogger()
        elif name == "brain_init":
            from core.memory import Memory
            from core.brain import Brain
            memory = Memory(Config.MEMORY_FILE)
            brain = Brain(memory)
            output.put((name, "ok", time.monotonic() - started, f"apis={','.join(getattr(brain, 'available_apis', []))} llm_loaded={bool(getattr(brain, 'llm', None))}"))
            return
        elif name == "voice_text_init":
            from core.voice import Voice
            voice = Voice(text_mode=True)
            output.put((name, "ok", time.monotonic() - started, f"io_disabled={getattr(voice, 'io_disabled', None)}"))
            return
        elif name == "main_import":
            import main  # noqa: F401
        else:
            raise ValueError(f"unknown stage: {name}")
        output.put((name, "ok", time.monotonic() - started, ""))
    except Exception as exc:
        output.put((name, "error", time.monotonic() - started, f"{type(exc).__name__}: {exc}"))


def _check_stage(name: str, timeout: float) -> tuple[str, str, float, str]:
    output: mp.Queue = mp.Queue()
    process = mp.Process(target=_run_stage, args=(name, output), daemon=True)
    process.start()
    process.join(timeout)
    if process.is_alive():
        process.terminate()
        process.join(2.0)
        return name, "timeout", timeout, f"stage exceeded {timeout:.1f}s"
    try:
        return output.get_nowait()
    except queue.Empty:
        return name, "error", 0.0, f"process exited with code {process.exitcode} without result"


def main() -> int:
    print("IRIS Boot Sequence Doctor")
    print("=" * 60)
    stages = [
        ("config_validate", 5.0),
        ("memory_init", 5.0),
        ("memory_archive_save", 8.0),
        ("session_logger", 5.0),
        ("brain_init", 10.0),
        ("voice_text_init", 8.0),
        ("main_import", 10.0),
    ]
    failed = False
    for name, timeout in stages:
        stage, status, elapsed, detail = _check_stage(name, timeout)
        print(f"{stage:<24} {status:<8} {elapsed:>6.2f}s  {detail}")
        if status != "ok":
            failed = True
    if failed:
        print("Doctor result: one or more boot stages failed or timed out.")
        return 1
    print("Doctor result: individual boot stages passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
