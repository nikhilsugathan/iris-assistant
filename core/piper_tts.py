"""
IRIS Piper TTS Engine v2.0
==========================
- Local neural TTS synthesis separated from playback
- Supports queued producer/consumer streaming in Voice
- In-memory playback via sounddevice
"""
import os
import shutil
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
        self.piper_exe = self._resolve_piper_exe(piper_exe)
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._sd = None
        self._np = None

    def _resolve_piper_exe(self, piper_exe: str) -> str:
        """Resolve Piper CLI location once up front so missing executables fail fast."""
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        names = []
        if piper_exe:
            names.append(piper_exe)
            if os.name == "nt" and not piper_exe.lower().endswith(".exe"):
                names.append(f"{piper_exe}.exe")
            basename = os.path.basename(piper_exe)
            if basename and basename not in names:
                names.append(basename)
                if os.name == "nt" and not basename.lower().endswith(".exe"):
                    names.append(f"{basename}.exe")
        for default_name in ["piper", "piper.exe"]:
            if default_name not in names:
                names.append(default_name)

        candidates = []
        for name in names:
            if os.path.isabs(name):
                candidates.append(name)
            else:
                candidates.append(name)
                candidates.append(os.path.join(project_root, name))
                candidates.append(os.path.join(project_root, "piper", name))
                candidates.append(os.path.join(project_root, "piper", "bin", name))

        seen = set()
        ordered_candidates = []
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            ordered_candidates.append(candidate)

        for candidate in ordered_candidates:
            if os.path.isfile(candidate):
                return candidate
            resolved = shutil.which(candidate)
            if resolved:
                return resolved

        raise FileNotFoundError(
            f"Piper executable not found. Looked for: {', '.join(ordered_candidates)}"
        )

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
        """Signal the engine to stop current playback."""
        self._stop_event.set()
        if self._sd is not None:
            try:
                self._sd.stop()
            except Exception:
                pass

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
        """Play raw PCM bytes via sounddevice."""
        if self._stop_event.is_set():
            return
        audio_array = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        sd.play(audio_array, samplerate=self.SAMPLE_RATE)
        sd.wait()
