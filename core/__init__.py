# Iris Core

from __future__ import annotations

import builtins

# Compatibility fallback for older exception paths that reference a module-level
# logger before the affected module defines one locally. This prevents recovery
# handlers from raising NameError while the modules are migrated to explicit
# local loggers.
try:
    from .logger import get_logger

    if not hasattr(builtins, "logger"):
        builtins.logger = get_logger("RuntimeFallback")
except Exception:
    pass

# Apply safe runtime defaults before importing the heavier core modules.
try:
    from .config_hardening import apply_config_hardening

    apply_config_hardening()
except Exception:
    pass

# Apply targeted runtime patches at package startup. The imports are module-only:
# they do not instantiate the microphone, LLM, browser, or action executor.
try:
    from . import runtime_patches as _runtime_patches
    from . import brain as _brain_module
    from . import security as _security_module
    from . import voice as _voice_module

    _runtime_patches.apply_patch("core.brain", _brain_module)
    _runtime_patches.apply_patch("core.security", _security_module)
    _runtime_patches.apply_patch("core.voice", _voice_module)

    from .voice_stable_override import apply_voice_stable_override

    apply_voice_stable_override(_voice_module)
except Exception:
    pass
