"""IRIS microphone doctor.

Run from project root:
    python tools\doctor_mic.py

Optional:
    python tools\doctor_mic.py --device 1 --seconds 4

Records a short sample from the chosen microphone, reports RMS/peak level, and
saves a WAV file under exports/ so device selection can be verified quickly.
"""

from __future__ import annotations

import argparse
import audioop
import sys
import wave
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

EXPORTS_DIR = PROJECT_ROOT / "exports"


def _list_devices():
    import speech_recognition as sr

    names = sr.Microphone.list_microphone_names()
    for idx, name in enumerate(names):
        print(f"[{idx}] {name}")
    return names


def _record(device_index: int | None, seconds: float, sample_rate: int = 16000):
    import speech_recognition as sr

    recognizer = sr.Recognizer()
    recognizer.energy_threshold = 300
    recognizer.dynamic_energy_threshold = False
    source = sr.Microphone(device_index=device_index, sample_rate=sample_rate)
    with source as mic:
        print(f"Recording {seconds:.1f}s from device_index={device_index}. Speak clearly now...")
        audio = recognizer.record(mic, duration=seconds)
    return audio


def _save_wav(audio, device_index: int | None) -> Path:
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    suffix = "default" if device_index is None else str(device_index)
    path = EXPORTS_DIR / f"mic_doctor_device_{suffix}.wav"
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(audio.sample_width)
        wav.setframerate(audio.sample_rate)
        wav.writeframes(audio.get_raw_data())
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Test microphone capture quality.")
    parser.add_argument("--device", type=int, default=None, help="Microphone device index. Omit for default input.")
    parser.add_argument("--seconds", type=float, default=4.0, help="Recording duration in seconds.")
    parser.add_argument("--list", action="store_true", help="List devices only.")
    args = parser.parse_args()

    print("IRIS Microphone Doctor")
    print("=" * 60)
    names = _list_devices()
    print()
    if args.list:
        return 0
    if args.device is not None and not (0 <= args.device < len(names)):
        print(f"Invalid device index: {args.device}")
        return 2

    try:
        audio = _record(args.device, args.seconds)
    except Exception as exc:
        print(f"capture: failed - {exc}")
        return 1

    raw = audio.get_raw_data()
    rms = audioop.rms(raw, audio.sample_width) if raw else 0
    peak = audioop.max(raw, audio.sample_width) if raw else 0
    wav_path = _save_wav(audio, args.device)

    print(f"sample_rate: {audio.sample_rate}")
    print(f"sample_width: {audio.sample_width}")
    print(f"bytes: {len(raw)}")
    print(f"rms: {rms}")
    print(f"peak: {peak}")
    print(f"wav: {wav_path}")

    if rms < 80:
        print("Doctor result: input is very quiet or wrong device. Try another device index.")
        return 1
    if rms < 250:
        print("Doctor result: input is low. It may work only with a lower COMMAND_RMS_THRESHOLD.")
        return 0
    print("Doctor result: microphone is capturing usable speech level.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
