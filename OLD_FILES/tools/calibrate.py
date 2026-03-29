import pyaudio, numpy as np, time

p = pyaudio.PyAudio()
stream = p.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True, frames_per_buffer=1024)

print("Speak normally. Watch the RMS number. Press Ctrl+C to stop.\n")
try:
    while True:
        data = stream.read(1024, exception_on_overflow=False)
        rms = np.sqrt(np.mean(np.frombuffer(data, dtype=np.int16).astype(np.float32) ** 2))
        print(f"\rCurrent Mic Volume (RMS): {rms:6.0f}", end="")
        time.sleep(0.05)
except KeyboardInterrupt:
    stream.stop_stream(); stream.close(); p.terminate()