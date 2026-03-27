"""
IRIS Core Package Marker
========================
Exposes the logger and console for system-wide access.
"""
from .logger import logger
from rich.console import Console

# Initialize the global terminal tool
console = Console()

__all__ = ['logger', 'console']