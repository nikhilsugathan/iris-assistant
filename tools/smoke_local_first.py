"""
IRIS local-first routing smoke test.

Verifies that local system answers and local voice backend preferences are
selected before cloud fallbacks.
"""

from __future__ import annotations

from pathlib import Path
import sys
import time

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from config import Config
from core.engine import IRISEngine
from core.voice import TranscriptCandidate, Voice


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class FakeSystemIntel:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def answer_query(self, query: str):
        self.queries.append(query)
        lowered = query.lower()
        if "battery" in lowered:
            return "Battery is at 82% and currently charging."
        if "computer name" in lowered:
            return "This machine is named IRIS-TEST-PC."
        return None


class FakeGuard:
    def __init__(self, allow_stt: bool = True, allow_tts: bool = True) -> None:
        self.allow_stt = allow_stt
        self.allow_tts = allow_tts

    def allows_local_stt(self):
        return self.allow_stt, ""

    def allows_local_tts(self):
        return self.allow_tts, ""

    def allows_local_geo(self):
        return True, ""


class QueueTestVoice(Voice):
    def _init_audio(self):
        self.audio_ready = True

    def _init_mic(self):
        self.mic_ready = False
        self.recognizer = None
        self.microphone = None


def test_system_routing() -> None:
    engine = IRISEngine(text_mode=True)
    engine.brain.system_intel = FakeSystemIntel()

    try:
        battery_result = engine.process_user_input("what's my battery status", speak_response=False)
        assert_true(
            "Battery is at 82%" in battery_result.response,
            "Battery status did not route through the local system-intel handler.",
        )

        host_result = engine.process_user_input("what is my computer name", speak_response=False)
        assert_true(
            "IRIS-TEST-PC" in host_result.response,
            "Hostname query did not route through the local system-intel handler.",
        )

        assert_true(
            engine.brain._classify_query("what is recursion") == "general",
            "Generic knowledge query should stay local-first instead of forcing web search.",
        )
        assert_true(
            engine.brain._classify_query("latest bitcoin price") == "web_search",
            "Time-sensitive market query should still escalate to live web search.",
        )
        assert_true(
            engine.brain._ollama_model_matches("phi3.5", "phi3.5:latest"),
            "Ollama model matching should still accept the configured base model with a tagged variant.",
        )
        assert_true(
            not engine.brain._ollama_model_matches("phi3.5", "phi3.5-mini:latest"),
            "Ollama model matching should not treat phi3.5-mini as phi3.5.",
        )
        assert_true(
            engine.brain._ollama_model_matches("llama3.1:8b", "llama3.1:8b"),
            "Tagged Ollama model matching should accept exact configured names.",
        )
    finally:
        engine.shutdown()


def test_voice_preferences() -> None:
    original_tts = Config.TTS_BACKEND_PRIORITY
    original_stt = Config.STT_PRIORITY
    original_wake = Config.WAKE_STT_PRIORITY

    voice = Voice(text_mode=True)
    voice.text_mode = False
    voice.audio_ready = True
    voice.resource_guard = FakeGuard()

    try:
        tts_calls: list[str] = []
        voice._clean = lambda text: text
        voice._speak_local_blocking = lambda text: tts_calls.append("system") or True
        voice._speak_edge_blocking = lambda text: tts_calls.append("edge") or True

        Config.TTS_BACKEND_PRIORITY = "system_first"
        voice.speak("Local first voice check.")
        assert_true(tts_calls == ["system"], "TTS did not prefer the local backend first.")

        stt_calls: list[str] = []
        voice._supports_faster_whisper = lambda: False  # type: ignore[method-assign]
        voice._transcribe_windows_candidate = lambda audio: stt_calls.append("system") or TranscriptCandidate(  # type: ignore[method-assign]
            backend="system",
            text="terminate now",
            confidence=0.95,
            language="en-US",
        )
        voice._transcribe_groq_candidate = lambda audio: stt_calls.append("groq") or TranscriptCandidate(backend="groq")  # type: ignore[method-assign]
        voice._transcribe_google_candidate = lambda audio: stt_calls.append("google") or TranscriptCandidate(backend="google")  # type: ignore[method-assign]

        Config.STT_PRIORITY = "system_first"
        result = voice._transcribe_command(object())
        assert_true(result == "terminate now", "System-first STT did not return the local recognizer result.")
        assert_true(stt_calls == ["system"], "System-first STT did not consult the local recognizer first.")

        wake_calls: list[str] = []
        voice._transcribe_windows_wake_candidate = lambda audio: wake_calls.append("system") or TranscriptCandidate(  # type: ignore[method-assign]
            backend="system",
            text="iris",
            confidence=0.91,
            language="en-US",
        )
        voice._transcribe_google_candidate = lambda audio: wake_calls.append("google") or TranscriptCandidate(backend="google")  # type: ignore[method-assign]

        Config.WAKE_STT_PRIORITY = "system_first"
        wake_result = voice._transcribe_wake(object())
        assert_true(wake_result == "iris", "Wake STT did not return the local recognizer result.")
        assert_true(wake_calls == ["system"], "Wake STT did not prefer the local recognizer first.")

        fallback_tts_calls: list[str] = []
        voice.resource_guard = FakeGuard(allow_stt=False, allow_tts=False)
        voice._speak_local_blocking = lambda text: fallback_tts_calls.append("system") or True
        voice._speak_edge_blocking = lambda text: fallback_tts_calls.append("edge") or True
        voice.speak("Guarded voice check.")
        assert_true(
            fallback_tts_calls == ["edge"],
            "Resource guard should skip local TTS and fall back safely.",
        )

        guarded_stt_calls: list[str] = []
        voice._transcribe_windows_candidate = lambda audio: guarded_stt_calls.append("system") or TranscriptCandidate(  # type: ignore[method-assign]
            backend="system",
            text="local result",
            confidence=0.95,
            language="en-US",
        )
        voice._transcribe_groq_candidate = lambda audio: guarded_stt_calls.append("groq") or TranscriptCandidate(  # type: ignore[method-assign]
            backend="groq",
            text="cloud result",
            confidence=1.0,
            language="en",
        )
        voice._transcribe_google_candidate = lambda audio: guarded_stt_calls.append("google") or TranscriptCandidate(backend="google")  # type: ignore[method-assign]
        guarded_result = voice._transcribe_command(object())
        assert_true(
            guarded_result == "cloud result",
            "Resource guard should skip local STT and use the fallback recognizer.",
        )
        assert_true(
            guarded_stt_calls == ["groq"],
            "Resource guard should bypass local STT when local resources are constrained.",
        )
    finally:
        Config.TTS_BACKEND_PRIORITY = original_tts
        Config.STT_PRIORITY = original_stt
        Config.WAKE_STT_PRIORITY = original_wake
        voice.stop()


def test_background_speech_cancellation() -> None:
    voice = QueueTestVoice(text_mode=False)
    spoken: list[str] = []
    voice._clean = lambda text: text  # type: ignore[method-assign]
    voice._speak_with_backends = lambda text, backend_priority=None: spoken.append(text)  # type: ignore[method-assign]

    try:
        voice._tts_lock.acquire()
        first = voice.speak_background("first")
        second = voice.speak_background("second")
        time.sleep(0.05)
        voice._tts_lock.release()
        first.join(timeout=1)
        second.join(timeout=1)

        assert_true(
            spoken == ["second"],
            "Only the latest queued background speech should survive the speech-generation guard.",
        )

        voice._tts_lock.acquire()
        third = voice.speak_background("third")
        time.sleep(0.05)
        voice.stop_speaking()
        voice._tts_lock.release()
        third.join(timeout=1)

        assert_true(
            spoken == ["second"],
            "stop_speaking() should cancel queued background speech before it reaches playback.",
        )
    finally:
        if voice._tts_lock.locked():
            voice._tts_lock.release()
        voice.stop()


def main() -> None:
    test_system_routing()
    test_voice_preferences()
    test_background_speech_cancellation()
    print("PASS: IRIS local-first smoke test completed.")


if __name__ == "__main__":
    main()
