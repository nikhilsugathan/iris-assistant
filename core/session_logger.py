"""
IRIS Session Logger v1.0
========================
Handles persistent Markdown logging for Aletheia production sessions.
"""

import os
from datetime import datetime
from config import Config

class SessionLogger:
    def __init__(self):
        """Initializes the session log and ensures the history directory exists."""
        self.history_dir = "history"
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.filename = f"{self.history_dir}/session_{self.session_id}.md"
        
        # Ensure the history directory exists to prevent FileNotFoundError
        if not os.path.exists(self.history_dir):
            os.makedirs(self.history_dir)
            
        self._write_header()

    def _write_header(self):
        """Writes the session metadata header to the Markdown file."""
        header = (
            f"# IRIS Session Log: {self.session_id}\n"
            f"- **System**: {Config.SYSTEM_NAME} v4.8.3\n"
            f"- **Codename**: {Config.INNER_CODENAME}\n"
            f"- **Motto**: {Config.SYSTEM_MOTTO}\n"
            f"- **VRAM Target**: RTX 5050 (8GB)\n"
            f"---\n\n"
        )
        with open(self.filename, "w", encoding="utf-8") as f:
            f.write(header)

    def log_turn(self, speaker: str, text: str):
        """Appends a single turn to the session transcript."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = f"**[{timestamp}] {speaker}**: {text}\n\n"
        
        try:
            with open(self.filename, "a", encoding="utf-8") as f:
                f.write(entry)
        except Exception as e:
            print(f"[!] Logger Error: Could not write to session log: {e}")

    def finalize(self):
        """Closes the session log with a final timestamp."""
        footer = f"\n---\n*Session Terminated at {datetime.now().strftime('%H:%M:%S')}*"
        try:
            with open(self.filename, "a", encoding="utf-8") as f:
                f.write(footer)
        except Exception:
            pass