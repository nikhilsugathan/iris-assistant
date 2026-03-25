"""
IRIS local-first routing smoke test.

Verifies that local system answers and local voice backend preferences are
selected before cloud fallbacks.
"""

from __future__ import annotations

from pathlib import Path
import sys
import time
import types

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from config import Config
import core.brain as brain_module
from core.engine import IRISEngine
from core.system_intel import SystemIntel
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


class FakeDesktopIntel:
    def answer_query(self, query: str):
        lowered = query.lower()
        if "what am i looking at" in lowered:
            return "Active window: SmokePad at 20,30 sized 1280x720."
        if "what windows are open" in lowered:
            return "Open windows right now: active: SmokePad; open: Browser."
        return None


class FakeClipboardIntel:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def answer_query(self, query: str):
        lowered = query.lower()
        if "what's on my clipboard" in lowered or "what is on my clipboard" in lowered:
            return "Clipboard currently contains: Traceback: smoke failure."
        return None

    def build_prompt(self, query: str):
        self.prompts.append(query)
        lowered = query.lower()
        if "summarize what i copied" in lowered:
            return ("Summarize the following clipboard content concisely.\n\nClipboard content:\nTraceback: smoke failure", None)
        return None, None


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
    engine.brain.desktop_intel = FakeDesktopIntel()
    fake_clipboard = FakeClipboardIntel()
    engine.brain.clipboard_intel = fake_clipboard

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

        active_window_result = engine.process_user_input("what am I looking at", speak_response=False)
        assert_true(
            "Active window: SmokePad" in active_window_result.response,
            "Active-window question did not route through the local desktop-intel handler.",
        )

        clipboard_result = engine.process_user_input("what's on my clipboard", speak_response=False)
        assert_true(
            "Clipboard currently contains:" in clipboard_result.response,
            "Direct clipboard question did not route through the local clipboard handler.",
        )

        original_call_api = engine.brain._call_api
        llm_prompts: list[str] = []

        def fake_call_api(api: str, prompt: str, **kwargs):
            llm_prompts.append(prompt)
            return "Clipboard summary ready."

        engine.brain._call_api = fake_call_api  # type: ignore[method-assign]
        clipboard_summary = engine.process_user_input("summarize what I copied", speak_response=False)
        assert_true(
            clipboard_summary.response == "Clipboard summary ready.",
            "Clipboard-aware query did not return the mocked assistant response.",
        )
        assert_true(
            llm_prompts and "Clipboard content:" in llm_prompts[-1],
            "Clipboard-aware query did not expand into a clipboard-backed prompt.",
        )
        engine.brain._call_api = original_call_api  # type: ignore[method-assign]

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


def test_local_tts_engine_reuse() -> None:
    voice = Voice(text_mode=True)
    voice.text_mode = False
    voice.audio_ready = True

    class FakeEngine:
        def __init__(self) -> None:
            self.say_calls: list[str] = []
            self.run_count = 0
            self.stop_count = 0

        def say(self, text: str) -> None:
            self.say_calls.append(text)

        def runAndWait(self) -> None:
            self.run_count += 1

        def stop(self) -> None:
            self.stop_count += 1

        def getProperty(self, name: str):
            return []

        def setProperty(self, name: str, value) -> None:
            return None

    init_calls: list[FakeEngine] = []

    def fake_init():
        engine = FakeEngine()
        init_calls.append(engine)
        return engine

    original_pyttsx3 = sys.modules.get("pyttsx3")
    sys.modules["pyttsx3"] = types.SimpleNamespace(init=fake_init)
    voice._chunk_text = lambda text: [text]  # type: ignore[method-assign]

    try:
        assert_true(voice._speak_local_blocking("first line"), "First local TTS call should succeed with the fake engine.")
        assert_true(voice._speak_local_blocking("second line"), "Second local TTS call should reuse the fake engine successfully.")
        assert_true(len(init_calls) == 1, "Local TTS engine should be initialized once and reused across utterances.")
        assert_true(
            init_calls[0].say_calls == ["first line", "second line"],
            "Local TTS engine reuse should send both utterances through the same engine instance.",
        )
        assert_true(init_calls[0].stop_count == 0, "Reused local TTS engine should not be torn down between utterances.")
        voice.stop()
        assert_true(init_calls[0].stop_count == 1, "Stopping voice should release the cached local TTS engine once.")
    finally:
        if original_pyttsx3 is None:
            sys.modules.pop("pyttsx3", None)
        else:
            sys.modules["pyttsx3"] = original_pyttsx3
        try:
            voice.stop()
        except Exception:
            pass


def test_system_performance_queries() -> None:
    intel = SystemIntel()
    original_reader = intel._read_performance_snapshot
    intel._read_performance_snapshot = lambda: {  # type: ignore[method-assign]
        "CpuPercent": 76.2,
        "TopCpu": [
            {"Name": "chrome#1", "CpuPercent": 32.4},
            {"Name": "Code", "CpuPercent": 18.8},
            {"Name": "ollama", "CpuPercent": 9.1},
        ],
        "FreePhysicalMemory": 6 * 1024 * 1024,
        "TotalVisibleMemorySize": 16 * 1024 * 1024,
    }

    try:
        cpu_answer = intel.answer_query("what's using my cpu right now")
        assert_true(
            "CPU usage is about 76%" in cpu_answer,
            "CPU query did not report the local CPU percentage.",
        )
        assert_true(
            "chrome at 32%" in cpu_answer.lower(),
            "CPU query did not include the top local CPU process summary.",
        )

        slow_answer = intel.answer_query("why is my computer slow")
        assert_true(
            "cpu is around 76%" in slow_answer.lower(),
            "Performance query did not surface the local CPU bottleneck summary.",
        )
        assert_true(
            "memory is about 62% used" in slow_answer.lower(),
            "Performance query did not include the local memory summary.",
        )
    finally:
        intel._read_performance_snapshot = original_reader  # type: ignore[method-assign]


def test_local_first_planner_routing() -> None:
    engine = IRISEngine(text_mode=True)
    original_ollama = engine.brain._call_ollama
    original_call_api = engine.brain._call_api
    original_available = list(engine.brain.available_apis)

    ollama_calls: list[dict] = []
    api_calls: list[dict] = []

    try:
        engine.brain.available_apis = ["ollama_smart", "groq"]
        engine.brain._call_ollama = lambda model, prompt, use_persona, use_memory, **kwargs: ollama_calls.append(  # type: ignore[method-assign]
            {"model": model, "max_tokens": kwargs.get("max_tokens")}
        ) or '{"action_type":"unsupported"}'
        engine.brain._call_api = lambda api, prompt, **kwargs: api_calls.append(  # type: ignore[method-assign]
            {"api": api, "max_tokens": kwargs.get("max_tokens")}
        ) or None

        plan_response = engine.brain.plan_action_json("Generate a plan.")
        fix_response = engine.brain.diagnose_command_failure("Explain a command failure.")

        assert_true(
            plan_response == '{"action_type":"unsupported"}' and fix_response == '{"action_type":"unsupported"}',
            "Planner routing smoke did not return the mocked local planner response.",
        )
        assert_true(
            len(ollama_calls) == 2,
            "Local planner routing should prefer the local Ollama planner path for planning and fixes.",
        )
        assert_true(
            ollama_calls[0]["model"] == Config.OLLAMA_MODEL_PLANNER,
            "Local planner routing did not use the dedicated planner model.",
        )
        assert_true(
            ollama_calls[0]["max_tokens"] == Config.ACTION_PLAN_MAX_TOKENS
            and ollama_calls[1]["max_tokens"] == Config.COMMAND_FIX_MAX_TOKENS,
            "Local planner routing did not use the dedicated planner token budgets.",
        )
        assert_true(
            api_calls == [],
            "Local planner routing should not fall through to cloud APIs when local Ollama is available.",
        )
    finally:
        engine.brain._call_ollama = original_ollama  # type: ignore[method-assign]
        engine.brain._call_api = original_call_api  # type: ignore[method-assign]
        engine.brain.available_apis = original_available
        engine.shutdown()


def test_ollama_stream_chunk_parsing() -> None:
    engine = IRISEngine(text_mode=True)
    original_post = brain_module.requests.post

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def iter_lines(self, decode_unicode=True):
            yield '{"response":"First streamed sentence. ","done":false}'
            yield '{"response":"Second streamed sentence.","done":false}'
            yield '{"response":"","done":true}'

    chunks: list[str] = []

    try:
        brain_module.requests.post = lambda *args, **kwargs: FakeResponse()  # type: ignore[assignment]
        result = engine.brain._call_ollama_streaming(
            "http://localhost:11434",
            {"model": "phi3.5", "prompt": "hi", "stream": False, "options": {"num_predict": 64}},
            chunks.append,
        )
        assert_true(
            result == "First streamed sentence. Second streamed sentence.",
            "Streaming Ollama parser did not rebuild the full response text.",
        )
        assert_true(
            chunks == ["First streamed sentence.", "Second streamed sentence."],
            "Streaming Ollama parser did not emit sentence chunks in order.",
        )
    finally:
        brain_module.requests.post = original_post  # type: ignore[assignment]
        engine.shutdown()


def main() -> None:
    test_system_routing()
    test_voice_preferences()
    test_background_speech_cancellation()
    test_local_tts_engine_reuse()
    test_system_performance_queries()
    test_local_first_planner_routing()
    test_ollama_stream_chunk_parsing()
    print("PASS: IRIS local-first smoke test completed.")


if __name__ == "__main__":
    main()
