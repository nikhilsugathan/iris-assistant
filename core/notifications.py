import sys
import threading

class SystemNotifier:
    def __init__(self, app_id="IRIS Agentic Core"):
        self.app_id = app_id

    def send_toast(self, title, message, alert_type="info"):
        """Sends a non-blocking Windows Toast notification (no-op on non-Windows)."""
        if sys.platform != "win32":
            return

        def _show():
            try:
                from winotify import Notification, audio
                sound = audio.Default if alert_type == "info" else audio.LoopingAlarm
                toast = Notification(app_id=self.app_id, title=title, msg=message)
                toast.set_audio(sound, loop=False)
                toast.show()
            except Exception:
                pass

        # Run in background thread so it doesn't lag the Brain
        threading.Thread(target=_show, daemon=True).start()