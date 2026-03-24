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
        self.audio_ready     = False
        self.mic_ready       = False
        self.mic_error       = None
        self.calibrated      = False
        self.selected_mic_name  = "Default"
        self.selected_mic_index = None
        self.recognizer      = None
        self.microphone      = None

        self._init_audio()
        self._init_mic()

    # ─────────────────────────────────────────────────────────────
    # INIT
    # ─────────────────────────────────────────────────────────────

    def _init_audio(self):
        try:
            import pygame
            pygame.mixer.init()
            self.audio_ready = True
            console.print("[green]✓ Audio playback ready[/green]")
        except Exception as e:
            console.print(f"[red]Audio init failed:[/red] {e}")

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
        return self._listen(
            timeout=getattr(Config, "MIC_TIMEOUT", 6),
            phrase_time_limit=getattr(Config, "MIC_PHRASE_LIMIT", 12),
            wake_mode=False,
        )

    def _listen(self, timeout: int, phrase_time_limit: int, wake_mode: bool) -> str:
        import speech_recognition as sr

        if not self.mic_ready or self.microphone is None:
            time.sleep(1)
            return ""

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
            return ""
        except Exception as e:
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
            if wake_mode and getattr(Config, "SHOW_WAKE_DEBUG", True):
                console.print(f"[dim]Wake heard:[/dim] {text}")
            elif not wake_mode:
                console.print(f"[green]You:[/green] {text}")

        elif not wake_mode:
            console.print("[dim]Heard audio but couldn't transcribe it.[/dim]")

        return text or ""

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

        self._stop_flag.clear()
        with self._tts_lock:
            try:
                asyncio.run(self._speak_async(clean))
            except Exception as e:
                console.print(f"[red]TTS error:[/red] {e}")

    async def _speak_async(self, text: str):
        import edge_tts
        import pygame

        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
            tmp = f.name

        try:
            communicate = edge_tts.Communicate(
                text=text,
                voice=getattr(Config, "VOICE_NAME", "en-GB-SoniaNeural"),
                rate=getattr(Config, "VOICE_RATE", "+18%"),
            )
            await communicate.save(tmp)

            pygame.mixer.music.load(tmp)
            pygame.mixer.music.play()

            while pygame.mixer.music.get_busy():
                if self._stop_flag.is_set():
                    pygame.mixer.music.stop()
                    break
                await asyncio.sleep(0.03)

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

    def stop(self):
        self.stop_speaking()

    def _clean(self, text: str) -> str:
        import re
        text = re.sub(r"```[\s\S]*?```", "code block", text)
        text = re.sub(r"[*_`#→|]", "", text)
        text = re.sub(r"https?://\S+", "link", text)
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > 600:
            text = text[:600] + "..."
        return text
