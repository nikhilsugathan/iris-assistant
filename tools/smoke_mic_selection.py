"""
IRIS microphone-selection smoke test.

Ensures the preferred device matcher avoids low-quality headset/hands-free
profiles when a better microphone device from the same family exists.
"""

from __future__ import annotations

from pathlib import Path
import sys

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from core.voice import Voice


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class StubVoice(Voice):
    def _init_audio(self):
        self.audio_ready = False

    def _init_mic(self):
        self.mic_ready = False
        self.recognizer = None
        self.microphone = None


def main() -> None:
    voice = StubVoice(text_mode=True)
    devices = [
        "Microsoft Sound Mapper - Input",
        "Headset Microphone (700 Gen 2 MAX for PS)",
        "Microphone (Turtle Beach Stealth 700 G2 MAX)",
        "Headset Microphone (@System32\\drivers\\bthhfenum.sys,#2;%1 Hands-Free%0;(700 Gen 2 MAX for PS))",
        "Microphone Array (Realtek(R) Audio)",
    ]

    index, name = voice._select_microphone_device(devices, preferred="700 Gen 2")
    assert_true(index == 2, "Preferred Turtle Beach family should choose the direct microphone, not the headset profile.")
    assert_true(
        name == "Microphone (Turtle Beach Stealth 700 G2 MAX)",
        "Microphone selection returned the wrong device name.",
    )

    print("PASS: IRIS microphone selection smoke test completed.")


if __name__ == "__main__":
    main()
