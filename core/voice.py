"""
IRIS Voice Module v4
====================
STT  : Windows wake recognition, optional local faster-whisper for commands,
       then Groq Whisper and Google fallback
TTS  : Windows SAPI voices first, then Edge TTS fallback
"""

import asyncio
import difflib
import io
import json
import os
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
        self._recent_command_language = ""
        self._recent_wake_language = ""
        self._faster_whisper_model = None
        self._faster_whisper_error = ""

        self._init_audio()
        self._init_mic()

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
        except Exception as e:
            console.print(f"[red]Audio init failed:[/red] {e}")

    def set_state_callback(self, callback):
        self._state_callback = callback

    def _emit_state(self, state: str):
        if state == self.current_state:
            return
        self.current_state = state
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

            if mic_names:
                console.print("[dim]Available microphones:[/dim]")
                for i, name in enumerate(mic_names):
                    console.print(f"[dim]  {i}: {name}[/dim]")

            self._calibrate()

        except Exception as e:
            self.mic_error = str(e)
            console.print(f"[red]Microphone init failed:[/red] {e}")

    def _select_microphone_device(self, mic_names: list[str], preferred: str) -> tuple[int | None, str]:
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

        if normalized.startswith("microphone ("):
            score += 85
        if "microphone array" in normalized:
            score += 30
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
            with self.microphone as source:
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
        except Exception as e:
            console.print(f"[yellow]Calibration warning:[/yellow] {e}")

    def _recalibrate_with_source(self, source, duration: float) -> None:
        self.recognizer.adjust_for_ambient_noise(source, duration=max(0.1, float(duration)))
        self.last_calibrated_at = time.time()
        self.listen_failures = 0
        self.calibrated = True

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
            self._recalibrate_with_source(source, duration=duration)
        except Exception as e:
            console.print(f"[yellow]Mic recalibration warning:[/yellow] {e}")

    # ─────────────────────────────────────────────────────────────
    # LISTEN
    # ─────────────────────────────────────────────────────────────

    def listen_text(self) -> str:
        return input("You: ")

    def listen_for_wake(self) -> str:
        if self.text_mode:
            return self.listen_text()
        time.sleep(0.2)   # Brief cooldown to avoid TTS echo
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

        active_state = "standby" if wake_mode else "listening"
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
        listen_started_at = time.perf_counter()
        try:
            with self.microphone as source:
                self._maybe_recalibrate(source, wake_mode=wake_mode)
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
            self._emit_state(settle_state)
            return ""
        except Exception as e:
            self.last_listen_status = "mic_error"
            self.last_listen_detail = str(e)
            self.listen_failures += 1
            self.last_total_listen_duration_ms = int((time.perf_counter() - listen_started_at) * 1000)
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
            console.print("[dim]Heard audio but couldn't transcribe it.[/dim]")
        else:
            self.last_listen_status = "wake_not_understood"
            self.last_listen_detail = "Wake audio was captured, but no wake phrase was recognized."
            self.listen_failures += 1

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
        order = ["google"]
        if allow_local_stt:
            order = ["system", "google"]

        if priority == "google_first":
            order = ["google", "system"]
        elif priority == "google_only":
            order = ["google"]
        elif priority == "system_only":
            order = ["system"] if allow_local_stt else ["google"]
        elif priority == "system_first" and not allow_local_stt:
            order = ["google"]

        if not allow_local_stt:
            order = [backend for backend in order if backend != "system"]
            if not order:
                order = ["google"]

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

    def _get_faster_whisper_model(self):
        if self._faster_whisper_model is not None:
            return self._faster_whisper_model
        if self._faster_whisper_error:
            return None

        try:
            from faster_whisper import WhisperModel

            model_name = str(getattr(Config, "LOCAL_WHISPER_MODEL", "base") or "base").strip() or "base"
            init_options = {
                "device": str(getattr(Config, "LOCAL_WHISPER_DEVICE", "cpu") or "cpu").strip() or "cpu",
                "compute_type": str(getattr(Config, "LOCAL_WHISPER_COMPUTE_TYPE", "int8") or "int8").strip() or "int8",
            }
            self._faster_whisper_model = WhisperModel(model_name, **init_options)
            return self._faster_whisper_model
        except Exception as exc:
            self._faster_whisper_error = str(exc)
            console.print(f"[yellow]Local Whisper unavailable:[/yellow] {exc}")
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

        for backend in order:
            attempted.append(backend)
            candidate = self._transcribe_candidate(backend, audio, wake_mode=wake_mode)
            if not candidate.text:
                continue

            if wake_mode:
                if self._accept_wake_candidate(candidate):
                    self.last_transcript_attempts = " > ".join(attempted)
                    self._remember_transcript_candidate(candidate, wake_mode=True)
                    return candidate.text
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

    def _transcribe_candidate(self, backend: str, audio, wake_mode: bool = False) -> TranscriptCandidate:
        if backend == "system":
            if wake_mode:
                return self._transcribe_windows_wake_candidate(audio)
            return self._transcribe_windows_candidate(audio)
        if backend == "faster_whisper":
            if wake_mode:
                return TranscriptCandidate(backend="faster_whisper")
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
        if not self._looks_like_wake_phrase(text):
            return False

        threshold = float(getattr(Config, "WAKE_SYSTEM_ACCEPT_CONFIDENCE", 0.58))
        if candidate.backend == "system":
            return candidate.confidence >= threshold
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
        for wake in getattr(Config, "WAKE_WORDS", []) or []:
            wake_text = str(wake or "").strip().lower()
            if wake_text and wake_text not in variants:
                variants.append(wake_text)
            for alias in wake_aliases.get(wake_text, []) or []:
                alias_text = str(alias or "").strip().lower()
                if alias_text and alias_text not in variants:
                    variants.append(alias_text)
        return variants

    def _looks_like_wake_phrase(self, text: str) -> bool:
        normalized = re.sub(r"[^a-z0-9'\s]+", " ", (text or "").lower()).strip()
        if not normalized:
            return False

        tokens = [token for token in normalized.split() if token]
        if not tokens:
            return False

        chunks = [tokens[0]]
        if len(tokens) >= 2:
            chunks.append(f"{tokens[0]} {tokens[1]}")

        threshold = float(getattr(Config, "WAKE_FUZZY_THRESHOLD", 0.75))
        for variant in self._wake_phrase_variants():
            for chunk in chunks:
                if chunk == variant:
                    return True
                if difflib.SequenceMatcher(None, chunk, variant).ratio() >= threshold:
                    return True
        return False

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

        if priority == "edge_first":
            order = ["edge", "system"]
        elif priority == "system_only":
            order = ["system"]
        elif priority == "edge_only":
            order = ["edge"]
        else:
            order = ["system", "edge"]

        if not allow_local_tts:
            order = [backend for backend in order if backend != "system"]
            if "edge" not in order:
                order.append("edge")
        return order

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

                pygame.mixer.music.load(tmp)
                pygame.mixer.music.set_volume(1.0)
                pygame.mixer.music.play()

                while pygame.mixer.music.get_busy():
                    if self._stop_flag.is_set():
                        pygame.mixer.music.stop()
                        break
                    await asyncio.sleep(getattr(Config, "PLAYBACK_POLL_SECONDS", 0.03))

                try:
                    pygame.mixer.music.unload()
                except Exception:
                    pass
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

    def speak_background(self, text: str, backend_priority: str | None = None):
        generation_id = self._cancel_pending_speech()
        thread = threading.Thread(
            target=self.speak,
            args=(text,),
            kwargs={
                "backend_priority": backend_priority,
                "generation_id": generation_id,
                "interrupt_current": True,
            },
            daemon=True,
        )
        thread.start()
        return thread

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
