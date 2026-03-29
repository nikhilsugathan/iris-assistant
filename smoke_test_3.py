"""
IRIS Smoke Test 3: API Data Integrity
PURPOSE: Prove that Groq accepts our in-memory WAV bytes and transcribes it.
"""

import pyaudio
import numpy as np
from core.wake_engine import build_wav_bytes
from config import Config

def run_api_test():
    p = pyaudio.PyAudio()
    stream = p.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True, frames_per_buffer=512)

    print("Recording 2 seconds of audio. Say 'Iris' now...")
    frames = []
    # Capture exactly 2 seconds of audio
    for _ in range(0, int(16000 / 512 * 2)):
        frames.append(stream.read(512, exception_on_overflow=False))

    print("Recording complete. Converting to WAV bytes...")
    raw_data = b''.join(frames)
    samples = np.frombuffer(raw_data, dtype=np.int16)
    wav_bytes = build_wav_bytes(samples)

    print(f"WAV size: {len(wav_bytes)} bytes. Sending to Groq API...")
    
    stream.stop_stream()
    stream.close()
    p.terminate()

    try:
        from groq import Groq
        client = Groq(api_key=Config.GROQ_API_KEY)
        res = client.audio.transcriptions.create(
            file=("wake.wav", wav_bytes, "audio/wav"),
            model="whisper-large-v3-turbo",
            prompt="iris",
            response_format="text",
            temperature=0.0
        )
        print(f"\n[SUCCESS] Groq heard: '{res}'")
    except Exception as e:
        print(f"\n[FAILED] Groq API Error: {e}")

if __name__ == "__main__":
    run_api_test()