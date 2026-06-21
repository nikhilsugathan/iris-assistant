"""IRIS runtime doctor.

Run from project root:
    python tools\doctor_runtime.py

The report avoids printing API key values.
"""

from __future__ import annotations

import importlib.util
import os
import platform
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _env(name: str, default: str = "") -> str:
    value = os.getenv(name, default)
    return "" if value is None else str(value)


def _secret_state(name: str) -> str:
    return "set" if _env(name).strip() else "missing"


def _print(title: str, value) -> None:
    print(f"{title:<34} {value}")


def main() -> int:
    from config import Config
    try:
        import core  # applies runtime hardening without instantiating Voice
    except Exception as exc:
        print(f"core import failed: {exc}")
        return 2

    print("IRIS Runtime Doctor")
    print("=" * 60)
    _print("Python", sys.version.split()[0])
    _print("Platform", platform.platform())
    _print("Project root", PROJECT_ROOT)
    _print("Config version", getattr(Config, "VERSION", "unknown"))
    print()

    print("Voice configuration")
    print("-" * 60)
    _print("TTS_ENGINE", getattr(Config, "TTS_ENGINE", ""))
    _print("VOICE_PLAYBACK_MODE", getattr(Config, "VOICE_PLAYBACK_MODE", _env("VOICE_PLAYBACK_MODE", "balanced")))
    _print("TTS_FAST_CUT_ENABLED", getattr(Config, "TTS_FAST_CUT_ENABLED", False))
    _print("VOICE_NAME", getattr(Config, "VOICE_NAME", ""))
    _print("VOICE_RATE", getattr(Config, "VOICE_RATE", ""))
    _print("WAKE_RMS_THRESHOLD", getattr(Config, "WAKE_RMS_THRESHOLD", ""))
    _print("COMMAND_RMS_THRESHOLD", getattr(Config, "COMMAND_RMS_THRESHOLD", ""))
    _print("BARGE_IN_RMS_THRESHOLD", getattr(Config, "BARGE_IN_RMS_THRESHOLD", ""))
    _print("PREFERRED_MIC_NAME", getattr(Config, "PREFERRED_MIC_NAME", ""))
    print()

    print("Model routing")
    print("-" * 60)
    _print("LOCAL_MODEL_PATH", getattr(Config, "LOCAL_MODEL_PATH", ""))
    _print("Local model exists", Path(getattr(Config, "LOCAL_MODEL_PATH", "")).exists())
    _print("GROQ_MODEL", getattr(Config, "GROQ_MODEL", ""))
    _print("GROQ_STT_MODEL", getattr(Config, "GROQ_STT_MODEL", ""))
    _print("GEMINI_MODEL", getattr(Config, "GEMINI_MODEL", ""))
    _print("CLAUDE_MODEL", getattr(Config, "CLAUDE_MODEL", ""))
    print()

    print("API key presence")
    print("-" * 60)
    for key in ["GROQ_API_KEY", "GEMINI_API_KEY", "CLAUDE_API_KEY", "OPENWEATHER_API_KEY"]:
        _print(key, _secret_state(key))
    print()

    print("Dependency imports")
    print("-" * 60)
    deps = [
        "dotenv", "requests", "rich", "edge_tts", "pygame", "speech_recognition",
        "pyaudio", "numpy", "scipy", "groq", "anthropic", "google.generativeai",
        "llama_cpp", "sounddevice", "psutil", "mss", "PIL",
    ]
    missing = []
    for dep in deps:
        ok = _has_module(dep)
        _print(dep, "ok" if ok else "missing")
        if not ok:
            missing.append(dep)
    print()

    print("Microphones")
    print("-" * 60)
    if _has_module("speech_recognition"):
        try:
            import speech_recognition as sr
            names = sr.Microphone.list_microphone_names()
            if not names:
                print("No microphones reported by PyAudio.")
            for idx, name in enumerate(names):
                marker = ""
                preferred = str(getattr(Config, "PREFERRED_MIC_NAME", "") or "").lower()
                if preferred and preferred in str(name).lower():
                    marker = "  <-- preferred match"
                print(f"[{idx}] {name}{marker}")
        except Exception as exc:
            print(f"Microphone listing failed: {exc}")
    else:
        print("speech_recognition missing; microphone listing skipped.")
    print()

    if missing:
        print("Missing dependencies detected. Run:")
        print("python -m pip install -r requirements.txt")
        return 1

    print("Doctor result: basic runtime dependencies look available.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
