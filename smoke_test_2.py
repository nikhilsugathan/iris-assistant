"""
IRIS Smoke Test 2: Thread Event Regression
PURPOSE: Prove that the background thread is alive and emitting windows every 0.8s.
"""

import time
from core.wake_engine import SlidingWindowCapture

event_count = 0

def on_window(window):
    global event_count
    event_count += 1
    print(f"[EVENT FIRED] Window {event_count} received! Size: {len(window)}")

print("Starting SlidingWindowCapture thread...")
capture = SlidingWindowCapture(on_window=on_window)
capture.start()

try:
    print("Waiting for audio windows. You should see an event fire every ~0.8 seconds.")
    print("Watching for 10 seconds... Press Ctrl+C to stop manually.\n")
    time.sleep(10)
    print("\nTest complete.")
except KeyboardInterrupt:
    pass
finally:
    capture.stop()