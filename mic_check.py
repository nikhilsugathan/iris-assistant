
import speech_recognition as sr
import time

def test_index(idx):
    r = sr.Recognizer()
    try:
        with sr.Microphone(device_index=idx) as source:
            print(f"\n--- Testing Index {idx} ---")
            print("Say \"Iris\" several times...")
            # Use a fixed duration to sample noise
            r.adjust_for_ambient_noise(source, duration=2)
            print(f"Base Ambient Noise Level: {r.energy_threshold}")
            
            # Record for 5 seconds and print peaks
            start = time.time()
            while time.time() - start < 5:
                # We access the raw energy directly to see if it "wiggles"
                # This is a hack to get live levels
                pass 
            print("Done sampling.")
    except Exception as e:
        print(f"Index {idx} failed: {e}")

test_index(7)

