"""
IRIS Core Package
=================
Initializes the shared logger and Rich console so that any submodule (or
external caller) can do:

    from core import logger, console
"""

from __future__ import annotations

from rich.console import Console
from core.logger import get_logger

# Package-level singletons — import these everywhere instead of
# creating new instances scattered across modules.
logger = get_logger("IRIS")
console = Console()

__all__ = ["logger", "console", "get_logger"]
