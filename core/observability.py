"""Runtime observability hooks for IRIS.

Always-on pieces:
- boot marker
- uncaught main-thread exceptions
- uncaught worker-thread exceptions
- unraisable exceptions
- Python warnings redirected to logging
- faulthandler dump target under logs/

Optional deep tracing:
- set IRIS_TRACE_FUNCTIONS=true to log function/method start/end/error spans
- set IRIS_TRACE_ARGS=true to include sanitized argument previews
"""

from __future__ import annotations

import faulthandler
import functools
import inspect
import logging
import os
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any

from core.logger import get_logger, get_trace_logger

_logger = get_logger("Observability")
_trace = get_trace_logger("Observability")
_INSTALLED = False
_FAULT_FILE_HANDLE = None
_SECRET_HINTS = ("key", "token", "secret", "password", "authorization", "bearer")


def _enabled(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _logs_dir() -> Path:
    path = _project_root() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_preview(value: Any, limit: int = 160) -> str:
    try:
        text = repr(value)
    except Exception:
        text = f"<{type(value).__name__}>"
    lowered = text.lower()
    if any(hint in lowered for hint in _SECRET_HINTS):
        return "<redacted>"
    if len(text) > limit:
        return text[: limit - 3] + "..."
    return text


def _format_call(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    if not _enabled("IRIS_TRACE_ARGS", False):
        return ""
    parts = []
    if args:
        parts.extend(_safe_preview(arg) for arg in args[:4])
        if len(args) > 4:
            parts.append("...")
    for key, value in list(kwargs.items())[:8]:
        if any(hint in str(key).lower() for hint in _SECRET_HINTS):
            parts.append(f"{key}=<redacted>")
        else:
            parts.append(f"{key}={_safe_preview(value)}")
    return " args=" + ", ".join(parts) if parts else ""


def install_observability() -> None:
    """Install global runtime capture hooks once."""
    global _INSTALLED, _FAULT_FILE_HANDLE
    if _INSTALLED:
        return
    _INSTALLED = True

    _trace.info("[OBS] boot project_root=%s pid=%s python=%s", _project_root(), os.getpid(), sys.version.split()[0])
    logging.captureWarnings(True)

    original_excepthook = sys.excepthook

    def _excepthook(exc_type, exc, tb):
        _logger.critical("Uncaught exception", exc_info=(exc_type, exc, tb))
        _trace.critical("[OBS] uncaught_exception type=%s error=%s", getattr(exc_type, "__name__", exc_type), exc)
        return original_excepthook(exc_type, exc, tb)

    sys.excepthook = _excepthook

    if hasattr(threading, "excepthook"):
        original_threading_excepthook = threading.excepthook

        def _thread_excepthook(args):
            _logger.critical(
                "Uncaught thread exception in %s",
                getattr(args.thread, "name", "unknown-thread"),
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
            )
            _trace.critical(
                "[OBS] thread_exception thread=%s type=%s error=%s",
                getattr(args.thread, "name", "unknown-thread"),
                getattr(args.exc_type, "__name__", args.exc_type),
                args.exc_value,
            )
            return original_threading_excepthook(args)

        threading.excepthook = _thread_excepthook

    if hasattr(sys, "unraisablehook"):
        original_unraisablehook = sys.unraisablehook

        def _unraisablehook(unraisable):
            _logger.error(
                "Unraisable exception object=%r error=%r",
                getattr(unraisable, "object", None),
                getattr(unraisable, "exc_value", None),
                exc_info=(unraisable.exc_type, unraisable.exc_value, unraisable.exc_traceback),
            )
            _trace.error("[OBS] unraisable_exception error=%s", getattr(unraisable, "exc_value", None))
            return original_unraisablehook(unraisable)

        sys.unraisablehook = _unraisablehook

    try:
        fault_path = _logs_dir() / "iris_faults.log"
        _FAULT_FILE_HANDLE = open(fault_path, "a", encoding="utf-8")
        faulthandler.enable(file=_FAULT_FILE_HANDLE, all_threads=True)
        _trace.info("[OBS] faulthandler_enabled path=%s", fault_path)
    except Exception as exc:
        _logger.warning("Could not enable faulthandler: %s", exc)


def trace_callable(func, qualified_name: str):
    """Wrap a callable with start/end/error trace logs."""
    if getattr(func, "_iris_observed", False):
        return func

    @functools.wraps(func)
    def _wrapped(*args, **kwargs):
        if not _enabled("IRIS_TRACE_FUNCTIONS", False):
            return func(*args, **kwargs)
        started = time.perf_counter()
        call_preview = _format_call(args, kwargs)
        _trace.info("[CALL_START] %s%s", qualified_name, call_preview)
        try:
            result = func(*args, **kwargs)
            elapsed_ms = (time.perf_counter() - started) * 1000
            slow_ms = float(os.getenv("IRIS_TRACE_SLOW_MS", "750"))
            level = logging.WARNING if elapsed_ms >= slow_ms else logging.INFO
            _trace.log(level, "[CALL_END] %s elapsed_ms=%.1f", qualified_name, elapsed_ms)
            return result
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000
            _logger.exception("Observed function failed: %s elapsed_ms=%.1f error=%s", qualified_name, elapsed_ms, exc)
            _trace.error(
                "[CALL_ERROR] %s elapsed_ms=%.1f error_type=%s error=%s\n%s",
                qualified_name,
                elapsed_ms,
                exc.__class__.__name__,
                exc,
                "".join(traceback.format_exception(exc.__class__, exc, exc.__traceback__))[-4000:],
            )
            raise

    _wrapped._iris_observed = True
    return _wrapped


def instrument_module(module, module_name: str, *, include_private: bool = False) -> None:
    """Optionally wrap module functions and class methods for trace logging.

    The wrapping is inert unless IRIS_TRACE_FUNCTIONS=true, so installing it is
    cheap during normal operation.
    """
    if module is None or getattr(module, "_iris_observability_instrumented", False):
        return

    try:
        for name, obj in list(vars(module).items()):
            if inspect.isfunction(obj):
                if name.startswith("_") and not include_private:
                    continue
                setattr(module, name, trace_callable(obj, f"{module_name}.{name}"))
            elif inspect.isclass(obj) and getattr(obj, "__module__", "") == getattr(module, "__name__", ""):
                for method_name, method in list(vars(obj).items()):
                    if method_name.startswith("__"):
                        continue
                    if method_name.startswith("_") and not include_private:
                        continue
                    if isinstance(method, staticmethod):
                        wrapped = staticmethod(trace_callable(method.__func__, f"{module_name}.{obj.__name__}.{method_name}"))
                    elif isinstance(method, classmethod):
                        wrapped = classmethod(trace_callable(method.__func__, f"{module_name}.{obj.__name__}.{method_name}"))
                    elif inspect.isfunction(method):
                        wrapped = trace_callable(method, f"{module_name}.{obj.__name__}.{method_name}")
                    else:
                        continue
                    setattr(obj, method_name, wrapped)
        module._iris_observability_instrumented = True
        _trace.info("[OBS] module_instrumented module=%s include_private=%s", module_name, include_private)
    except Exception as exc:
        _logger.exception("Failed to instrument module %s: %s", module_name, exc)
