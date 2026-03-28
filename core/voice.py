"""
IRIS Voice Module v4 — Hardened
================================
STT  : Groq Whisper API (fast, accurate, free with your Groq key)
       Falls back to Google STT if Groq unavailable
TTS  : Edge TTS → dedicated worker thread + pygame playback

Threading architecture:
  Main thread   → calls speak(text), which enqueues text and returns instantly.
  Worker thread → drains _speech_queue in a loop; owns the asyncio event loop
                  and all pygame playback calls.  Only one thread ever touches
                  the mixer hardware, eliminating race conditions.
"""

import asyncio
import atexit
import io
import os
import queue
import re
import tempfile
import threading
import time
import wave

from rich.console import Console
from config import Config

console = Console()

# Sentinel placed on the queue to tell the worker to exit cleanly.
_SHUTDOWN_SENTINEL = object()


class Voice:
    def __init__(self, text_mode: bool = False):
        self.text_mode       = text_mode
        self._stop_flag      = threading.Event()
        self._tts_lock       = threading.Lock()   # guards stop_speaking coordination only
        self.audio_ready     = False
        self.mic_ready       = False
        self.mic_error       = None
        self.calibrated      = False
        self.selected_mic_name  = "Default"
        self.selected_mic_index = None
        self.recognizer      = None
        self.microphone      = None

        # ── Speech worker queue & thread ──────────────────────────────────
        # speak() enqueues text here and returns immediately.
        # The worker thread is the sole consumer and the sole pygame driver.
        self._speech_queue: queue.Queue = queue.Queue()
        self._worker_thread: threading.Thread = threading.Thread(
            target=self._speech_worker,
            name="iris-tts-worker",
            daemon=True,   # won't block process exit if shutdown() is skipped
        )

        self._init_audio()
        self._init_mic()

        # Start the worker only after audio is initialised
        self._worker_thread.start()

        # Register graceful teardown — fires on normal exit and sys.exit()
        atexit.register(self.shutdown)

    @property
    def io_disabled(self) -> bool:
        """True when voice I/O (mic + audio) is intentionally disabled."""
        env_flag = os.environ.get("IRIS_DISABLE_VOICE_IO", "").lower()
        return self.text_mode or env_flag in {"1", "true", "yes"}

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

    def _init_mic(self):
        if self.text_mode:
            return
        try:
            import speech_recognition as sr
            self.recognizer = sr.Recognizer()
            self.recognizer.dynamic_energy_threshold = False
            self.recognizer.energy_threshold         = getattr(Config, "MIC_ENERGY_THRESHOLD", 4500)
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
        if self.text_mode:
            return self.listen_text()
        time.sleep(0.2)   # brief cooldown to avoid TTS echo
        return self._listen(
            timeout=getattr(Config, "WAKE_TIMEOUT", 8),
            phrase_time_limit=getattr(Config, "WAKE_PHRASE_LIMIT", 10),
            wake_mode=True,
        )

    def listen_for_command(self) -> str:
        if self.text_mode:
            return self.listen_text()
        self.stop_speaking()
        return self._listen(
            timeout=getattr(Config, "MIC_TIMEOUT", 6),
            phrase_time_limit=getattr(Config, "MIC_PHRASE_LIMIT", 12),
            wake_mode=False,
        )

    def _listen(self, timeout: int, phrase_time_limit: int, wake_mode: bool) -> str:
        import speech_recognition as sr

        if not self.mic_ready or self.microphone is None:
            # Exponential-backoff guard — avoids hot-spinning when no mic is present.
            sleep_time = min(getattr(self, "_mic_retry_sleep", 1), 60)
            self._mic_retry_sleep = sleep_time * 2
            time.sleep(sleep_time)
            return ""

        self._mic_retry_sleep = 1   # reset backoff on successful mic access

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
            return self.recognizer.recognize_google(
                audio,
                language=getattr(Config, "STT_LANGUAGE", "en-US"),
            ).strip()
        except Exception:
            return ""

    # ─────────────────────────────────────────────────────────────
    # SPEAK — non-blocking public API
    # ─────────────────────────────────────────────────────────────

    def speak(self, text: str):
        """
        Enqueue text for speech and return immediately.

        The dedicated _speech_worker thread handles all TTS synthesis and
        pygame playback.  This method never blocks the main thread regardless
        of utterance length.
        """
        if not text:
            return
        if self.text_mode and not getattr(Config, "SPEAK_IN_TEXT_MODE", False):
            return
        if not self.audio_ready:
            return

        clean = self._clean(text)
        if not clean:
            return

        # Signal any in-progress speech to stop, then enqueue the new text.
        self._stop_flag.set()
        self._speech_queue.put(clean)

    def stop_speaking(self):
        """Signal the worker to stop the current utterance."""
        self._stop_flag.set()
        try:
            import pygame
            pygame.mixer.music.stop()
        except Exception:
            pass

    def stop(self):
        self.stop_speaking()

    # ─────────────────────────────────────────────────────────────
    # SPEECH WORKER — runs in its own thread, owns the event loop
    # ─────────────────────────────────────────────────────────────

    def _speech_worker(self):
        """
        Dedicated TTS worker thread.

        Owns a single asyncio event loop for the lifetime of the process.
        Drains _speech_queue one item at a time, skipping any items that
        were superseded by a newer speak() call while waiting.
        """
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            while True:
                item = self._speech_queue.get()

                # Shutdown sentinel — exit the loop cleanly
                if item is _SHUTDOWN_SENTINEL:
                    self._speech_queue.task_done()
                    break

                # If more items are already queued (user spoke again while
                # we were waiting), skip this stale utterance immediately.
                if not self._speech_queue.empty():
                    self._speech_queue.task_done()
                    continue

                # Clear the stop flag so this new utterance can play fully.
                self._stop_flag.clear()

                try:
                    loop.run_until_complete(self._speak_async(item))
                except Exception as e:
                    console.print(f"[red]TTS worker error:[/red] {e}")
                finally:
                    self._speech_queue.task_done()
        finally:
            loop.close()

    async def _speak_async(self, text: str):
        """Async TTS synthesis + pygame playback (runs inside the worker's event loop)."""
        import edge_tts
        import pygame

        chunks = self._chunk_text(text)
        if not chunks:
            return

        for chunk in chunks:
            if self._stop_flag.is_set():
                break

            tmp = None
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
                    tmp = f.name

                communicate = edge_tts.Communicate(
                    text=chunk,
                    voice=getattr(Config, "VOICE_NAME", "en-GB-SoniaNeural"),
                    rate=getattr(Config, "VOICE_RATE", "+8%"),
                )
                await communicate.save(tmp)

                if self._stop_flag.is_set():
                    break

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
                # ── Retry unlink to handle Pygame's delayed file release ──
                # On Windows, pygame holds an OS file handle briefly after
                # unload().  We retry up to 5 times before giving up silently.
                if tmp:
                    for attempt in range(5):
                        try:
                            os.unlink(tmp)
                            break
                        except PermissionError:
                            if attempt < 4:
                                time.sleep(0.1)
                        except FileNotFoundError:
                            break
                        except Exception:
                            break

    # ─────────────────────────────────────────────────────────────
    # GRACEFUL SHUTDOWN — hardware release
    # ─────────────────────────────────────────────────────────────

    def shutdown(self):
        """
        Full graceful shutdown.  Safe to call multiple times.

        1. Signals the worker thread to stop the current utterance.
        2. Enqueues the shutdown sentinel so the worker loop exits cleanly.
        3. Waits up to 3 seconds for the worker to finish (non-blocking on timeout).
        4. Releases pygame.mixer hardware hooks.

        Registered with atexit so it fires automatically on normal exit,
        sys.exit(), and exceptions that propagate to the top level.
        """
        if getattr(self, "_shutdown_called", False):
            return
        self._shutdown_called = True

        # Tell the worker to stop the current chunk and exit after finishing
        self.stop_speaking()
        try:
            self._speech_queue.put_nowait(_SHUTDOWN_SENTINEL)
        except Exception:
            pass

        # Wait for the worker to drain gracefully (max 3s)
        if self._worker_thread.is_alive():
            self._worker_thread.join(timeout=3.0)

        # Release the pygame hardware device
        try:
            import pygame
            if pygame.mixer.get_init():
                pygame.mixer.music.stop()
                pygame.mixer.quit()   # ← releases OS audio handle
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────
    # AUDIO WARMUP
    # ─────────────────────────────────────────────────────────────

    def _prime_audio_output(self):
        """Warm the output device once so the first spoken word is not clipped."""
        try:
            import pygame

            duration_ms = max(20, int(getattr(Config, "AUDIO_WARMUP_MS", 120)))
            sample_rate = int(getattr(Config, "AUDIO_SAMPLE_RATE", 24000))
            channels    = int(getattr(Config, "AUDIO_CHANNELS", 2))
            frames      = max(1, int(sample_rate * duration_ms / 1000))

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
                for attempt in range(5):
                    try:
                        os.unlink(tmp)
                        break
                    except PermissionError:
                        if attempt < 4:
                            time.sleep(0.1)
                    except (FileNotFoundError, Exception):
                        break
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────
    # TEXT UTILITIES
    # ─────────────────────────────────────────────────────────────

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
        max_chars     = max(80, int(getattr(Config, "TTS_MAX_CHARS_PER_CHUNK", 220)))

        chunks  = []
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