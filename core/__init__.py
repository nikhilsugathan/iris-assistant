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
