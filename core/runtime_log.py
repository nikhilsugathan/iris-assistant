from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from config import Config

_LOGGER = None
_LOGGER_PATH = None
_LOGGER_LOCK = threading.Lock()


def get_runtime_log_path() -> Path:
    raw = str(getattr(Config, "RUNTIME_LOG_FILE", "build/logs/iris_runtime.log") or "build/logs/iris_runtime.log").strip()
    path = Path(raw)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[1] / path
    return path


def _sanitize(value):
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _sanitize(val) for key, val in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_sanitize(item) for item in value]
    return str(value)


def get_runtime_logger():
    global _LOGGER, _LOGGER_PATH

    path = get_runtime_log_path()
    with _LOGGER_LOCK:
        if _LOGGER is not None and _LOGGER_PATH == path:
            return _LOGGER

        path.parent.mkdir(parents=True, exist_ok=True)

        logger = logging.getLogger(f"iris.runtime.{path}")
        logger.setLevel(logging.INFO)
        logger.propagate = False
        logger.handlers.clear()

        handler = RotatingFileHandler(
            path,
            maxBytes=max(1, int(getattr(Config, "RUNTIME_LOG_MAX_MB", 5))) * 1024 * 1024,
            backupCount=max(1, int(getattr(Config, "RUNTIME_LOG_BACKUPS", 3))),
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)

        _LOGGER = logger
        _LOGGER_PATH = path
        return logger


def log_runtime(event: str, **fields) -> None:
    if not getattr(Config, "RUNTIME_LOG_ENABLED", True):
        return

    payload = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "event": str(event or "runtime"),
    }
    for key, value in fields.items():
        payload[str(key)] = _sanitize(value)

    try:
        get_runtime_logger().info(json.dumps(payload, ensure_ascii=True))
    except Exception:
        pass
