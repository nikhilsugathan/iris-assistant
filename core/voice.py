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
    def __init__(self, text_mode: bool = False):
        self.text_mode = text_mode
        self.io_disabled = text_mode  # Fixes CRIT-01 build assertion
        self.privacy_mode = False
        self.mic_ready = False
        self.engine = "edge-tts"
        
        self._window_ready = threading.Event()
        self._latest_window = None
        self._tts_lock = threading.Lock()
        self._speech_thread = None
        
        if not self.text_mode:
            self._init_mic()
            # CRIT-01: Gated hardware initialization
            try:
                mixer.init()
            except Exception as e:
                logger.error(f"Mixer init failed: {e}")

    def _init_mic(self):
        """Probes hardware for the Aletheia spec."""
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

    def is_speaking(self):
        try:
            return mixer.get_init() and mixer.music.get_busy()
        except: return False

    def stop_speaking(self):
        try:
            if mixer.get_init():
                mixer.music.stop()
                mixer.music.unload()
        except: pass

    def speak(self, text):
        if not text: return
        if self.text_mode and not Config.SPEAK_IN_TEXT_MODE: return
        
        with self._tts_lock:
            self.stop_speaking()
            if self._speech_thread and self._speech_thread.is_alive():
                self._speech_thread.join(timeout=0.3)
            
            self._speech_thread = threading.Thread(target=self._speak_async, args=(text,))
            self._speech_thread.daemon = True
            self._speech_thread.start()

    def _speak_async(self, text):
        # Now Config.VOICE_NAME is guaranteed to exist
        piper_model = Config.PIPER_MODEL_PATH
        if piper_model and os.path.exists(piper_model):
            try:
                from core.piper_tts import PiperTTSEngine
                engine = PiperTTSEngine(model_path=piper_model, piper_exe=Config.PIPER_EXE_PATH)
                engine.speak(text)
                return
            except: pass
        self._speak_edge_tts(text)

    def _speak_edge_tts(self, text):
        temp_file = "temp_speech.mp3"
        try:
            if os.path.exists(temp_file):
                try: os.remove(temp_file)
                except: pass

            subprocess.run(
                ["edge-tts", "--voice", Config.VOICE_NAME, "--rate", Config.VOICE_RATE, 
                 "--text", text, "--write-media", temp_file],
                check=False, capture_output=True
            )
            
            if os.path.exists(temp_file) and os.path.getsize(temp_file) > 0:
                try:
                    mixer.music.load(temp_file)
                    mixer.music.play()
                    while mixer.music.get_busy():
                        time.sleep(0.1)
                except Exception as e:
                    logger.error(f"Playback failed: {e}")
        finally:
            self.stop_speaking()
            if os.path.exists(temp_file):
                try: os.remove(temp_file)
                except: pass