"""IRIS startup preflight doctor.

Run from project root:
    python tools\doctor_startup.py
"""

from __future__ import annotations

import importlib
import os
import sys
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

REQUIRED_CONFIG_ATTRS = [
    "PROJECT_ROOT",
    "PUBLIC_NAME",
    "SYSTEM_NAME",
    "INNER_CODENAME",
    "COUNCIL_NAME",
    "SYSTEM_MOTTO",
    "VERSION",
    "MEMORY_FILE",
    "MAX_MEMORY_TURNS",
    "RUNBOOK_MODE",
    "ENABLE_AUTO_SYNC",
    "validate",
    "VOICE_NAME",
    "VOICE_RATE",
    "TTS_ENGINE",
    "SPEAK_IN_TEXT_MODE",
    "GROQ_API_KEY",
    "GROQ_STT_MODEL",
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "WAKE_RMS_THRESHOLD",
    "COMMAND_RMS_THRESHOLD",
    "BARGE_IN_RMS_THRESHOLD",
    "PREFERRED_MIC_NAME",
    "MIC_DEVICE_INDEX",
]


def main() -> int:
    print("IRIS Startup Doctor")
    print("=" * 60)
    os.environ.setdefault("IRIS_DISABLE_VOICE_IO", "true")

    try:
        import core  # noqa: F401
        from config import Config
    except Exception as exc:
        print(f"core/config import: failed - {exc}")
        traceback.print_exc()
        return 2

    missing = [name for name in REQUIRED_CONFIG_ATTRS if not hasattr(Config, name)]
    if missing:
        print("config symbols: failed")
        for name in missing:
            print(f"  missing: {name}")
        return 1
    print("config symbols: ok")

    try:
        result = Config.validate()
        print(f"Config.validate: ok ({result})")
    except Exception as exc:
        print(f"Config.validate: failed - {exc}")
        traceback.print_exc()
        return 1

    for relative in ["logs", "models", os.path.join("models", ".cache"), "exports"]:
        path = Path(getattr(Config, "PROJECT_ROOT")) / relative
        print(f"dir {relative}: {'ok' if path.exists() else 'missing'}")

    try:
        imported_main = importlib.import_module("main")
        print("main import: ok")
        print(f"banner: {'ok' if getattr(imported_main, 'BANNER', '') else 'empty'}")
    except Exception as exc:
        print(f"main import: failed - {exc}")
        traceback.print_exc()
        return 1

    print("Doctor result: startup preflight passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
