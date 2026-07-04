"""Executor hardening for normal-risk application launch actions."""

from __future__ import annotations

import os
import platform
import subprocess
import webbrowser


_APP_PROTOCOLS = {
    "spotify": ("spotify:", "https://open.spotify.com"),
    "youtube": (None, "https://www.youtube.com"),
    "netflix": ("netflix:", "https://www.netflix.com"),
    "whatsapp": ("whatsapp:", "https://web.whatsapp.com"),
    "gmail": (None, "https://mail.google.com"),
}

_APP_MAP = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "explorer": "explorer.exe",
    "file explorer": "explorer.exe",
    "chrome": "chrome",
    "google chrome": "chrome",
    "firefox": "firefox",
    "edge": "msedge",
    "microsoft edge": "msedge",
    "powershell": "powershell",
    "cmd": "cmd",
    "command prompt": "cmd",
    "word": "winword",
    "excel": "excel",
    "paint": "mspaint",
    "task manager": "taskmgr",
}


def _launch_direct(target: str) -> None:
    if not target:
        raise OSError("No application target specified.")
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if platform.system() == "Windows" else 0
    subprocess.Popen([target], creationflags=creationflags)


def apply_executor_hardening(executor_module) -> None:
    executor_cls = getattr(executor_module, "ActionExecutor", None)
    if executor_cls is None or getattr(executor_cls, "_iris_executor_open_app_hardening_applied", False):
        return

    def _open_app_hardened(self, plan: dict) -> str:
        app = str(plan.get("app_name") or "").strip()
        command = str(plan.get("command") or "").strip()
        url = str(plan.get("url") or "").strip()

        if url:
            if not url.lower().startswith(("https://", "http://")):
                return "I won't open that as a web URL because the scheme is unsupported."
            webbrowser.open(url)
            self._log(f"OPENED URL: {url}")
            return "Done."

        app_key = app.lower()
        if app_key in _APP_PROTOCOLS:
            protocol, fallback_url = _APP_PROTOCOLS[app_key]
            if protocol and platform.system() == "Windows":
                try:
                    os.startfile(protocol)
                    self._log(f"OPENED native app via protocol: {protocol}")
                    return "Done."
                except OSError:
                    pass
            webbrowser.open(fallback_url)
            self._log(f"OPENED browser fallback: {fallback_url}")
            return "Done."

        if not app and command:
            self._log("REJECTED open_app shell command; use run_command permission path")
            return "That plan contains a shell command, not an application target. Use the command action with confirmation."

        target = _APP_MAP.get(app_key, app)
        if not target:
            return "I'm not sure what to open."

        try:
            _launch_direct(target)
            self._log(f"OPENED: {target}")
            return "Done."
        except Exception as exc:
            return f"Couldn't open {app or target}: {exc}"

    def _handle_followup_response_hardened(self, user_input: str):
        text = (user_input or "").lower().strip()
        followup = self.follow_up
        self.follow_up = None
        if not followup:
            return None

        if any(word in text for word in executor_module.YES_WORDS):
            action = followup.get("action")
            if action == "open_file":
                path = followup.get("path", "")
                try:
                    if platform.system() == "Windows":
                        os.startfile(path)
                    else:
                        subprocess.Popen(["xdg-open", path])
                    return f"Opened '{os.path.basename(path)}'."
                except Exception as exc:
                    return f"Couldn't open it: {exc}"
            if action == "open_app":
                app = str(followup.get("app") or "").strip()
                return _open_app_hardened(self, {"action_type": "open_app", "app_name": app})
        elif any(word in text for word in executor_module.NO_WORDS):
            return "No problem."
        return None

    executor_cls._open_app = _open_app_hardened
    executor_cls.handle_followup_response = _handle_followup_response_hardened
    executor_cls._iris_executor_open_app_hardening_applied = True
