import speech_recognition as sr
import pyttsx3
import queue
import threading
import os
import pygame
from pathlib import Path
from core import logger, console
from config import Config

class Voice:
    def __init__(self, device_index=None, text_mode=False):
        self.text_mode = text_mode
        self.current_mood = "normal"
        self.device_index = self._find_working_mic(device_index)
        
        # 1. AUDIO OUTPUT (Hazel)
        self.engine = pyttsx3.init()
        voices = self.engine.getProperty('voices')
        if voices: self.engine.setProperty('voice', voices[0].id) 
        
        # 2. AUDIO FEEDBACK (Chime)
        # Forced to 48000Hz to match Turtle Beach hardware
        pygame.mixer.init(frequency=48000, size=-16, channels=2, buffer=512)
        self.chime_path = Path(__file__).resolve().parent.parent / "media" / "chime.wav"
        
        # 3. HARDWARE SETUP
        self.recognizer = sr.Recognizer()
        # Lowered to 4000 to stabilize the signal on Index 1
        self.recognizer.energy_threshold = 4000 
        self.recognizer.dynamic_energy_threshold = False
        
        self.speech_queue = queue.Queue()
        threading.Thread(target=self._speech_worker, daemon=True).start()

    def _find_working_mic(self, preferred_index):
        """Hunts for the Stealth 700 without cluttering the console."""
        mics = sr.Microphone.list_microphone_names()
        search_order = [preferred_index] if preferred_index is not None else [1, 7, 15, 25]
        for idx in search_order:
            try:
                if idx < len(mics):
                    with sr.Microphone(device_index=idx) as source:
                        logger.info(f"✔ IRIS linked to mic Index {idx}")
                        return idx
            except: continue
        return None

    def _play_chime(self):
        """Audit Fix: Added fail-safe chime logic."""
        if self.chime_path.exists():
            try:
                pygame.mixer.music.load(str(self.chime_path))
                pygame.mixer.music.play()
            except: pass

    def _speech_worker(self):
        while True:
            item = self.speech_queue.get()
            if item:
                text, rate = item
                try:
                    self.engine.setProperty('rate', rate)
                    self.engine.say(text)
                    self.engine.runAndWait()
                except: pass
            self.speech_queue.task_done()

    def speak(self, text, mood="normal"):
        self.current_mood = mood
        rates = {"urgent": 215, "calm": 165, "normal": 185}
        if text.strip():
            # Phonetic correction for "Iris"
            clean_text = text.replace("IRIS", "Eye-ris") 
            self.speech_queue.put((clean_text, rates.get(mood, 185)))

    def listen_for_wake(self):
        if self.text_mode or self.device_index is None: return False
        try:
            with sr.Microphone(device_index=self.device_index) as source:
                audio = self.recognizer.listen(source, timeout=5, phrase_time_limit=3)
                text = self.recognizer.recognize_google(audio).lower()
                if "iris" in text:
                    self._play_chime()
                    return True
        except: return False

    def listen_for_command(self):
        if self.device_index is None: return ""
        with sr.Microphone(device_index=self.device_index) as source:
            try:
                console.print("[cyan]Listening...[/cyan]")
                audio = self.recognizer.listen(source, timeout=5, phrase_time_limit=7)
                return self.recognizer.recognize_google(audio)
            except: return ""