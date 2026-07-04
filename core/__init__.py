from __future__ import annotations

import builtins

_bootstrap_logger = None

try:
    from .logger import get_logger

    _bootstrap_logger = get_logger("CoreBootstrap")
    if not hasattr(builtins, "logger"):
        builtins.logger = get_logger("RuntimeFallback")
except Exception:
    pass


def _bootstrap_failure(stage: str, exc: Exception) -> None:
    if _bootstrap_logger is None:
        return
    try:
        _bootstrap_logger.exception("[CoreBootstrap] stage failed stage=%s error=%s", stage, exc)
    except Exception:
        pass


def _run_stage(stage: str, callback) -> bool:
    try:
        callback()
        return True
    except Exception as exc:
        _bootstrap_failure(stage, exc)
        return False


try:
    from .config_hardening import apply_config_hardening

    _run_stage("config_hardening", apply_config_hardening)
except Exception as exc:
    _bootstrap_failure("config_hardening_import", exc)

try:
    from . import brain as _brain_module
    from . import executor as _executor_module
    from . import memory as _memory_module
    from . import security as _security_module
    from . import voice as _voice_module
except Exception as exc:
    _bootstrap_failure("core_module_import", exc)
else:
    try:
        from . import runtime_patches as _runtime_patches

        _run_stage("runtime_brain", lambda: _runtime_patches.apply_patch("core.brain", _brain_module))
        _run_stage("runtime_security", lambda: _runtime_patches.apply_patch("core.security", _security_module))
        _run_stage("runtime_voice", lambda: _runtime_patches.apply_patch("core.voice", _voice_module))
    except Exception as exc:
        _bootstrap_failure("runtime_patches_import", exc)

    try:
        from .executor_hardening import apply_executor_hardening

        _run_stage("executor_hardening", lambda: apply_executor_hardening(_executor_module))
    except Exception as exc:
        _bootstrap_failure("executor_hardening_import", exc)

    try:
        from .memory_hardening import apply_memory_hardening

        _run_stage("memory_hardening", lambda: apply_memory_hardening(_memory_module))
    except Exception as exc:
        _bootstrap_failure("memory_hardening_import", exc)

    try:
        from . import performance_patches as _performance_module
        from .performance_patches import apply_performance_patches

        _run_stage("performance_patches", lambda: apply_performance_patches(_brain_module))
    except Exception as exc:
        _performance_module = None
        _bootstrap_failure("performance_patches_import", exc)

    try:
        from . import multilingual_patches as _multilingual_module
        from .multilingual_patches import apply_multilingual_patches

        _run_stage(
            "multilingual_patches",
            lambda: apply_multilingual_patches(_brain_module, _voice_module),
        )
    except Exception as exc:
        _multilingual_module = None
        _bootstrap_failure("multilingual_patches_import", exc)

    if _multilingual_module is not None:
        try:
            from .language_priority_patches import apply_language_priority_patches as _apply_lp

            _run_stage(
                "language_priority_patches",
                lambda: _apply_lp(_multilingual_module, _performance_module),
            )
        except Exception as exc:
            _bootstrap_failure("language_priority_patches_import", exc)

        try:
            from .language_voice_bridge import apply_language_voice_bridge

            _run_stage(
                "language_voice_bridge",
                lambda: apply_language_voice_bridge(_brain_module, _voice_module, _multilingual_module),
            )
        except Exception as exc:
            _bootstrap_failure("language_voice_bridge_import", exc)

        try:
            from .language_voice_enforcer import apply_language_voice_enforcer

            _run_stage(
                "language_voice_enforcer",
                lambda: apply_language_voice_enforcer(_voice_module, _multilingual_module),
            )
        except Exception as exc:
            _bootstrap_failure("language_voice_enforcer_import", exc)

    try:
        from .local_whisper_multilingual_patch import apply_local_whisper_multilingual_patch

        _run_stage(
            "local_whisper_multilingual_patch",
            lambda: apply_local_whisper_multilingual_patch(_voice_module),
        )
    except Exception as exc:
        _bootstrap_failure("local_whisper_multilingual_patch_import", exc)

    try:
        from .tts_sanitizer import apply_tts_sanitizer

        _run_stage("tts_sanitizer", lambda: apply_tts_sanitizer(_voice_module))
    except Exception as exc:
        _bootstrap_failure("tts_sanitizer_import", exc)

    try:
        from .voice_stable_override import apply_voice_stable_override

        _run_stage("voice_stable_override", lambda: apply_voice_stable_override(_voice_module))
    except Exception as exc:
        _bootstrap_failure("voice_stable_override_import", exc)
