"""
IRIS Voice Engine v4.8.3
========================
- Hardened Thread Locking (Zombie Thread Fix)
- Dynamic RMS Gates: Wake (400) / Command (550)
- Support for Calibration & Privacy Mode
"""

import subprocess
import os
import time
import threading
import numpy as np
import speech_recognition as sr
from pygame import mixer
from config import Config
from core.logger import get_logger

logger = get_logger("Voice")

class Voice:
    def __init__(self, text_mode=False):
        """Initializes the voice engine with v4.8.3 hardened gates."""
        self.text_mode = text_mode
        self.privacy_mode = False
        self.mic_ready = False
        self.engine = "edge-tts"
        
        # Calibration support for diagnostics.py
        self._window_ready = threading.Event()
        self._latest_window = None
        
        # Thread safety locks
        self._tts_lock = threading.Lock()
        self._speech_thread = None
        
        if not self.text_mode:
            self._init_mic()
        
        mixer.init()

    def _init_mic(self):
        """Probes audio hardware for the Aletheia spec."""
        try:
            self.recognizer = sr.Recognizer()
            self.recognizer.energy_threshold = Config.WAKE_RMS_THRESHOLD
            self.mic = sr.Microphone()
            with self.mic as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
            self.mic_ready = True
        except Exception as e:
            logger.error(f"Microphone init failed: {e}")
            self.mic_ready = False

    def toggle_privacy(self):
        """Toggles eavesdropping on/off."""
        self.privacy_mode = not self.privacy_mode
        status = "ENABLED" if self.privacy_mode else "DISABLED"
        logger.warning(f"Privacy Mode {status}")

    def is_speaking(self):
        """Checks if the mixer is currently active."""
        return mixer.get_init() and mixer.music.get_busy()

    def stop_speaking(self):
        """Stops audio immediately to allow barge-in."""
        if mixer.get_init():
            mixer.music.stop()
            mixer.music.unload()

    def speak(self, text):
        """Atomic TTS execution with thread serialization."""
        if not text: return
        
        with self._tts_lock:
            self.stop_speaking()
            # Serialize: Wait for any previous thread to die
            if self._speech_thread and self._speech_thread.is_alive():
                self._speech_thread.join(timeout=0.3)
            
            self._speech_thread = threading.Thread(target=self._speak_async, args=(text,))
            self._speech_thread.daemon = True
            self._speech_thread.start()

    def _speak_async(self, text):
        """Internal worker: tries Piper TTS first, falls back to edge-tts + pygame."""
        piper_model = Config.PIPER_MODEL_PATH
        piper_exe = Config.PIPER_EXE_PATH
        if piper_model and os.path.exists(piper_model):
            try:
                from core.piper_tts import PiperTTSEngine
                engine = PiperTTSEngine(model_path=piper_model, piper_exe=piper_exe)
                engine.speak(text)
                return  # Success — skip the old pipeline
            except Exception as e:
                from rich.console import Console as _Console
                _Console().print(f"[yellow]Piper TTS failed, falling back: {e}[/yellow]")
        self._speak_edge_tts(text)

    def _speak_edge_tts(self, text):
        """Internal worker for edge-tts generation with hardened file validation."""
        temp_file = "temp_speech.mp3"
        try:
            # 1. Clean up stale files before starting
            if os.path.exists(temp_file):
                try: os.remove(temp_file)
                except: pass

            # 2. Call Edge-TTS using a list to prevent shell injection
            subprocess.run(
                [
                    "edge-tts",
                    "--voice", Config.VOICE_NAME,
                    "--rate", Config.VOICE_RATE,
                    "--text", text,
                    "--write-media", temp_file,
                ],
                check=False,
                capture_output=True,
            )
            
            # 3. Security Gate: Only load if file exists AND is larger than 0 bytes
            if os.path.exists(temp_file) and os.path.getsize(temp_file) > 0:
                try:
                    mixer.music.load(temp_file)
                    mixer.music.play()
                    while mixer.music.get_busy():
                        time.sleep(0.1)
                except Exception as e:
                    logger.error(f"Pygame failed to play audio: {e}")
            else:
                logger.error("TTS generation failed. Microsoft API may be down (403 Forbidden).")
                
        finally:
            self.stop_speaking()
            if os.path.exists(temp_file):
                try: os.remove(temp_file)
                except: pass

    def listen_for_wake(self):
        """Listens for triggers using the WAKE_RMS_THRESHOLD."""
        if self.text_mode or self.privacy_mode: return None
        
        with self.mic as source:
            try:
                audio = self.recognizer.listen(source, timeout=2, phrase_time_limit=3)
                # Calibration hook: update latest window for diagnostics
                self._latest_window = np.frombuffer(audio.get_raw_data(), dtype=np.int16)
                self._window_ready.set()
                
                text = self.recognizer.recognize_google(audio).lower()
                return text
            except:
                return None

    def listen_for_command(self):
        """Listens for follow-ups using the COMMAND_RMS_THRESHOLD."""
        if self.text_mode: return None
        
        with self.mic as source:
            self.recognizer.energy_threshold = Config.COMMAND_RMS_THRESHOLD
            try:
                audio = self.recognizer.listen(source, timeout=5, phrase_time_limit=10)
                return self.recognizer.recognize_google(audio)
            except:
                return None
            finally:
                self.recognizer.energy_threshold = Config.WAKE_RMS_THRESHOLD