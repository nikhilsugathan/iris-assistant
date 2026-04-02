import subprocess
import os
import time
import threading
import tempfile
import queue
import re
import numpy as np
import speech_recognition as sr
from pygame import mixer
from rich.console import Console
from config import Config
from core.logger import get_logger

logger = get_logger("Voice")
console = Console()

class Voice:
    _QUEUE_SENTINEL = object()
    _CHUNK_MIN_CHARS = 120

    def __init__(self, text_mode=False):
        self.text_mode = text_mode
        self.mic_ready = False
        self.recognizer = None
        self.mic = None
        self._piper_engine = None
        self._piper_disabled = False
        self._piper_lock = threading.Lock()
        self._resolved_piper_model_path = None
        self._piper_ready_announced = False
        self._whisper_model = None
        self._whisper_disabled = False
        self._whisper_lock = threading.Lock()
        self._whisper_loading = False
        self._whisper_ready_announced = False
        self._whisper_download_announced = False
        
        self._tts_lock = threading.Lock()
        self._active_stop_event = None
        self._utterance_queue = queue.Queue()
        self._speech_active = False
        self._speech_state_lock = threading.Lock()
        self._speech_worker = threading.Thread(target=self._run_speech_worker, daemon=True)
        self._speech_worker.start()
        
        if not self.text_mode or getattr(Config, "SPEAK_IN_TEXT_MODE", False):
            try:
                mixer.init()
            except Exception as e:
                logger.error(f"Audio Warning: Could not initialize pygame mixer - {e}")

        if not self.text_mode:
            self._init_mic()
            if getattr(Config, "WAKE_STT_PRIORITY", "cloud_first") == "local_first":
                threading.Thread(target=self._warm_local_stt, daemon=True).start()
            if getattr(Config, "PIPER_TTS_WARMUP", False):
                threading.Thread(target=self._warm_local_tts, daemon=True).start()

    def _init_mic(self):
        """Probes hardware for the Aletheia spec."""
        try:
            self.recognizer = sr.Recognizer()
            self.recognizer.pause_threshold = 0.45
            self.recognizer.phrase_threshold = 0.2
            self.recognizer.non_speaking_duration = 0.25
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
        with self._speech_state_lock:
            queue_pending = not self._utterance_queue.empty()
            speech_active = self._speech_active
        try:
            mixer_busy = mixer.get_init() and mixer.music.get_busy()
        except:
            mixer_busy = False
        return speech_active or queue_pending or mixer_busy

    def stop_speaking(self):
        stop_event = self._active_stop_event
        if stop_event is not None:
            stop_event.set()
        if self._piper_engine is not None:
            try:
                self._piper_engine.stop()
            except Exception:
                pass
        try:
            if mixer.get_init():
                mixer.music.stop()
                mixer.music.unload()
        except: pass
        while True:
            try:
                self._utterance_queue.get_nowait()
                self._utterance_queue.task_done()
            except queue.Empty:
                break

    def speak(self, text, interrupt=True):
        if not text: return
        if self.text_mode and not getattr(Config, "SPEAK_IN_TEXT_MODE", False): return
        
        with self._tts_lock:
            if interrupt or self._active_stop_event is None or self._active_stop_event.is_set():
                self.stop_speaking()
                self._active_stop_event = threading.Event()
            self._utterance_queue.put((text, self._active_stop_event))

    def _run_speech_worker(self):
        while True:
            text, stop_event = self._utterance_queue.get()
            try:
                if stop_event.is_set():
                    continue
                self._set_speech_active(True)
                self._speak_utterance(text, stop_event)
            except Exception as e:
                logger.error(f"Speech worker failed: {e}")
            finally:
                self._set_speech_active(False)
                self._utterance_queue.task_done()

    def _set_speech_active(self, active):
        with self._speech_state_lock:
            self._speech_active = active

    def _speak_utterance(self, text, stop_event):
        clean_text = self._clean_for_speech(text)
        if not clean_text or stop_event.is_set():
            return
        engine = self._get_piper_engine()
        if engine is not None:
            try:
                chunks = self._split_speech_chunks(clean_text)
                if len(chunks) == 1:
                    engine.speak(chunks[0])
                else:
                    self._stream_piper_chunks(engine, chunks, stop_event)
                return
            except Exception as e:
                self._piper_disabled = True
                self._piper_engine = None
                logger.error(f"Piper TTS Engine Failed: {e}")
                logger.warning("Falling back to Edge-TTS...")

        if not stop_event.is_set():
            self._speak_edge_tts(clean_text, stop_event)

    def _stream_piper_chunks(self, engine, chunks, stop_event):
        audio_queue = queue.Queue(maxsize=2)
        producer_error = []

        def produce():
            try:
                for chunk in chunks:
                    if stop_event.is_set():
                        return
                    audio_bytes = engine.synthesize(chunk)
                    if stop_event.is_set():
                        return
                    while not stop_event.is_set():
                        try:
                            audio_queue.put(audio_bytes, timeout=0.1)
                            break
                        except queue.Full:
                            continue
            except Exception as e:
                producer_error.append(e)
            finally:
                while True:
                    try:
                        audio_queue.put(self._QUEUE_SENTINEL, timeout=0.1)
                        break
                    except queue.Full:
                        if stop_event.is_set():
                            break

        def consume():
            while True:
                if stop_event.is_set():
                    return
                try:
                    item = audio_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                if item is self._QUEUE_SENTINEL:
                    return
                engine.play_audio(item)

        producer = threading.Thread(target=produce, daemon=True)
        consumer = threading.Thread(target=consume, daemon=True)
        producer.start()
        consumer.start()
        producer.join()
        consumer.join()

        if producer_error:
            raise producer_error[0]

    def _clean_for_speech(self, text):
        cleaned = re.sub(r'[*_`#>]+', '', text or '')
        cleaned = re.sub(r'\[(.*?)\]\((.*?)\)', r'\1', cleaned)
        cleaned = re.sub(r'\s+', ' ', cleaned)
        return cleaned.strip()

    def _split_speech_chunks(self, text):
        if not text:
            return []
        if len(text) < self._CHUNK_MIN_CHARS:
            return [text]

        sentences = re.split(r'(?<=[.!?])\s+', text)
        chunks = [sentence.strip() for sentence in sentences if sentence.strip()]
        return chunks if len(chunks) > 1 else [text]

    def _get_piper_engine(self):
        if self._piper_disabled:
            return None
        if self._piper_engine is not None:
            return self._piper_engine

        with self._piper_lock:
            if self._piper_engine is not None:
                return self._piper_engine

            piper_model = self._resolve_piper_model_path()
            if not piper_model:
                return None

            try:
                from core.piper_tts import PiperTTSEngine
                self._piper_engine = PiperTTSEngine(
                    model_path=piper_model,
                    piper_exe=getattr(Config, "PIPER_EXE_PATH", "piper"),
                )
                if not self._piper_ready_announced:
                    console.print(f"[bold green][Voice] Local TTS Active ({os.path.basename(piper_model)})[/bold green]")
                    self._piper_ready_announced = True
                return self._piper_engine
            except Exception as e:
                self._piper_disabled = True
                logger.error(f"Piper TTS setup failed: {e}")
                logger.warning("Falling back to Edge-TTS...")
                return None

    def _resolve_piper_model_path(self):
        if self._resolved_piper_model_path is not None:
            return self._resolved_piper_model_path

        configured = getattr(Config, "PIPER_MODEL_PATH", "")
        candidates = []
        if configured:
            candidates.append(configured)

        project_root = os.path.dirname(os.path.dirname(__file__))
        models_dir = os.path.join(project_root, "models")
        if os.path.isdir(models_dir):
            for name in sorted(os.listdir(models_dir)):
                if name.endswith(".onnx"):
                    candidates.append(os.path.join(models_dir, name))

        for candidate in candidates:
            if candidate and os.path.exists(candidate):
                self._resolved_piper_model_path = candidate
                if configured and candidate != configured:
                    logger.warning(f"Configured Piper model missing; using fallback model: {candidate}")
                return self._resolved_piper_model_path

        if configured:
            logger.warning(f"Configured Piper model not found: {configured}")
        self._resolved_piper_model_path = ""
        return None

    def _warm_local_tts(self):
        engine = self._get_piper_engine()
        if engine is None:
            return
        try:
            engine.synthesize("Ready.")
        except Exception as e:
            logger.warning(f"Local TTS warm-up failed: {e}")

    def listen_for_wake(self):
        """Listen for wake word using speech recognition."""
        if not self.mic_ready: 
            import time; time.sleep(0.5); return None
        try:
            with self.mic as source:
                audio = self.recognizer.listen(source, timeout=4, phrase_time_limit=4)
            return self._transcribe_audio(audio, phrase_type="wake")
        except Exception:
            return None

    def listen_for_command(self):
        """Listen for a follow-up command."""
        if not self.mic_ready: return None
        self.recognizer.energy_threshold = Config.COMMAND_RMS_THRESHOLD
        try:
            with self.mic as source:
                audio = self.recognizer.listen(source, timeout=5, phrase_time_limit=7)
            return self._transcribe_audio(audio, phrase_type="command")
        except Exception:
            return None

    def _transcribe_audio(self, audio, phrase_type="command"):
        priority = getattr(Config, "WAKE_STT_PRIORITY", "cloud_first")
        if priority == "local_first":
            text = self._transcribe_local(audio, phrase_type=phrase_type)
            if text:
                return text
            return self._transcribe_google(audio)
        text = self._transcribe_google(audio)
        if text:
            return text
        return self._transcribe_local(audio, phrase_type=phrase_type)

    def _transcribe_google(self, audio):
        try:
            return self.recognizer.recognize_google(audio, language=getattr(Config, "STT_LANGUAGE", "en-US"))
        except Exception:
            return None

    def _transcribe_local(self, audio, phrase_type="command"):
        if self._whisper_loading and self._whisper_model is None:
            return None
        model = self._get_whisper_model()
        if model is None:
            return None

        try:
            samples = np.frombuffer(
                audio.get_raw_data(convert_rate=16000, convert_width=2),
                dtype=np.int16,
            ).astype(np.float32) / 32768.0
            prompt = "iris" if phrase_type == "wake" else None
            segments, _ = model.transcribe(
                samples,
                beam_size=1,
                best_of=1,
                temperature=0.0,
                language=getattr(Config, "LOCAL_WHISPER_LANGUAGE_HINT", "en") or None,
                vad_filter=True,
                condition_on_previous_text=False,
                initial_prompt=prompt,
            )
            text = " ".join(segment.text.strip() for segment in segments).strip()
            return text or None
        except Exception as e:
            self._whisper_disabled = True
            logger.error(f"Local STT failed: {e}")
            return None

    def _warm_local_stt(self):
        self._get_whisper_model()

    def _get_whisper_model(self):
        if self._whisper_disabled:
            return None
        if self._whisper_model is not None:
            return self._whisper_model

        with self._whisper_lock:
            if self._whisper_model is not None:
                return self._whisper_model

            try:
                self._whisper_loading = True
                from faster_whisper import WhisperModel
                cache_root = os.path.join(os.path.dirname(os.path.dirname(__file__)), "models", ".cache")
                os.makedirs(cache_root, exist_ok=True)
                download_needed = self._reset_incomplete_whisper_downloads(cache_root)
                if not download_needed:
                    download_needed = not self._has_whisper_weights(cache_root)
                if download_needed and not self._whisper_download_announced:
                    console.print("[bold yellow][Voice] Downloading Local Whisper...[/bold yellow]")
                    self._whisper_download_announced = True

                self._whisper_model = WhisperModel(
                    getattr(Config, "LOCAL_WHISPER_MODEL", "base"),
                    device=getattr(Config, "LOCAL_WHISPER_DEVICE", "cpu"),
                    compute_type=getattr(Config, "LOCAL_WHISPER_COMPUTE_TYPE", "int8"),
                    download_root=cache_root,
                )
                if not self._whisper_ready_announced:
                    console.print("[bold green][Voice] Local STT Active[/bold green]")
                    self._whisper_ready_announced = True
                return self._whisper_model
            except Exception as e:
                self._whisper_disabled = True
                logger.warning(f"Local STT unavailable, falling back to Google STT: {e}")
                return None
            finally:
                self._whisper_loading = False

    def _reset_incomplete_whisper_downloads(self, cache_root):
        removed = False
        for root, _, files in os.walk(cache_root):
            for name in files:
                if not name.endswith(".incomplete"):
                    continue
                try:
                    os.remove(os.path.join(root, name))
                    removed = True
                except OSError:
                    continue
        return removed

    def _has_whisper_weights(self, cache_root):
        model_name = getattr(Config, "LOCAL_WHISPER_MODEL", "base").replace("/", "--")
        repo_dir = os.path.join(cache_root, f"models--Systran--faster-whisper-{model_name}")
        snapshots_dir = os.path.join(repo_dir, "snapshots")
        if not os.path.isdir(snapshots_dir):
            return False
        for root, _, files in os.walk(snapshots_dir):
            if any(name.endswith((".bin", ".safetensors")) for name in files):
                return True
        return False

    def _speak_edge_tts(self, text, stop_event=None):
        temp_file = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
                temp_file = tmp.name

            subprocess.run(
                ["edge-tts", "--voice", Config.VOICE_NAME, "--rate", Config.VOICE_RATE, 
                 "--text", text, "--write-media", temp_file],
                check=False, capture_output=True
            )
            
            if stop_event is not None and stop_event.is_set():
                return

            if os.path.exists(temp_file) and os.path.getsize(temp_file) > 0:
                try:
                    # Final safety check before loading
                    if not mixer.get_init():
                        mixer.init()
                    mixer.music.load(temp_file)
                    mixer.music.play()
                    while mixer.music.get_busy():
                        time.sleep(0.1)
                except Exception as e:
                    logger.error(f"Playback failed: {e}")
        finally:
            if temp_file and os.path.exists(temp_file):
                try: os.remove(temp_file)
                except: pass
