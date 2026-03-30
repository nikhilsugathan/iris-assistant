"""
IRIS Piper TTS Engine v1.0
==========================
- Local C++ neural TTS (no cloud dependency)
- In-memory audio streaming (no disk I/O)
- Drop-in replacement for edge-tts + pygame pipeline
"""
import subprocess
import threading
import os
import io
import wave


class PiperTTSEngine:
    """
    Synthesizes speech using a local Piper TTS model and streams it
    directly to the speakers via sounddevice — no disk writes.
    """
    def __init__(self, model_path: str, piper_exe: str = "piper"):
        self.model_path = model_path
        self.piper_exe = piper_exe
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

    def speak(self, text: str) -> None:
        """Synthesize text and play it immediately in-memory."""
        with self._lock:
            self._stop_event.clear()
            try:
                import sounddevice as sd
                import numpy as np
                audio_bytes = self._synthesize(text)
                if audio_bytes and not self._stop_event.is_set():
                    self._play_wav_bytes(audio_bytes, sd, np)
            except ImportError:
                raise RuntimeError("sounddevice not installed. Run: pip install sounddevice")
            except Exception as e:
                raise RuntimeError(f"Piper TTS playback failed: {e}")

    def stop(self) -> None:
        """Signal the engine to stop current playback."""
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

    def _play_wav_bytes(self, raw_bytes: bytes, sd, np) -> None:
        """Play raw PCM bytes via sounddevice."""
        # Piper outputs 16-bit PCM at 22050 Hz mono by default
        audio_array = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        sd.play(audio_array, samplerate=22050)
        sd.wait()
