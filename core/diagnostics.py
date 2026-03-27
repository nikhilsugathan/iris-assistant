from __future__ import annotations
import os
import re
from typing import List, Optional
from collections import deque
from config import Config

class SelfDiagnostics:
    TRIGGERS = ["self diagnostic", "health check", "status report", "debug yourself"]

    def should_handle(self, text: str) -> bool:
        lowered = (text or "").lower().strip()
        return any(trigger in lowered for trigger in self.TRIGGERS)

    def _get_available_apis(self, brain) -> List[str]:
        candidates = ("available_apis", "available", "apis", "detected_apis")
        for attr in candidates:
            val = getattr(brain, attr, None)
            if val is not None:
                return list(val)
        return []

    def _audio_ready(self, voice) -> bool:
        if voice is None: return False
        if hasattr(voice, "audio_ready"):
            return bool(getattr(voice, "audio_ready"))
        if hasattr(voice, "io_disabled"):
            return not bool(getattr(voice, "io_disabled")) # Inversion for CI
        return False

    def _voice_findings(self, voice) -> List[str]:
        findings = []
        if not getattr(voice, "mic_ready", False):
            findings.append("Microphone initialization failed.")
        return findings

    def _recent_action_findings(self, executor) -> List[str]:
        log_path = getattr(executor, "log_file", "iris_actions.log")
        lines = self._tail_log(log_path, lines=5)
        return [f"Log Trace: {l}" for l in lines] if lines else ["No recent logs found."]

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
        observations.append(f"Active APIs: {', '.join(available) if available else 'None'}")
        
        if not self._audio_ready(voice):
            findings.append("Audio output is currently disabled (CI mode or manual).")

        findings.extend(self._voice_findings(voice))
        findings.extend(self._recent_action_findings(executor))

        return "\n".join(observations + findings)