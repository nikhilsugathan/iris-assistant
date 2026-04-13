"""
IRIS Sliding Window Wake Engine
===============================
Captures raw audio in a continuous circular buffer.
Emits a fixed 2-second window every 0.8 seconds for Wake Word checking.
Immune to background noise deadlocks.
"""

import io
import logging
import time
import wave
import struct
import threading
import collections
import numpy as np
import pyaudio
from typing import Optional

_log = logging.getLogger("WakeEngine")

# ── Configuration ─────────────────────────────────────────────────────────────
SAMPLE_RATE = 16000          
SAMPLE_WIDTH = 2             
CHANNELS = 1
CHUNK_FRAMES = 512           
WINDOW_DURATION = 2.0        # Seconds of audio to analyze
EMIT_INTERVAL = 0.8          # How often to check for the wake word

_WINDOW_FRAMES = int(SAMPLE_RATE * WINDOW_DURATION)   
_CHUNK_SIZE = CHUNK_FRAMES * SAMPLE_WIDTH * CHANNELS   


class SlidingWindowCapture:
    def __init__(
        self,
        device_index: Optional[int] = None,
        on_window: Optional[callable] = None,
    ):
        self._device_index = device_index
        self._on_window = on_window
        self._buffer = collections.deque(maxlen=_WINDOW_FRAMES)
        self._pa: Optional[pyaudio.PyAudio] = None
        self._stream = None
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        # R-05: acquire PyAudio handle first, then open the stream inside a
        # try/except so that a failed open() always terminates the PA instance
        # rather than leaving a dangling handle holding the Windows audio session.
        self._pa = pyaudio.PyAudio()
        try:
            self._stream = self._pa.open(
                format=pyaudio.paInt16,
                channels=CHANNELS,
                rate=SAMPLE_RATE,
                input=True,
                frames_per_buffer=CHUNK_FRAMES,
                input_device_index=self._device_index,
            )
        except Exception:
            self._pa.terminate()
            self._pa = None
            raise
        self._running = True
        self._thread = threading.Thread(
            target=self._capture_loop,
            daemon=True,
            name="IRIS-WakeCapture",
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._stream:
            self._stream.stop_stream()
            self._stream.close()
        if self._pa:
            self._pa.terminate()

    def _capture_loop(self) -> None:
        last_emit = time.monotonic()

        while self._running:
            try:
                raw = self._stream.read(CHUNK_FRAMES, exception_on_overflow=False)
            except Exception:
                time.sleep(0.01)
                continue

            n_samples = len(raw) // SAMPLE_WIDTH
            samples = struct.unpack(f"<{n_samples}h", raw)
            self._buffer.extend(samples)

            now = time.monotonic()
            if (now - last_emit) >= EMIT_INTERVAL and len(self._buffer) >= _WINDOW_FRAMES:
                last_emit = now
                window = np.array(list(self._buffer), dtype=np.int16)
                if self._on_window:
                    try:
                        self._on_window(window)
                    except Exception as _wce:
                        # R-03: log so we know if the wake-word callback drops
                        # (e.g. Groq 429, audio buffer issue).  Without this the
                        # mic silently stops triggering and IRIS appears hung.
                        _log.warning("[WakeEngine] on_window callback error: %s", _wce)

def build_wav_bytes(samples: np.ndarray) -> bytes:
    """Safely converts raw numpy audio into a WAV format for Groq."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(samples.tobytes())
    return buf.getvalue()