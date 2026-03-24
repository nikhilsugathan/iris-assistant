"""
IRIS Self-Diagnostics
=====================
Provides a runtime-aware health report when the user asks
why IRIS is not working as expected.
"""

from __future__ import annotations

import os
from typing import List

from config import Config


class SelfDiagnostics:
    TRIGGERS = [
        "self diagnostic",
        "self-diagnostic",
        "diagnose yourself",
        "health check",
        "status report",
        "what's wrong with you",
        "what is wrong with you",
        "why are you not working",
        "why aren't you working",
        "why are you not working as expected",
        "why is this not working",
        "why is this not working as expected",
        "debug yourself",
        "inspect yourself",
        "what problem do you have",
    ]

    def should_handle(self, text: str) -> bool:
        lowered = (text or "").lower().strip()
        return any(trigger in lowered for trigger in self.TRIGGERS)

    def run(self, user_input: str, brain, voice, executor, copilot, memory, self_model=None) -> str:
        findings: List[str] = []
        observations: List[str] = []
        lowered = (user_input or "").lower()

        available = list(getattr(brain, "available_apis", []))
        primary = getattr(Config, "PRIMARY_BRAIN", "unknown")
        fallback = getattr(Config, "FALLBACK_BRAIN", "unknown")

        if not available:
            findings.append("No language model backends are available, so I cannot reason reliably right now.")
        else:
            observations.append(
                f"My active brain routing is {primary} with {fallback} as fallback, and I currently see {', '.join(available)}."
            )
            if primary not in available:
                findings.append(
                    f"My configured primary brain is {primary}, but it is not currently available. I am relying on fallback routing."
                )

        if not getattr(voice, "audio_ready", False):
            findings.append("My audio output is not ready, so speech playback is currently unavailable.")

        if not getattr(voice, "mic_ready", False):
            mic_error = getattr(voice, "mic_error", "") or "the microphone did not initialize cleanly"
            findings.append(f"My microphone path is degraded: {mic_error}.")

        if getattr(executor, "waiting_for_permission", lambda: False)():
            findings.append("I am paused waiting for permission on an action, which can make me seem stuck until you answer.")
        elif getattr(executor, "waiting_for_clarification", lambda: False)():
            findings.append("I am waiting for a clarification reply, so the conversation is currently mid-action.")
        elif getattr(executor, "waiting_for_plan_choice", lambda: False)():
            findings.append("I generated fallback plans after a failed action and I am waiting for you to choose one.")

        if getattr(copilot, "active", False):
            observations.append("Co-Pilot mode is active, so I am answering as a guided step-by-step assistant right now.")

        if getattr(Config, "USE_ENSEMBLE", False):
            findings.append("Ensemble mode is enabled, which improves answer quality sometimes but slows live conversation.")

        if "audio" in lowered or "voice" in lowered or "silent" in lowered or "latency" in lowered:
            findings.extend(self._voice_findings(voice))

        action_findings = self._recent_action_findings()
        findings.extend(action_findings)

        turns = len(getattr(memory, "conversation", []))
        observations.append(f"My memory file is {Config.MEMORY_FILE} and I currently have {turns} stored conversation entries.")
        if self_model is not None:
            observations.append(f"My current self-model is {self_model.summary()}.")

        if not findings:
            findings.append("I do not see a hard failure in my current runtime state. The most likely issues are timing-related voice latency, model availability shifts, or a task-specific failure outside the core loop.")

        top_findings = findings[:4]
        top_observations = observations[:2]

        lines = [f"Self-diagnostic report from {Config.INNER_CODENAME}:"]
        for item in top_findings:
            lines.append(f"- {item}")
        for item in top_observations:
            lines.append(f"- {item}")

        return "\n".join(lines)

    def _voice_findings(self, voice) -> List[str]:
        findings: List[str] = []
        buffer_size = getattr(Config, "AUDIO_BUFFER_SIZE", 512)
        chunk_sentences = getattr(Config, "TTS_CHUNK_SENTENCES", 1)
        poll = getattr(Config, "PLAYBACK_POLL_SECONDS", 0.03)

        findings.append(
            f"My speech path is using sentence chunking with {chunk_sentences} sentence per chunk, mixer buffer {buffer_size}, and playback poll {poll:.2f}s."
        )

        if buffer_size > 1024:
            findings.append("My audio buffer is relatively large, which can increase perceived speech lag.")

        if not getattr(voice, "audio_ready", False):
            findings.append("That directly explains missing speech output.")
        else:
            findings.append("If the first word is still getting clipped, the likely cause is the local audio device or pygame playback starting late rather than the language model itself.")

        return findings

    def _recent_action_findings(self) -> List[str]:
        log_path = "iris_actions.log"
        if not os.path.exists(log_path):
            return []

        try:
            with open(log_path, "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f.readlines() if line.strip()]
        except Exception:
            return []

        recent = lines[-20:]
        failures = [line for line in recent if any(tag in line for tag in ["FAILED:", "BLOCKED:", "EXCEPTION:"])]
        if not failures:
            return []

        latest = failures[-1]
        return [f"My recent action log shows a failure path: {latest}"]
