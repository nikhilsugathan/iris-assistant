"""
IRIS Piper TTS Engine v2.0
==========================
- Local neural TTS synthesis separated from playback
- Supports queued producer/consumer streaming in Voice
- In-memory playback via sounddevice
"""
import subprocess
import threading


class PiperTTSEngine:
    """
    Synthesizes speech using a local Piper TTS model and plays raw PCM
    audio buffers via sounddevice.
    """
    SAMPLE_RATE = 22050

    def __init__(self, model_path: str, piper_exe: str = "piper"):
        self.model_path = model_path
        self.piper_exe = piper_exe
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._playback_lock = threading.Lock()
        self._active_stream = None
        self._sd = None
        self._np = None

    def synthesize(self, text: str) -> bytes:
        """Run Piper and return raw PCM bytes for a single text chunk."""
        with self._lock:
            self._stop_event.clear()
            return self._synthesize(text)

    def play_audio(self, raw_bytes: bytes) -> None:
        """Play synthesized PCM bytes unless playback has been cancelled."""
        if not raw_bytes or self._stop_event.is_set():
            return
        sd, np = self._ensure_audio_modules()
        self._play_wav_bytes(raw_bytes, sd, np)

    def speak(self, text: str) -> None:
        """Backward-compatible convenience path for one-shot synthesis + playback."""
        try:
            audio_bytes = self.synthesize(text)
            if audio_bytes and not self._stop_event.is_set():
                self.play_audio(audio_bytes)
        except Exception as e:
            raise RuntimeError(f"Piper TTS playback failed: {e}")

    def stop(self) -> None:
        """Signal the engine to stop current playback.

        Sets the stop event so the chunk loop exits at the next write boundary.
        Does not call sd.stop() or stream.abort() — both cause audible artefacts
        on interrupt. The chunk loop drains within one chunk (~46ms at 22050Hz).
        """
        self._stop_event.set()

    def _synthesize(self, text: str) -> bytes:
        """Run piper CLI and capture raw WAV bytes from stdout."""
        cmd = [
            self.piper_exe,
            "--model", self.model_path,
            "--output-raw",
        ]
        try:
            proc = subprocess.run(
                cmd,
                input=text.encode("utf-8"),
                capture_output=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("Piper TTS timed out after 30 seconds")
        if proc.returncode != 0:
            raise RuntimeError(f"Piper failed: {proc.stderr.decode()}")
        return proc.stdout

    def _ensure_audio_modules(self):
        if self._sd is None or self._np is None:
            try:
                import sounddevice as sd
                import numpy as np
            except ImportError:
                raise RuntimeError("sounddevice not installed. Run: pip install sounddevice")
            self._sd = sd
            self._np = np
        return self._sd, self._np

    def _play_wav_bytes(self, raw_bytes: bytes, sd, np) -> None:
        """Play raw PCM bytes via an owned OutputStream with stop checks."""
        if self._stop_event.is_set():
            return

        audio_array = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        target_rate = self.SAMPLE_RATE

        try:
            from config import Config
            import scipy.signal

            target_rate = int(getattr(Config, "TTS_OUTPUT_SAMPLE_RATE", self.SAMPLE_RATE))
            if target_rate != self.SAMPLE_RATE:
                audio_array = scipy.signal.resample_poly(
                    audio_array, target_rate, self.SAMPLE_RATE
                ).astype(np.float32, copy=False)
        except Exception:
            target_rate = self.SAMPLE_RATE

        with self._playback_lock:
            if self._stop_event.is_set():
                return

            stream = sd.OutputStream(
                samplerate=target_rate,
                channels=1,
                dtype="float32",
            )
            self._active_stream = stream

            try:
                stream.start()
                chunk_size = 2048
                for start in range(0, len(audio_array), chunk_size):
                    if self._stop_event.is_set():
                        break
                    chunk = audio_array[start:start + chunk_size].reshape(-1, 1)
                    stream.write(chunk)
            finally:
                self._active_stream = None
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass
