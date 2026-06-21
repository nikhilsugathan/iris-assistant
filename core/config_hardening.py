"""Optional runtime configuration defaults for IRIS."""

from __future__ import annotations

import os


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _ensure_attr(obj, name: str, value) -> None:
    if not hasattr(obj, name):
        setattr(obj, name, value)


def _compat_validate() -> bool:
    from config import Config

    project_root = getattr(Config, "PROJECT_ROOT", os.getcwd())
    for relative in ["logs", "models", os.path.join("models", ".cache"), "exports"]:
        os.makedirs(os.path.join(project_root, relative), exist_ok=True)
    return True


def _apply_startup_defaults(Config) -> None:
    _ensure_attr(Config, "PROJECT_ROOT", os.getcwd())
    _ensure_attr(Config, "PUBLIC_NAME", os.getenv("IRIS_PUBLIC_NAME", "Iris"))
    _ensure_attr(Config, "SYSTEM_NAME", os.getenv("IRIS_SYSTEM_NAME", "IRIS"))
    _ensure_attr(Config, "INNER_CODENAME", os.getenv("IRIS_INNER_CODENAME", "Internal"))
    _ensure_attr(Config, "COUNCIL_NAME", os.getenv("IRIS_COUNCIL_NAME", "Internal Council"))
    _ensure_attr(Config, "SYSTEM_MOTTO", "Intelligence. Redefined.")
    _ensure_attr(Config, "VERSION", "5.2.5-STABLE")
    _ensure_attr(Config, "MEMORY_FILE", os.path.join(Config.PROJECT_ROOT, "iris_memory.json"))
    _ensure_attr(Config, "MAX_MEMORY_TURNS", 200)
    _ensure_attr(Config, "RUNBOOK_MODE", False)
    _ensure_attr(Config, "ENABLE_AUTO_SYNC", False)
    _ensure_attr(Config, "STT_LANGUAGE", os.getenv("STT_LANGUAGE", "auto"))
    _ensure_attr(Config, "IRIS_LOCK_TTS_VOICE", True)
    _ensure_attr(Config, "IRIS_MULTILINGUAL_TTS", False)
    _ensure_attr(Config, "validate", _compat_validate)


def apply_config_hardening() -> None:
    """Apply lightweight startup defaults and runtime observability."""
    from config import Config

    _apply_startup_defaults(Config)

    Config.STT_LANGUAGE = os.getenv("STT_LANGUAGE", getattr(Config, "STT_LANGUAGE", "auto") or "auto")
    Config.IRIS_LOCK_TTS_VOICE = _env_bool("IRIS_LOCK_TTS_VOICE", True)
    Config.IRIS_MULTILINGUAL_TTS = _env_bool("IRIS_MULTILINGUAL_TTS", False)
    Config.VOICE_PLAYBACK_MODE = os.getenv("VOICE_PLAYBACK_MODE", "balanced").strip().lower() or "balanced"
    Config.TTS_FAST_CUT_ENABLED = _env_bool("TTS_FAST_CUT_ENABLED", False)

    if _env_bool("IRIS_OBSERVABILITY_ENABLED", True):
        try:
            from core.observability import install_observability

            install_observability()
        except Exception:
            pass

    if _env_bool("IRIS_APPLY_RUNTIME_HARDENING", False):
        Config.REQUIRE_ADMIN_APPROVAL = True
        Config.ALLOW_ADMIN_SAFETY_BYPASS = False
