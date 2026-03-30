"""
IRIS Diagnostics Suite v4.8.3 (Architect's Edition)
==================================================
- VRAM Probe: Hardware awareness for RTX 5050
- D1-D3: Hardened pre-flight and exception handling
"""

from __future__ import annotations
import os
import shutil
import subprocess
import time
import importlib
import dataclasses
from typing import Any, Dict, List

import requests
import numpy as np
from rich.console import Console
from pynvml import nvmlInit, nvmlDeviceGetHandleByIndex, nvmlDeviceGetMemoryInfo, nvmlShutdown

from config import Config
from core.logger import get_logger

console = Console()
logger = get_logger("Diagnostics")

@dataclasses.dataclass
class DiagnosticResult:
    name: str
    ok: bool
    severity: str = "warning"
    message: str = ""

def get_vram_status():
    """Returns (percent_used, free_mib) for the primary GPU."""
    try:
        nvmlInit()
        handle = nvmlDeviceGetHandleByIndex(0)
        info = nvmlDeviceGetMemoryInfo(handle)
        used_mib = info.used / (1024**2)
        total_mib = info.total / (1024**2)
        percent = (info.used / info.total) * 100
        nvmlShutdown()
        return percent, (total_mib - used_mib)
    except Exception:
        return 0, 0

class BootDiagnostics:
    def __init__(self):
        self.project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def run_preflight(self):
        results = {"Ollama": self.check_ollama(), "Storage": self._check_storage()}
        for sys, ok in results.items():
            if not ok:
                console.print(f"[bold red]! {sys} Check Failed.[/bold red]")
        return results

    def _check_storage(self) -> bool:
        drive, _ = os.path.splitdrive(self.project_root)
        try:
            return shutil.disk_usage(drive or "/").free / (1024**3) > 1.0
        except Exception:
            return False

    def check_ollama(self) -> bool:
        url = getattr(Config, "OLLAMA_BASE_URL", "http://localhost:11434")
        try:
            requests.get(f"{url}/api/tags", timeout=2).raise_for_status()
            return True
        except Exception:
            logger.warning("Ollama offline. Attempting auto-start...")
            try:
                flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
                subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
                time.sleep(2)
                return True
            except Exception:
                return False

class SelfDiagnostics:
    TRIGGERS = ["diagnostics", "calibrate", "mic check", "noise floor"]

    def should_handle(self, text: str) -> bool:
        return any(t in (text or "").lower() for t in self.TRIGGERS)

    def run_calibration(self, voice, duration=5) -> str:
        console.print(f"[bold cyan]→ Calibrating... Please stay silent for {duration}s.[/bold cyan]")
        samples = []
        start_time = time.time()
        while time.time() - start_time < duration:
            if voice._window_ready.wait(timeout=0.5):
                window = voice._latest_window
                samples.append(float(np.sqrt(np.mean(window.astype(np.float32) ** 2))))
                voice._window_ready.clear()
        
        if not samples:
            return "Error: Calibration failed. No audio detected."
        
        avg_noise = sum(samples) / len(samples)
        rec_wake = int((avg_noise * 1.5) + 100)
        rec_cmd = int((avg_noise * 2.0) + 150)
        return f"Noise Floor: {avg_noise:.0f} | Recommended WAKE: {rec_wake} | Recommended CMD: {rec_cmd}"

    def run(self, user_input: str, brain, voice, executor, copilot, memory, self_model=None) -> str:
        lowered = user_input.lower()
        if any(t in lowered for t in ["calibrate", "mic check"]):
            return self.run_calibration(voice)
        findings = []
        if not getattr(voice, "audio_ready", False):
            findings.append("Audio Offline")
        return " | ".join(findings) if findings else "All systems nominal."

def run_smoke_tests() -> List[DiagnosticResult]:
    required = ["config", "core.logger", "core.wake_engine", "core.brain", "core.voice", "core.memory", "core.executor", "core.dialog_manager", "core.copilot", "core.council", "core.autocorrect", "core.self_model"]
    results = []
    for mod in required:
        try:
            importlib.import_module(mod)
            results.append(DiagnosticResult(mod, True))
        except Exception as e:
            results.append(DiagnosticResult(mod, False, "critical", str(e)))
    return results