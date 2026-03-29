"""
IRIS Voice Module v4.7 (Sliding Window Edition)
===============================================
- SlidingWindowCapture (Immune to background noise deadlocks)
- 16000Hz Pygame audio pipeline
- Safe Groq BytesIO Tuple upload
- Hallucination Gate (Prevents silence-induced AI hallucinations)
"""

import asyncio
import io
import os
import re
import tempfile
import threading
import time
import wave
import numpy as np

from rich.console import Console
from config import Config
from core.wake_engine import SlidingWindowCapture, build_wav_bytes

console = Console()

class Voice:
    def __init__(self, text_mode: bool = False):
        self.text_mode       = text_mode
        self._tts_lock       = threading.Lock()
        self._stop_flag      = threading.Event()
        self.audio_ready     = False
        self.mic_ready       = False
        self.privacy_mode    = False 
        
        # New Sliding Window State
        self.engine          = None
        self._latest_window  = None
        self._window_ready   = threading.Event()

        self._init_audio()
        self._init_mic()

    @property
    def io_disabled(self) -> bool:
        env_flag = os.environ.get("IRIS_DISABLE_VOICE_IO", "").lower()
        return self.text_mode or env_flag in {"1", "true", "yes"}

    def _init_audio(self):
        try:
            import pygame
            pygame.mixer.pre_init(frequency=16000, size=-16, channels=1, buffer=512)
            pygame.mixer.init()
            self.audio_ready = True
        except Exception as e:
            console.print(f"[red]Audio init failed:[/red] {e}")

    def _on_new_window(self, window: np.ndarray):
        """Callback for the SlidingWindowCapture."""
        self._latest_window = window
        self._window_ready.set()

    def _init_mic(self):
        if self.text_mode: return
        try:
            # Start the sliding window continuous capture
            self.engine = SlidingWindowCapture(on_window=self._on_new_window)
            self.engine.start()
            self.mic_ready  = True
        except Exception as e:
            console.print(f"[red]Microphone engine failed to start:[/red] {e}")

    def toggle_privacy(self) -> bool:
        self.privacy_mode = not self.privacy_mode
        if self.privacy_mode:
            console.print("[bold red]  🔒 Privacy Mode: ON[/bold red]")
        else:
            console.print("[bold green]  🔓 Privacy Mode: OFF[/bold green]")
        return self.privacy_mode

    def _audio_to_rms(self, audio) -> float:
        """Helper to calculate RMS volume from a SpeechRecognition AudioData object."""
        try:
            raw = audio.get_raw_data(convert_rate=16000, convert_width=2)
            samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
            if len(samples) == 0: return 0.0
            return float(np.sqrt(np.mean(samples ** 2)))
        except: return 0.0

    def _transcribe_groq_bytes(self, wav_bytes: bytes, prompt="") -> str:
        """Uploads raw bytes to Groq securely."""
        try:
            from groq import Groq
            client = Groq(api_key=Config.GROQ_API_KEY)
            
            # API FIX: Use tuple format to bypass SDK corruption
            res = client.audio.transcriptions.create(
                file=("wake.wav", wav_bytes, "audio/wav"),
                model="whisper-large-v3-turbo",
                prompt=prompt, 
                response_format="text",
                temperature=0.0
            )
            return (res or "").strip()
        except Exception as e:
            console.print(f"[bold red][DEBUG] Groq Failed:[/bold red] {e}")
            return ""

    def listen_for_wake(self) -> str:
        if self.text_mode: return input("You: ")
        if not self.mic_ready: return ""

        # Wait up to 0.5s for the next 2-second audio window
        if not self._window_ready.wait(timeout=0.5):
            return ""
        
        self._window_ready.clear()
        window = self._latest_window

        # Phase 1: RMS Gate
        rms = float(np.sqrt(np.mean(window.astype(np.float32) ** 2)))
        rms_threshold = getattr(Config, "WAKE_RMS_THRESHOLD", 500)
        if self.privacy_mode: rms_threshold += 2500

        # --- X-RAY DEBUG PRINT ---
        console.print(f"[dim]  (Mic Check -> Current RMS: {rms:.0f} | Target: {rms_threshold})[/dim]", end="\r")
            
        if rms < rms_threshold:
            return ""

        # Phase 2: Whisper Transcription
        console.print(f"\n[cyan]  (Volume passed! Sending to Groq...)[/cyan]")
        wav_bytes = build_wav_bytes(window)
        
        result = self._transcribe_groq_bytes(wav_bytes, prompt="iris")
        console.print(f"[cyan]  (Groq returned: '{result}')[/cyan]")
        
        return result

    def listen_for_command(self) -> str:
        """Temporarily uses the old sr.Recognizer for the long command capture."""
        if self.text_mode: return input("You: ")
        self.stop_speaking()
        if not self.mic_ready: return ""
        
        # Suspend the sliding window temporarily
        self.engine.stop()
        
        import speech_recognition as sr
        r = sr.Recognizer()
        r.energy_threshold = getattr(Config, "MIC_ENERGY_THRESHOLD", 150)
        r.pause_threshold = getattr(Config, "MIC_PAUSE_THRESHOLD", 0.8)
        
        try:
            with sr.Microphone() as source:
                console.print("[dim]Listening...[/dim]")
                audio = r.listen(source, timeout=10, phrase_time_limit=30)
            
            # --- HALLUCINATION GATE ---
            # Rejects audio that doesn't clear the volume threshold
            if self._audio_to_rms(audio) < getattr(Config, "WAKE_RMS_THRESHOLD", 150):
                self.engine.start()
                return ""
                
            import random
            acks = getattr(Config, "THINKING_ACKS", ["On it."])
            console.print(f"[italic cyan]  → {random.choice(acks)}[/italic cyan]")
            
            wav_bytes = audio.get_wav_data(convert_rate=16000, convert_width=2)
            result = self._transcribe_groq_bytes(wav_bytes)
            
            # Restart the sliding window
            self.engine.start()
            return result
            
        except:
            self.engine.start()
            return ""

    def speak(self, text: str):
        if not text or self.io_disabled: return
        clean = re.sub(r"[*_`#→|]", "", text)
        with self._tts_lock:
            self.stop_speaking()
            self._stop_flag.clear()
            asyncio.run(self._speak_async(clean))

    async def _speak_async(self, text: str):
        import edge_tts, pygame
        chunks = [text] if len(text) < 1000 else [s.strip() for s in re.split(r"\n\n", text) if s.strip()]
        
        for chunk in chunks:
            if self._stop_flag.is_set(): break
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
                tmp = f.name
            try:
                comm = edge_tts.Communicate(text=chunk, voice=Config.VOICE_NAME, rate=Config.VOICE_RATE)
                await comm.save(tmp)
                pygame.mixer.music.load(tmp)
                pygame.mixer.music.play()
                
                while pygame.mixer.music.get_busy():
                    if self._stop_flag.is_set(): 
                        pygame.mixer.music.stop()
                        break
                    await asyncio.sleep(0.05)
            finally:
                try: 
                    pygame.mixer.music.unload()
                    os.unlink(tmp)
                except: pass

        # Cooldown so the mic doesn't hear the end of the TTS
        time.sleep(0.6)
        self._window_ready.clear()

    def stop_speaking(self):
        self._stop_flag.set()
        try: import pygame; pygame.mixer.music.stop()
        except: pass