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
    assert hasattr(Brain, "_call_gemini_vision")


def test_voice_stability_patch_is_applied_in_text_mode():
    from config import Config
    from core.voice import Voice

    assert getattr(Voice, "_iris_voice_stability_patch_applied", False)
    assert getattr(Voice, "_iris_voice_interrupt_patch_applied", False)
    assert getattr(Voice, "_iris_conservative_voice_override", False)
    assert getattr(Voice, "_iris_balanced_interrupt_default", False)
    assert getattr(Voice, "_iris_single_input_default", False)
    voice = Voice(text_mode=True)
    assert voice.io_disabled
    assert Config.TTS_ENGINE in {"edge", "piper", "auto"}
    assert getattr(Config, "VOICE_PLAYBACK_MODE", "balanced") in {"balanced", "stable", "realtime"}


def test_config_hardening_is_lightweight_by_default():
    import core  # noqa: F401 - applies lightweight runtime config defaults
    from config import Config

    assert getattr(Config, "GROQ_STT_MODEL", "") == "whisper-large-v3-turbo"
    assert getattr(Config, "COMMAND_RMS_THRESHOLD", 0) >= 400
    assert getattr(Config, "VOICE_PLAYBACK_MODE", "balanced") in {"balanced", "stable", "realtime"}


def test_startup_config_compatibility_defaults_exist():
    import core  # noqa: F401 - applies compatibility defaults
    from config import Config

    assert getattr(Config, "PUBLIC_NAME", "")
    assert getattr(Config, "SYSTEM_NAME", "")
    assert getattr(Config, "SYSTEM_MOTTO", "")
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
