"""IRIS logging doctor.

Run from project root:
    python tools\doctor_logs.py

Verifies that normal logs, trace logs, exception stack traces, and observability
boot hooks are written into the expected files under logs/.
"""

from __future__ import annotations

import logging
import os
import sys
import time
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _flush_handlers(logger) -> None:
    for handler in list(getattr(logger, "handlers", [])):
        try:
            handler.flush()
        except Exception:
            pass


def _flush_parent_trace() -> None:
    parent = logging.getLogger("iris.trace")
    for handler in list(parent.handlers):
        try:
            handler.flush()
        except Exception:
            pass


def _contains(path: Path, marker: str) -> bool:
    if not path.exists():
        return False
    try:
        return marker in path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return False


def main() -> int:
    from core.logger import get_logger, get_trace_logger
    from core.observability import install_observability, trace_callable

    logs_dir = PROJECT_ROOT / "logs"
    iris_log = logs_dir / "iris.log"
    trace_log = logs_dir / "iris_trace.log"
    fault_log = logs_dir / "iris_faults.log"

    marker = f"doctor-log-{uuid.uuid4().hex}"
    exc_marker = f"doctor-exception-{uuid.uuid4().hex}"
    trace_marker = f"doctor-trace-{uuid.uuid4().hex}"
    call_marker = f"doctor-call-{uuid.uuid4().hex}"

    install_observability()
    logger = get_logger("DoctorLogs")
    trace_logger = get_trace_logger("DoctorLogs")

    logger.info("%s normal log write check", marker)
    try:
        raise RuntimeError(exc_marker)
    except RuntimeError:
        logger.exception("%s exception stacktrace check", exc_marker)
    trace_logger.info("%s trace log write check", trace_marker)

    previous_trace_functions = os.environ.get("IRIS_TRACE_FUNCTIONS")
    os.environ["IRIS_TRACE_FUNCTIONS"] = "true"
    try:
        def _sample(value):
            return value + 1

        wrapped = trace_callable(_sample, f"doctor.{call_marker}")
        wrapped(1)
    finally:
        if previous_trace_functions is None:
            os.environ.pop("IRIS_TRACE_FUNCTIONS", None)
        else:
            os.environ["IRIS_TRACE_FUNCTIONS"] = previous_trace_functions

    _flush_handlers(logger)
    _flush_parent_trace()
    time.sleep(0.05)

    ok_normal = _contains(iris_log, marker)
    ok_exception = _contains(iris_log, exc_marker) and _contains(iris_log, "Traceback")
    ok_trace = _contains(trace_log, trace_marker)
    ok_observability_boot = _contains(trace_log, "[OBS] boot")
    ok_call_trace = _contains(trace_log, call_marker) and _contains(trace_log, "[CALL_START]") and _contains(trace_log, "[CALL_END]")
    ok_fault_target = fault_log.exists()

    print("IRIS Log Doctor")
    print("=" * 60)
    print(f"logs dir:             {logs_dir}")
    print(f"iris.log:             {'ok' if ok_normal else 'missing marker'}")
    print(f"exception log:        {'ok' if ok_exception else 'missing stacktrace'}")
    print(f"trace log:            {'ok' if ok_trace else 'missing marker'}")
    print(f"observability boot:   {'ok' if ok_observability_boot else 'missing boot marker'}")
    print(f"function trace path:  {'ok' if ok_call_trace else 'missing call span'}")
    print(f"fault log target:     {'ok' if ok_fault_target else 'missing file'}")

    if ok_normal and ok_exception and ok_trace and ok_observability_boot and ok_call_trace and ok_fault_target:
        print("Doctor result: logging and observability capture are working.")
        return 0

    print("Doctor result: logging/observability check failed.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
