"""
IRIS Self-Diagnostics (Version 2 - Tolerant)
===========================================
"""

from __future__ import annotations
import os
from typing import List, Optional
from collections import deque
from config import Config

class SelfDiagnostics:
    TRIGGERS = ["self diagnostic", "health check", "status report", "debug yourself"]

    def should_handle(self, text: str) -> bool:
        lowered = (text or "").lower().strip()
        return any(trigger in lowered for trigger in self.TRIGGERS)

    # Helper: tolerant accessor for available APIs across rename variants
    def _get_available_apis(self, brain) -> List[str]:
        candidates = ("available_apis", "available", "apis", "detected_apis")
        for attr in candidates:
            val = getattr(brain, attr, None)
            if val is not None:
                return list(val)
        return []

    # Helper: tolerant audio-ready evaluation (supports audio_ready or inverse io_disabled)
    def _audio_ready(self, voice) -> bool:
        if voice is None: return False
        if hasattr(voice, "audio_ready"):
            return bool(getattr(voice, "audio_ready"))
        if hasattr(voice, "io_disabled"):
            return not bool(getattr(voice, "io_disabled")) # Inversion Logic
        return False

    def _tail_log(self, path: str, lines: int = 15) -> List[str]:
        if not path or not os.path.exists(path): return []
        try:
            dq = deque(maxlen=lines)
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                for ln in fh:
                    dq.append(ln.rstrip("\n"))
            return list(dq)
        except Exception: return []

    def run(self, user_input: str, brain, voice, executor, copilot, memory, self_model=None) -> str:
        findings: List[str] = []
        observations: List[str] = []
        
        available = self._get_available_apis(brain)
        if not available:
            findings.append("No language model backends are available.")
        
        if not self._audio_ready(voice):
            findings.append("My audio output is not ready (I/O might be disabled).")

        # ... (rest of the diagnostic logic)
        return "\n".join(findings + observations) if findings or observations else "All systems nominal."