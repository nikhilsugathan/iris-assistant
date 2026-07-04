from __future__ import annotations

import os

os.environ["IRIS_DISABLE_VOICE_IO"] = "true"
os.environ["STT_LANGUAGE"] = "auto"
os.environ["IRIS_LOCK_TTS_VOICE"] = "true"
os.environ["IRIS_MULTILINGUAL_TTS"] = "false"
os.environ["IRIS_STICKY_LANGUAGE_TTS"] = "false"


def test_recognized_single_word_multilingual_cues_are_substantive():
    import main
    from core.self_model import SelfModel

    model = SelfModel()
    for cue in ("dime", "hola", "merci", "danke", "ciao", "namaste"):
        assert main._is_recognized_multilingual_cue(cue), cue
        assert main._is_substantive_voice_input(cue, model), cue


def test_known_short_noise_words_remain_non_substantive():
    import main
    from core.self_model import SelfModel

    model = SelfModel()
    for noise in ("urn", "rifle", "aloft"):
        assert not main._is_recognized_multilingual_cue(noise), noise
        assert not main._is_substantive_voice_input(noise, model), noise


def test_non_substantive_control_fragments_remain_filtered():
    import main
    from core.self_model import SelfModel

    model = SelfModel()
    for fragment in ("yes", "no", "okay", "hmm", "thing"):
        assert main._is_substantive_voice_input(fragment, model) is False
