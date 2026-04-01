# -*- coding: utf-8 -*-
"""
IRIS Log Cleaner — tools/clear_logs.py
=======================================
Resets iris_actions.log and logs/crash.log to empty files.

Usage (from the project root):
    python tools/clear_logs.py

Run this whenever you want a completely clean operational slate.
Both files are truncated to zero bytes but left on disk so the
runtime never hits a FileNotFoundError on first write.
"""

import os

# Resolve paths relative to this file so the script works from any cwd
_ROOT   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOGS   = os.path.join(_ROOT, "logs")

TARGETS = [
    os.path.join(_ROOT, "iris_actions.log"),
    os.path.join(_LOGS, "crash.log"),
]


def clear_logs() -> None:
    os.makedirs(_LOGS, exist_ok=True)

    for path in TARGETS:
        with open(path, "w", encoding="utf-8") as f:
            pass   # truncate to zero bytes
        print(f"  [✓] Cleared: {path}")

    print("\nAll IRIS logs cleared. Clean slate established.")


if __name__ == "__main__":
    print("Clearing IRIS operational logs...\n")
    clear_logs()