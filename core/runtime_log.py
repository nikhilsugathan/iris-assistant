"""
IRIS Runtime Logger
====================
Handles internal system events, performance tracking, 
and operational telemetry.
"""

import os
from datetime import datetime

LOG_FILE = "iris_system.log"

def log_runtime(event_type: str, message: str = "", level: str = "INFO", **kwargs):
    # You can also optionally format the kwargs into the log message inside the function:
    if kwargs:
        message += f" | Details: {kwargs}"
    
    # Ensure we don't crash if the log file is temporarily locked
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_entry)
    except Exception as e:
        print(f"--- [Runtime Log Error] Could not write to log: {e} ---")

def log_error(module: str, error_msg: str):
    """Specific helper for error telemetry."""
    log_runtime(f"ERROR:{module}", error_msg, level="CRITICAL")