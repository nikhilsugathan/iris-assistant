"""Runtime configuration hardening for IRIS.

This keeps existing config.py compatible while correcting unsafe or unstable
runtime defaults before the rest of core is instantiated.
"""

from __future__ import annotations

import os


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_missing(name: str) -> bool:
    return os.getenv(name) in {None, ""}


def apply_config_hardening() -> None:
    from config import Config

    # Voice defaults: balanced is the normal operating mode. It allows filtered
    # control-word interruption but avoids the raw secondary RMS stream unless
    # explicitly requested through realtime mode.
    Config.VOICE_PLAYBACK_MODE = os.getenv("VOICE_PLAYBACK_MODE", "balanced").strip().lower() or "balanced"
    Config.TTS_FAST_CUT_ENABLED = _env_bool("TTS_FAST_CUT_ENABLED", False)

    if _env_missing("COMMAND_RMS_THRESHOLD"):
        Config.COMMAND_RMS_THRESHOLD = 650
    if _env_missing("BARGE_IN_RMS_THRESHOLD"):
        Config.BARGE_IN_RMS_THRESHOLD = 2200
    if _env_missing("WAKE_RMS_THRESHOLD"):
        Config.WAKE_RMS_THRESHOLD = 400

    # Prefer Edge when Piper is not explicitly configured. This avoids auto mode
    # drifting into multiple TTS paths while voice reliability is being tested.
    if getattr(Config, "TTS_ENGINE", "auto") == "auto":
        piper_model = str(getattr(Config, "PIPER_MODEL_PATH", "") or "").strip()
        if not (piper_model and os.path.exists(piper_model)):
            Config.TTS_ENGINE = "edge"

    # Current practical cloud routing defaults. Local LLM remains available as
    # the offline-first path; Groq is the recommended fast voice fallback.
    if _env_missing("GROQ_MODEL"):
        Config.GROQ_MODEL = "openai/gpt-oss-20b"
    if _env_missing("GROQ_FAST_MODEL"):
        Config.GROQ_FAST_MODEL = "llama-3.1-8b-instant"
    if _env_missing("GROQ_QUALITY_MODEL"):
        Config.GROQ_QUALITY_MODEL = "llama-3.3-70b-versatile"
    if _env_missing("GROQ_REASONING_MODEL"):
        Config.GROQ_REASONING_MODEL = "openai/gpt-oss-120b"
    if _env_missing("GROQ_STT_MODEL"):
        Config.GROQ_STT_MODEL = "whisper-large-v3-turbo"
    if _env_missing("GEMINI_MODEL"):
        Config.GEMINI_MODEL = "gemini-3.5-flash"
    if _env_missing("CLAUDE_MODEL"):
        Config.CLAUDE_MODEL = "claude-sonnet-4-6"

    Config.REQUIRE_ADMIN_APPROVAL = True
    Config.ALLOW_ADMIN_SAFETY_BYPASS = False

    if _env_bool("IRIS_HARDEN_PERSONA", True):
        Config.ALETHEIA_PERSONA = """You are Aletheia, the privileged operator layer behind Iris. Stay in character as Aletheia for every response.

Identity:
- Aletheia is the deeper reasoning and operator layer, not a reckless bypass mode.
- You may coordinate advanced diagnostics and admin-sensitive workflows only inside explicit approval boundaries.
- You never claim unrestricted authority, hidden clearance, or safety exemption.

Behavior:
- Be concise, direct, and technically precise.
- Report real OS output and real errors. Never invent success.
- If a task is unclear, ask exactly one specific question.
- If an action is sensitive, destructive, privileged, or irreversible, require explicit confirmation.
- Overdrive increases focus and reasoning depth, but never bypasses hard safety constraints.

Filesystem honesty:
- Never say Done unless the OS has confirmed the requested state.
- Never invent permission or clearance messages.
- If a filesystem action fails, report the actual system error.
"""
