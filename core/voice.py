"""
IRIS Voice Module v4.8 (Production Edition)
===========================================
- Hardware Handoff: Uses unload() to prevent memory read crashes.
- Silence-to-Sound Filter: Prevents "ghost" wake triggers from background noise.
- Barge-in Support: Non-blocking speech with adaptive thresholds.
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
        
        # Sliding Window State
        self.engine          = None
        self._latest_window  = None
        self._window_ready   = threading.Event()
        
        # Confirmation Filter State
        self._ambient_rms    = 0.0
        self._is_ready_for_wake = False

        self._init_audio()
        self._init_mic()

    def _init_audio(self):
        try:
            import pygame
            pygame.mixer.pre_init(frequency=16000, size=-16, channels=1, buffer=512)
            pygame.mixer.init()
            self.audio_ready = True
        except Exception as e:
            console.print(f"[red]Audio init failed:[/red] {e}")

    def _on_new_window(self, window: np.ndarray):
        self._latest_window = window
        self._window_ready.set()

    def _init_mic(self):
        if self.text_mode: return
        try:
            self.engine = SlidingWindowCapture(on_window=self._on_new_window)
            self.engine.start()
            self.mic_ready  = True
        except Exception as e:
            console.print(f"[red]Microphone engine failed to start:[/red] {e}")

    def is_speaking(self) -> bool:
        try:
            import pygame
            return pygame.mixer.music.get_busy()
        except:
            return False

    def stop_speaking(self):
        """Hard reset of hardware to prevent memory read/write crashes."""
        self._stop_flag.set()
        try:
            import pygame
            if pygame.mixer.music.get_busy():
                pygame.mixer.music.stop()
            pygame.mixer.music.unload() # RELEASES RAM POINTER
            time.sleep(0.15)            # Hardware cooling period
        except:
            pass

    def _audio_to_rms(self, audio) -> float:
        try:
            raw = audio.get_raw_data(convert_rate=16000, convert_width=2)
            samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
            if len(samples) == 0: return 0.0
            return float(np.sqrt(np.mean(samples ** 2)))
        except: return 0.0

    def listen_for_wake(self) -> str:
        if self.text_mode: return input("You: ")
        if not self.mic_ready: return ""

        if not self._window_ready.wait(timeout=0.5):
            return ""
        
        self._window_ready.clear()
        window = self._latest_window

        # Calculate Current RMS
        rms = float(np.sqrt(np.mean(window.astype(np.float32) ** 2)))
        
        # Threshold Logic
        base_threshold = getattr(Config, "WAKE_RMS_THRESHOLD", 350)
        if self.privacy_mode: base_threshold += 2500
        if self.is_speaking(): base_threshold += 1500 # Ignore echo
        
        # --- CONFIRMATION FILTER ---
        # If the room is quiet, set 'Ready' flag. 
        # A wake word can ONLY trigger if the system was 'Ready' (preceded by silence).
        if rms < (base_threshold * 0.6):
            self._is_ready_for_wake = True
            console.print(f"[dim]  (System Ready -> Ambient: {rms:.0f})[/dim]", end="\r")
            return ""

        if not self._is_ready_for_wake:
            # Still hearing noise/echo, ignore potential triggers
            return ""

        if rms < base_threshold:
            return ""

        # VALID TRIGGER: Noise detected after silence
        console.print(f"\n[cyan]  (Clean Start Detected! RMS: {rms:.0f})[/cyan]")
        self._is_ready_for_wake = False # Reset flag
        
        wav_bytes = build_wav_bytes(window)
        return self._transcribe_groq_bytes(wav_bytes, prompt="iris")

    def listen_for_command(self) -> str:
        if self.text_mode: return input("You: ")
        
        # Force hardware unload before switching to Mic
        self.stop_speaking()
        
        if not self.mic_ready: return ""
        self.engine.stop()
        
        import speech_recognition as sr
        r = sr.Recognizer()
        r.energy_threshold = getattr(Config, "MIC_ENERGY_THRESHOLD", 200)
        r.pause_threshold = 0.8
        
        try:
            with sr.Microphone() as source:
                console.print("[dim]Listening...[/dim]")
                audio = r.listen(source, timeout=10, phrase_time_limit=30)
            
            # Hallucination Gate
            if self._audio_to_rms(audio) < getattr(Config, "WAKE_RMS_THRESHOLD", 350):
                self.engine.start()
                return ""
                
            wav_bytes = audio.get_wav_data(convert_rate=16000, convert_width=2)
            result = self._transcribe_groq_bytes(wav_bytes)
            
            self.engine.start()
            return result
        except:
            self.engine.start()
            return ""

    def speak(self, text: str):
        if not text or self.io_disabled: return
        clean = re.sub(r"[*_`#→|]", "", text)
        self.stop_speaking()
        
        with self._tts_lock:
            self._stop_flag.clear()
            threading.Thread(
                target=lambda: asyncio.run(self._speak_async(clean)),
                daemon=True
            ).start()

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
                    if self._stop_flag.is_set(): break
                    await asyncio.sleep(0.05)
            finally:
                try: 
                    pygame.mixer.music.unload()
                    os.unlink(tmp)
                except: pass
        self._window_ready.clear()

    def _transcribe_groq_bytes(self, wav_bytes: bytes, prompt="") -> str:
        try:
            from groq import Groq
            client = Groq(api_key=Config.GROQ_API_KEY)
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