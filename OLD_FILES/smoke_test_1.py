"""
IRIS Smoke Test 1: Hardware & RMS Regression
PURPOSE: Isolate PyAudio, prove the mic works, and check your raw volume.
"""

import pyaudio
import numpy as np
import time

def run_mic_test():
    p = pyaudio.PyAudio()
    
    # 1. Show available microphones
    print("--- AVAILABLE MICROPHONES ---")
    for i in range(p.get_device_count()):
        dev = p.get_device_info_by_index(i)
        if dev.get('maxInputChannels') > 0:
            print(f"Index {i}: {dev.get('name')}")
            
    print("\n--- STARTING LIVE MIC FEED ---")
    try:
        # 2. Open the exact audio format Whisper requires (16000Hz)
        stream = p.open(
            format=pyaudio.paInt16, 
            channels=1, 
            rate=16000, 
            input=True, 
            frames_per_buffer=512
        )
        print("Speak into your headset now! Press Ctrl+C to stop.\n")
        
        # 3. Read audio and calculate RMS volume
        while True:
            data = stream.read(512, exception_on_overflow=False)
            rms = np.sqrt(np.mean(np.frombuffer(data, dtype=np.int16).astype(np.float32) ** 2))
            
            # Create a visual volume bar
            bar = "█" * min(int(rms / 100), 40)
            print(f"\rLive Volume (RMS): {rms:6.0f} | {bar:<40}", end="")
            time.sleep(0.05)
            
    except KeyboardInterrupt:
        print("\n\nStopping test...")
    except Exception as e:
        print(f"\n[ERROR] PyAudio failed: {e}")
    finally:
        p.terminate()

if __name__ == "__main__":
    run_mic_test()