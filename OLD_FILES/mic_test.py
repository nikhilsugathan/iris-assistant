import pyaudio
import numpy as np
import time

p = pyaudio.PyAudio()

print("--- AVAILABLE MICROPHONES ---")
for i in range(p.get_device_count()):
    dev = p.get_device_info_by_index(i)
    if dev.get('maxInputChannels') > 0:
        print(f"Index {i}: {dev.get('name')}")

print("\n--- TESTING DEFAULT OS MICROPHONE ---")
try:
    stream = p.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True, frames_per_buffer=512)
    print("Speak into your headset now! Press Ctrl+C to stop.\n")
    while True:
        data = stream.read(512, exception_on_overflow=False)
        rms = np.sqrt(np.mean(np.frombuffer(data, dtype=np.int16).astype(np.float32) ** 2))
        bar = "█" * min(int(rms / 100), 40)
        print(f"\rLive Volume (RMS): {rms:6.0f} | {bar:<40}", end="")
        time.sleep(0.05)
except Exception as e:
    print(f"\nError: {e}")
finally:
    p.terminate()