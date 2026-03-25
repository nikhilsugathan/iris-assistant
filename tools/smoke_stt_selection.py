"""
IRIS speech-selection smoke test.

Validates the adaptive command transcription path without requiring a live
microphone or network call.
"""

from __future__ import annotations

from pathlib import Path
import sys

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from config import Config
from core.voice import TranscriptCandidate, Voice


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class DummyGuard:
    def allows_local_stt(self):
        return True, ""


class FakeAudio:
    def __init__(self, seconds: float) -> None:
        self.sample_rate = 16000
        self.sample_width = 2
        self.frame_data = b"\x00" * int(self.sample_rate * self.sample_width * seconds)


class StubVoice(Voice):
    def _init_audio(self):
        self.audio_ready = False

    def _init_mic(self):
        self.mic_ready = False
        self.recognizer = None
        self.microphone = None


def main() -> None:
    original_priority = Config.STT_PRIORITY

    try:
        Config.STT_PRIORITY = "adaptive"
        voice = StubVoice(text_mode=True)
        voice.resource_guard = DummyGuard()

        long_audio = FakeAudio(seconds=3.2)
        short_audio = FakeAudio(seconds=0.9)

        groq_calls = {"count": 0}

        voice._transcribe_windows_candidate = lambda audio: TranscriptCandidate(  # type: ignore[method-assign]
            backend="system",
            text="open notepad",
            confidence=0.93,
            language="en-US",
        )

        def should_not_call(audio):
            groq_calls["count"] += 1
            return TranscriptCandidate(backend="groq", text="cloud fallback", confidence=1.0)

        voice._transcribe_groq_candidate = should_not_call  # type: ignore[method-assign]
        voice._transcribe_google_candidate = lambda audio: TranscriptCandidate(backend="google")  # type: ignore[method-assign]

        text = voice._transcribe_command(long_audio)
        assert_true(text == "open notepad", "High-confidence local transcript should be accepted.")
        assert_true(groq_calls["count"] == 0, "Cloud fallback should not run when the local transcript is strong.")

        groq_calls["count"] = 0
        voice._transcribe_windows_candidate = lambda audio: TranscriptCandidate(  # type: ignore[method-assign]
            backend="system",
            text="open",
            confidence=0.41,
            language="en-US",
        )

        def groq_candidate(audio):
            groq_calls["count"] += 1
            return TranscriptCandidate(
                backend="groq",
                text="open notepad and type hello",
                confidence=1.0,
                language="en",
            )

        voice._transcribe_groq_candidate = groq_candidate  # type: ignore[method-assign]
        text = voice._transcribe_command(long_audio)
        assert_true(
            text == "open notepad and type hello",
            "Low-confidence local transcription should fall back to Groq.",
        )
        assert_true(groq_calls["count"] == 1, "Groq fallback should run for weak local transcripts.")

        voice._transcribe_windows_candidate = lambda audio: TranscriptCandidate(  # type: ignore[method-assign]
            backend="system",
            text="terminate",
            confidence=0.76,
            language="en-US",
        )
        voice._transcribe_groq_candidate = lambda audio: TranscriptCandidate(backend="groq", text="")  # type: ignore[method-assign]
        text = voice._transcribe_command(short_audio)
        assert_true(text == "terminate", "Short, clear local safety commands should stay local.")

        voice._transcribe_windows_candidate = lambda audio: TranscriptCandidate(  # type: ignore[method-assign]
            backend="system",
            text="open",
            confidence=0.34,
            language="en-US",
        )
        voice._transcribe_groq_candidate = lambda audio: TranscriptCandidate(backend="groq", text="")  # type: ignore[method-assign]
        voice._transcribe_google_candidate = lambda audio: TranscriptCandidate(backend="google", text="")  # type: ignore[method-assign]
        text = voice._transcribe_command(long_audio)
        assert_true(
            text == "open",
            "A weak local transcript should still be returned when every fallback recognizer fails.",
        )

        print("PASS: IRIS adaptive STT selection smoke test completed.")
    finally:
        Config.STT_PRIORITY = original_priority


if __name__ == "__main__":
    main()
