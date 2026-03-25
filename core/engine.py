"""
IRIS Runtime Engine
===================
Reusable session engine for GUI and terminal entry points.
"""

from __future__ import annotations

import difflib
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta

from config import Config
from core.autocorrect import AutoCorrector
from core.brain import Brain
from core.council import Council
from core.copilot import CoPilot
from core.dialog_manager import DialogManager
from core.diagnostics import SelfDiagnostics
from core.executor import ActionExecutor
from core.memory import Memory
from core.self_model import SelfModel
from core.voice import Voice


@dataclass
class EngineResult:
    label: str
    response: str
    should_exit: bool = False
    mode: str = "chat"


class IRISEngine:
    OVERDRIVE_ON_COMMANDS = {
        "activate overdrive",
        "overdrive on",
        "turn on overdrive",
        "enable overdrive",
        "start overdrive",
    }
    OVERDRIVE_OFF_COMMANDS = {
        "deactivate overdrive",
        "overdrive off",
        "turn off overdrive",
        "disable overdrive",
        "stop overdrive",
    }
    OVERDRIVE_STATUS_COMMANDS = {
        "overdrive status",
        "is overdrive on",
        "status overdrive",
    }

    def __init__(self, text_mode: bool = False):
        self.text_mode = text_mode
        self._interaction_lock = threading.Lock()
        self.overdrive_active = False
        self.overdrive_activated_at: datetime | None = None
        self.overdrive_last_activity_at: datetime | None = None
        self.memory = Memory(Config.MEMORY_FILE)
        self.brain = Brain(self.memory)
        self.voice = Voice(text_mode=text_mode)
        self.copilot = CoPilot(self.brain, self.voice, self.memory)
        self.executor = ActionExecutor(self.voice, self.brain)
        self.autocorrect = AutoCorrector(self.brain)
        self.self_model = SelfModel()
        self.dialog_manager = DialogManager()
        self.council = Council()
        self.diagnostics = SelfDiagnostics()

    def status_snapshot(self) -> dict:
        return {
            "public_name": Config.PUBLIC_NAME,
            "system_name": Config.SYSTEM_NAME,
            "inner_codename": Config.INNER_CODENAME,
            "primary_brain": Config.PRIMARY_BRAIN,
            "fallback_brain": Config.FALLBACK_BRAIN,
            "audio_ready": getattr(self.voice, "audio_ready", False),
            "mic_ready": getattr(self.voice, "mic_ready", False),
            "wake_words": list(getattr(Config, "WAKE_WORDS", [])),
            "self_model": self.self_model.summary(),
            "memory": self.memory.summary(),
            "overdrive_active": self.overdrive_active,
            "overdrive_activated_at": self.overdrive_activated_at.isoformat(timespec="seconds")
            if self.overdrive_activated_at
            else None,
        }

    def process_user_input(
        self,
        user_input: str,
        speak_response: bool = True,
        input_source: str | None = None,
    ) -> EngineResult:
        with self._interaction_lock:
            user_input = (user_input or "").strip()
            if not user_input:
                return EngineResult(label=Config.PUBLIC_NAME, response="", should_exit=False, mode="empty")

            inferred_source = input_source or ("text" if self.text_mode else "unknown")
            self.executor.set_input_source(inferred_source)
            self.refresh_overdrive()

            if user_input.lower() in {"exit", "quit", "goodbye iris", "shutdown"}:
                msg = "Shutting down. Try not to break anything while I'm gone."
                self._speak_if_enabled(msg, speak_response)
                return EngineResult(label=Config.PUBLIC_NAME, response=msg, should_exit=True, mode="shutdown")

            corrected, _ = self.autocorrect.correct_input(user_input)
            user_input = corrected

            overdrive_result = self._maybe_handle_overdrive_command(
                user_input,
                speak_response=speak_response,
                input_source=inferred_source,
            )
            if overdrive_result is not None:
                self._update_self_model_after_response(overdrive_result.response, "overdrive")
                return overdrive_result

            try:
                self.voice.stop_speaking()
            except Exception:
                pass

            if self.executor.waiting_for_followup():
                response = self.executor.handle_followup_response(user_input)
                if response is not None:
                    self._update_self_model_after_response(response, "followup")
                    self._speak_if_enabled(response, speak_response)
                    return EngineResult(label=Config.PUBLIC_NAME, response=response, mode="followup")

            if self.executor.waiting_for_clarification():
                response = self.executor.handle_clarification_response(user_input)
                if response is not None:
                    self._update_self_model_after_response(response, "clarification")
                    self._speak_if_enabled(response, speak_response)
                    return EngineResult(label=Config.PUBLIC_NAME, response=response, mode="clarification")

            if self.executor.waiting_for_plan_choice():
                response = self.executor.handle_plan_choice(user_input)
                if response is not None:
                    self._update_self_model_after_response(response, "plan-choice")
                    self._speak_if_enabled(response, speak_response)
                    return EngineResult(label=Config.PUBLIC_NAME, response=response, mode="plan-choice")

            if self.executor.waiting_for_presence_check():
                response = self.executor.handle_presence_check_response(user_input)
                if response is not None:
                    self._update_self_model_after_response(response, "presence-check")
                    self._speak_if_enabled(response, speak_response)
                    return EngineResult(label=Config.PUBLIC_NAME, response=response, mode="presence-check")

            if self.executor.waiting_for_permission():
                response = self.executor.handle_permission_response(user_input)
                self._update_self_model_after_response(response, "permission")
                self._speak_if_enabled(response, speak_response)
                return EngineResult(label=Config.PUBLIC_NAME, response=response, mode="permission")

            decision = self.dialog_manager.analyze(
                user_input,
                self.executor,
                self.copilot,
                self.diagnostics,
                self.self_model,
            )
            self.self_model.observe_user_input(user_input, decision)

            if decision.mode == "diagnostics":
                response = self.diagnostics.run(
                    user_input,
                    self.brain,
                    self.voice,
                    self.executor,
                    self.copilot,
                    self.memory,
                    self.self_model,
                )
                self._update_self_model_after_response(response, "diagnostics")
                self._speak_if_enabled(response, speak_response)
                return EngineResult(label=f"{Config.PUBLIC_NAME} (Diagnostics)", response=response, mode="diagnostics")

            if self.copilot.active:
                response = self.copilot.handle_input(user_input)
                if response:
                    self._update_self_model_after_response(response, "copilot")
                    self._speak_if_enabled(response, speak_response)
                return EngineResult(label=f"{Config.PUBLIC_NAME} (Co-Pilot)", response=response or "", mode="copilot")

            if decision.mode == "copilot":
                response = self.copilot.start(user_input)
                self._update_self_model_after_response(response, "copilot")
                self._speak_if_enabled(response, speak_response)
                return EngineResult(label=f"{Config.PUBLIC_NAME} (Co-Pilot)", response=response, mode="copilot")

            if decision.mode == "action":
                response = self.executor.plan_action(user_input)
                self._update_self_model_after_response(response, "action")
                self._speak_if_enabled(response, speak_response)
                return EngineResult(label=f"{Config.PUBLIC_NAME} (Action)", response=response, mode="action")

            packet = self.council.deliberate(user_input, decision, self.self_model)
            packet = self._apply_overdrive_to_packet(packet)
            self.self_model.apply_council(packet.roles)
            response = self.brain.think(user_input, council_packet=packet)
            self._update_self_model_after_response(response, "brain")
            self._speak_if_enabled(response, speak_response)
            return EngineResult(label=Config.PUBLIC_NAME, response=response, mode=decision.mode)

    def activate_overdrive(self) -> None:
        now = datetime.now()
        self.overdrive_active = True
        self.overdrive_activated_at = now
        self.overdrive_last_activity_at = now

    def deactivate_overdrive(self) -> None:
        self.overdrive_active = False
        self.overdrive_activated_at = None
        self.overdrive_last_activity_at = None

    def refresh_overdrive(self) -> None:
        if not self.overdrive_active:
            return

        now = datetime.now()
        if self.overdrive_last_activity_at and now - self.overdrive_last_activity_at > timedelta(minutes=10):
            self.deactivate_overdrive()
            return

        self.overdrive_last_activity_at = now

    def _maybe_handle_overdrive_command(
        self,
        user_input: str,
        speak_response: bool,
        input_source: str,
    ) -> EngineResult | None:
        lowered = (user_input or "").lower().strip()
        if lowered in self.OVERDRIVE_ON_COMMANDS:
            if self.overdrive_active:
                msg = "Overdrive is already active."
            else:
                self.activate_overdrive()
                self.executor._audit(
                    "OVERDRIVE_ACTIVATED",
                    {
                        "action_type": "overdrive_mode",
                        "description": "activate overdrive",
                        "command": lowered,
                    },
                    source=input_source,
                )
                msg = (
                    "Overdrive is active. I'll use the deepest available reasoning and fuller audit logging, "
                    "but safety approvals still hold."
                )
            self._speak_if_enabled(msg, speak_response)
            return EngineResult(label=f"{Config.PUBLIC_NAME} (Overdrive)", response=msg, mode="overdrive")

        if lowered in self.OVERDRIVE_OFF_COMMANDS:
            if not self.overdrive_active:
                msg = "Overdrive is already off."
            else:
                self.deactivate_overdrive()
                self.executor._audit(
                    "OVERDRIVE_DEACTIVATED",
                    {
                        "action_type": "overdrive_mode",
                        "description": "deactivate overdrive",
                        "command": lowered,
                    },
                    source=input_source,
                )
                msg = "Overdrive is off. IRIS is back to the normal execution profile."
            self._speak_if_enabled(msg, speak_response)
            return EngineResult(label=f"{Config.PUBLIC_NAME} (Overdrive)", response=msg, mode="overdrive")

        if lowered in self.OVERDRIVE_STATUS_COMMANDS:
            if self.overdrive_active:
                since = (
                    self.overdrive_activated_at.strftime("%H:%M")
                    if self.overdrive_activated_at
                    else "recently"
                )
                msg = f"Overdrive is active. It has been on since {since}."
            else:
                msg = "Overdrive is off."
            self._speak_if_enabled(msg, speak_response)
            return EngineResult(label=f"{Config.PUBLIC_NAME} (Overdrive)", response=msg, mode="overdrive")

        return None

    def _apply_overdrive_to_packet(self, packet):
        if not self.overdrive_active:
            return packet

        preferred = [
            "ollama_deep",
            "claude",
            "ollama_smart",
            "groq",
            "gemini",
            "ollama_fast",
        ]
        merged = []
        for api in preferred + list(getattr(packet, "preferred_apis", []) or []):
            if api not in merged:
                merged.append(api)
        packet.preferred_apis = merged

        extra_lines = [
            packet.extra_system.strip() if packet.extra_system else "",
            "Overdrive is active.",
            "- Prefer the deepest available reasoning stack before speed-only models.",
            "- Do not widen permissions or weaken the safety contract.",
            "- Be explicit about assumptions, verification, and execution risk.",
        ]
        packet.extra_system = "\n\n".join(line for line in extra_lines if line)
        packet.allow_long_response = True
        return packet

    def listen_for_voice_command(self) -> str:
        return self.voice.listen_for_command()

    def shutdown(self) -> None:
        try:
            self.voice.stop()
        except Exception:
            pass
        try:
            self.memory._save()
        except Exception:
            pass

    def _update_self_model_after_response(self, response: str, source: str) -> None:
        lowered = (response or "").lower()
        if any(token in lowered for token in ["failed", "error", "couldn't", "didn't work", "blocked"]):
            self.self_model.note_failure(response)
            self.self_model.note_response(response, source="error")
            return

        self.self_model.note_response(response, source=source)
        if any(token in lowered for token in ["done", "created", "opened", "cancelled", "completed"]):
            self.self_model.note_success(response)

    def _speak_if_enabled(self, text: str, enabled: bool) -> None:
        if enabled:
            self.voice.speak(text)

    def contains_wake_word(self, text: str) -> bool:
        text_l = (text or "").lower().strip()
        wake_words = [w.lower() for w in getattr(Config, "WAKE_WORDS", [])]

        if any(w in text_l for w in wake_words):
            return True

        words = text_l.split()
        chunks = []
        for i in range(len(words)):
            chunks.append(words[i])
            if i + 1 < len(words):
                chunks.append(f"{words[i]} {words[i + 1]}")

        threshold = getattr(Config, "WAKE_FUZZY_THRESHOLD", 0.82)
        for wake in wake_words:
            for chunk in chunks:
                if difflib.SequenceMatcher(None, chunk, wake).ratio() >= threshold:
                    return True

        return False

    def strip_wake_word(self, text: str) -> str:
        cleaned = (text or "").strip()
        text_l = cleaned.lower()

        for wake in sorted(getattr(Config, "WAKE_WORDS", []), key=len, reverse=True):
            wake_l = wake.lower()
            if text_l.startswith(wake_l):
                return cleaned[len(wake):].strip(" ,:.-")

        parts = cleaned.split(maxsplit=1)
        if len(parts) == 2 and self.contains_wake_word(parts[0]):
            return parts[1].strip()

        return cleaned

    def should_end_followup(self, text: str) -> bool:
        lowered = (text or "").lower().strip()
        return any(
            token in lowered
            for token in ["stop", "bye", "goodbye", "that's all", "thanks iris", "thank you iris"]
        )
