from __future__ import annotations

import builtins

try:
    from .logger import get_logger

    if not hasattr(builtins, "logger"):
        builtins.logger = get_logger("RuntimeFallback")
except Exception:
    pass

try:
    from .config_hardening import apply_config_hardening

    apply_config_hardening()
except Exception:
    pass

try:
    from . import runtime_patches as _runtime_patches
    from . import brain as _brain_module
    from . import security as _security_module
    from . import voice as _voice_module

    _runtime_patches.apply_patch("core.brain", _brain_module)
    _runtime_patches.apply_patch("core.security", _security_module)
    _runtime_patches.apply_patch("core.voice", _voice_module)

    from .performance_patches import apply_performance_patches

    apply_performance_patches(_brain_module)

    from .multilingual_patches import apply_multilingual_patches

    apply_multilingual_patches(_brain_module, _voice_module)

    from .tts_sanitizer import apply_tts_sanitizer

    apply_tts_sanitizer(_voice_module)

    from .voice_stable_override import apply_voice_stable_override

    apply_voice_stable_override(_voice_module)
except Exception:
    pass
