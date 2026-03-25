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
    original_wake_priority = Config.WAKE_STT_PRIORITY
    original_system_stt_max_languages = Config.SYSTEM_STT_MAX_LANGUAGES
    original_wake_system_max_languages = Config.WAKE_SYSTEM_MAX_LANGUAGES
    original_additional_languages = list(Config.STT_ADDITIONAL_LANGUAGES)
    original_model = Config.LOCAL_WHISPER_MODEL
    original_device = Config.LOCAL_WHISPER_DEVICE
    original_compute_type = Config.LOCAL_WHISPER_COMPUTE_TYPE

    try:
        Config.STT_PRIORITY = "adaptive"
        Config.WAKE_STT_PRIORITY = "adaptive"
        Config.SYSTEM_STT_MAX_LANGUAGES = 2
        Config.WAKE_SYSTEM_MAX_LANGUAGES = 2
        Config.STT_ADDITIONAL_LANGUAGES = ["de-DE", "fr-FR"]
        Config.LOCAL_WHISPER_MODEL = "auto"
        Config.LOCAL_WHISPER_DEVICE = "auto"
        Config.LOCAL_WHISPER_COMPUTE_TYPE = "auto"
        voice = StubVoice(text_mode=True)
        voice.resource_guard = DummyGuard()
        voice._supports_faster_whisper = lambda: True  # type: ignore[method-assign]

        long_audio = FakeAudio(seconds=3.2)
        short_audio = FakeAudio(seconds=0.9)

        local_whisper_calls = {"count": 0}
        groq_calls = {"count": 0}

        def faster_candidate(audio):
            local_whisper_calls["count"] += 1
            return TranscriptCandidate(
                backend="faster_whisper",
                text="open calculator",
                confidence=0.91,
                language="en",
            )

        voice._transcribe_faster_whisper_candidate = faster_candidate  # type: ignore[method-assign]

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
        assert_true(text == "open calculator", "Adaptive mode should prefer the local Whisper backend when available.")
        assert_true(local_whisper_calls["count"] == 1, "Local Whisper backend should be consulted in adaptive mode.")
        assert_true(groq_calls["count"] == 0, "Cloud fallback should not run when the local transcript is strong.")

        groq_calls["count"] = 0
        local_whisper_calls["count"] = 0
        voice._transcribe_faster_whisper_candidate = lambda audio: TranscriptCandidate(  # type: ignore[method-assign]
            backend="faster_whisper",
            text="open",
            confidence=0.62,
            language="en",
        )
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
            "Weak local Whisper transcription should fall back to Groq.",
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
        assert_true(
            voice._recent_command_language == "en-US",
            "Accepted local command transcripts should update the recent command language cache.",
        )

        local_whisper_calls["count"] = 0
        voice._transcribe_faster_whisper_candidate = lambda audio: TranscriptCandidate(backend="faster_whisper", text="")  # type: ignore[method-assign]
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

        voice._recent_command_language = "de-DE"
        command_languages = voice._system_stt_languages(wake_mode=False)
        assert_true(
            command_languages == ["de-DE", "en-US"],
            "System command STT should prioritize the recent language and then the primary configured language.",
        )

        voice._recent_wake_language = "en-GB"
        wake_languages = voice._system_stt_languages(wake_mode=True)
        assert_true(
            wake_languages == ["en-GB", "en-US"],
            "Wake STT should prioritize the most recent wake language without scanning the full language list.",
        )

        gpu_profile_voice = StubVoice(text_mode=True)
        gpu_profile_voice._local_whisper_runtime_cache = {"has_cuda": True, "total_ram_gb": 24.0}
        gpu_runtime = gpu_profile_voice._resolve_local_whisper_runtime()
        assert_true(
            gpu_runtime == {
                "model": "distil-large-v3",
                "device": "cuda",
                "compute_type": "float16",
            },
            "Auto Whisper runtime selection should choose the GPU distil profile on CUDA machines.",
        )

        cpu_profile_voice = StubVoice(text_mode=True)
        cpu_profile_voice._local_whisper_runtime_cache = {"has_cuda": False, "total_ram_gb": 6.0}
        cpu_runtime = cpu_profile_voice._resolve_local_whisper_runtime()
        assert_true(
            cpu_runtime == {
                "model": "tiny.en",
                "device": "cpu",
                "compute_type": "int8",
            },
            "Auto Whisper runtime selection should downshift to a lightweight CPU profile on smaller machines.",
        )

        wake_faster_calls = {"count": 0}
        google_wake_calls = {"count": 0}
        voice._transcribe_windows_wake_candidate = lambda audio: TranscriptCandidate(backend="system", text="")  # type: ignore[method-assign]

        def wake_faster_candidate(audio):
            wake_faster_calls["count"] += 1
            return TranscriptCandidate(
                backend="faster_whisper",
                text="hey iris",
                confidence=0.81,
                language="en",
            )

        def wake_google_candidate(audio):
            google_wake_calls["count"] += 1
            return TranscriptCandidate(
                backend="google",
                text="cloud wake",
                confidence=0.9,
                language="en-US",
            )

        voice._transcribe_faster_whisper_candidate = wake_faster_candidate  # type: ignore[method-assign]
        voice._transcribe_google_candidate = wake_google_candidate  # type: ignore[method-assign]
        wake_text = voice._transcribe_wake(short_audio)
        assert_true(
            wake_text == "hey iris",
            "Adaptive wake STT should fall back to local Whisper before using Google.",
        )
        assert_true(
            wake_faster_calls["count"] == 1 and google_wake_calls["count"] == 0,
            "Adaptive wake STT should satisfy a strong local Whisper wake transcript without a cloud fallback.",
        )

        print("PASS: IRIS adaptive STT selection smoke test completed.")
    finally:
        Config.STT_PRIORITY = original_priority
        Config.WAKE_STT_PRIORITY = original_wake_priority
        Config.SYSTEM_STT_MAX_LANGUAGES = original_system_stt_max_languages
        Config.WAKE_SYSTEM_MAX_LANGUAGES = original_wake_system_max_languages
        Config.STT_ADDITIONAL_LANGUAGES = original_additional_languages
        Config.LOCAL_WHISPER_MODEL = original_model
        Config.LOCAL_WHISPER_DEVICE = original_device
        Config.LOCAL_WHISPER_COMPUTE_TYPE = original_compute_type


if __name__ == "__main__":
    main()
