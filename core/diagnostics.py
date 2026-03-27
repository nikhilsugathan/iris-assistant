"""
IRIS Integrated Diagnostics Suite (Engineering Polish)
======================================================
Consolidated suite for proactive auto-healing, reactive status reports,
and CI/CD validation. Fully hardened for Windows and cross-platform use.
"""

from __future__ import annotations

import dataclasses
import importlib
import os
import shutil
import subprocess
import time
from collections import deque
from typing import Any, Dict, List  # Removed unused Optional

import requests
from config import Config
from core.logger import get_logger

# Guarded Import: Prevents startup crash if the notifications module is missing
try:
    from core.notifications import SystemNotifier
except Exception:
    SystemNotifier = None

logger = get_logger("Diagnostics")

if SystemNotifier is None:
    logger.warning("core.notifications module unavailable; desktop alerts disabled.")

@dataclasses.dataclass
class DiagnosticResult:
    name: str
    ok: bool
    severity: str = "warning"  # info, warning, error, critical
    message: str = ""
    details: Dict[str, Any] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)

# ─────────────────────────────────────────────────────────────
# 1. BOOT DIAGNOSTICS (Proactive / Auto-Healing)
# ─────────────────────────────────────────────────────────────

class BootDiagnostics:
    def __init__(self):
        self.notifier = SystemNotifier() if SystemNotifier is not None else None
        # Dynamic project root for cross-platform portability
        self.project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def check_ollama(self) -> bool:
        """Pings local Ollama; attempts auto-start with re-probe if offline."""
        ollama_url = getattr(Config, "OLLAMA_BASE_URL", "http://localhost:11434")
        try:
            resp = requests.get(f"{ollama_url}/api/tags", timeout=2)
            resp.raise_for_status()
            return True
        except requests.exceptions.RequestException:
            # Use deferred formatting for logging performance
            logger.warning("Ollama probe failed at %s. Attempting auto-heal...", ollama_url)
            
            if self.notifier:
                self.notifier.send_toast(
                    "System Warning", 
                    "Ollama is offline. Starting local model service...", 
                    "warning"
                )
            
            try:
                # Windows-specific: Use process groups to ensure easier cleanup
                creation_flags = 0
                if os.name == 'nt':
                    creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP

                subprocess.Popen(
                    ["ollama", "serve"], 
                    shell=False, 
                    stdout=subprocess.DEVNULL, 
                    stderr=subprocess.DEVNULL,
                    creationflags=creation_flags
                )
                
                # Give the service time to bind to the port
                time.sleep(1.5)
                try:
                    retry_resp = requests.get(f"{ollama_url}/api/tags", timeout=2)
                    retry_resp.raise_for_status()
                    return True
                except requests.exceptions.RequestException:
                    logger.exception("Ollama did not respond after starting 'ollama serve'.")
                    return False
            except Exception:
                logger.exception("Failed to launch 'ollama serve' subprocess.")
                return False

    def run_preflight(self):
        """Standard check run by launch_iris.bat with robust drive detection."""
        # Robust cross-platform drive detection
        drive, _ = os.path.splitdrive(self.project_root)
        if not drive:
            drive = os.path.abspath(os.sep)

        try:
            free_gb = shutil.disk_usage(drive).free / (1024**3)
            storage_ok = free_gb > 1.0
        except Exception:
            logger.exception("Failed to check disk usage for %s", drive)
            storage_ok = False

        status = {
            "Ollama": self.check_ollama(),
            "Workspace": os.path.exists(self.project_root),
            "Storage": storage_ok
        }

        if all(status.values()):
            if self.notifier:
                # Safe attribute access for dynamic codenames
                codename = getattr(Config, "INNER_CODENAME", "<unknown>")
                self.notifier.send_toast(
                    "IRIS Online", 
                    f"Core {codename} active. All systems nominal.", 
                    "info"
                )
        else:
            logger.error("Pre-flight failures detected: %s", status)
        return status

# ─────────────────────────────────────────────────────────────
# 2. SELF-DIAGNOSTICS (Reactive / User-Facing)
# ─────────────────────────────────────────────────────────────

class SelfDiagnostics:
    TRIGGERS = [
        "self diagnostic", "health check", "status report", 
        "what's wrong with you", "what is wrong with you", 
        "why are you not working", "diagnostics"
    ]

    def should_handle(self, text: str) -> bool:
        lowered = (text or "").lower().strip()
        return any(trigger in lowered for trigger in self.TRIGGERS)

    def run(self, user_input: str, brain, voice, executor, copilot, memory, self_model=None) -> str:
        findings: List[str] = []
        available = list(getattr(brain, "available_apis", []))
        primary = getattr(Config, "PRIMARY_BRAIN", "<unset>")
        
        if not available:
            findings.append("No active AI backends detected.")
        else:
            findings.append(f"Connected to {len(available)} APIs (Primary: {primary}).")

        if not getattr(voice, "audio_ready", False):
            findings.append("Audio output system is offline.")
        
        # Precise, line-by-line log scanning
        action_log = os.path.join(os.path.dirname(os.path.dirname(__file__)), "iris_actions.log")
        if os.path.exists(action_log):
            try:
                with open(action_log, "r", encoding="utf-8") as f:
                    last_lines = deque(f, maxlen=15)
                    # Check lines individually to avoid boundary false-positives
                    if any(tag in line for line in last_lines for tag in ["FAILED:", "EXCEPTION:"]):
                        findings.append("Recent execution failures detected in logs.")
            except Exception:
                logger.exception("Error reading action log during self-test.")

        return " | ".join(findings) if findings else "All systems nominal."

# ─────────────────────────────────────────────────────────────
# 3. SMOKE TESTS (CI / Validation)
# ─────────────────────────────────────────────────────────────

def run_smoke_tests() -> List[DiagnosticResult]:
    """CI suite that treats notifications as an optional component."""
    results = []
    required = ["core.brain", "core.voice", "core.memory"]
    optional = ["core.notifications"]
    
    for mod in required + optional:
        try:
            importlib.import_module(mod)
            results.append(DiagnosticResult(name=f"import:{mod}", ok=True, severity="info"))
        except Exception as e:
            severity = "warning" if mod in optional else "critical"
            results.append(DiagnosticResult(
                name=f"import:{mod}", ok=False, 
                severity=severity,
                message=str(e)
            ))
            
    if not getattr(Config, "INNER_CODENAME", None):
        results.append(DiagnosticResult("config:codename", False, "error", "INNER_CODENAME missing"))
        
    return results