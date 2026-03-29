"""
IRIS Audio Capture Engine (Phase 1)
===================================
Non-blocking audio capture engine.
Replaces the blocking sr.Recognizer.listen() loop with listen_in_background(),
which runs audio capture on a daemon thread. The main thread polls a queue
with a timeout, giving Python time to process KeyboardInterrupts cleanly.
"""

import queue
import threading
import time
import speech_recognition as sr
from typing import Optional, Callable

class AudioCaptureEngine:
    def __init__(
        self,
        phrase_time_limit: float = 2.5,
        energy_threshold: int = 400,
        dynamic_threshold: bool = True,
        device_index: Optional[int] = None,
    ):
        self._recognizer = sr.Recognizer()
        self._recognizer.energy_threshold = energy_threshold
        self._recognizer.dynamic_energy_threshold = dynamic_threshold
        
        # Continuous flow settings
        self._recognizer.pause_threshold = 0.6  
        self._recognizer.non_speaking_duration = 0.3

        self._phrase_time_limit = phrase_time_limit
        self._device_index = device_index
        
        # The queue is the bridge between the C-audio thread and Python's main thread
        self._audio_queue: queue.Queue[sr.AudioData] = queue.Queue(maxsize=10)
        self._stop_fn: Optional[Callable] = None
        self._mic: Optional[sr.Microphone] = None
        self._running = False

    def start(self) -> None:
        """
        Calibrates ambient noise then starts background listening.
        Returns immediately — audio capture runs on a daemon thread.
        """
        self._mic = sr.Microphone(device_index=self._device_index)
        with self._mic as source:
            # Brief one-time calibration to establish the noise floor
            self._recognizer.adjust_for_ambient_noise(source, duration=0.8)

        def _callback(recognizer: sr.Recognizer, audio: sr.AudioData) -> None:
            """
            Called by speech_recognition's background thread when a phrase is captured.
            Drops frames if the queue is full to prevent memory leaks.
            """
            try:
                self._audio_queue.put_nowait(audio)
            except queue.Full:
                pass 

        # This spawns the daemon thread
        self._stop_fn = self._recognizer.listen_in_background(
            self._mic,
            _callback,
            phrase_time_limit=self._phrase_time_limit,
        )
        self._running = True

    def get_audio(self, timeout: float = 0.5) -> Optional[sr.AudioData]:
        """
        Get the next audio chunk from the queue, or None if timeout expires.

        CRITICAL FIX: 
        Each call blocks for at most `timeout` seconds. After each timeout, 
        Python checks the OS signal flag, allowing KeyboardInterrupt (Ctrl+C) 
        to be processed safely.
        """
        try:
            return self._audio_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def stop(self) -> None:
        """Stops background listening and releases the microphone hardware."""
        self._running = False
        if self._stop_fn:
            self._stop_fn(wait_for_stop=False) 
        # Give the background thread ~100ms to release WASAPI locks
        time.sleep(0.1)

    def flush(self) -> None:
        """Discards all queued audio (used to prevent IRIS from hearing her own TTS echo)."""
        while not self._audio_queue.empty():
            try:
                self._audio_queue.get_nowait()
            except queue.Empty:
                break

    @property
    def is_running(self) -> bool:
        return self._running