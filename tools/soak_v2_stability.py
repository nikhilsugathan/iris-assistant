"""
IRIS v2 stability soak runner.

Runs the hardened smoke suite sequentially and stops on the first failure.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import time


WORKSPACE = Path(__file__).resolve().parents[1]
SMOKE_SCRIPTS = [
    "tools/smoke_single_session.py",
    "tools/smoke_local_first.py",
    "tools/smoke_voice_session.py",
    "tools/smoke_gui_shell.py",
    "tools/smoke_terminal_entry.py",
    "tools/smoke_memory_persistence.py",
    "tools/smoke_stt_selection.py",
]


def run_script(path: Path) -> tuple[bool, str, float]:
    started_at = time.perf_counter()
    completed = subprocess.run(
        [sys.executable, str(path)],
        cwd=str(WORKSPACE),
        capture_output=True,
        text=True,
    )
    elapsed = time.perf_counter() - started_at
    output = (completed.stdout or "") + (completed.stderr or "")
    return completed.returncode == 0, output, elapsed


def main() -> None:
    print("IRIS v2 stability soak")
    print(f"Workspace: {WORKSPACE}")
    print("")

    for relative_path in SMOKE_SCRIPTS:
        script_path = WORKSPACE / relative_path
        ok, output, elapsed = run_script(script_path)
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {relative_path} ({elapsed:.1f}s)")
        if ok:
            continue

        print("")
        print(output.rstrip())
        raise SystemExit(1)

    print("")
    print("PASS: IRIS v2 soak suite completed.")


if __name__ == "__main__":
    main()
