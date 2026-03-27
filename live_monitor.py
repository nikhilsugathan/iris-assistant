
import speech_recognition as sr
import os

def live_monitor(idx):
    r = sr.Recognizer()
    # High-quality headsets often need a specific sample rate
    mic = sr.Microphone(device_index=idx, sample_rate=44100)
    print(f"Monitoring Index {idx}. Talk into your Turtle Beach...")
    
    with mic as source:
        while True:
            # Short 0.1s snapshots of energy
            try:
                # We are essentially "listening" to the raw energy
                energy = r.listen_raw(source, timeout=0.1)
                # This is a simplified way to get a volume bar
                level = r.energy_threshold
                bar = "#" * int(level / 100)
                print(f"Volume: {bar} ({int(level)})", end="\r")
            except:
                pass

live_monitor(7)

