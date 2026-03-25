"""
IRIS local context helpers.

Provides read-only desktop and clipboard context so IRIS can answer
environmental questions and reason over explicit clipboard requests without
defaulting to cloud lookups or guessing.
"""

from __future__ import annotations

import re
import subprocess
from typing import Optional

from config import Config
from core.desktop_control import DesktopControlError, DesktopController
from core.subprocess_utils import hidden_process_kwargs


class DesktopIntel:
    def __init__(self, desktop: DesktopController | None = None) -> None:
        self.desktop = desktop or DesktopController()

    def answer_query(self, query: str) -> Optional[str]:
        lowered = (query or "").lower().strip()
        if not lowered:
            return None

        if self._is_active_window_query(lowered):
            return self._answer_active_window()
        if self._is_window_list_query(lowered):
            return self._answer_window_list()
        return None

    def _is_active_window_query(self, lowered: str) -> bool:
        phrases = [
            "what am i looking at",
            "what app am i in",
            "which app am i in",
            "what window am i in",
            "which window am i in",
            "what is the active window",
            "what's the active window",
            "which window is active",
            "which app is active",
            "what app is active",
            "current window",
            "active window",
        ]
        return any(phrase in lowered for phrase in phrases)

    def _is_window_list_query(self, lowered: str) -> bool:
        phrases = [
            "what windows are open",
            "which windows are open",
            "what apps are open",
            "which apps are open",
            "what do i have open",
            "show my windows",
            "list my windows",
            "list open windows",
            "what is open right now",
            "what's open right now",
        ]
        return any(phrase in lowered for phrase in phrases)

    def _answer_active_window(self) -> str:
        try:
            return self.desktop.describe_active_window()
        except DesktopControlError as exc:
            return f"I couldn't inspect the active window locally right now: {exc}"

    def _answer_window_list(self) -> str:
        try:
            windows = self.desktop.list_windows(limit=6)
        except DesktopControlError as exc:
            return f"I couldn't inspect the open windows locally right now: {exc}"

        if not windows:
            return "I couldn't find any visible titled windows right now."

        entries = []
        for item in windows:
            prefix = "active" if item.active else "open"
            entries.append(f"{prefix}: {item.title}")
        return "Open windows right now: " + "; ".join(entries) + "."


class ClipboardIntel:
    def answer_query(self, query: str) -> Optional[str]:
        lowered = (query or "").lower().strip()
        if not lowered or not self._is_direct_clipboard_query(lowered):
            return None

        text = self._read_clipboard_text()
        if not text:
            return "Clipboard is empty or doesn't contain text right now."
        return self._build_clipboard_preview(text)

    def build_prompt(self, query: str) -> tuple[Optional[str], Optional[str]]:
        lowered = (query or "").lower().strip()
        if not lowered:
            return None, None

        intent = self._match_transform_intent(lowered)
        if not intent:
            return None, None

        text = self._read_clipboard_text()
        if not text:
            return None, "Clipboard is empty or doesn't contain text right now."

        trimmed = text[: max(200, int(getattr(Config, "CLIPBOARD_CONTEXT_MAX_CHARS", 4000)))]
        if intent == "summarize":
            prompt = "Summarize the following clipboard content concisely and clearly."
        elif intent == "explain":
            prompt = "Explain the following clipboard content clearly and directly."
        elif intent == "fix":
            prompt = "Review the following clipboard content and suggest the most likely fix."
        elif intent == "translate":
            prompt = "Translate the following clipboard content into natural English."
        else:
            return None, None

        return f"{prompt}\n\nClipboard content:\n{trimmed}", None

    def _is_direct_clipboard_query(self, lowered: str) -> bool:
        phrases = [
            "what's on my clipboard",
            "what is on my clipboard",
            "show my clipboard",
            "read my clipboard",
            "what did i copy",
            "tell me what i copied",
            "clipboard contents",
        ]
        return any(phrase in lowered for phrase in phrases)

    def _match_transform_intent(self, lowered: str) -> Optional[str]:
        if not self._mentions_clipboard(lowered):
            return None

        if any(token in lowered for token in ["summarize", "summarise", "summary", "key points"]):
            return "summarize"
        if any(token in lowered for token in ["explain", "what does this mean", "what is this", "interpret"]):
            return "explain"
        if any(token in lowered for token in ["fix", "debug", "diagnose", "what's wrong", "what is wrong"]):
            return "fix"
        if "translate" in lowered:
            return "translate"
        return None

    def _mentions_clipboard(self, lowered: str) -> bool:
        markers = [
            "clipboard",
            "what i copied",
            "i copied",
            "copied text",
            "copied content",
        ]
        return any(marker in lowered for marker in markers)

    def _build_clipboard_preview(self, text: str) -> str:
        preview_limit = max(80, int(getattr(Config, "CLIPBOARD_PREVIEW_CHARS", 260)))
        clean = re.sub(r"\s+", " ", text).strip()
        if len(clean) > preview_limit:
            clean = clean[: preview_limit - 1].rstrip() + "..."
        return f"Clipboard currently contains: {clean}"

    def _read_clipboard_text(self) -> str:
        script = """
$text = Get-Clipboard -Raw -Format Text -ErrorAction Stop
if ($null -ne $text) {
  $text
}
""".strip()
        try:
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True,
                text=True,
                timeout=4,
                check=False,
                **hidden_process_kwargs(),
            )
        except Exception:
            return ""

        if completed.returncode != 0:
            return ""
        return str(completed.stdout or "").strip()
