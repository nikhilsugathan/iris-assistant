import os

os.environ.setdefault("IRIS_DISABLE_VOICE_IO", "true")


def test_security_url_validation_uses_hostname_matching():
    from core.security import SAFE, WARNING, SecurityGuard

    guard = SecurityGuard(brain=None)

    assert guard._check_url("https://github.com/owner/repo")[0] == SAFE
    assert guard._check_url("https://github.com.example.invalid/download.exe")[0] == WARNING
    assert guard._check_url("https://example.invalid/?next=github.com")[0] == WARNING


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


def test_config_hardening_defaults_are_present():
    import core  # noqa: F401 - applies runtime config hardening
    from config import Config

    assert getattr(Config, "GROQ_STT_MODEL", "") == "whisper-large-v3-turbo"
    assert getattr(Config, "COMMAND_RMS_THRESHOLD", 0) >= 400
    assert getattr(Config, "ALLOW_ADMIN_SAFETY_BYPASS", True) is False
    assert getattr(Config, "REQUIRE_ADMIN_APPROVAL", False) is True
