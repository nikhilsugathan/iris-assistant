from __future__ import annotations

import os

os.environ["IRIS_DISABLE_VOICE_IO"] = "true"
os.environ["STT_LANGUAGE"] = "auto"


def test_common_english_phrases_remain_default_language():
    import core  # noqa: F401
    from core.multilingual_patches import detect_language_style

    samples = (
        "I was nearby",
        "comment on the result",
        "come over here",
    )
    for sample in samples:
        assert detect_language_style(sample) is None, sample


def test_distinctive_multiword_cues_still_detect_language():
    import core  # noqa: F401
    from core.multilingual_patches import detect_language_style

    german = detect_language_style("was ist das")
    italian = detect_language_style("come stai")

    assert german is not None and german[0] == "german"
    assert italian is not None and italian[0] == "italian"
