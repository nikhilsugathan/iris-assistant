import subprocess
import os
import time
import threading
import numpy as np
import speech_recognition as sr
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "hide")
from pygame import mixer
from config import Config
from core.logger import get_logger

logger = get_logger("Voice")

class Voice:
    def __init__(self, text_mode: bool = False):
        self.text_mode = text_mode
        self._force_io_disabled = os.getenv("IRIS_DISABLE_VOICE_IO", "false").lower() == "true"
        self.io_disabled = text_mode or self._force_io_disabled  # Fixes CRIT-01 build assertion
        self.privacy_mode = False
        self.mic_ready = False
        self.engine = "edge-tts"
        self._whisper_model = None
        self._whisper_lock = threading.Lock()
        self._whisper_load_failed = False
        self._stt_language = self._normalize_stt_language()
        
        self._window_ready = threading.Event()
        self._latest_window = None
        self._tts_lock = threading.Lock()
        self._speech_thread = None
        
        if not self.io_disabled:
            self._init_mic()
            # CRIT-01: Gated hardware initialization
            try:
                mixer.init()
            except Exception as e:
                logger.error(f"Mixer init failed: {e}")
            if self._prefer_local_stt():
                self._load_local_stt()

    def _normalize_stt_language(self) -> str:
        language = getattr(Config, "STT_LANGUAGE", "en-US") or "en"
        return language.split("-", 1)[0].split("_", 1)[0].lower()

    def _prefer_local_stt(self) -> bool:
        return getattr(Config, "WAKE_STT_PRIORITY", "cloud_first").lower() == "local_first"

    def _load_local_stt(self):
        if self._whisper_model is not None:
            return self._whisper_model
        if self._whisper_load_failed:
            return None

        with self._whisper_lock:
            if self._whisper_model is not None:
                return self._whisper_model
            if self._whisper_load_failed:
                return None

            try:
                from faster_whisper import WhisperModel

                self._whisper_model = WhisperModel(
                    getattr(Config, "LOCAL_WHISPER_MODEL", "base"),
                    device=getattr(Config, "LOCAL_WHISPER_DEVICE", "cpu"),
                    compute_type=getattr(Config, "LOCAL_WHISPER_COMPUTE_TYPE", "int8"),
                    download_root=getattr(Config, "LOCAL_WHISPER_CACHE_DIR", None),
                )
                return self._whisper_model
            except Exception as e:
                self._whisper_load_failed = True
                logger.warning(f"Local STT unavailable: {e}")
                return None

    def _transcribe_local(self, audio: sr.AudioData, mode: str = "command"):
        model = self._whisper_model or self._load_local_stt()
        if model is None:
            raise RuntimeError("Local Whisper model unavailable")

        raw_pcm = audio.get_raw_data(
            convert_rate=Config.MIC_SAMPLE_RATE,
            convert_width=2,
        )
        audio_samples = np.frombuffer(raw_pcm, dtype=np.int16).astype(np.float32)
        if audio_samples.size == 0:
            return None

        audio_samples /= 32768.0
        initial_prompt = "iris aletheia protocol" if mode == "wake" else "iris aletheia protocol command"
        beam_size = 1 if mode == "wake" else 5

        segments, _ = model.transcribe(
            audio_samples,
            language=self._stt_language,
            beam_size=beam_size,
            vad_filter=True,
            condition_on_previous_text=False,
            initial_prompt=initial_prompt,
        )
        transcript = " ".join(segment.text.strip() for segment in segments if segment.text.strip()).strip()
        return transcript or None

    def _transcribe_cloud(self, audio: sr.AudioData):
        return self.recognizer.recognize_google(
            audio,
            language=getattr(Config, "STT_LANGUAGE", "en-US"),
        )

    def _transcribe_audio(self, audio: sr.AudioData, mode: str):
        if self._prefer_local_stt():
            try:
                if self._whisper_model is None and self._load_local_stt() is None:
                    raise RuntimeError("Local Whisper model unavailable")
                return self._transcribe_local(audio, mode=mode)
            except Exception as e:
                logger.warning(f"Local STT failed during {mode}: {e}")
        return self._transcribe_cloud(audio)

    def _init_mic(self):
        """Probes hardware for the Aletheia spec."""
        try:
            self.recognizer = sr.Recognizer()
            self.recognizer.dynamic_energy_threshold = False
            self.recognizer.energy_threshold = Config.WAKE_RMS_THRESHOLD
            self.mic = sr.Microphone()
            with self.mic as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
            self.recognizer.energy_threshold = max(
                self.recognizer.energy_threshold, Config.WAKE_RMS_THRESHOLD
            )
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


    def listen_for_wake(self):
        """Listen for wake word using speech recognition."""
        if not self.mic_ready: 
            import time; time.sleep(0.5); return None
        try:
            self.recognizer.energy_threshold = Config.WAKE_RMS_THRESHOLD
            with self.mic as source:
                audio = self.recognizer.listen(source, timeout=5, phrase_time_limit=5)
            return self._transcribe_audio(audio, mode="wake")
        except Exception:
            return None

    def listen_for_command(self):
        """Listen for a follow-up command."""
        if not self.mic_ready: return None
        try:
            self.recognizer.energy_threshold = Config.COMMAND_RMS_THRESHOLD
            with self.mic as source:
                audio = self.recognizer.listen(source, timeout=8, phrase_time_limit=10)
            return self._transcribe_audio(audio, mode="command")
        except Exception:
            return None
        finally:
            self.recognizer.energy_threshold = Config.WAKE_RMS_THRESHOLD

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
