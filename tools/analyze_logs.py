"""IRIS log analyzer.

Run from project root:
    python tools\analyze_logs.py

Optional:
    python tools\analyze_logs.py --lines 1200 --since-hours 48 --write-report

Scans logs/iris.log, logs/iris_trace.log, and logs/iris_faults.log for recent
runtime problems and prints a prioritized diagnosis without exposing API keys.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOGS_DIR = PROJECT_ROOT / "logs"
EXPORTS_DIR = PROJECT_ROOT / "exports"

_SECRET_RE = re.compile(
    r"(?i)(api[_-]?key|authorization|bearer|token|secret|password)(\s*[=:]\s*)[^\s,;]+"
)
_TIMESTAMP_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")


@dataclass
class Finding:
    severity: str
    title: str
    evidence: list[str] = field(default_factory=list)
    recommendation: str = ""

    def render(self) -> str:
        lines = [f"[{self.severity}] {self.title}"]
        for item in self.evidence[:8]:
            lines.append(f"  - {item}")
        if self.recommendation:
            lines.append(f"  Recommendation: {self.recommendation}")
        return "\n".join(lines)


def _redact(text: str) -> str:
    return _SECRET_RE.sub(r"\1\2<redacted>", text)


def _line_time(line: str):
    match = _TIMESTAMP_RE.match(line)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _filter_recent(lines: list[str], since_hours: int | None) -> list[str]:
    if not since_hours or since_hours <= 0:
        return lines
    cutoff = datetime.now() - timedelta(hours=since_hours)
    filtered: list[str] = []
    keep_continuation = False
    for line in lines:
        ts = _line_time(line)
        if ts is not None:
            keep_continuation = ts >= cutoff
            if keep_continuation:
                filtered.append(line)
            continue
        if keep_continuation:
            filtered.append(line)
    return filtered


def _tail(path: Path, max_lines: int, since_hours: int | None) -> list[str]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        lines = [_redact(line) for line in lines[-max_lines:]]
        return _filter_recent(lines, since_hours)
    except Exception as exc:
        return [f"<failed to read {path}: {exc}>"]


def _grep(lines: Iterable[str], *patterns: str) -> list[str]:
    compiled = [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
    matches = []
    for line in lines:
        if any(pattern.search(line) for pattern in compiled):
            matches.append(line.strip())
    return matches


def _count_tags(lines: Iterable[str]) -> Counter:
    tags = Counter()
    for line in lines:
        for tag in re.findall(r"\[(?:BRAIN|VOICE|OBS|CALL_[A-Z]+|Memory|Vision)[^\]]*\]", line):
            tags[tag] += 1
    return tags


def _latest(lines: Iterable[str], count: int = 5) -> list[str]:
    cleaned = [line for line in lines if line.strip()]
    return cleaned[-count:]


def analyze(max_lines: int = 1000, since_hours: int | None = 48) -> tuple[list[Finding], dict[str, list[str]], Counter]:
    iris_log = _tail(LOGS_DIR / "iris.log", max_lines, since_hours)
    trace_log = _tail(LOGS_DIR / "iris_trace.log", max_lines, since_hours)
    fault_log = _tail(LOGS_DIR / "iris_faults.log", max_lines, since_hours)
    all_lines = iris_log + trace_log + fault_log

    findings: list[Finding] = []
    evidence_buckets: dict[str, list[str]] = {
        "iris.log": iris_log,
        "iris_trace.log": trace_log,
        "iris_faults.log": fault_log,
    }

    if not iris_log and not trace_log:
        findings.append(Finding(
            "CRITICAL",
            "No recent application logs found",
            [str(LOGS_DIR), f"since_hours={since_hours}"],
            "Run python tools\\doctor_logs.py, then start IRIS again. Use --since-hours 0 to include all history.",
        ))
        return findings, evidence_buckets, Counter()

    fatal = _grep(all_lines, r"CRITICAL", r"Fatal Python error", r"Traceback \(most recent call last\)", r"Uncaught exception", r"thread_exception")
    doctor_only = [line for line in fatal if "DoctorLogs" in line or "doctor-exception" in line]
    real_fatal = [line for line in fatal if line not in doctor_only]
    if real_fatal:
        findings.append(Finding(
            "CRITICAL",
            "Crash or uncaught exception evidence found",
            _latest(real_fatal, 8),
            "Open surrounding lines in iris.log and iris_trace.log; fix the first exception, not later cascade errors.",
        ))

    llm_start = _grep(trace_log, r"local_llm_load_start", r"Spinning up C\+\+ LLM Engine")
    llm_end = _grep(trace_log + iris_log, r"local_llm_load_end", r"C\+\+ Engine Ready")
    preload_skipped = _grep(trace_log, r"local_llm_preload_skipped")
    if llm_start and not preload_skipped:
        findings.append(Finding(
            "HIGH",
            "Local C++ LLM appears to load during startup or early runtime",
            _latest(llm_start + llm_end, 8),
            "Keep IRIS_PRELOAD_LOCAL_LLM=false for faster boot; local model should lazy-load only when needed.",
        ))
    elif preload_skipped:
        findings.append(Finding(
            "INFO",
            "Local C++ LLM preload is skipped",
            _latest(preload_skipped, 3),
            "This is expected for faster boot. First local-only query may still trigger lazy-load.",
        ))

    slow_calls = _grep(trace_log, r"\[CALL_END\].*elapsed_ms=([1-9][0-9]{3,}|[5-9][0-9]{2}\.[0-9])")
    if slow_calls:
        findings.append(Finding(
            "MEDIUM",
            "Slow function calls detected",
            _latest(slow_calls, 8),
            "Check whether slow calls are LLM, STT, TTS, vision, or microphone operations. Disable IRIS_TRACE_FUNCTIONS after diagnosis.",
        ))

    mic_errors = _grep(all_lines, r"listen_error", r"mic_name='Microphone Array", r"Microphone init failed", r"Stream closed", r"-9988", r"input overflow", r"No Default Input Device")
    voice_rejections = _grep(trace_log, r"voice_poll_rejected", r"transcript_ignored", r"single_word_echo_risk", r"short_non_control_echo_risk")
    listen_start = _grep(trace_log, r"listen_start")
    listen_end = _grep(trace_log, r"listen_end")
    if mic_errors:
        findings.append(Finding(
            "HIGH",
            "Microphone/listening errors or device mismatch evidence found",
            _latest(mic_errors, 8),
            "Set Windows default input to the desired mic, or set PREFERRED_MIC_NAME/MIC_DEVICE_INDEX only for debugging.",
        ))
    if listen_start and not listen_end[-3:]:
        findings.append(Finding(
            "MEDIUM",
            "Listening starts are present; verify matching listen_end events",
            _latest(listen_start, 5),
            "If listen_start appears without listen_end near freezes, the recognizer may be blocking on the selected mic.",
        ))
    if voice_rejections:
        findings.append(Finding(
            "MEDIUM",
            "Voice transcripts are being rejected by filters",
            _latest(voice_rejections, 8),
            "If real commands are rejected, use clearer wake/control phrases first; then adjust filters only if needed.",
        ))

    stt_fail = _grep(all_lines, r"groq_stt_error", r"google_transcribe_error", r"transcribe.*engine=none", r"429", r"rate_limit")
    if stt_fail:
        recommendation = "Upgrade Groq while keeping httpx>=0.28.1: python -m pip install --upgrade 'groq>=0.20.0' 'httpx>=0.28.1,<1.0.0'."
        findings.append(Finding("HIGH", "STT/API transcription failures detected", _latest(stt_fail, 8), recommendation))

    tts_fail = _grep(all_lines, r"Edge-TTS", r"edge_tts", r"TTS.*failed", r"pygame", r"mixer", r"Prefetch.*failed")
    tts_errors = [line for line in tts_fail if re.search(r"failed|error|exception|timeout", line, re.IGNORECASE)]
    if tts_errors:
        findings.append(Finding(
            "HIGH",
            "TTS/playback failures detected",
            _latest(tts_errors, 8),
            "Keep TTS_ENGINE=edge and Piper disabled while debugging; if only old history appears, rerun with default --since-hours 48.",
        ))

    vision_fail = _grep(all_lines, r"vision_failed", r"vision_capture_failed", r"vision_provider_failed", r"Vision API", r"screen capture failed")
    vision_ok = _grep(all_lines, r"vision_capture_ok", r"vision_provider_ok", r"vision_response_ok")
    if vision_fail:
        findings.append(Finding(
            "HIGH",
            "Screen reading / vision failures detected",
            _latest(vision_fail, 8),
            "Upgrade Groq/httpx compatibility, then run python tools\\doctor_vision.py. Prefer VISION_PROVIDER=gemini.",
        ))
    elif vision_ok:
        findings.append(Finding("INFO", "Vision capture/provider success evidence found", _latest(vision_ok, 5), "Vision path appears available in recent logs."))

    memory_fail = _grep(all_lines, r"\[Memory\].*failed", r"corrupt", r"could not save", r"archive_session failed")
    if memory_fail:
        findings.append(Finding(
            "HIGH",
            "Memory persistence issue detected",
            _latest(memory_fail, 8),
            "Inspect any .corrupt-*.json files and verify write permissions under project/data directory.",
        ))

    warnings = _grep(all_lines, r"\[WARNING\]", r" WARNING ")
    errors = _grep(all_lines, r"\[ERROR\]", r"\[CRITICAL\]", r" ERROR ", r" CRITICAL ")
    errors = [line for line in errors if "DoctorLogs" not in line and "doctor-exception" not in line]
    if warnings:
        findings.append(Finding("INFO", f"Warnings present: {len(warnings)}", _latest(warnings, 5), "Review if repeated."))
    if errors and not real_fatal:
        findings.append(Finding("MEDIUM", f"Errors present: {len(errors)}", _latest(errors, 8), "Review the first error chronologically."))

    tags = _count_tags(trace_log)
    if not findings:
        findings.append(Finding(
            "OK",
            "No obvious critical issues detected in recent logs",
            _latest(all_lines, 5),
            "Increase --lines or enable IRIS_TRACE_FUNCTIONS=true for one diagnostic run if the issue is intermittent.",
        ))

    return findings, evidence_buckets, tags


def render_report(findings: list[Finding], evidence_buckets: dict[str, list[str]], tags: Counter, since_hours: int | None) -> str:
    lines = ["# IRIS Log Analysis Report", ""]
    lines.append(f"Project: `{PROJECT_ROOT}`")
    lines.append(f"Logs: `{LOGS_DIR}`")
    lines.append(f"Window: last {since_hours} hours" if since_hours else "Window: all available tailed history")
    lines.append("")
    lines.append("## Findings")
    for finding in findings:
        lines.append("")
        lines.append(finding.render())
    if tags:
        lines.append("")
        lines.append("## Top trace tags")
        for tag, count in tags.most_common(15):
            lines.append(f"- `{tag}`: {count}")
    lines.append("")
    lines.append("## Latest log tails")
    for name, bucket in evidence_buckets.items():
        lines.append("")
        lines.append(f"### {name}")
        if not bucket:
            lines.append("No recent lines found.")
            continue
        lines.append("```text")
        lines.extend(bucket[-60:])
        lines.append("```")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze IRIS logs for likely runtime issues.")
    parser.add_argument("--lines", type=int, default=1000, help="Tail this many lines from each log file.")
    parser.add_argument("--since-hours", type=int, default=48, help="Only include timestamped log entries from the last N hours. Use 0 for all tailed history.")
    parser.add_argument("--write-report", action="store_true", help="Write exports/log_analysis_report.md")
    args = parser.parse_args()

    since_hours = args.since_hours if args.since_hours > 0 else None
    findings, buckets, tags = analyze(max_lines=args.lines, since_hours=since_hours)
    report = render_report(findings, buckets, tags, since_hours)
    print(report)

    if args.write_report:
        EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
        report_path = EXPORTS_DIR / "log_analysis_report.md"
        report_path.write_text(report, encoding="utf-8")
        print(f"\nReport written to: {report_path}")

    severities = {finding.severity for finding in findings}
    if "CRITICAL" in severities:
        return 2
    if "HIGH" in severities:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
