from __future__ import annotations

import importlib
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


def _make_stub(name: str, **attrs) -> types.ModuleType:
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class _DummyConsole:
    def print(self, *args, **kwargs):
        return None


class _DummyMixerMusic:
    def get_busy(self):
        return False

    def stop(self):
        return None

    def unload(self):
        return None


class _DummyMixer:
    music = _DummyMixerMusic()

    @staticmethod
    def init():
        return None

    @staticmethod
    def get_init():
        return True


class _DummyRecognizer:
    def __init__(self):
        self.pause_threshold = 0
        self.phrase_threshold = 0
        self.non_speaking_duration = 0
        self.dynamic_energy_threshold = False
        self.energy_threshold = 0

    def adjust_for_ambient_noise(self, source, duration=0.5):
        return None


class _DummyMicrophone:
    _names = ["Default Mic", "USB Headset", "Array Mic", "Studio Mic"]

    def __init__(self, device_index=None):
        self.device_index = device_index

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    @staticmethod
    def list_microphone_names():
        return list(_DummyMicrophone._names)

    @staticmethod
    def get_pyaudio():
        class _PyAudioModule:
            class PyAudio:
                def get_default_input_device_info(self):
                    return {"index": 1, "name": "USB Headset"}

                def terminate(self):
                    return None

        return _PyAudioModule


_make_stub("numpy")
_make_stub("rich", __path__=[])
_make_stub("rich.console", Console=_DummyConsole)
_make_stub("pygame", __path__=[], mixer=_DummyMixer)
_make_stub("config")
_make_stub("core", __path__=[str(ROOT / "core")])
_make_stub("core.logger", get_logger=lambda name: MagicMock(debug=MagicMock(), info=MagicMock(), warning=MagicMock(), error=MagicMock()))
_make_stub("speech_recognition", Recognizer=_DummyRecognizer, Microphone=_DummyMicrophone)

import config


class _Config:
    WAKE_RMS_THRESHOLD = 400
    COMMAND_RMS_THRESHOLD = 550
    WAKE_STT_PRIORITY = "cloud_first"
    PIPER_TTS_WARMUP = False
    SPEAK_IN_TEXT_MODE = False
    PREFERRED_MIC_NAME = ""
    MIC_DEVICE_INDEX = 3
    MIC_SAMPLE_RATE = 16000
    LOCAL_WHISPER_LANGUAGE_HINT = "en"


config.Config = _Config

sys.modules.pop("core.voice", None)
voice_module = importlib.import_module("core.voice")
Voice = voice_module.Voice


class TestVoiceStartupHardening(unittest.TestCase):
    def test_voice_init_uses_configured_mic_index_and_sets_name(self):
        voice = Voice(text_mode=False)
        self.assertTrue(voice.mic_ready)
        self.assertEqual(voice.mic_device_index, 3)
        self.assertEqual(voice.mic_name, "Studio Mic")

    def test_voice_init_uses_default_device_when_not_configured(self):
        with patch.object(voice_module.Config, "MIC_DEVICE_INDEX", None), patch.object(voice_module.Config, "PREFERRED_MIC_NAME", ""):
            voice = Voice(text_mode=False)
        self.assertTrue(voice.mic_ready)
        self.assertEqual(voice.mic_device_index, 1)
        self.assertEqual(voice.mic_name, "USB Headset")

    def test_voice_init_uses_preferred_mic_name_when_configured(self):
        with patch.object(voice_module.Config, "MIC_DEVICE_INDEX", None), patch.object(voice_module.Config, "PREFERRED_MIC_NAME", "Array"):
            voice = Voice(text_mode=False)
        self.assertTrue(voice.mic_ready)
        self.assertEqual(voice.mic_device_index, 2)
        self.assertEqual(voice.mic_name, "Array Mic")

    def test_warm_local_stt_swallows_keyboard_interrupt(self):
        voice = Voice(text_mode=True)
        with patch.object(voice, "_get_whisper_model", side_effect=KeyboardInterrupt()):
            voice._warm_local_stt()


if __name__ == "__main__":
    unittest.main(verbosity=2)
