"""
IRIS Voice Module
=================
Two-stage voice handling for Windows with wake debug.
"""

import asyncio
import os
import tempfile
import threading
import time

from rich.console import Console

from config import Config

console = Console()


class Voice:
    def __init__(self, text_mode: bool = False):
        self.text_mode = text_mode
        self._tts_lock = threading.Lock()
        self.audio_ready = False
        self.mic_ready = False
        self.mic_error = None
        self.last_heard_status = ""
        self.calibrated = False
        self.selected_mic_name = "Default Windows microphone"
        self.selected_mic_index = None

        try:
            import pygame

            pygame.mixer.init()
            self.audio_ready = True
            console.print("[green]✓ Audio playback ready[/green]")
        except Exception as e:
            self.audio_ready = False
            console.print(f"[red]Audio init failed:[/red] {e}")

        try:
            import speech_recognition as sr

            self.recognizer = sr.Recognizer()
            self.recognizer.dynamic_energy_threshold = True
            self.recognizer.energy_threshold = getattr(Config, "MIC_ENERGY_THRESHOLD", 200)
            self.recognizer.pause_threshold = getattr(Config, "MIC_PAUSE_THRESHOLD", 0.9)
            self.recognizer.phrase_threshold = getattr(Config, "MIC_PHRASE_THRESHOLD", 0.2)
            self.recognizer.non_speaking_duration = getattr(
                Config, "MIC_NON_SPEAKING_DURATION", 0.4
            )

            mic_names = sr.Microphone.list_microphone_names()
            preferred_mic_name = getattr(Config, "PREFERRED_MIC_NAME", "").strip()

            mic_index = None
            mic_name = "Default Windows microphone"

            if preferred_mic_name:
                for i, name in enumerate(mic_names):
                    if preferred_mic_name.lower() in name.lower():
                        mic_index = i
                        mic_name = name
                        break

            self.microphone = sr.Microphone(
                device_index=mic_index,
                sample_rate=getattr(Config, "MIC_SAMPLE_RATE", 16000),
                chunk_size=getattr(Config, "MIC_CHUNK_SIZE", 1024),
            )

            self.selected_mic_index = mic_index
            self.selected_mic_name = mic_name
            self.mic_ready = True

            console.print(
                f"[green]✓ Microphone ready[/green] [dim]({self.selected_mic_name})[/dim]"
            )

            if mic_names:
                console.print("[dim]Available microphones:[/dim]")
                for i, name in enumerate(mic_names):
                    console.print(f"[dim]  {i}: {name}[/dim]")

            self._calibrate_once()

        except Exception as e:
            self.microphone = None
            self.mic_ready = False
            self.mic_error = str(e)
            if not self.text_mode:
                console.print(f"[red]Microphone init failed:[/red] {e}")

    def _calibrate_once(self):
        if self.text_mode or not self.mic_ready or self.microphone is None or self.calibrated:
            return

        try:
            with self.microphone as source:
                console.print("[dim]Calibrating microphone... stay quiet for a moment.[/dim]")
                self.recognizer.adjust_for_ambient_noise(
                    source,
                    duration=getattr(Config, "MIC_CALIBRATION_SECONDS", 1.5),
                )
            self.calibrated = True
            console.print(
                f"[green]✓ Calibration complete[/green] [dim](energy={self.recognizer.energy_threshold:.0f})[/dim]"
            )
        except Exception as e:
            console.print(f"[yellow]Calibration warning:[/yellow] {e}")

    def listen_text(self) -> str:
        return input("You: ")

    def listen_for_wake(self) -> str:
        # Brief cooldown to prevent mic picking up TTS echo
        time.sleep(0.3)
        if self.text_mode:
            return self.listen_text()

        if not self.mic_ready or self.microphone is None:
            if self.mic_error:
                console.print(f"[dim]Mic error: {self.mic_error}[/dim]")
            time.sleep(1)
            return ""

        return self._listen_voice(
            timeout=getattr(Config, "WAKE_TIMEOUT", 3),
            phrase_time_limit=getattr(Config, "WAKE_PHRASE_LIMIT", 4),
            show_listening=False,
            unknown_msg=False,
            wake_debug=True,
        )

    def listen_for_command(self) -> str:
        if self.text_mode:
            return self.listen_text()

        if not self.mic_ready or self.microphone is None:
            return ""

        return self._listen_voice(
            timeout=getattr(Config, "MIC_TIMEOUT", 6),
            phrase_time_limit=getattr(Config, "MIC_PHRASE_LIMIT", 10),
            show_listening=True,
            unknown_msg=True,
            wake_debug=False,
        )

    def _listen_voice(
        self,
        timeout: int,
        phrase_time_limit: int,
        show_listening: bool,
        unknown_msg: bool,
        wake_debug: bool,
    ) -> str:
        import speech_recognition as sr

        self.last_heard_status = ""

        try:
            with self.microphone as source:
                if show_listening:
                    console.print("[dim]Listening...[/dim]")

                audio = self.recognizer.listen(
                    source,
                    timeout=timeout,
                    phrase_time_limit=phrase_time_limit,
                )
        except sr.WaitTimeoutError:
            self.last_heard_status = "timeout"
            return ""
        except Exception as e:
            self.last_heard_status = f"listen_error: {e}"
            if show_listening or wake_debug:
                console.print(f"[red]Microphone listen failed:[/red] {e}")
            return ""

        # Primary language: UK English
        try:
            text = self.recognizer.recognize_google(
                audio,
                language=getattr(Config, "STT_LANGUAGE", "en-GB"),
            ).strip()

            if text:
                self.last_heard_status = "heard"
                if show_listening:
                    console.print(f"[green]You:[/green] {text}")
                elif wake_debug and getattr(Config, "SHOW_WAKE_DEBUG", True):
                    console.print(f"[dim]Wake heard:[/dim] {text}")
                return text

            self.last_heard_status = "empty"
            return ""

        except sr.UnknownValueError:
            pass
        except sr.RequestError as e:
            self.last_heard_status = f"request_error: {e}"
            if show_listening or wake_debug:
                console.print(f"[red]Speech recognition service failed:[/red] {e}")
            return ""
        except Exception as e:
            self.last_heard_status = f"recognition_error: {e}"
            if show_listening or wake_debug:
                console.print(f"[red]Speech recognition error:[/red] {e}")
            return ""

        # Fallback language: Indian English
        try:
            text = self.recognizer.recognize_google(
                audio,
                language=getattr(Config, "STT_FALLBACK_LANGUAGE", "en-IN"),
            ).strip()

            if text:
                self.last_heard_status = "heard_fallback"
                if show_listening:
                    console.print(f"[green]You:[/green] {text}")
                elif wake_debug and getattr(Config, "SHOW_WAKE_DEBUG", True):
                    console.print(f"[dim]Wake heard:[/dim] {text}")
                return text

        except sr.UnknownValueError:
            self.last_heard_status = "unknown_value"
            if unknown_msg and show_listening:
                console.print("[dim]Heard audio, but speech was not clear enough to transcribe.[/dim]")
            elif wake_debug and getattr(Config, "SHOW_WAKE_DEBUG", True):
                console.print("[dim]Wake audio detected, but words were unclear.[/dim]")
            return ""
        except sr.RequestError as e:
            self.last_heard_status = f"request_error: {e}"
            if show_listening or wake_debug:
                console.print(f"[red]Speech recognition service failed:[/red] {e}")
            return ""
        except Exception as e:
            self.last_heard_status = f"recognition_error: {e}"
            if show_listening or wake_debug:
                console.print(f"[red]Speech recognition error:[/red] {e}")
            return ""

        return ""

    def speak(self, text: str):
        if not text:
            return

        if self.text_mode and not getattr(Config, "SPEAK_IN_TEXT_MODE", False):
            return

        if not self.audio_ready:
            console.print("[yellow]Audio output unavailable, skipping speech.[/yellow]")
            return

        clean = self._clean(text)
        if not clean:
            return

        for chunk in self._chunk_text(clean):
            self._speak_chunk(chunk)

    def _speak_chunk(self, text: str):
        try:
            import edge_tts
            import pygame

            async def _run():
                with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
                    temp_file = f.name

                try:
                    communicate = edge_tts.Communicate(
                        text=text,
                        voice=getattr(Config, "VOICE_NAME", "en-GB-SoniaNeural"),
                        rate=getattr(Config, "VOICE_RATE", "+18%"),
                    )
                    await communicate.save(temp_file)

                    pygame.mixer.music.load(temp_file)
                    pygame.mixer.music.play()

                    while pygame.mixer.music.get_busy():
                        await asyncio.sleep(getattr(Config, "PLAYBACK_POLL_SECONDS", 0.03))
                finally:
                    try:
                        pygame.mixer.music.unload()
                    except Exception:
                        pass

                    if os.path.exists(temp_file):
                        try:
                            os.remove(temp_file)
                        except Exception:
                            pass

            with self._tts_lock:
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(_run())
                except RuntimeError:
                    asyncio.run(_run())

        except Exception as e:
            console.print(f"[red]TTS error:[/red] {e}")

    def _clean(self, text: str) -> str:
        return text.replace("*", "").strip()

    def _chunk_text(self, text: str):
        import re

        parts = re.split(r"(?<=[.!?])\s+", text)
        chunks = []
        current = ""

        for part in parts:
            if not part.strip():
                continue

            if len(current) + len(part) + 1 < 140:
                current = f"{current} {part}".strip() if current else part
            else:
                if current:
                    chunks.append(current.strip())
                current = part

        if current:
            chunks.append(current.strip())

        return chunks

    def stop(self):
        try:
            import pygame
            pygame.mixer.music.stop()
        except Exception:
            pass

    def stop_speaking(self):
        self.stop()