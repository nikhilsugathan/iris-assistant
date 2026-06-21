"""Optional runtime configuration hardening for IRIS."""

from __future__ import annotations

import os


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def apply_config_hardening() -> None:
    """Apply only lightweight compatibility defaults.

    The full hardening pass is kept opt-in so normal startup follows the user's
    .env values exactly and avoids surprising runtime changes during voice tests.
    """
    from config import Config

    Config.VOICE_PLAYBACK_MODE = os.getenv("VOICE_PLAYBACK_MODE", "balanced").strip().lower() or "balanced"
    Config.TTS_FAST_CUT_ENABLED = _env_bool("TTS_FAST_CUT_ENABLED", False)

    if _env_bool("IRIS_APPLY_RUNTIME_HARDENING", False):
        Config.REQUIRE_ADMIN_APPROVAL = True
        Config.ALLOW_ADMIN_SAFETY_BYPASS = False
