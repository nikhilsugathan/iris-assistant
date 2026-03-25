"""
IRIS Runtime Engine
===================
Reusable session engine for GUI and terminal entry points.
"""

from __future__ import annotations

import difflib
import re
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
from core.runtime_log import log_runtime
from core.self_model import SelfModel
from core.voice import Voice


@dataclass
class EngineResult:
    label: str
    response: str
    should_exit: bool = False
    mode: str = "chat"
    exit_immediately: bool = False
    speech_started: bool = False


class IRISEngine:
    SHUTDOWN_COMMANDS = {
        "exit",
        "quit",
        "goodbye iris",
        "shutdown",
    }
    TERMINATE_COMMANDS = {
        "terminate",
        "terminate iris",
        "iris terminate",
        "terminate immediately",
    }
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
        snapshot = {
            "public_name": Config.PUBLIC_NAME,
            "system_name": Config.SYSTEM_NAME,
            "inner_codename": Config.INNER_CODENAME,
            "primary_brain": Config.PRIMARY_BRAIN,
            "fallback_brain": Config.FALLBACK_BRAIN,
            "voice_state": getattr(self.voice, "current_state", "idle"),
            "audio_ready": getattr(self.voice, "audio_ready", False),
            "mic_ready": getattr(self.voice, "mic_ready", False),
            "selected_mic_name": getattr(self.voice, "selected_mic_name", ""),
            "last_listen_status": getattr(self.voice, "last_listen_status", "idle"),
            "last_listen_detail": getattr(self.voice, "last_listen_detail", ""),
            "last_transcript_backend": getattr(self.voice, "last_transcript_backend", ""),
            "last_transcript_confidence": getattr(self.voice, "last_transcript_confidence", 0.0),
            "last_transcript_language": getattr(self.voice, "last_transcript_language", ""),
            "last_transcript_attempts": getattr(self.voice, "last_transcript_attempts", ""),
            "last_transcript_uncertain": getattr(self.voice, "last_transcript_uncertain", False),
            "last_rejected_wake_text": getattr(self.voice, "last_rejected_wake_text", ""),
            "last_rejected_wake_backend": getattr(self.voice, "last_rejected_wake_backend", ""),
            "last_rejected_wake_confidence": getattr(self.voice, "last_rejected_wake_confidence", 0.0),
            "last_rejected_wake_score": getattr(self.voice, "last_rejected_wake_score", 0.0),
            "last_capture_duration_ms": getattr(self.voice, "last_capture_duration_ms", 0),
            "last_transcription_duration_ms": getattr(self.voice, "last_transcription_duration_ms", 0),
            "last_total_listen_duration_ms": getattr(self.voice, "last_total_listen_duration_ms", 0),
            "last_tts_backend": getattr(self.voice, "last_tts_backend", ""),
            "wake_words": list(getattr(Config, "WAKE_WORDS", [])),
            "self_model": self.self_model.summary(),
            "memory": self.memory.summary(),
            "overdrive_active": self.overdrive_active,
            "overdrive_activated_at": self.overdrive_activated_at.isoformat(timespec="seconds")
            if self.overdrive_activated_at
            else None,
        }
        snapshot.update(self.executor.background_task_snapshot())
        snapshot.update(self.executor.focus_mode_snapshot())
        return snapshot

    def drain_background_updates(self) -> list[dict]:
        return self.executor.drain_background_updates()

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
            skip_autocorrect = False
            log_runtime(
                "engine_input_received",
                text=user_input[:240],
                input_source=inferred_source,
                speak_response=bool(speak_response),
            )

            if self._should_reprompt_uncertain_voice(inferred_source):
                message = self._uncertain_voice_prompt()
                log_runtime(
                    "engine_uncertain_voice_reprompt",
                    text=user_input[:240],
                    input_source=inferred_source,
                )
                self._speak_if_enabled(message, speak_response)
                return EngineResult(label=Config.PUBLIC_NAME, response=message, mode="voice-repeat")

            lowered_input = user_input.lower()

            if self._is_terminate_command(lowered_input):
                try:
                    self.voice.stop_speaking()
                except Exception:
                    pass
                msg = "Terminating now."
                return EngineResult(
                    label=Config.PUBLIC_NAME,
                    response=msg,
                    should_exit=True,
                    mode="terminate",
                    exit_immediately=True,
                )

            if lowered_input in self.SHUTDOWN_COMMANDS:
                msg = "Shutting down. Try not to break anything while I'm gone."
                self._speak_if_enabled(msg, speak_response)
                return EngineResult(label=Config.PUBLIC_NAME, response=msg, should_exit=True, mode="shutdown")

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
                if self._should_supersede_pending_permission(user_input):
                    previous_action = self.executor.pending_action_snapshot()
                    self.executor.cancel_pending_action(reason="superseded_by_new_input")
                    skip_autocorrect = True
                    log_runtime(
                        "engine_permission_superseded",
                        new_input=user_input[:240],
                        input_source=inferred_source,
                        previous_action=previous_action,
                    )
                else:
                    response = self.executor.handle_permission_response(user_input)
                    log_runtime(
                        "engine_permission_response",
                        text=user_input[:240],
                        input_source=inferred_source,
                        response=response[:240],
                    )
                    self._update_self_model_after_response(response, "permission")
                    self._speak_if_enabled(response, speak_response)
                    return EngineResult(label=Config.PUBLIC_NAME, response=response, mode="permission")

            if not skip_autocorrect:
                corrected, _ = self.autocorrect.correct_input(user_input)
                if corrected != user_input:
                    log_runtime(
                        "engine_input_corrected",
                        original=user_input[:240],
                        corrected=corrected[:240],
                        input_source=inferred_source,
                    )
                user_input = corrected
            else:
                log_runtime(
                    "engine_autocorrect_skipped",
                    text=user_input[:240],
                    input_source=inferred_source,
                    reason="superseded_pending_permission",
                )

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

            decision = self.dialog_manager.analyze(
                user_input,
                self.executor,
                self.copilot,
                self.diagnostics,
                self.self_model,
            )
            log_runtime(
                "engine_decision",
                text=user_input[:240],
                mode=getattr(decision, "mode", "unknown"),
                reason=getattr(decision, "reason", ""),
                tone=getattr(decision, "tone", ""),
                depth=getattr(decision, "depth", ""),
                input_source=inferred_source,
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
                log_runtime("engine_response", mode="diagnostics", response=response[:240])
                self._update_self_model_after_response(response, "diagnostics")
                self._speak_if_enabled(response, speak_response)
                return EngineResult(label=f"{Config.PUBLIC_NAME} (Diagnostics)", response=response, mode="diagnostics")

            if self.copilot.active:
                response = self.copilot.handle_input(user_input)
                if response:
                    log_runtime("engine_response", mode="copilot", response=response[:240])
                    self._update_self_model_after_response(response, "copilot")
                    self._speak_if_enabled(response, speak_response)
                return EngineResult(label=f"{Config.PUBLIC_NAME} (Co-Pilot)", response=response or "", mode="copilot")

            if decision.mode == "copilot":
                response = self.copilot.start(user_input)
                log_runtime("engine_response", mode="copilot", response=response[:240])
                self._update_self_model_after_response(response, "copilot")
                self._speak_if_enabled(response, speak_response)
                return EngineResult(label=f"{Config.PUBLIC_NAME} (Co-Pilot)", response=response, mode="copilot")

            if decision.mode == "action":
                response = self.executor.plan_action(user_input)
                log_runtime("engine_response", mode="action", response=response[:240])
                self._update_self_model_after_response(response, "action")
                self._speak_if_enabled(response, speak_response)
                return EngineResult(label=f"{Config.PUBLIC_NAME} (Action)", response=response, mode="action")

            packet = self.council.deliberate(user_input, decision, self.self_model)
            packet = self._apply_overdrive_to_packet(packet)
            self.self_model.apply_council(packet.roles)
            stream_state = self._make_voice_stream_state(
                input_source=inferred_source,
                speak_response=speak_response,
                allow_long_response=bool(getattr(packet, "allow_long_response", False)),
            )
            response = self.brain.think_with_stream(
                user_input,
                council_packet=packet,
                stream_callback=stream_state["callback"],
            )
            log_runtime(
                "engine_response",
                mode=decision.mode,
                response=response[:240],
                speech_started=bool(stream_state["started"]),
            )
            self._update_self_model_after_response(response, "brain")
            self._speak_if_enabled(response, speak_response)
            return EngineResult(
                label=Config.PUBLIC_NAME,
                response=response,
                mode=decision.mode,
                speech_started=bool(stream_state["started"]),
            )

    def _should_supersede_pending_permission(self, user_input: str) -> bool:
        text = (user_input or "").strip()
        if not text:
            return False
        if self.executor.is_permission_response(text):
            return False

        lowered = text.lower()
        if self.diagnostics.should_handle(lowered):
            return True
        if self.copilot.should_activate(lowered):
            return True
        if self.executor.should_handle(lowered):
            return True

        question_like_prefixes = (
            "what ",
            "what's ",
            "what is ",
            "why ",
            "how ",
            "when ",
            "where ",
            "who ",
            "can you ",
            "could you ",
            "would you ",
            "please ",
            "tell me ",
            "show me ",
        )
        return lowered.endswith("?") or lowered.startswith(question_like_prefixes)

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

    def listen_for_voice_command(self, interrupt_speech: bool = True) -> str:
        return self.voice.listen_for_command(interrupt_speech=interrupt_speech)

    def process_voice_turn(
        self,
        command_text: str,
        *,
        input_source: str = "voice",
        enable_slow_ack: bool = True,
    ) -> EngineResult:
        ack_token = self.begin_slow_voice_ack(command_text, enabled=enable_slow_ack)
        try:
            return self.process_user_input(command_text, speak_response=False, input_source=input_source)
        finally:
            self.finish_slow_voice_ack(ack_token, stop_audio=True)

    def _make_voice_stream_state(self, input_source: str, speak_response: bool, allow_long_response: bool) -> dict:
        state = {"started": False, "callback": None}
        if speak_response:
            return state
        if input_source != "voice":
            return state
        if not getattr(Config, "OLLAMA_STREAM_VOICE_RESPONSES", True):
            return state
        if not getattr(self.voice, "audio_ready", False):
            return state

        max_sentences = max(
            1,
            int(getattr(Config, "VOICE_MAX_SENTENCES", 2)),
        )
        if allow_long_response or not bool(getattr(Config, "SHORT_VOICE_RESPONSES", False)):
            max_sentences = 999

        sequence_id = None
        spoken_sentences = 0

        def stream_callback(text: str) -> None:
            nonlocal sequence_id, spoken_sentences
            chunk = str(text or "").strip()
            if not chunk:
                return
            if spoken_sentences >= max_sentences:
                return

            if callable(getattr(self.voice, "begin_background_speech_sequence", None)) and callable(
                getattr(self.voice, "queue_background_speech", None)
            ):
                if sequence_id is None:
                    sequence_id = self.voice.begin_background_speech_sequence(cancel_pending=True)
                    interrupt_current = True
                else:
                    interrupt_current = False
                self.voice.queue_background_speech(
                    chunk,
                    generation_id=sequence_id,
                    interrupt_current=interrupt_current,
                )
            else:
                self.voice.speak_background(chunk)
            state["started"] = True
            spoken_sentences += 1

        state["callback"] = stream_callback
        return state

    def should_hold_voice_followup_open(self) -> bool:
        return any(
            (
                self.executor.waiting_for_followup(),
                self.executor.waiting_for_clarification(),
                self.executor.waiting_for_plan_choice(),
                self.executor.waiting_for_presence_check(),
                self.executor.waiting_for_permission(),
                bool(getattr(self.copilot, "active", False)),
            )
        )

    def begin_slow_voice_ack(self, user_input: str, enabled: bool = True):
        if not enabled or not getattr(self.voice, "audio_ready", False):
            return None

        delay_ms = max(0, int(getattr(Config, "ACK_ON_SLOW_THINK_MS", 0)))
        if delay_ms <= 0:
            return None

        ack_text = self.brain.quick_ack(user_input)
        if not ack_text:
            thinking_acks = list(getattr(Config, "THINKING_ACKS", []) or [])
            ack_text = thinking_acks[0].strip() if thinking_acks else ""
        if not ack_text:
            return None

        stop_event = threading.Event()

        def delayed_ack():
            if stop_event.wait(delay_ms / 1000):
                return
            try:
                self.voice.speak_background(ack_text)
            except Exception:
                pass

        threading.Thread(target=delayed_ack, daemon=True).start()
        return stop_event

    def finish_slow_voice_ack(self, token, stop_audio: bool = True) -> None:
        if token is None:
            return
        try:
            token.set()
        except Exception:
            return
        if not stop_audio:
            return
        try:
            self.voice.stop_speaking()
        except Exception:
            pass

    def shutdown(self) -> None:
        try:
            self.voice.stop()
        except Exception:
            pass
        try:
            close = getattr(self.memory, "close", None)
            if callable(close):
                close()
            else:
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

    def _should_reprompt_uncertain_voice(self, input_source: str) -> bool:
        if input_source != "voice":
            return False
        return bool(getattr(self.voice, "last_transcript_uncertain", False))

    def _uncertain_voice_prompt(self) -> str:
        describe = getattr(self.voice, "describe_uncertain_transcript", None)
        if callable(describe):
            message = str(describe() or "").strip()
            if message:
                return message
        return "That sounded uncertain. Please say it again."

    def _is_terminate_command(self, lowered_input: str) -> bool:
        lowered_input = (lowered_input or "").strip()
        if lowered_input in self.TERMINATE_COMMANDS:
            return True

        tokens = re.findall(r"[a-z]+", lowered_input)
        if not tokens or "terminate" not in tokens:
            return False

        blocked_context = {
            "command", "commands", "why", "what", "when", "how", "meaning",
            "means", "meant", "example", "examples", "test", "testing",
        }
        if any(token in blocked_context for token in tokens):
            return False

        if len(tokens) <= 4:
            return True

        if Config.PUBLIC_NAME.lower() in tokens and len(tokens) <= 6:
            return True

        if any(token in {"now", "immediately", "app", "application"} for token in tokens):
            return True

        return False

    def contains_wake_word(self, text: str) -> bool:
        text_l = (text or "").lower().strip()
        wake_words = [w.lower() for w in getattr(Config, "WAKE_WORDS", [])]

        if any(w in text_l for w in wake_words):
            return True

        if self._leading_wake_match(text_l):
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

    def normalize_wake_transcript(self, text: str) -> str:
        cleaned = (text or "").strip()
        if not cleaned:
            return ""

        match = self._leading_wake_match(cleaned.lower())
        if not match:
            return cleaned

        matched_phrase, canonical_wake = match
        phrase_tokens = re.findall(r"[a-z0-9']+", matched_phrase.lower())
        if phrase_tokens:
            prefix_pattern = r"^\s*" + r"[^a-z0-9']*".join(re.escape(token) for token in phrase_tokens)
            prefix_match = re.match(prefix_pattern, cleaned.lower())
            cut_index = prefix_match.end() if prefix_match else len(matched_phrase)
        else:
            cut_index = len(matched_phrase)

        remainder = cleaned[cut_index:].strip(" ,:.-")
        canonical_display = canonical_wake.capitalize()
        return f"{canonical_display} {remainder}".strip()

    def strip_wake_word(self, text: str) -> str:
        cleaned = self.normalize_wake_transcript(text)
        text_l = cleaned.lower()

        for wake in sorted(getattr(Config, "WAKE_WORDS", []), key=len, reverse=True):
            wake_l = wake.lower()
            if text_l.startswith(wake_l):
                return cleaned[len(wake):].strip(" ,:.-")

        parts = cleaned.split(maxsplit=1)
        if len(parts) == 2 and self.contains_wake_word(parts[0]):
            return parts[1].strip()

        return cleaned

    def _leading_wake_match(self, text: str) -> tuple[str, str] | None:
        raw = (text or "").strip().lower()
        if not raw:
            return None

        wake_aliases = getattr(Config, "WAKE_WORD_ALIASES", {}) or {}
        wake_prefixes = [
            str(prefix or "").strip().lower()
            for prefix in getattr(Config, "WAKE_WORD_PREFIXES", []) or []
            if str(prefix or "").strip()
        ]
        variants: list[tuple[str, str]] = []

        for wake in getattr(Config, "WAKE_WORDS", []) or []:
            wake_l = str(wake or "").lower().strip()
            if not wake_l:
                continue
            variants.append((wake_l, wake_l))
            for prefix in wake_prefixes:
                variants.append((f"{prefix} {wake_l}".strip(), wake_l))
            for alias in wake_aliases.get(wake_l, []) or []:
                alias_l = str(alias or "").lower().strip()
                if alias_l:
                    variants.append((alias_l, wake_l))
                    for prefix in wake_prefixes:
                        variants.append((f"{prefix} {alias_l}".strip(), wake_l))

        normalized = re.sub(r"[^a-z0-9'\s]+", " ", raw)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        if not normalized:
            return None

        for variant, canonical in sorted(variants, key=lambda item: len(item[0]), reverse=True):
            variant_norm = re.sub(r"[^a-z0-9'\s]+", " ", variant)
            variant_norm = re.sub(r"\s+", " ", variant_norm).strip()
            if not variant_norm:
                continue
            if normalized == variant_norm:
                return variant, canonical
            if normalized.startswith(f"{variant_norm} "):
                return variant, canonical

        return None

    def should_end_followup(self, text: str) -> bool:
        lowered = (text or "").lower().strip()
        return any(
            token in lowered
            for token in ["stop", "bye", "goodbye", "that's all", "thanks iris", "thank you iris"]
        )
