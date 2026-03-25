"""
IRIS Voice Module v4
====================
STT  : Windows wake recognition, optional local faster-whisper for commands,
       then Groq Whisper and Google fallback
TTS  : Optional Piper local neural voice, then Windows SAPI and Edge fallback
"""

import asyncio
import ctypes
import difflib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import time
import wave
from dataclasses import dataclass

from rich.console import Console
from config import Config
from core.resource_guard import ResourceGuard
from core.runtime_log import log_runtime
from core.subprocess_utils import hidden_process_kwargs

console = Console()


@dataclass
class TranscriptCandidate:
    backend: str
    text: str = ""
    confidence: float = 0.0
    language: str = ""


class Voice:
    def __init__(self, text_mode: bool = False):
        self.text_mode       = text_mode
        self._tts_lock       = threading.Lock()
        self._mic_lock       = threading.Lock()
        self._stop_flag      = threading.Event()
        self._speech_generation_lock = threading.Lock()
        self._speech_generation = 0
        self._state_callback = None
        self.current_state   = "idle"
        self.audio_ready     = False
        self.mic_ready       = False
        self.mic_error       = None
        self._local_tts_engine = None
        self.resource_guard = ResourceGuard()
        self.calibrated      = False
        self.selected_mic_name  = "Default"
        self.selected_mic_index = None
        self.recognizer      = None
        self.microphone      = None
        self.last_listen_status = "idle"
        self.last_listen_detail = ""
        self.last_calibrated_at = 0.0
        self.listen_failures = 0
        self.last_transcript_backend = ""
        self.last_transcript_confidence = 0.0
        self.last_transcript_language = ""
        self.last_tts_backend = ""
        self.last_capture_duration_ms = 0
        self.last_transcription_duration_ms = 0
        self.last_total_listen_duration_ms = 0
        self.last_transcript_attempts = ""
        self.last_transcript_uncertain = False
        self.last_uncertain_transcript = ""
        self.last_uncertain_transcript_backend = ""
        self.last_uncertain_transcript_confidence = 0.0
        self.last_rejected_wake_text = ""
        self.last_rejected_wake_backend = ""
        self.last_rejected_wake_confidence = 0.0
        self.last_rejected_wake_score = 0.0
        self._recent_command_language = ""
        self._recent_wake_language = ""
        self._faster_whisper_model = None
        self._faster_whisper_model_key = ""
        self._faster_whisper_error = ""
        self._piper_tts_voice = None
        self._piper_tts_voice_key = ""
        self._piper_tts_error = ""
        self._local_whisper_runtime_cache = None
        self._local_whisper_runtime_override = None

        self._init_audio()
        self._init_mic()
        self._warm_tts_backends_async()
        log_runtime(
            "voice_initialized",
            text_mode=self.text_mode,
            audio_ready=self.audio_ready,
            mic_ready=self.mic_ready,
            selected_mic=self.selected_mic_name,
            mic_error=self.mic_error,
        )

    # ─────────────────────────────────────────────────────────────
    # INIT
    # ─────────────────────────────────────────────────────────────

    def _init_audio(self):
        try:
            import pygame
            pygame.mixer.pre_init(
                frequency=getattr(Config, "AUDIO_SAMPLE_RATE", 24000),
                size=-16,
                channels=getattr(Config, "AUDIO_CHANNELS", 2),
                buffer=getattr(Config, "AUDIO_BUFFER_SIZE", 512),
            )
            pygame.mixer.init()
            self._prime_audio_output()
            self.audio_ready = True
            console.print("[green]✓ Audio playback ready[/green]")
            log_runtime("audio_ready", backend="pygame")
        except Exception as e:
            console.print(f"[red]Audio init failed:[/red] {e}")
            log_runtime("audio_init_failed", error=str(e))

    def _warm_tts_backends_async(self) -> None:
        if not self.audio_ready:
            return
        if not bool(getattr(Config, "PIPER_TTS_WARMUP", True)):
            return

        worker = threading.Thread(target=self._warm_tts_backends, daemon=True)
        worker.start()

    def _warm_tts_backends(self) -> None:
        try:
            if self._supports_piper():
                log_runtime("piper_warm_start", voice=getattr(Config, "PIPER_TTS_VOICE", ""))
                warmed = self._get_piper_tts_voice() is not None
                log_runtime("piper_warm_result", warmed=warmed, voice=getattr(Config, "PIPER_TTS_VOICE", ""))
        except Exception as exc:
            log_runtime("piper_warm_failed", error=str(exc), voice=getattr(Config, "PIPER_TTS_VOICE", ""))

    def set_state_callback(self, callback):
        self._state_callback = callback

    def _emit_state(self, state: str):
        if state == self.current_state:
            return
        previous = self.current_state
        self.current_state = state
        log_runtime("voice_state", previous=previous, state=state)
        callback = self._state_callback
        if not callback:
            return
        try:
            callback(state)
        except Exception:
            pass

    def _init_mic(self):
        if self.text_mode:
            return
        try:
            import speech_recognition as sr
            self.recognizer = sr.Recognizer()
            self.recognizer.dynamic_energy_threshold = bool(
                getattr(Config, "MIC_DYNAMIC_ENERGY_THRESHOLD", True)
            )
            self.recognizer.dynamic_energy_adjustment_damping = float(
                getattr(Config, "MIC_DYNAMIC_ENERGY_ADJUSTMENT_DAMPING", 0.18)
            )
            self.recognizer.dynamic_energy_ratio = float(
                getattr(Config, "MIC_DYNAMIC_ENERGY_RATIO", 1.6)
            )
            self.recognizer.energy_threshold         = getattr(Config, "MIC_ENERGY_THRESHOLD", 50)
            self.recognizer.pause_threshold          = getattr(Config, "MIC_PAUSE_THRESHOLD", 0.6)
            self.recognizer.phrase_threshold         = getattr(Config, "MIC_PHRASE_THRESHOLD", 0.2)
            self.recognizer.non_speaking_duration    = getattr(Config, "MIC_NON_SPEAKING_DURATION", 0.3)

            mic_names = sr.Microphone.list_microphone_names()
            preferred = getattr(Config, "PREFERRED_MIC_NAME", "").strip()
            mic_index, mic_name = self._select_microphone_device(mic_names, preferred)

            self.microphone = sr.Microphone(
                device_index=mic_index,
                sample_rate=getattr(Config, "MIC_SAMPLE_RATE", 16000),
                chunk_size=getattr(Config, "MIC_CHUNK_SIZE", 1024),
            )
            self.selected_mic_index = mic_index
            self.selected_mic_name  = mic_name
            self.mic_ready          = True

            console.print(f"[green]✓ Microphone ready[/green] [dim]({mic_name})[/dim]")
            log_runtime(
                "microphone_ready",
                selected_mic=mic_name,
                selected_index=mic_index,
                preferred=str(preferred or ""),
                available_count=len(mic_names),
            )

            if mic_names:
                console.print("[dim]Available microphones:[/dim]")
                for i, name in enumerate(mic_names):
                    console.print(f"[dim]  {i}: {name}[/dim]")

            self._calibrate()

        except Exception as e:
            self.mic_error = str(e)
            console.print(f"[red]Microphone init failed:[/red] {e}")
            log_runtime("microphone_init_failed", error=str(e))

    def _select_microphone_device(self, mic_names: list[str], preferred: str) -> tuple[int | None, str]:
        preferred = str(preferred or "").strip()
        if not preferred:
            default_name = self._default_microphone_name(mic_names)
            return None, default_name

        if not mic_names:
            return None, "Default Windows microphone"

        ranked = sorted(
            ((self._score_microphone_name(name, preferred), index, name) for index, name in enumerate(mic_names)),
            key=lambda item: (-item[0], item[1]),
        )

        best_score, best_index, best_name = ranked[0]
        if best_score <= -100:
            return None, "Default Windows microphone"

        if len(ranked) > 1:
            preview = ", ".join(
                f"{idx}:{name.strip()} ({score})"
                for score, idx, name in ranked[:3]
                if score > -100
            )
            if preview:
                console.print(f"[dim]Top microphone candidates:[/dim] {preview}")

        return best_index, best_name

    def _default_microphone_name(self, mic_names: list[str]) -> str:
        try:
            import pyaudio

            audio = pyaudio.PyAudio()
            try:
                info = audio.get_default_input_device_info()
            finally:
                audio.terminate()
            default_name = str(info.get("name", "") or "").strip()
            if default_name:
                return f"{default_name} [Windows default]"
        except Exception:
            pass

        if mic_names:
            return "Default Windows microphone"
        return "No microphone detected"

    def _score_microphone_name(self, name: str, preferred: str) -> int:
        normalized = self._normalize_microphone_name(name)
        preferred = self._normalize_microphone_name(preferred)
        score = 0

        if not normalized:
            return -1000

        if preferred:
            if preferred in normalized:
                score += 120
            else:
                score -= 20

        if normalized.startswith("microphone array (") or "mic array input" in normalized:
            score += 115
        if normalized.startswith("microphone ("):
            score += 85
        if "microphone array" in normalized:
            score += 45
        if "mic input" in normalized and "array" not in normalized:
            score -= 35
        if normalized.startswith("headset microphone"):
            score -= 105

        if "hands-free" in normalized or "bthhfenum" in normalized:
            score -= 120
        if "@system32" in normalized:
            score -= 80
        if "mapper" in normalized or "primary sound" in normalized:
            score -= 120
        if normalized.startswith("input ("):
            score -= 90
        if "stereo mix" in normalized:
            score -= 140
        if "output" in normalized or "speaker" in normalized or "headphones" in normalized:
            score -= 160

        if "realtek" in normalized or "turtle beach" in normalized:
            score += 15

        if preferred:
            preferred_tokens = [token for token in re.split(r"[^a-z0-9]+", preferred) if len(token) >= 3]
            token_hits = sum(1 for token in preferred_tokens if token in normalized)
            score += token_hits * 12

        return score

    def _normalize_microphone_name(self, text: str) -> str:
        normalized = str(text or "").lower().strip()
        normalized = re.sub(r"\bg(\d+)\b", r"gen \1", normalized)
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized

    def _calibrate(self):
        if not self.mic_ready or self.calibrated:
            return
        try:
            with self._mic_lock:
                with self.microphone as source:
                    if not self._source_stream_ready(source):
                        raise RuntimeError(
                            "Microphone stream did not open during calibration. Check whether another app is using the mic."
                        )
                    console.print("[dim]Calibrating microphone... stay quiet.[/dim]")
                    self._recalibrate_with_source(
                        source,
                        duration=getattr(Config, "MIC_CALIBRATION_SECONDS", 2.0),
                    )
            self.calibrated = True
            console.print(
                f"[green]✓ Calibration complete[/green] "
                f"[dim](energy={self.recognizer.energy_threshold:.0f})[/dim]"
            )
            log_runtime(
                "microphone_calibrated",
                selected_mic=self.selected_mic_name,
                energy_threshold=getattr(self.recognizer, "energy_threshold", 0),
            )
        except Exception as e:
            console.print(f"[yellow]Calibration warning:[/yellow] {e}")
            log_runtime("microphone_calibration_warning", error=str(e), selected_mic=self.selected_mic_name)

    def _source_stream_ready(self, source) -> bool:
        try:
            return getattr(source, "stream", None) is not None
        except Exception:
            return False

    def _recalibrate_with_source(self, source, duration: float) -> None:
        if not self._source_stream_ready(source):
            raise RuntimeError("Microphone stream is not active for recalibration.")
        self.recognizer.adjust_for_ambient_noise(source, duration=max(0.1, float(duration)))
        self._clamp_energy_threshold()
        self.last_calibrated_at = time.time()
        self.listen_failures = 0
        self.calibrated = True
        log_runtime(
            "microphone_recalibrated",
            selected_mic=self.selected_mic_name,
            energy_threshold=getattr(self.recognizer, "energy_threshold", 0),
        )

    def _clamp_energy_threshold(self) -> None:
        recognizer = getattr(self, "recognizer", None)
        if recognizer is None or not hasattr(recognizer, "energy_threshold"):
            return

        minimum = max(1, int(getattr(Config, "MIC_ENERGY_THRESHOLD", 60) or 60))
        maximum = max(minimum, int(getattr(Config, "MIC_MAX_ENERGY_THRESHOLD", 4000) or 4000))
        try:
            recognizer.energy_threshold = max(
                minimum,
                min(maximum, int(getattr(recognizer, "energy_threshold", minimum) or minimum)),
            )
        except Exception:
            pass

    def _maybe_recalibrate(self, source, wake_mode: bool) -> None:
        now = time.time()
        max_age = max(15, int(getattr(Config, "MIC_AUTO_RECALIBRATE_SECONDS", 180)))
        failure_threshold = max(1, int(getattr(Config, "MIC_RECALIBRATE_ON_FAILURES", 2)))
        quick_duration = float(getattr(Config, "MIC_RECALIBRATION_QUICK_SECONDS", 0.35))

        should_recalibrate = not self.calibrated
        should_recalibrate = should_recalibrate or (self.last_calibrated_at and (now - self.last_calibrated_at) >= max_age)
        should_recalibrate = should_recalibrate or (self.listen_failures >= failure_threshold)

        if not should_recalibrate:
            return

        duration = getattr(Config, "MIC_CALIBRATION_SECONDS", 2.0) if not self.calibrated else quick_duration
        if not wake_mode and self.listen_failures >= failure_threshold:
            console.print("[dim]Recalibrating microphone for the current room noise...[/dim]")
        try:
            if not self._source_stream_ready(source):
                return
            self._recalibrate_with_source(source, duration=duration)
        except Exception as e:
            console.print(f"[yellow]Mic recalibration warning:[/yellow] {e}")
            log_runtime("microphone_recalibration_warning", wake_mode=wake_mode, error=str(e))

    # ─────────────────────────────────────────────────────────────
    # LISTEN
    # ─────────────────────────────────────────────────────────────

    def listen_text(self) -> str:
        return input("You: ")

    def listen_for_wake(self) -> str:
        if self.text_mode:
            return self.listen_text()
        time.sleep(0.2)   # Brief cooldown to avoid TTS echo
        log_runtime("wake_listen_requested", selected_mic=self.selected_mic_name)
        return self._listen(
            timeout=getattr(Config, "WAKE_TIMEOUT", 8),
            phrase_time_limit=getattr(Config, "WAKE_PHRASE_LIMIT", 10),
            wake_mode=True,
        )

    def listen_for_command(self, interrupt_speech: bool = True) -> str:
        if self.text_mode:
            return self.listen_text()
        # Stop Iris speaking if she is — user interrupted
        if interrupt_speech:
            self.stop_speaking()
        log_runtime(
            "command_listen_requested",
            selected_mic=self.selected_mic_name,
            interrupt_speech=interrupt_speech,
        )
        return self._listen(
            timeout=getattr(Config, "MIC_TIMEOUT", 6),
            phrase_time_limit=getattr(Config, "MIC_PHRASE_LIMIT", 12),
            wake_mode=False,
        )

    def _listen(self, timeout: int, phrase_time_limit: int, wake_mode: bool) -> str:
        import speech_recognition as sr

        if not self.mic_ready or self.microphone is None:
            self.last_listen_status = "mic_unavailable"
            self.last_listen_detail = self.mic_error or "Microphone is not ready."
            self.last_capture_duration_ms = 0
            self.last_transcription_duration_ms = 0
            self.last_total_listen_duration_ms = 0
            time.sleep(1)
            return ""

        active_state = "listening"
        settle_state = "standby" if wake_mode else "idle"
        self.last_listen_status = "listening"
        self.last_listen_detail = ""
        self.last_capture_duration_ms = 0
        self.last_transcription_duration_ms = 0
        self.last_total_listen_duration_ms = 0
        self.last_transcript_uncertain = False
        self.last_uncertain_transcript = ""
        self.last_uncertain_transcript_backend = ""
        self.last_uncertain_transcript_confidence = 0.0
        self._emit_state(active_state)
        log_runtime(
            "listen_started",
            wake_mode=wake_mode,
            timeout=timeout,
            phrase_time_limit=phrase_time_limit,
            selected_mic=self.selected_mic_name,
            state=active_state,
        )
        listen_started_at = time.perf_counter()
        try:
            with self._mic_lock:
                with self.microphone as source:
                    if not self._source_stream_ready(source):
                        raise RuntimeError(
                            "Microphone stream failed to open. Another app may be using the selected input device."
                        )
                    self._maybe_recalibrate(source, wake_mode=wake_mode)
                    self._clamp_energy_threshold()
                    if not wake_mode:
                        console.print("[dim]Listening...[/dim]")
                    audio = self.recognizer.listen(
                        source,
                        timeout=timeout,
                        phrase_time_limit=phrase_time_limit,
                    )
                    self.last_capture_duration_ms = int((time.perf_counter() - listen_started_at) * 1000)
        except sr.WaitTimeoutError:
            self.last_listen_status = "timeout"
            self.last_listen_detail = "No speech was detected before the listen timeout."
            self.listen_failures += 1
            self.last_total_listen_duration_ms = int((time.perf_counter() - listen_started_at) * 1000)
            log_runtime(
                "listen_timeout",
                wake_mode=wake_mode,
                total_ms=self.last_total_listen_duration_ms,
                listen_failures=self.listen_failures,
            )
            self._emit_state(settle_state)
            return ""
        except Exception as e:
            self.last_listen_status = "mic_error"
            self.last_listen_detail = str(e)
            self.listen_failures += 1
            self.last_total_listen_duration_ms = int((time.perf_counter() - listen_started_at) * 1000)
            log_runtime(
                "listen_mic_error",
                wake_mode=wake_mode,
                error=str(e),
                total_ms=self.last_total_listen_duration_ms,
                listen_failures=self.listen_failures,
            )
            self._emit_state("idle")
            if not wake_mode:
                console.print(f"[red]Mic error:[/red] {e}")
            return ""

        transcribe_started_at = time.perf_counter()
        if wake_mode:
            text = self._transcribe_wake(audio)
        else:
            text = self._transcribe_command(audio)
        self.last_transcription_duration_ms = int((time.perf_counter() - transcribe_started_at) * 1000)
        self.last_total_listen_duration_ms = int((time.perf_counter() - listen_started_at) * 1000)

        if text:
            self.last_listen_status = "uncertain_transcript" if self.last_transcript_uncertain and not wake_mode else "heard"
            self.last_listen_detail = text
            self.listen_failures = 0
            log_runtime(
                "listen_heard",
                wake_mode=wake_mode,
                status=self.last_listen_status,
                text=text,
                backend=self.last_transcript_backend,
                confidence=self.last_transcript_confidence,
                attempts=self.last_transcript_attempts,
                capture_ms=self.last_capture_duration_ms,
                transcribe_ms=self.last_transcription_duration_ms,
                total_ms=self.last_total_listen_duration_ms,
            )
            if wake_mode and getattr(Config, "SHOW_WAKE_DEBUG", True):
                console.print(f"[dim]Wake heard:[/dim] {text}")
            elif self.last_transcript_uncertain:
                console.print(f"[yellow]Uncertain transcription:[/yellow] {text}")
            elif not wake_mode:
                console.print(f"[green]You:[/green] {text}")

        elif not wake_mode:
            self.last_listen_status = "transcription_failed"
            self.last_listen_detail = "Audio was captured, but speech recognition could not produce text."
            self.listen_failures += 1
            log_runtime(
                "listen_transcription_failed",
                wake_mode=False,
                attempts=self.last_transcript_attempts,
                capture_ms=self.last_capture_duration_ms,
                transcribe_ms=self.last_transcription_duration_ms,
                total_ms=self.last_total_listen_duration_ms,
            )
            console.print("[dim]Heard audio but couldn't transcribe it.[/dim]")
        else:
            self.last_listen_status = "wake_not_understood"
            self.last_listen_detail = "Wake audio was captured, but no wake phrase was recognized."
            self.listen_failures += 1
            log_runtime(
                "wake_not_understood",
                attempts=self.last_transcript_attempts,
                capture_ms=self.last_capture_duration_ms,
                transcribe_ms=self.last_transcription_duration_ms,
                total_ms=self.last_total_listen_duration_ms,
                rejected_text=self.last_rejected_wake_text,
                rejected_backend=self.last_rejected_wake_backend,
                rejected_confidence=self.last_rejected_wake_confidence,
                rejected_score=self.last_rejected_wake_score,
            )

        self._emit_state(settle_state)
        return text or ""

    def describe_last_listen_feedback(self) -> str:
        status = getattr(self, "last_listen_status", "idle")
        detail = getattr(self, "last_listen_detail", "")

        if status == "mic_unavailable":
            return "My microphone is not ready yet. Check the selected input device and try again."
        if status == "mic_error":
            return f"My microphone hit an error: {detail or 'unknown microphone failure'}."
        if status == "timeout":
            return "I didn't hear anything that time. Try again or type your request."
        if status == "transcription_failed":
            return "I heard audio, but I couldn't turn it into text. Try speaking a little closer or type the request."
        if status == "uncertain_transcript":
            return self.describe_uncertain_transcript()
        return "That didn't come through clearly. Please try again."

    def short_last_listen_feedback(self) -> str:
        status = getattr(self, "last_listen_status", "idle")
        if status == "mic_unavailable":
            return "My microphone is not ready."
        if status == "mic_error":
            return "My microphone ran into a problem."
        if status == "transcription_failed":
            return "I heard you, but I couldn't make that out."
        if status == "uncertain_transcript":
            return "That sounded uncertain. Please repeat it."
        return "I didn't catch that."

    def describe_uncertain_transcript(self) -> str:
        text = str(getattr(self, "last_uncertain_transcript", "") or "").strip()
        backend = str(getattr(self, "last_uncertain_transcript_backend", "") or "").replace("_", " ").strip()
        if text and backend:
            return f"I caught something like '{text}' from {backend}, but it sounded uncertain. Please say it again."
        if text:
            return f"I caught something like '{text}', but it sounded uncertain. Please say it again."
        return "That sounded uncertain. Please say it again."

    def _transcribe_wake(self, audio) -> str:
        priority = getattr(Config, "WAKE_STT_PRIORITY", "system_first").lower().strip()
        allow_local_stt, _ = self.resource_guard.allows_local_stt()
        has_local_whisper = allow_local_stt and self._supports_faster_whisper()
        order = ["system", "google"] if allow_local_stt else ["google"]

        if priority == "adaptive":
            order = ["system", "faster_whisper", "google"] if has_local_whisper else ["system", "google"]
        elif priority == "google_first":
            order = ["google", "system", "faster_whisper"] if has_local_whisper else ["google", "system"]
        elif priority == "google_only":
            order = ["google"]
        elif priority in {"local_first", "faster_whisper_first"}:
            order = ["faster_whisper", "system", "google"] if has_local_whisper else ["system", "google"]
        elif priority == "faster_whisper_only":
            order = ["faster_whisper"] if has_local_whisper else ["google"]
        elif priority == "system_only":
            order = ["system"] if allow_local_stt else ["google"]
        elif priority == "system_first" and not allow_local_stt:
            order = ["google"]
        elif priority == "system_first":
            order = ["system", "faster_whisper", "google"] if has_local_whisper else ["system", "google"]

        if not allow_local_stt:
            order = [backend for backend in order if backend not in {"system", "faster_whisper"}]
            if not order:
                order = ["google"]

        log_runtime(
            "wake_transcribe_order",
            priority=priority,
            order=order,
            allow_local_stt=allow_local_stt,
            has_local_whisper=has_local_whisper,
        )
        return self._select_transcript(order, audio, wake_mode=True)

    def _transcribe_command(self, audio) -> str:
        priority = getattr(Config, "STT_PRIORITY", "adaptive").lower().strip()
        allow_local_stt, _ = self.resource_guard.allows_local_stt()
        has_local_whisper = allow_local_stt and self._supports_faster_whisper()
        order = ["groq", "system", "google"]

        if priority == "adaptive":
            order = ["groq", "system", "google"]
            if has_local_whisper:
                order = ["faster_whisper", "system", "groq", "google"]

        elif priority == "system_first":
            order = ["system", "groq", "google"]
            if has_local_whisper:
                order = ["system", "faster_whisper", "groq", "google"]

        if priority == "groq_first":
            order = ["groq", "faster_whisper", "system", "google"] if has_local_whisper else ["groq", "system", "google"]
        elif priority == "google_first":
            order = ["google", "faster_whisper", "system", "groq"] if has_local_whisper else ["google", "system", "groq"]
        elif priority in {"local_first", "faster_whisper_first"}:
            order = ["faster_whisper", "system", "groq", "google"] if has_local_whisper else ["system", "groq", "google"]
        elif priority == "system_only":
            if allow_local_stt and has_local_whisper:
                order = ["faster_whisper", "system"]
            else:
                order = ["system"] if allow_local_stt else ["groq", "google"]
        elif priority == "groq_only":
            order = ["groq"]
        elif priority == "google_only":
            order = ["google"]

        if not allow_local_stt:
            order = [backend for backend in order if backend not in {"system", "faster_whisper"}]
            if not order:
                order = ["groq", "google"]

        return self._select_transcript(order, audio, wake_mode=False)

    def _transcribe_windows(self, audio) -> str:
        return self._transcribe_windows_candidate(audio).text

    def _transcribe_windows_wake_candidate(self, audio) -> TranscriptCandidate:
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as handle:
                tmp_path = handle.name

            self._write_audio_wav(audio, tmp_path)
            escaped_path = tmp_path.replace("'", "''")
            languages = []
            for lang in self._system_stt_languages(wake_mode=True):
                safe_lang = str(lang or "").replace("'", "''")
                if safe_lang:
                    languages.append(f"'{safe_lang}'")
            language_array = ", ".join(languages)

            variants = []
            for variant in self._wake_phrase_variants():
                safe_variant = str(variant or "").replace("'", "''")
                if safe_variant:
                    variants.append(f"'{safe_variant}'")
            variant_array = ", ".join(variants)

            script = f"""
Add-Type -AssemblyName System.Speech
$path = '{escaped_path}'
$languages = @({language_array})
$variants = @({variant_array})
$best = $null
$bestScore = -1.0
foreach ($lang in $languages) {{
  try {{
    $culture = [System.Globalization.CultureInfo]::GetCultureInfo($lang)
    $engine = New-Object System.Speech.Recognition.SpeechRecognitionEngine($culture)
    $choices = New-Object System.Speech.Recognition.Choices
    foreach ($variant in $variants) {{
      [void]$choices.Add($variant)
    }}
    $builder = New-Object System.Speech.Recognition.GrammarBuilder
    $builder.Culture = $culture
    [void]$builder.Append($choices)
    $grammar = New-Object System.Speech.Recognition.Grammar($builder)
    $engine.LoadGrammar($grammar)
    $engine.InitialSilenceTimeout = [TimeSpan]::FromSeconds(1.0)
    $engine.EndSilenceTimeout = [TimeSpan]::FromMilliseconds(350)
    $engine.EndSilenceTimeoutAmbiguous = [TimeSpan]::FromMilliseconds(500)
    $engine.BabbleTimeout = [TimeSpan]::FromMilliseconds(500)
    $engine.SetInputToWaveFile($path)
    $result = $engine.Recognize()
    if ($result -and $result.Text) {{
      $confidence = 0.0
      try {{
        $confidence = [double]$result.Confidence
      }} catch {{
      }}
      if (-not $best -or $confidence -gt $bestScore) {{
        $bestScore = $confidence
        $best = [pscustomobject]@{{
          text = $result.Text
          confidence = $confidence
          language = $lang
        }}
      }}
    }}
  }} catch {{
  }}
}}
if ($best) {{
  $best | ConvertTo-Json -Compress
}}
""".strip()

            completed = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True,
                text=True,
                timeout=12,
                check=False,
                **hidden_process_kwargs(),
            )
            output = (completed.stdout or "").strip()
            if output:
                payload = output.splitlines()[-1].strip()
                try:
                    data = json.loads(payload)
                    return TranscriptCandidate(
                        backend="system",
                        text=str(data.get("text", "") or "").strip(),
                        confidence=float(data.get("confidence", 0.0) or 0.0),
                        language=str(data.get("language", "") or "").strip(),
                    )
                except Exception:
                    return TranscriptCandidate(backend="system", text=payload)
            return self._transcribe_windows_candidate(audio)
        except Exception:
            return self._transcribe_windows_candidate(audio)
        finally:
            try:
                if "tmp_path" in locals():
                    os.unlink(tmp_path)
            except Exception:
                pass

    def _transcribe_windows_candidate(self, audio) -> TranscriptCandidate:
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as handle:
                tmp_path = handle.name

            self._write_audio_wav(audio, tmp_path)
            escaped_path = tmp_path.replace("'", "''")
            languages = []
            for lang in self._system_stt_languages(wake_mode=False):
                safe_lang = str(lang or "").replace("'", "''")
                if safe_lang:
                    languages.append(f"'{safe_lang}'")
            language_array = ", ".join(languages)

            script = f"""
Add-Type -AssemblyName System.Speech
$path = '{escaped_path}'
$languages = @({language_array})
$best = $null
$bestScore = -1.0
foreach ($lang in $languages) {{
  try {{
    $culture = [System.Globalization.CultureInfo]::GetCultureInfo($lang)
    $engine = New-Object System.Speech.Recognition.SpeechRecognitionEngine($culture)
    $engine.LoadGrammar((New-Object System.Speech.Recognition.DictationGrammar))
    $engine.InitialSilenceTimeout = [TimeSpan]::FromSeconds(1.2)
    $engine.EndSilenceTimeout = [TimeSpan]::FromMilliseconds(450)
    $engine.EndSilenceTimeoutAmbiguous = [TimeSpan]::FromMilliseconds(650)
    $engine.BabbleTimeout = [TimeSpan]::FromMilliseconds(650)
    $engine.SetInputToWaveFile($path)
    $result = $engine.Recognize()
    if ($result -and $result.Text) {{
      $confidence = 0.0
      try {{
        $confidence = [double]$result.Confidence
      }} catch {{
      }}
      if (-not $best -or $confidence -gt $bestScore) {{
        $bestScore = $confidence
        $best = [pscustomobject]@{{
          text = $result.Text
          confidence = $confidence
          language = $lang
        }}
      }}
    }}
  }} catch {{
  }}
}}
if ($best) {{
  $best | ConvertTo-Json -Compress
}}
""".strip()

            completed = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True,
                text=True,
                timeout=12,
                check=False,
                **hidden_process_kwargs(),
            )
            output = (completed.stdout or "").strip()
            if output:
                payload = output.splitlines()[-1].strip()
                try:
                    data = json.loads(payload)
                    return TranscriptCandidate(
                        backend="system",
                        text=str(data.get("text", "") or "").strip(),
                        confidence=float(data.get("confidence", 0.0) or 0.0),
                        language=str(data.get("language", "") or "").strip(),
                    )
                except Exception:
                    return TranscriptCandidate(backend="system", text=payload)
            return TranscriptCandidate(backend="system")
        except Exception:
            return TranscriptCandidate(backend="system")
        finally:
            try:
                if "tmp_path" in locals():
                    os.unlink(tmp_path)
            except Exception:
                pass

    def _transcribe_groq(self, audio) -> str:
        return self._transcribe_groq_candidate(audio).text

    def _supports_faster_whisper(self) -> bool:
        if not getattr(Config, "LOCAL_WHISPER_ENABLED", True):
            return False
        if self._faster_whisper_model is not None:
            return True
        if self._faster_whisper_error:
            return False
        try:
            import faster_whisper  # noqa: F401
        except Exception:
            return False
        return True

    def _local_whisper_hardware_profile(self) -> dict[str, float | bool]:
        if self._local_whisper_runtime_cache is not None:
            return dict(self._local_whisper_runtime_cache)

        has_cuda = False
        try:
            import ctranslate2

            has_cuda = int(ctranslate2.get_cuda_device_count() or 0) > 0
        except Exception:
            has_cuda = False

        total_ram_gb = 0.0
        try:
            class MemoryStatusEx(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = MemoryStatusEx()
            status.dwLength = ctypes.sizeof(MemoryStatusEx)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                total_ram_gb = float(status.ullTotalPhys) / float(1024 ** 3)
        except Exception:
            total_ram_gb = 0.0

        profile = {
            "has_cuda": has_cuda,
            "total_ram_gb": total_ram_gb,
        }
        self._local_whisper_runtime_cache = dict(profile)
        return profile

    def _resolve_local_whisper_runtime(self) -> dict[str, str]:
        if self._local_whisper_runtime_override is not None:
            return dict(self._local_whisper_runtime_override)

        profile = self._local_whisper_hardware_profile()
        has_cuda = bool(profile.get("has_cuda"))
        total_ram_gb = float(profile.get("total_ram_gb", 0.0) or 0.0)

        device = str(getattr(Config, "LOCAL_WHISPER_DEVICE", "auto") or "auto").strip().lower() or "auto"
        model = str(getattr(Config, "LOCAL_WHISPER_MODEL", "auto") or "auto").strip() or "auto"
        compute_type = str(getattr(Config, "LOCAL_WHISPER_COMPUTE_TYPE", "auto") or "auto").strip().lower() or "auto"

        if device == "auto":
            device = "cuda" if has_cuda else "cpu"

        if model.lower() == "auto":
            if device == "cuda":
                model = "distil-large-v3"
            elif total_ram_gb >= 16:
                model = "small.en"
            elif total_ram_gb >= 8:
                model = "base"
            else:
                model = "tiny.en"

        if compute_type == "auto":
            compute_type = "float16" if device == "cuda" else "int8"

        return {
            "model": model,
            "device": device,
            "compute_type": compute_type,
        }

    def _default_cpu_local_whisper_model(self) -> str:
        profile = self._local_whisper_hardware_profile()
        total_ram_gb = float(profile.get("total_ram_gb", 0.0) or 0.0)
        if total_ram_gb >= 16:
            return "small.en"
        if total_ram_gb >= 8:
            return "base"
        return "tiny.en"

    def _cpu_local_whisper_runtime(self, model: str) -> dict[str, str]:
        configured_model = str(getattr(Config, "LOCAL_WHISPER_MODEL", "auto") or "auto").strip() or "auto"
        normalized_model = str(model or "").strip() or "base"
        if configured_model.lower() == "auto":
            normalized_model = self._default_cpu_local_whisper_model()
        return {
            "model": normalized_model,
            "device": "cpu",
            "compute_type": "int8",
        }

    def _get_faster_whisper_model(self):
        runtime = self._resolve_local_whisper_runtime()
        runtime_key = "|".join([runtime["model"], runtime["device"], runtime["compute_type"]])

        if self._faster_whisper_model is not None and self._faster_whisper_model_key == runtime_key:
            return self._faster_whisper_model
        if self._faster_whisper_model is not None and self._faster_whisper_model_key != runtime_key:
            self._faster_whisper_model = None
            self._faster_whisper_model_key = ""

        if self._faster_whisper_error and self._faster_whisper_model_key == runtime_key:
            return None

        try:
            from faster_whisper import WhisperModel

            init_options = {
                "device": runtime["device"],
                "compute_type": runtime["compute_type"],
            }
            self._faster_whisper_model = WhisperModel(runtime["model"], **init_options)
            self._faster_whisper_model_key = runtime_key
            self._faster_whisper_error = ""
            return self._faster_whisper_model
        except Exception as exc:
            if runtime["device"] == "cuda":
                fallback_runtime = self._cpu_local_whisper_runtime(runtime["model"])
                fallback_key = "|".join(
                    [fallback_runtime["model"], fallback_runtime["device"], fallback_runtime["compute_type"]]
                )
                try:
                    from faster_whisper import WhisperModel

                    self._faster_whisper_model = WhisperModel(
                        fallback_runtime["model"],
                        device=fallback_runtime["device"],
                        compute_type=fallback_runtime["compute_type"],
                    )
                    self._faster_whisper_model_key = fallback_key
                    self._faster_whisper_error = ""
                    self._local_whisper_runtime_override = dict(fallback_runtime)
                    console.print(
                        "[yellow]Local Whisper CUDA runtime unavailable; falling back to CPU int8.[/yellow]"
                    )
                    log_runtime(
                        "local_whisper_cuda_fallback",
                        error=str(exc),
                        model=runtime["model"],
                        fallback_model=fallback_runtime["model"],
                        fallback_device="cpu",
                        fallback_compute_type="int8",
                    )
                    return self._faster_whisper_model
                except Exception as fallback_exc:
                    exc = fallback_exc
            self._faster_whisper_model_key = runtime_key
            self._faster_whisper_error = str(exc)
            console.print(f"[yellow]Local Whisper unavailable:[/yellow] {exc}")
            log_runtime(
                "local_whisper_unavailable",
                error=str(exc),
                model=runtime["model"],
                device=runtime["device"],
                compute_type=runtime["compute_type"],
            )
            return None

    def _transcribe_faster_whisper_candidate(self, audio) -> TranscriptCandidate:
        model = self._get_faster_whisper_model()
        if model is None:
            return TranscriptCandidate(backend="faster_whisper")

        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as handle:
                tmp_path = handle.name

            self._write_audio_wav(audio, tmp_path)
            transcribe_options = {
                "beam_size": max(1, int(getattr(Config, "LOCAL_WHISPER_BEAM_SIZE", 1) or 1)),
                "vad_filter": True,
                "condition_on_previous_text": False,
                "temperature": 0.0,
            }
            language_hint = self._local_whisper_language_hint()
            if language_hint:
                transcribe_options["language"] = language_hint

            segments, info = model.transcribe(tmp_path, **transcribe_options)
            pieces = [str(segment.text or "").strip() for segment in segments if str(segment.text or "").strip()]
            text = " ".join(pieces).strip()
            language_probability = float(getattr(info, "language_probability", 0.0) or 0.0)
            confidence = min(0.98, max(0.55, language_probability)) if text else 0.0
            return TranscriptCandidate(
                backend="faster_whisper",
                text=text,
                confidence=confidence,
                language=str(getattr(info, "language", "") or language_hint or "").strip(),
            )
        except Exception as exc:
            self._faster_whisper_error = str(exc)
            console.print(f"[yellow]Local Whisper transcription warning:[/yellow] {exc}")
            return TranscriptCandidate(backend="faster_whisper")
        finally:
            try:
                if "tmp_path" in locals():
                    os.unlink(tmp_path)
            except Exception:
                pass

    def _transcribe_groq_candidate(self, audio) -> TranscriptCandidate:
        """Use Groq Whisper API — fastest and most accurate."""
        try:
            wav_data = self._audio_to_wav_bytes(audio)

            from groq import Groq
            client = Groq(api_key=Config.GROQ_API_KEY)
            request = {
                "file": ("audio.wav", wav_data, "audio/wav"),
                "model": "whisper-large-v3-turbo",
                "response_format": "text",
            }
            language_hint = str(getattr(Config, "STT_GROQ_LANGUAGE_HINT", "") or "").strip()
            if language_hint:
                request["language"] = language_hint

            transcription = client.audio.transcriptions.create(**request)
            return TranscriptCandidate(
                backend="groq",
                text=(transcription or "").strip(),
                confidence=1.0 if transcription else 0.0,
            )

        except Exception:
            return TranscriptCandidate(backend="groq")

    def _transcribe_google(self, audio) -> str:
        return self._transcribe_google_candidate(audio).text

    def _transcribe_google_candidate(self, audio) -> TranscriptCandidate:
        """Fallback: Google STT."""
        tried = set()
        for language in self._stt_languages():
            language = (language or "").strip()
            if not language or language in tried:
                continue
            tried.add(language)
            try:
                text = self.recognizer.recognize_google(audio, language=language).strip()
                if text:
                    return TranscriptCandidate(
                        backend="google",
                        text=text,
                        confidence=0.9,
                        language=language,
                    )
            except Exception:
                continue
        return TranscriptCandidate(backend="google")

    def _select_transcript(self, order: list[str], audio, wake_mode: bool) -> str:
        fallback_local = None
        self.last_transcript_backend = ""
        self.last_transcript_confidence = 0.0
        self.last_transcript_language = ""
        attempted: list[str] = []
        self.last_transcript_uncertain = False
        self.last_uncertain_transcript = ""
        self.last_uncertain_transcript_backend = ""
        self.last_uncertain_transcript_confidence = 0.0
        self.last_rejected_wake_text = ""
        self.last_rejected_wake_backend = ""
        self.last_rejected_wake_confidence = 0.0
        self.last_rejected_wake_score = 0.0

        for backend in order:
            attempted.append(backend)
            candidate = self._transcribe_candidate(backend, audio, wake_mode=wake_mode)
            if not candidate.text:
                continue

            if wake_mode:
                score = self._wake_phrase_score(candidate.text)
                accepted = self._accept_wake_candidate(candidate)
                log_runtime(
                    "wake_candidate",
                    backend=backend,
                    text=candidate.text,
                    confidence=candidate.confidence,
                    language=candidate.language,
                    score=score,
                    accepted=accepted,
                )
                if accepted:
                    self.last_transcript_attempts = " > ".join(attempted)
                    self._remember_transcript_candidate(candidate, wake_mode=True)
                    return candidate.text
                self._remember_rejected_wake_candidate(candidate)
                continue

            if backend == "system":
                accepted = self._accept_local_command_candidate(candidate, audio)
                if accepted:
                    self.last_transcript_attempts = " > ".join(attempted)
                    self._remember_transcript_candidate(candidate, wake_mode=False)
                    return candidate.text
                if order == ["system"]:
                    self.last_transcript_attempts = " > ".join(attempted)
                    self._remember_transcript_candidate(candidate, wake_mode=False)
                    self._mark_uncertain_transcript(candidate)
                    return candidate.text
                fallback_local = candidate
                console.print(
                    "[dim]Local transcription looked weak "
                    f"(confidence {candidate.confidence:.2f}); checking fallback recognizers.[/dim]"
                )
                continue

            if backend == "faster_whisper":
                accepted = self._accept_local_whisper_candidate(candidate, audio)
                if accepted:
                    self.last_transcript_attempts = " > ".join(attempted)
                    self._remember_transcript_candidate(candidate, wake_mode=False)
                    return candidate.text
                if order == ["faster_whisper"]:
                    self.last_transcript_attempts = " > ".join(attempted)
                    self._remember_transcript_candidate(candidate, wake_mode=False)
                    self._mark_uncertain_transcript(candidate)
                    return candidate.text
                fallback_local = candidate
                console.print(
                    "[dim]Local Whisper looked weak; checking fallback recognizers.[/dim]"
                )
                continue

            self.last_transcript_attempts = " > ".join(attempted)
            self._remember_transcript_candidate(candidate, wake_mode=False)
            return candidate.text

        if fallback_local:
            self.last_transcript_attempts = " > ".join(attempted)
            self._remember_transcript_candidate(fallback_local, wake_mode=False)
            self._mark_uncertain_transcript(fallback_local)
            return fallback_local.text
        self.last_transcript_attempts = " > ".join(attempted)
        return ""

    def _remember_transcript_candidate(self, candidate: TranscriptCandidate, wake_mode: bool = False) -> None:
        self.last_transcript_backend = candidate.backend
        self.last_transcript_confidence = float(candidate.confidence or 0.0)
        self.last_transcript_language = str(candidate.language or "")
        if self.last_transcript_language:
            if wake_mode:
                self._recent_wake_language = self.last_transcript_language
            else:
                self._recent_command_language = self.last_transcript_language

    def _mark_uncertain_transcript(self, candidate: TranscriptCandidate) -> None:
        self.last_transcript_uncertain = True
        self.last_uncertain_transcript = str(candidate.text or "").strip()
        self.last_uncertain_transcript_backend = str(candidate.backend or "")
        self.last_uncertain_transcript_confidence = float(candidate.confidence or 0.0)

    def _remember_rejected_wake_candidate(self, candidate: TranscriptCandidate) -> None:
        text = str(candidate.text or "").strip()
        if not text:
            return
        score = self._wake_phrase_score(text)
        current_score = float(getattr(self, "last_rejected_wake_score", 0.0) or 0.0)
        current_confidence = float(getattr(self, "last_rejected_wake_confidence", 0.0) or 0.0)
        candidate_confidence = float(candidate.confidence or 0.0)
        if score < current_score:
            return
        if score == current_score and candidate_confidence <= current_confidence:
            return
        self.last_rejected_wake_text = text
        self.last_rejected_wake_backend = str(candidate.backend or "")
        self.last_rejected_wake_confidence = candidate_confidence
        self.last_rejected_wake_score = score

    def _transcribe_candidate(self, backend: str, audio, wake_mode: bool = False) -> TranscriptCandidate:
        if backend == "system":
            if wake_mode:
                return self._transcribe_windows_wake_candidate(audio)
            return self._transcribe_windows_candidate(audio)
        if backend == "faster_whisper":
            return self._transcribe_faster_whisper_candidate(audio)
        if backend == "groq":
            return self._transcribe_groq_candidate(audio)
        if backend == "google":
            return self._transcribe_google_candidate(audio)
        return TranscriptCandidate(backend=backend)

    def _accept_wake_candidate(self, candidate: TranscriptCandidate) -> bool:
        text = (candidate.text or "").strip()
        if not text:
            return False
        if self._looks_like_noise_transcript(text):
            return False
        phrase_score = self._wake_phrase_score(text)
        if phrase_score < 0.75:
            return False

        threshold = float(getattr(Config, "WAKE_SYSTEM_ACCEPT_CONFIDENCE", 0.58))
        if candidate.backend == "system":
            if phrase_score >= 0.94:
                return candidate.confidence >= max(0.3, threshold - 0.2)
            if phrase_score >= 0.88:
                return candidate.confidence >= max(0.4, threshold - 0.1)
            return candidate.confidence >= threshold
        if candidate.backend == "faster_whisper":
            local_threshold = float(getattr(Config, "WAKE_LOCAL_WHISPER_ACCEPT_CONFIDENCE", 0.62))
            if phrase_score >= 0.94:
                return candidate.confidence >= max(0.4, local_threshold - 0.15)
            if phrase_score >= 0.88:
                return candidate.confidence >= max(0.48, local_threshold - 0.08)
            return candidate.confidence >= local_threshold
        return True

    def _accept_local_wake_candidate(self, candidate: TranscriptCandidate) -> bool:
        return self._accept_wake_candidate(candidate)

    def _accept_local_command_candidate(self, candidate: TranscriptCandidate, audio) -> bool:
        text = (candidate.text or "").strip()
        if not text or self._looks_like_noise_transcript(text):
            return False

        words = self._word_count(text)
        threshold = float(getattr(Config, "STT_SYSTEM_ACCEPT_CONFIDENCE", 0.82))
        if words <= 2:
            threshold = min(
                threshold,
                float(getattr(Config, "STT_SYSTEM_SHORT_ACCEPT_CONFIDENCE", 0.7)),
            )

        duration = self._audio_duration_seconds(audio)
        if duration >= float(getattr(Config, "STT_SYSTEM_LONG_AUDIO_SECONDS", 2.6)):
            minimum_words = max(1, int(getattr(Config, "STT_SYSTEM_LONG_AUDIO_MIN_WORDS", 3)))
            if words < minimum_words:
                threshold = max(threshold, 0.9)

        return candidate.confidence >= threshold

    def _accept_local_whisper_candidate(self, candidate: TranscriptCandidate, audio) -> bool:
        text = (candidate.text or "").strip()
        if not text or self._looks_like_noise_transcript(text):
            return False

        words = self._word_count(text)
        duration = self._audio_duration_seconds(audio)
        if candidate.confidence and candidate.confidence < 0.58:
            return False
        if words <= 2 and candidate.confidence and candidate.confidence < 0.72:
            return False
        if words <= 1 and duration >= 2.0:
            return False
        if duration >= 3.2 and words < 2:
            return False
        return True

    def _audio_duration_seconds(self, audio) -> float:
        sample_rate = max(1, int(getattr(audio, "sample_rate", 16000) or 16000))
        sample_width = max(1, int(getattr(audio, "sample_width", 2) or 2))
        frame_data = getattr(audio, "frame_data", b"") or b""
        return len(frame_data) / float(sample_rate * sample_width)

    def _word_count(self, text: str) -> int:
        return len(re.findall(r"[A-Za-z0-9']+", text or ""))

    def _looks_like_noise_transcript(self, text: str) -> bool:
        normalized = re.sub(r"[^a-z0-9'\s]+", " ", (text or "").lower()).strip()
        if not normalized:
            return True
        if normalized in {"uh", "um", "hmm", "huh", "ah", "the"}:
            return True
        tokens = [token for token in normalized.split() if token]
        if len(tokens) >= 3 and len(set(tokens)) == 1:
            return True
        return False

    def _wake_phrase_variants(self) -> list[str]:
        variants = []
        wake_aliases = getattr(Config, "WAKE_WORD_ALIASES", {}) or {}
        wake_prefixes = [str(prefix or "").strip().lower() for prefix in getattr(Config, "WAKE_WORD_PREFIXES", []) or []]
        for wake in getattr(Config, "WAKE_WORDS", []) or []:
            wake_text = str(wake or "").strip().lower()
            if wake_text and wake_text not in variants:
                variants.append(wake_text)
            for prefix in wake_prefixes:
                combined = f"{prefix} {wake_text}".strip()
                if prefix and combined not in variants:
                    variants.append(combined)
            for alias in wake_aliases.get(wake_text, []) or []:
                alias_text = str(alias or "").strip().lower()
                if alias_text and alias_text not in variants:
                    variants.append(alias_text)
                for prefix in wake_prefixes:
                    combined = f"{prefix} {alias_text}".strip()
                    if prefix and combined not in variants:
                        variants.append(combined)
        return variants

    def _looks_like_wake_phrase(self, text: str) -> bool:
        return self._wake_phrase_score(text) >= float(getattr(Config, "WAKE_FUZZY_THRESHOLD", 0.75))

    def _wake_phrase_score(self, text: str) -> float:
        normalized = re.sub(r"[^a-z0-9'\s]+", " ", (text or "").lower()).strip()
        if not normalized:
            return 0.0

        tokens = [token for token in normalized.split() if token]
        if not tokens:
            return 0.0

        chunks = [tokens[0]]
        if len(tokens) >= 2:
            chunks.append(f"{tokens[0]} {tokens[1]}")

        best = 0.0
        for variant in self._wake_phrase_variants():
            for chunk in chunks:
                if chunk == variant:
                    return 1.0
                best = max(best, difflib.SequenceMatcher(None, chunk, variant).ratio())
        return best

    # ─────────────────────────────────────────────────────────────
    # SPEAK — Edge TTS, immediate playback, no chunking lag
    # ─────────────────────────────────────────────────────────────

    def speak(
        self,
        text: str,
        backend_priority: str | None = None,
        generation_id: int | None = None,
        interrupt_current: bool = True,
    ):
        if not text:
            return
        if self.text_mode and not getattr(Config, "SPEAK_IN_TEXT_MODE", False):
            return
        if not self.audio_ready:
            return

        clean = self._clean(text)
        if not clean:
            return

        if generation_id is None and interrupt_current:
            self._cancel_pending_speech()

        if generation_id is not None and self._is_stale_speech_generation(generation_id):
            return

        with self._tts_lock:
            if generation_id is not None and self._is_stale_speech_generation(generation_id):
                return
            if interrupt_current:
                self._interrupt_active_speech()
            self._stop_flag.clear()
            if generation_id is not None and self._is_stale_speech_generation(generation_id):
                return
            self._emit_state("speaking")
            try:
                self._speak_with_backends(clean, backend_priority=backend_priority)
            finally:
                self._emit_state("idle")

    def speak_quick_ack(self, text: str):
        priority = getattr(Config, "WAKE_ACK_TTS_BACKEND_PRIORITY", "system_first")
        return self.speak_background(text, backend_priority=priority)

    def _speak_with_backends(self, text: str, backend_priority: str | None = None):
        last_error = None
        self.last_tts_backend = ""
        for backend in self._tts_backend_order(backend_priority=backend_priority):
            try:
                if backend == "piper" and self._speak_piper_blocking(text):
                    self.last_tts_backend = "piper"
                    return
                if backend == "system" and self._speak_local_blocking(text):
                    self.last_tts_backend = "system"
                    return
                if backend == "edge" and self._speak_edge_blocking(text):
                    self.last_tts_backend = "edge"
                    return
            except Exception as exc:
                last_error = exc

        if last_error is not None:
            console.print(f"[red]TTS error:[/red] {last_error}")

    def _tts_backend_order(self, backend_priority: str | None = None) -> list[str]:
        priority = str(
            backend_priority if backend_priority is not None else getattr(Config, "TTS_BACKEND_PRIORITY", "system_first")
        ).lower().strip()
        allow_local_tts, _ = self.resource_guard.allows_local_tts()
        piper_available = self._supports_piper()

        if priority == "piper_first":
            order = ["piper", "edge", "system"]
        elif priority == "piper_only":
            order = ["piper"]
        elif priority == "edge_first":
            order = ["piper", "edge", "system"] if piper_available else ["edge", "system"]
        elif priority == "system_only":
            order = ["system"]
        elif priority == "edge_only":
            order = ["edge"]
        else:
            order = ["system", "piper", "edge"] if piper_available else ["system", "edge"]

        if not allow_local_tts:
            order = [backend for backend in order if backend not in {"system", "piper"}]
            if "edge" not in order:
                order.append("edge")
        return list(dict.fromkeys(order))

    def _supports_piper(self) -> bool:
        model_path, _ = self._resolve_piper_voice_paths()
        return model_path is not None

    def _resolve_piper_voice_paths(self) -> tuple[str | None, str | None]:
        if not bool(getattr(Config, "PIPER_TTS_ENABLED", True)):
            return None, None

        model_raw = str(getattr(Config, "PIPER_TTS_MODEL_PATH", "") or "").strip()
        config_raw = str(getattr(Config, "PIPER_TTS_CONFIG_PATH", "") or "").strip()
        download_dir_raw = str(getattr(Config, "PIPER_TTS_DOWNLOAD_DIR", "") or "").strip()
        voice_name = str(getattr(Config, "PIPER_TTS_VOICE", "") or "").strip()

        model_path = self._resolve_runtime_path(model_raw) if model_raw else None
        if model_path is None and download_dir_raw and voice_name:
            download_dir = self._resolve_runtime_path(download_dir_raw)
            if download_dir is not None:
                candidate = Path(download_dir) / f"{voice_name}.onnx"
                if candidate.exists():
                    model_path = str(candidate)

        if model_path is None:
            return None, None

        config_path = self._resolve_runtime_path(config_raw) if config_raw else None
        if config_path is None:
            model = Path(model_path)
            candidates = [
                model.with_suffix(model.suffix + ".json"),
                model.with_suffix(".json"),
            ]
            for candidate in candidates:
                if candidate.exists():
                    config_path = str(candidate)
                    break

        return str(model_path), (str(config_path) if config_path else None)

    def _resolve_runtime_path(self, raw_path: str) -> str | None:
        if not raw_path:
            return None
        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            candidate = Path(os.getcwd()) / candidate
        if candidate.exists():
            return str(candidate)
        return None

    def _get_piper_tts_voice(self, force_reinit: bool = False):
        model_path, config_path = self._resolve_piper_voice_paths()
        if not model_path:
            return None

        voice_key = "|".join(
            [
                model_path,
                config_path or "",
                "cuda" if bool(getattr(Config, "PIPER_TTS_USE_CUDA", False)) else "cpu",
            ]
        )
        if force_reinit:
            self._reset_piper_tts_voice()
        if self._piper_tts_voice is not None and self._piper_tts_voice_key == voice_key:
            return self._piper_tts_voice

        try:
            from piper import PiperVoice

            self._piper_tts_voice = PiperVoice.load(
                model_path,
                config_path=config_path or None,
                use_cuda=bool(getattr(Config, "PIPER_TTS_USE_CUDA", False)),
            )
            self._piper_tts_voice_key = voice_key
            self._piper_tts_error = ""
            return self._piper_tts_voice
        except Exception as exc:
            self._piper_tts_voice = None
            self._piper_tts_voice_key = ""
            self._piper_tts_error = str(exc)
            return None

    def _reset_piper_tts_voice(self) -> None:
        self._piper_tts_voice = None
        self._piper_tts_voice_key = ""

    def _piper_synthesis_config(self):
        speaker_raw = str(getattr(Config, "PIPER_TTS_SPEAKER_ID", "") or "").strip()
        volume = self._local_tts_volume()
        if not speaker_raw and abs(volume - 1.0) < 0.001:
            return None

        try:
            from piper.config import SynthesisConfig

            speaker_id = int(speaker_raw) if speaker_raw else None
            return SynthesisConfig(speaker_id=speaker_id, volume=volume)
        except Exception:
            return None

    def _speak_piper_blocking(self, text: str) -> bool:
        voice = self._get_piper_tts_voice()
        if voice is None:
            return False

        syn_config = self._piper_synthesis_config()
        for attempt in range(2):
            if voice is None:
                return False
            try:
                for chunk in self._chunk_text(text):
                    if self._stop_flag.is_set():
                        break
                    audio_chunks = list(voice.synthesize(chunk, syn_config=syn_config))
                    if not audio_chunks:
                        continue
                    self._play_piper_audio_chunks(audio_chunks)
                return True
            except Exception:
                self._reset_piper_tts_voice()
                if attempt == 0:
                    voice = self._get_piper_tts_voice(force_reinit=True)
                    continue
                return False
        return False

    def _play_piper_audio_chunks(self, audio_chunks) -> None:
        if not audio_chunks:
            return
        first = audio_chunks[0]
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
            tmp = f.name
        try:
            with wave.open(tmp, "wb") as wf:
                wf.setnchannels(int(getattr(first, "sample_channels", 1)))
                wf.setsampwidth(int(getattr(first, "sample_width", 2)))
                wf.setframerate(int(getattr(first, "sample_rate", 22050)))
                for audio_chunk in audio_chunks:
                    if self._stop_flag.is_set():
                        break
                    wf.writeframes(audio_chunk.audio_int16_bytes)
            self._play_audio_file_blocking(tmp)
        finally:
            try:
                os.unlink(tmp)
            except Exception:
                pass

    def _speak_local_blocking(self, text: str) -> bool:
        try:
            engine = self._get_local_tts_engine()
        except Exception:
            return False

        for attempt in range(2):
            if engine is None:
                return False
            try:
                self._configure_local_tts_engine(engine)
                for chunk in self._chunk_text(text):
                    if self._stop_flag.is_set():
                        break
                    engine.say(chunk)
                    engine.runAndWait()
                return True
            except Exception:
                self._reset_local_tts_engine()
                if attempt == 0:
                    try:
                        engine = self._get_local_tts_engine(force_reinit=True)
                        continue
                    except Exception:
                        return False
                return False
        return False

    def _get_local_tts_engine(self, force_reinit: bool = False):
        if force_reinit:
            self._reset_local_tts_engine()
        if self._local_tts_engine is not None:
            return self._local_tts_engine
        import pyttsx3

        self._local_tts_engine = pyttsx3.init()
        return self._local_tts_engine

    def _reset_local_tts_engine(self, already_stopped: bool = False) -> None:
        engine = self._local_tts_engine
        self._local_tts_engine = None
        if engine is None or already_stopped:
            return
        try:
            engine.stop()
        except Exception:
            pass

    def _configure_local_tts_engine(self, engine) -> None:
        hint = str(getattr(Config, "LOCAL_TTS_VOICE_HINT", "") or "").lower().strip()
        if hint:
            for voice in engine.getProperty("voices") or []:
                voice_name = str(getattr(voice, "name", "") or "").lower()
                voice_id = str(getattr(voice, "id", "") or "").lower()
                if hint in voice_name or hint in voice_id:
                    engine.setProperty("voice", voice.id)
                    break

        engine.setProperty("rate", self._local_tts_rate())
        engine.setProperty("volume", self._local_tts_volume())

    def _local_tts_rate(self) -> int:
        raw = str(getattr(Config, "VOICE_RATE", "0")).strip()
        base_rate = 185
        if raw.endswith("%"):
            try:
                percent = float(raw.rstrip("%"))
                return max(120, int(base_rate * (1 + percent / 100.0)))
            except ValueError:
                return base_rate
        try:
            return max(120, int(float(raw)))
        except ValueError:
            return base_rate

    def _local_tts_volume(self) -> float:
        raw = str(getattr(Config, "VOICE_VOLUME", "+0%")).strip()
        if raw.endswith("%"):
            try:
                percent = float(raw.rstrip("%"))
                return max(0.2, min(1.0, 1.0 + percent / 100.0))
            except ValueError:
                return 1.0
        try:
            return max(0.2, min(1.0, float(raw)))
        except ValueError:
            return 1.0

    def _play_audio_file_blocking(self, path: str) -> None:
        import pygame

        pygame.mixer.music.load(path)
        pygame.mixer.music.set_volume(1.0)
        pygame.mixer.music.play()

        while pygame.mixer.music.get_busy():
            if self._stop_flag.is_set():
                pygame.mixer.music.stop()
                break
            time.sleep(getattr(Config, "PLAYBACK_POLL_SECONDS", 0.03))

        try:
            pygame.mixer.music.unload()
        except Exception:
            pass

    def _speak_edge_blocking(self, text: str) -> bool:
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(self._speak_async(text))
        finally:
            try:
                loop.close()
            except Exception:
                pass
        return True

    async def _speak_async(self, text: str):
        import edge_tts
        import pygame

        chunks = self._chunk_text(text)
        if not chunks:
            return

        for chunk in chunks:
            if self._stop_flag.is_set():
                break

            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
                tmp = f.name

            try:
                communicate = edge_tts.Communicate(
                    text=chunk,
                    voice=getattr(Config, "VOICE_NAME", "en-US-JennyNeural"),
                    rate=getattr(Config, "VOICE_RATE", "+4%"),
                    pitch=getattr(Config, "VOICE_PITCH", "+0Hz"),
                    volume=getattr(Config, "VOICE_VOLUME", "+0%"),
                )
                await communicate.save(tmp)
                self._play_audio_file_blocking(tmp)
            finally:
                try:
                    os.unlink(tmp)
                except Exception:
                    pass

    def stop_speaking(self, cancel_pending: bool = True):
        if cancel_pending:
            self._cancel_pending_speech()
        self._interrupt_active_speech()

    def _interrupt_active_speech(self) -> None:
        self._stop_flag.set()
        try:
            if self._local_tts_engine is not None:
                self._local_tts_engine.stop()
        except Exception:
            pass
        try:
            import pygame
            pygame.mixer.music.stop()
        except Exception:
            pass
        self._emit_state("idle")

    def stop(self):
        self.stop_speaking()
        self._reset_local_tts_engine(already_stopped=True)
        self._reset_piper_tts_voice()

    def begin_background_speech_sequence(self, cancel_pending: bool = True) -> int:
        if cancel_pending:
            return self._cancel_pending_speech()
        with self._speech_generation_lock:
            return self._speech_generation

    def queue_background_speech(
        self,
        text: str,
        generation_id: int,
        backend_priority: str | None = None,
        interrupt_current: bool = False,
    ):
        thread = threading.Thread(
            target=self.speak,
            args=(text,),
            kwargs={
                "backend_priority": backend_priority,
                "generation_id": generation_id,
                "interrupt_current": interrupt_current,
            },
            daemon=True,
        )
        thread.start()
        return thread

    def speak_background(self, text: str, backend_priority: str | None = None):
        generation_id = self.begin_background_speech_sequence(cancel_pending=True)
        return self.queue_background_speech(
            text,
            generation_id=generation_id,
            backend_priority=backend_priority,
            interrupt_current=True,
        )

    def _cancel_pending_speech(self) -> int:
        with self._speech_generation_lock:
            self._speech_generation += 1
            return self._speech_generation

    def _is_stale_speech_generation(self, generation_id: int) -> bool:
        with self._speech_generation_lock:
            return generation_id != self._speech_generation

    def _prime_audio_output(self):
        """Warm the output device once so the first spoken word is not clipped."""
        try:
            import pygame

            duration_ms = max(20, int(getattr(Config, "AUDIO_WARMUP_MS", 120)))
            sample_rate = int(getattr(Config, "AUDIO_SAMPLE_RATE", 24000))
            channels = int(getattr(Config, "AUDIO_CHANNELS", 2))
            frames = max(1, int(sample_rate * duration_ms / 1000))

            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
                tmp = f.name

            try:
                silence_frame = (b"\x00\x00" * channels)
                with wave.open(tmp, "wb") as wf:
                    wf.setnchannels(channels)
                    wf.setsampwidth(2)
                    wf.setframerate(sample_rate)
                    wf.writeframes(silence_frame * frames)

                sound = pygame.mixer.Sound(tmp)
                channel = sound.play()
                if channel is not None:
                    while channel.get_busy():
                        time.sleep(0.01)
            finally:
                try:
                    os.unlink(tmp)
                except Exception:
                    pass
        except Exception:
            pass

    def _clean(self, text: str) -> str:
        text = re.sub(r"```[\s\S]*?```", "code block", text)
        text = re.sub(r"[*_`#→|]", "", text)
        text = re.sub(r"https?://\S+", "link", text)
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > 600:
            text = text[:600] + "..."
        return text

    def _chunk_text(self, text: str) -> list[str]:
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]
        if not sentences:
            return []

        max_sentences = max(1, int(getattr(Config, "TTS_CHUNK_SENTENCES", 1)))
        max_chars = max(80, int(getattr(Config, "TTS_MAX_CHARS_PER_CHUNK", 220)))

        chunks = []
        current = []

        for sentence in sentences:
            candidate = " ".join(current + [sentence]).strip()
            if current and (len(current) >= max_sentences or len(candidate) > max_chars):
                chunks.append(" ".join(current).strip())
                current = [sentence]
            else:
                current.append(sentence)

        if current:
            chunks.append(" ".join(current).strip())

        return chunks

    def _stt_languages(self) -> list[str]:
        languages = []
        configured = [
            getattr(Config, "STT_LANGUAGE", "en-US"),
            getattr(Config, "STT_FALLBACK_LANGUAGE", "en-GB"),
            getattr(Config, "STT_SECONDARY_FALLBACK_LANGUAGE", "en-IN"),
            *list(getattr(Config, "STT_ADDITIONAL_LANGUAGES", []) or []),
        ]
        for language in configured:
            language = str(language or "").strip()
            if language and language not in languages:
                languages.append(language)
        return languages

    def _system_stt_languages(self, wake_mode: bool) -> list[str]:
        recent_language = self._recent_wake_language if wake_mode else self._recent_command_language
        configured = [recent_language, *self._stt_languages()]
        languages: list[str] = []
        for language in configured:
            language = str(language or "").strip()
            if language and language not in languages:
                languages.append(language)

        max_languages = int(
            getattr(
                Config,
                "WAKE_SYSTEM_MAX_LANGUAGES" if wake_mode else "SYSTEM_STT_MAX_LANGUAGES",
                2,
            )
            or 2
        )
        if max_languages <= 0:
            return languages
        return languages[:max_languages]

    def _local_whisper_language_hint(self) -> str:
        configured = str(getattr(Config, "LOCAL_WHISPER_LANGUAGE_HINT", "") or "").strip().lower()
        if configured:
            return configured
        return ""

    def _audio_to_wav_bytes(self, audio) -> io.BytesIO:
        wav_data = io.BytesIO()
        with wave.open(wav_data, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(audio.sample_width)
            wf.setframerate(audio.sample_rate)
            wf.writeframes(audio.frame_data)
        wav_data.seek(0)
        return wav_data

    def _write_audio_wav(self, audio, path: str) -> None:
        wav_data = self._audio_to_wav_bytes(audio)
        with open(path, "wb") as handle:
            handle.write(wav_data.read())
