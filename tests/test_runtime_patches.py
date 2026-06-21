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
    voice = Voice(text_mode=True)
    assert voice.io_disabled
    assert Config.TTS_ENGINE in {"edge", "piper", "auto"}
