"""
IRIS Runtime Profiler
=====================
Prevents ModuleNotFoundError in the profile sub-system.
"""
from core import logger

def log_runtime(module_name, message):
    """Logs sub-system performance to the anchored log file."""
    logger.info(f"[RUNTIME][{module_name}] {message}")