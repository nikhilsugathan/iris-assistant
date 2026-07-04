"""Executor hardening for normal-risk launches and permission parsing."""

from __future__ import annotations

import os
import platform
import re
import subprocess
import webbrowser
from urllib.parse import quote_plus


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

_NEGATIVE_CONFIRMATIONS = {
    "no",
    "nope",
    "cancel",
    "stop",
    "do not",
    "don t",
    "dont",
    "abort",
    "wait",
    "hold on",
    "negative",
    "never mind",
    "nevermind",
    "skip",
    "not yet",
    "not correct",
    "that s not correct",
    "that is not correct",
    "not sure",
}

_AFFIRMATIVE_CONFIRMATIONS = {
    "yes",
    "yeah",
    "yep",
    "yup",
    "sure",
    "go ahead",
    "do it",
    "proceed",
    "confirm",
    "ok",
    "okay",
    "affirmative",
    "correct",
    "go for it",
    "run it",
    "execute",
    "do that",
    "sounds good",
}


def _normalize_confirmation(text: str) -> str:
    normalized = str(text or "").lower().replace("’", "'")
    normalized = re.sub(r"[^a-z0-9']+", " ", normalized)
    normalized = normalized.replace("'", " ")
    return re.sub(r"\s+", " ", normalized).strip()


def _contains_phrase(normalized: str, phrase: str) -> bool:
    return f" {phrase} " in f" {normalized} "


def _confirmation_intent(text: str) -> str | None:
    normalized = _normalize_confirmation(text)
    if not normalized:
        return None
    if any(_contains_phrase(normalized, phrase) for phrase in _NEGATIVE_CONFIRMATIONS):
        return "no"
    if _contains_phrase(normalized, "override"):
        return "override"
    if any(_contains_phrase(normalized, phrase) for phrase in _AFFIRMATIVE_CONFIRMATIONS):
        return "yes"
    return None


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

    def _play_music_hardened(self, plan: dict) -> str:
        raw_query = str(plan.get("search_query") or plan.get("description") or "music").strip()
        query = raw_query.removeprefix("play ").strip() or "popular songs"
        music_platform = str(plan.get("platform") or "youtube").strip().lower()
        encoded = quote_plus(query)

        if music_platform == "spotify":
            spotify_uri = f"spotify:search:{encoded}"
            if platform.system() == "Windows":
                try:
                    os.startfile(spotify_uri)
                    self._log(f"PLAY SPOTIFY (app): {query}")
                    return "Done."
                except OSError:
                    pass
            webbrowser.open(f"https://open.spotify.com/search/{encoded}")
            self._log(f"PLAY SPOTIFY (web): {query}")
            return "Done."

        webbrowser.open(f"https://www.youtube.com/results?search_query={encoded}")
        self._log(f"PLAY YOUTUBE: {query}")
        return "Done."

    def _search_web_hardened(self, plan: dict) -> str:
        query = str(plan.get("search_query") or "").strip()
        if not query:
            return "No search query provided."
        webbrowser.open(f"https://www.google.com/search?q={quote_plus(query)}")
        self._log(f"SEARCHED: {query}")
        return "Done."

    def _handle_permission_response_hardened(self, user_input: str) -> str:
        intent = _confirmation_intent(user_input)

        if intent == "no":
            self.pending_action = None
            self.pending_verdict = None
            return "Cancelled."

        if intent == "override":
            if self.pending_verdict == executor_module.BLOCKED:
                pending = self.pending_action or {}
                self._log(f"OVERRIDE DENIED (BLOCKED): {pending.get('command', '?')}")
                self.pending_action = None
                self.pending_verdict = None
                return (
                    "That action is hard-blocked for security reasons. "
                    "Override is not available for blocked commands. Cancelled."
                )
            if self.pending_verdict not in {executor_module.WARNING, executor_module.NEED_ADMIN}:
                return "There is no warning or admin gate to override. Say go ahead, or cancel."
            pending = self.pending_action or {}
            command = pending.get("command") or pending.get("description", "?")
            self._log(f"ADMIN OVERRIDE [{self.pending_verdict}]: {command}")
            return self._execute_pending()

        if intent == "yes":
            if self.pending_verdict == executor_module.BLOCKED:
                return "That action is blocked. Say 'cancel' to dismiss."
            return self._execute_pending()

        return "Go ahead, or cancel?"

    def _handle_followup_response_hardened(self, user_input: str):
        followup = self.follow_up
        if not followup:
            return None

        intent = _confirmation_intent(user_input)
        if intent == "no":
            self.follow_up = None
            return "No problem."
        if intent != "yes":
            return "Yes, or no?"

        self.follow_up = None
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
        return None

    executor_cls._open_app = _open_app_hardened
    executor_cls._play_music = _play_music_hardened
    executor_cls._search_web = _search_web_hardened
    executor_cls.handle_permission_response = _handle_permission_response_hardened
    executor_cls.handle_followup_response = _handle_followup_response_hardened
    executor_cls._iris_executor_open_app_hardening_applied = True
    executor_cls._iris_executor_confirmation_hardening_applied = True
    executor_cls._iris_executor_shell_free_media_applied = True
