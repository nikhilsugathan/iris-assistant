"""
IRIS Voice Module v4
====================
STT  : Groq Whisper API (fast, accurate, free with your Groq key)
       Falls back to Google STT if Groq unavailable
TTS  : Edge TTS with immediate single-chunk playback (no lag)
"""

import asyncio
import io
import os
import re
import tempfile
import threading
import time
import wave

from rich.console import Console
from config import Config

console = Console()


class Voice:
    def __init__(self, text_mode: bool = False):
        self.text_mode       = text_mode
        self._tts_lock       = threading.Lock()
        self._stop_flag      = threading.Event()
        self._state_callback = None
        self.current_state   = "idle"
        self.audio_ready     = False
        self.mic_ready       = False
        self.mic_error       = None
        self.calibrated      = False
        self.selected_mic_name  = "Default"
        self.selected_mic_index = None
        self.recognizer      = None
        self.microphone      = None
        self.last_listen_status = "idle"
        self.last_listen_detail = ""

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
            self.recognizer.dynamic_energy_threshold = False
            self.recognizer.energy_threshold         = getattr(Config, "MIC_ENERGY_THRESHOLD", 50)
            self.recognizer.pause_threshold          = getattr(Config, "MIC_PAUSE_THRESHOLD", 0.6)
            self.recognizer.phrase_threshold         = getattr(Config, "MIC_PHRASE_THRESHOLD", 0.2)
            self.recognizer.non_speaking_duration    = getattr(Config, "MIC_NON_SPEAKING_DURATION", 0.3)

            mic_names = sr.Microphone.list_microphone_names()
            preferred = getattr(Config, "PREFERRED_MIC_NAME", "").strip()
            mic_index = None
            mic_name  = "Default Windows microphone"

            if preferred:
                for i, name in enumerate(mic_names):
                    if preferred.lower() in name.lower():
                        mic_index = i
                        mic_name  = name
                        break

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

    def _calibrate(self):
        if not self.mic_ready or self.calibrated:
            return
        try:
            with self.microphone as source:
                console.print("[dim]Calibrating microphone... stay quiet.[/dim]")
                self.recognizer.adjust_for_ambient_noise(
                    source,
                    duration=getattr(Config, "MIC_CALIBRATION_SECONDS", 2.0)
                )
            self.calibrated = True
            console.print(
                f"[green]✓ Calibration complete[/green] "
                f"[dim](energy={self.recognizer.energy_threshold:.0f})[/dim]"
            )
        except Exception as e:
            console.print(f"[yellow]Calibration warning:[/yellow] {e}")

    # ─────────────────────────────────────────────────────────────
    # LISTEN
    # ─────────────────────────────────────────────────────────────

    def listen_text(self) -> str:
        return input("You: ")

    def listen_for_wake(self) -> str:
        # Wake detection uses fast Google STT, not Groq Whisper
        if self.text_mode:
            return self.listen_text()
        time.sleep(0.2)   # Brief cooldown to avoid TTS echo
        return self._listen(
            timeout=getattr(Config, "WAKE_TIMEOUT", 8),
            phrase_time_limit=getattr(Config, "WAKE_PHRASE_LIMIT", 10),
            wake_mode=True,
        )

    def listen_for_command(self) -> str:
        if self.text_mode:
            return self.listen_text()
        # Stop Iris speaking if she is — user interrupted
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
            time.sleep(1)
            return ""

        self.last_listen_status = "listening"
        self.last_listen_detail = ""
        self._emit_state("listening")
        try:
            with self.microphone as source:
                if not wake_mode:
                    console.print("[dim]Listening...[/dim]")
                audio = self.recognizer.listen(
                    source,
                    timeout=timeout,
                    phrase_time_limit=phrase_time_limit,
                )
        except sr.WaitTimeoutError:
            self.last_listen_status = "timeout"
            self.last_listen_detail = "No speech was detected before the listen timeout."
            self._emit_state("idle")
            return ""
        except Exception as e:
            self.last_listen_status = "mic_error"
            self.last_listen_detail = str(e)
            self._emit_state("idle")
            if not wake_mode:
                console.print(f"[red]Mic error:[/red] {e}")
            return ""

        # Wake mode: use fast Google STT only (Groq adds 1-2s latency)
        # Command mode: use accurate Groq Whisper, fall back to Google
        if wake_mode:
            text = self._transcribe_google(audio)
        else:
            text = self._transcribe_groq(audio)
            if not text:
                text = self._transcribe_google(audio)

        if text:
            self.last_listen_status = "heard"
            self.last_listen_detail = text
            if wake_mode and getattr(Config, "SHOW_WAKE_DEBUG", True):
                console.print(f"[dim]Wake heard:[/dim] {text}")
            elif not wake_mode:
                console.print(f"[green]You:[/green] {text}")

        elif not wake_mode:
            self.last_listen_status = "transcription_failed"
            self.last_listen_detail = "Audio was captured, but speech recognition could not produce text."
            console.print("[dim]Heard audio but couldn't transcribe it.[/dim]")
        else:
            self.last_listen_status = "wake_not_understood"
            self.last_listen_detail = "Wake audio was captured, but no wake phrase was recognized."

        self._emit_state("idle")
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
        return "That didn't come through clearly. Please try again."

    def short_last_listen_feedback(self) -> str:
        status = getattr(self, "last_listen_status", "idle")
        if status == "mic_unavailable":
            return "My microphone is not ready."
        if status == "mic_error":
            return "My microphone ran into a problem."
        if status == "transcription_failed":
            return "I heard you, but I couldn't make that out."
        return "I didn't catch that."

    def _transcribe_groq(self, audio) -> str:
        """Use Groq Whisper API — fastest and most accurate."""
        try:
            import speech_recognition as sr

            # Export audio to WAV bytes
            wav_data = io.BytesIO()
            with wave.open(wav_data, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(audio.sample_width)
                wf.setframerate(audio.sample_rate)
                wf.writeframes(audio.frame_data)
            wav_data.seek(0)

            from groq import Groq
            client = Groq(api_key=Config.GROQ_API_KEY)

            transcription = client.audio.transcriptions.create(
                file=("audio.wav", wav_data, "audio/wav"),
                model="whisper-large-v3-turbo",
                language="en",
                response_format="text",
            )
            return (transcription or "").strip()

        except Exception:
            return ""

    def _transcribe_google(self, audio) -> str:
        """Fallback: Google STT."""
        try:
            import speech_recognition as sr
            text = self.recognizer.recognize_google(
                audio,
                language=getattr(Config, "STT_LANGUAGE", "en-US"),
            ).strip()
            return text
        except Exception:
            return ""

    # ─────────────────────────────────────────────────────────────
    # SPEAK — Edge TTS, immediate playback, no chunking lag
    # ─────────────────────────────────────────────────────────────

    def speak(self, text: str):
        if not text:
            return
        if self.text_mode and not getattr(Config, "SPEAK_IN_TEXT_MODE", False):
            return
        if not self.audio_ready:
            return

        clean = self._clean(text)
        if not clean:
            return

        with self._tts_lock:
            self.stop_speaking()
            self._stop_flag.clear()
            self._emit_state("speaking")
            try:
                self._speak_blocking(clean)
            finally:
                self._emit_state("idle")

    def _speak_blocking(self, text: str):
        """Blocking speak — runs in thread."""
        try:
            asyncio.run(self._speak_async(text))
        except Exception as e:
            console.print(f"[red]TTS error:[/red] {e}")

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

    def stop_speaking(self):
        self._stop_flag.set()
        try:
            import pygame
            pygame.mixer.music.stop()
        except Exception:
            pass
        self._emit_state("idle")

    def stop(self):
        self.stop_speaking()

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
