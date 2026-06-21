"""Optional runtime configuration hardening for IRIS."""

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
    """Minimal Config.validate replacement used when config.py omits it."""
    from config import Config

    project_root = getattr(Config, "PROJECT_ROOT", os.getcwd())
    for relative in ["logs", "models", os.path.join("models", ".cache"), "exports"]:
        os.makedirs(os.path.join(project_root, relative), exist_ok=True)
    return True


def apply_config_hardening() -> None:
    """Apply lightweight startup defaults and runtime observability."""
    from config import Config

    # Compatibility defaults required by main.py and older modules. These keep
    # startup alive if config.py is edited and a branding value is omitted.
    _ensure_attr(Config, "PUBLIC_NAME", os.getenv("IRIS_PUBLIC_NAME", "Iris"))
    _ensure_attr(Config, "SYSTEM_NAME", os.getenv("IRIS_SYSTEM_NAME", "IRIS"))
    _ensure_attr(Config, "SYSTEM_MOTTO", "Intelligence. Redefined.")
    _ensure_attr(Config, "validate", _compat_validate)

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
