"""
IRIS Diagnostics Suite v5.1 (Ironclad Edition)
==============================================
- Thermal Sentry: Integrated method for main.py access
- VRAM Probe: NVML-level memory tracking with resource safety
- Smoke Tests: Full module integrity verification
- Hardware: Optimized for RTX 5050 Mobile
"""

from __future__ import annotations
import os
import shutil
import subprocess
import time
import importlib
import dataclasses
import psutil
from typing import Any, Dict, List, Tuple

import requests
import numpy as np
from rich.console import Console
from rich.table import Table

# NVML Hardware Interface
try:
    from pynvml import (
        nvmlInit, nvmlDeviceGetHandleByIndex, nvmlDeviceGetMemoryInfo, 
        nvmlDeviceGetTemperature, nvmlShutdown, NVML_TEMPERATURE_GPU
    )
    NVML_AVAILABLE = True
except ImportError:
    NVML_AVAILABLE = False

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

def get_vram_status() -> Tuple[float, float]:
    """Standalone utility for quick VRAM checks with safe shutdown."""
    if not NVML_AVAILABLE:
        return 0.0, 0.0
    try:
        nvmlInit()
        try:
            handle = nvmlDeviceGetHandleByIndex(0)
            info = nvmlDeviceGetMemoryInfo(handle)
            percent = (info.used / info.total) * 100
            free_mib = (info.total - info.used) / (1024**2)
            return percent, free_mib
        finally:
            nvmlShutdown() # Ensure driver handle is released
    except Exception:
        return 0.0, 0.0

class BootDiagnostics:
    def __init__(self):
        self.project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def run_preflight(self) -> Dict[str, bool]:
        results = {
            "Ollama": self.check_ollama(), 
            "Storage": self._check_storage(),
            "VRAM": get_vram_status()[1] > 500 
        }
        return results

    def _check_storage(self) -> bool:
        drive, _ = os.path.splitdrive(self.project_root)
        try:
            # Require 1GB for logs/models/cache
            return shutil.disk_usage(drive or "/").free / (1024**3) > 1.0
        except Exception:
            return False

    def check_ollama(self) -> bool:
        url = getattr(Config, "OLLAMA_BASE_URL", "http://localhost:11434")
        try:
            requests.get(f"{url}/api/tags", timeout=2).raise_for_status()
            return True
        except Exception:
            # Only spawn Ollama if we're not using the local GGUF model
            if os.path.exists(Config.LOCAL_MODEL_PATH):
                return False

            # Check if ollama is installed before trying to serve
            if not shutil.which("ollama"):
                return False
            
            try:
                flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
                subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
                time.sleep(2)
                return True
            except Exception:
                return False

class SelfDiagnostics:
    TRIGGERS = ["diagnostics", "calibrate", "mic check", "noise floor", "system health"]

    def should_handle(self, text: str) -> bool:
        return any(t in (text or "").lower() for t in self.TRIGGERS)

    def check_thermal_integrity(self) -> Tuple[bool, int]:
        """Integrated Sentry for RTX 5050 Mobile (85°C Throttle Threshold)."""
        if not NVML_AVAILABLE:
            return psutil.cpu_percent() < 95, 0
            
        try:
            nvmlInit()
            try:
                handle = nvmlDeviceGetHandleByIndex(0)
                temp = nvmlDeviceGetTemperature(handle, NVML_TEMPERATURE_GPU)
                return (temp < 85), temp
            finally:
                nvmlShutdown()
        except Exception:
            return True, 0

    def run_calibration(self, voice, duration=5) -> str:
        if getattr(voice, "io_disabled", False):
            return "Calibration skipped: Text-mode active."

        console.print(f"[bold cyan]→ Calibrating... Stay silent for {duration}s.[/bold cyan]")
        samples = []
        start_time = time.time()
        
        while time.time() - start_time < duration:
            if voice._window_ready.wait(timeout=0.5):
                window = voice._latest_window
                rms = float(np.sqrt(np.mean(window.astype(np.float32) ** 2)))
                samples.append(rms)
                voice._window_ready.clear()
        
        if not samples:
            return "Error: No audio stream detected."
        
        avg_noise = sum(samples) / len(samples)
        rec_wake = int((avg_noise * 1.5) + 100)
        rec_cmd = int((avg_noise * 2.0) + 150)
        return f"Noise Floor: {avg_noise:.0f} | Rec. WAKE: {rec_wake} | Rec. CMD: {rec_cmd}"

    def run(self, user_input: str, brain, voice, executor, copilot, memory, self_model=None) -> str:
        lowered = user_input.lower()
        if any(t in lowered for t in ["calibrate", "mic check", "noise floor"]):
            return self.run_calibration(voice)
        
        findings = []
        safe, temp = self.check_thermal_integrity()
        if not safe:
            findings.append(f"Thermal Alert ({temp}°C)")
        
        if not getattr(voice, "mic_ready", False) and not getattr(voice, "io_disabled", False):
            findings.append("Mic Disconnected")

        return " | ".join(findings) if findings else "All systems nominal."

def run_smoke_tests() -> List[DiagnosticResult]:
    """Verification of core module integrity for the v5.1 architecture."""
    required = [
        "config", "core.brain", "core.voice", "core.executor", 
        "core.logic_engine", "core.self_model", "core.evolution"
    ]
    results = []
    for mod in required:
        try:
            importlib.import_module(mod)
            results.append(DiagnosticResult(mod, True))
        except Exception as e:
            results.append(DiagnosticResult(mod, False, "critical", str(e)))
    return results