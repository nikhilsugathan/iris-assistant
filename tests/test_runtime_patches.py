import os

os.environ.setdefault("IRIS_DISABLE_VOICE_IO", "true")


def test_security_url_validation_uses_hostname_matching():
    from core.security import SAFE, WARNING, SecurityGuard

    guard = SecurityGuard(brain=None)

    assert guard._check_url("https://github.com/owner/repo")[0] == SAFE
    assert guard._check_url("https://github.com.example.invalid/download.exe")[0] == WARNING
    assert guard._check_url("https://example.invalid/?next=github.com")[0] == WARNING


def test_brain_runtime_patches_are_applied():
    from core.brain import Brain

    assert getattr(Brain, "_iris_brain_runtime_patch_applied", False)
    assert getattr(Brain, "_iris_lazy_llm_patch_applied", False)
    assert getattr(Brain, "_iris_vision_fallback_patch_applied", False)
    assert getattr(Brain, "_iris_performance_patch_applied", False)
    assert getattr(Brain, "_iris_multilingual_patch_applied", False)
    assert hasattr(Brain, "_call_gemini_vision")


def test_short_prompt_fast_path_and_settings():
    import core  # noqa: F401
    from core.brain import Brain

    class DummyMemory:
        def add(self, *args, **kwargs):
            pass

        def get_context(self, *args, **kwargs):
            return []

    brain = Brain(DummyMemory())
    assert brain._rewrite_generic_response("hello")
    assert brain._rewrite_generic_response("thanks")
    assert "That's Spanish for" not in brain._rewrite_generic_response("hello")
    assert "llama_cpp" not in brain._get_apis_for_query("general")
    boot = brain._call_groq_simple("Give ONE unique, witty, in-character boot-up line.")
    assert boot
    assert "That's" not in boot
    settings = brain._generation_settings("general", user_input="how are you")
    assert settings["max_tokens"] <= 120
    assert settings["context_turns"] <= 2


def test_multilingual_generation_settings_and_voice_routing():
    import core  # noqa: F401
    from core.brain import Brain
    from core.multilingual_patches import language_instruction_for, tts_voice_for
    from core.voice import Voice

    class DummyMemory:
        def add(self, *args, **kwargs):
            pass

        def get_context(self, *args, **kwargs):
            return []

    brain = Brain(DummyMemory())
    settings = brain._generation_settings("general", user_input="puedes explicarme esto en detalle")
    assert "Spanish" in settings.get("extra_system", "")
    assert "same language" in settings.get("extra_system", "")
    assert language_instruction_for("guten morgen kannst du mir helfen")
    assert tts_voice_for("Hola, mi amor. ¿Qué hacemos?") == "es-ES-ElviraNeural"
    assert tts_voice_for("Guten Morgen. Was steht an?") == "de-DE-KatjaNeural"
    assert getattr(Voice, "_iris_multilingual_voice_patch_applied", False)


def test_language_aware_fast_smalltalk():
    import core  # noqa: F401
    from core.brain import Brain

    class DummyMemory:
        def add(self, *args, **kwargs):
            pass

        def get_context(self, *args, **kwargs):
            return []

    brain = Brain(DummyMemory())
    namaste = brain._rewrite_generic_response("namaste")
    spanish = brain._rewrite_generic_response("mi amor")
    german = brain._rewrite_generic_response("guten morgen")
    malayalam = brain._rewrite_generic_response("namaskaram")
    assert namaste
    assert spanish
    assert german
    assert malayalam
    assert "That's" not in namaste + spanish + german + malayalam
    assert any(token in namaste.lower() for token in ["namaste", "namaskar", "pranam", "aaj", "batao", "bolo"])
    assert any(token in spanish.lower() for token in ["hola", "amor", "dime", "qué", "mision", "misión"])
    assert any(token in german.lower() for token in ["guten", "hallo", "was", "weiter", "aufgabe"])


def test_voice_stability_patch_is_applied_in_text_mode():
    from config import Config
    from core.voice import Voice

    assert getattr(Voice, "_iris_voice_stability_patch_applied", False)
    assert getattr(Voice, "_iris_voice_interrupt_patch_applied", False)
    assert getattr(Voice, "_iris_conservative_voice_override", False)
    assert getattr(Voice, "_iris_balanced_interrupt_default", False)
    assert getattr(Voice, "_iris_single_input_default", False)
    assert getattr(Voice, "_iris_tts_sanitizer_applied", False)
    voice = Voice(text_mode=True)
    assert voice.io_disabled
    assert Config.TTS_ENGINE in {"edge", "piper", "auto"}
    assert getattr(Config, "VOICE_PLAYBACK_MODE", "balanced") in {"balanced", "stable", "realtime"}
    sample = "Hey there! " + chr(0x1F44B) + " How can I help? :sparkles:"
    assert voice._clean_for_speech(sample) == "Hey there! How can I help?"


def test_tts_sanitizer_removes_visual_symbols():
    from core.tts_sanitizer import sanitize_for_tts

    assert sanitize_for_tts("Hey there! " + chr(0x1F44B) + " How can I make your day brighter?") == "Hey there! How can I make your day brighter?"
    assert sanitize_for_tts("Done " + chr(0x2705)) == "Done"
    assert sanitize_for_tts("Great :smile: test") == "Great test"


def test_config_hardening_is_lightweight_by_default():
    import core  # noqa: F401 - applies lightweight runtime config defaults
    from config import Config

    assert getattr(Config, "GROQ_STT_MODEL", "") == "whisper-large-v3-turbo"
    assert getattr(Config, "COMMAND_RMS_THRESHOLD", 0) >= 400
    assert getattr(Config, "VOICE_PLAYBACK_MODE", "balanced") in {"balanced", "stable", "realtime"}
    assert getattr(Config, "STT_LANGUAGE", "")


def test_startup_config_compatibility_defaults_exist():
    import core  # noqa: F401 - applies compatibility defaults
    from config import Config

    required = [
        "PROJECT_ROOT",
        "PUBLIC_NAME",
        "SYSTEM_NAME",
        "INNER_CODENAME",
        "COUNCIL_NAME",
        "SYSTEM_MOTTO",
        "VERSION",
        "MEMORY_FILE",
        "MAX_MEMORY_TURNS",
        "RUNBOOK_MODE",
        "ENABLE_AUTO_SYNC",
        "STT_LANGUAGE",
        "validate",
    ]
    for name in required:
        assert hasattr(Config, name), name
    assert callable(getattr(Config, "validate", None))
    assert Config.validate() is True


def test_memory_uses_lock_and_atomic_helper():
    from core.memory import Memory, _atomic_json_write

    assert callable(_atomic_json_write)
    memory = Memory("test_runtime_memory.json")
    assert hasattr(memory, "_lock")


def test_logger_has_file_and_trace_handlers():
    import logging
    from core.logger import get_logger, get_trace_logger

    logger = get_logger("TestRuntimeLogger")
    trace_logger = get_trace_logger("TestRuntimeLogger")
    trace_parent = logging.getLogger("iris.trace")

    assert any(hasattr(handler, "baseFilename") and handler.baseFilename.endswith("iris.log") for handler in logger.handlers)
    assert trace_logger.propagate is True
    assert any(hasattr(handler, "baseFilename") and handler.baseFilename.endswith("iris_trace.log") for handler in trace_parent.handlers)


def test_observability_hooks_are_available():
    from core.observability import install_observability, trace_callable

    install_observability()

    def sample(value):
        return value + 1

    wrapped = trace_callable(sample, "tests.sample")
    assert wrapped(2) == 3
    assert getattr(wrapped, "_iris_observed", False)
