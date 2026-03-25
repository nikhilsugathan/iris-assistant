"""
IRIS desktop control helpers.

This module keeps desktop automation optional and lazy-loaded so IRIS can
still boot on machines where the automation dependency is not installed.
"""

from __future__ import annotations

from dataclasses import dataclass
import difflib


class DesktopControlError(RuntimeError):
    """Raised when desktop automation cannot be completed safely."""


KEY_ALIASES = {
    "control": "ctrl",
    "ctl": "ctrl",
    "windows": "win",
    "command": "win",
    "return": "enter",
    "escape": "esc",
    "spacebar": "space",
    "page up": "pageup",
    "page down": "pagedown",
    "pgup": "pageup",
    "pgdn": "pagedown",
    "delete": "delete",
    "backspace": "backspace",
    "del": "delete",
}


def normalize_key_token(token: str) -> str:
    normalized = (token or "").strip().lower()
    return KEY_ALIASES.get(normalized, normalized)


@dataclass
class DesktopActionResult:
    ok: bool
    message: str


class DesktopController:
    LOCKED_WINDOW_TOKENS = (
        "windows default lock screen",
        "lock screen",
    )

    def __init__(self):
        self._backend = None
        self._window_backend = None

    def _pyautogui(self):
        if self._backend is not None:
            return self._backend

        try:
            import pyautogui
        except Exception as exc:  # pragma: no cover - local dependency path
            raise DesktopControlError(
                "Desktop automation is unavailable because PyAutoGUI is not installed."
            ) from exc

        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0.05
        self._backend = pyautogui
        return self._backend

    def _pygetwindow(self):
        if self._window_backend is not None:
            return self._window_backend

        try:
            import pygetwindow
        except Exception as exc:  # pragma: no cover - local dependency path
            raise DesktopControlError(
                "Window targeting is unavailable because PyGetWindow is not installed."
            ) from exc

        self._window_backend = pygetwindow
        return self._window_backend

    def screen_size(self) -> tuple[int, int]:
        backend = self._pyautogui()
        size = backend.size()
        return int(size.width), int(size.height)

    def get_active_window_title(self) -> str:
        backend = self._pygetwindow()
        try:
            title = str(backend.getActiveWindowTitle() or "").strip()
            if title:
                return title
        except Exception:
            pass

        try:
            active_window = backend.getActiveWindow()
            return str(getattr(active_window, "title", "") or "").strip()
        except Exception as exc:
            raise DesktopControlError(f"Couldn't determine the active window: {exc}") from exc

    def list_window_titles(self, limit: int = 24) -> list[str]:
        backend = self._pygetwindow()
        try:
            titles = [str(title).strip() for title in backend.getAllTitles() if str(title).strip()]
        except Exception as exc:
            raise DesktopControlError(f"Couldn't read the current window titles: {exc}") from exc

        seen: set[str] = set()
        unique_titles: list[str] = []
        for title in titles:
            lowered = title.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            unique_titles.append(title)
        return unique_titles[: max(1, int(limit))]

    def focus_window(self, title_query: str) -> DesktopActionResult:
        query = (title_query or "").strip()
        if not query:
            raise DesktopControlError("There is no window title to focus.")

        self._ensure_interactive_session()
        window = self._find_best_window(query)
        if window is None:
            known = self.list_window_titles(limit=8)
            sample = ", ".join(known) if known else "no visible titled windows"
            raise DesktopControlError(
                f"I couldn't find a window matching '{query}'. Available examples: {sample}."
            )

        try:
            if getattr(window, "isMinimized", False):
                window.restore()
            window.activate()
        except Exception as exc:
            raise DesktopControlError(f"Couldn't focus the '{window.title}' window: {exc}") from exc

        return DesktopActionResult(True, f"Focused '{window.title}'.")

    def type_text(self, text: str, interval: float = 0.02) -> DesktopActionResult:
        if not text:
            raise DesktopControlError("There is no text to type.")

        self._ensure_interactive_session()
        backend = self._pyautogui()
        backend.write(text, interval=max(0.0, float(interval)))
        return DesktopActionResult(True, "Done.")

    def press_hotkey(self, keys: list[str]) -> DesktopActionResult:
        normalized = [normalize_key_token(key) for key in (keys or []) if str(key).strip()]
        if not normalized:
            raise DesktopControlError("There is no key or shortcut to press.")

        self._ensure_interactive_session()
        backend = self._pyautogui()
        if len(normalized) == 1:
            backend.press(normalized[0])
        else:
            backend.hotkey(*normalized)
        return DesktopActionResult(True, "Done.")

    def click_at(
        self,
        x: int,
        y: int,
        button: str = "left",
        clicks: int = 1,
    ) -> DesktopActionResult:
        self._ensure_interactive_session()
        backend = self._pyautogui()
        width, height = self.screen_size()
        x = int(x)
        y = int(y)
        button = (button or "left").strip().lower()
        clicks = max(1, int(clicks or 1))

        if x < 0 or y < 0 or x > width or y > height:
            raise DesktopControlError(
                f"Requested click coordinates {x},{y} are outside the current screen bounds {width}x{height}."
            )

        if button not in {"left", "right", "middle"}:
            raise DesktopControlError(f"'{button}' is not a supported mouse button.")

        backend.click(x=x, y=y, button=button, clicks=clicks, interval=0.12)
        return DesktopActionResult(True, "Done.")

    def _ensure_interactive_session(self) -> None:
        active_title = self.get_active_window_title().lower()
        if any(token in active_title for token in self.LOCKED_WINDOW_TOKENS):
            raise DesktopControlError(
                "The Windows session appears to be locked. Unlock the desktop before IRIS can control windows, clicks, or typing."
            )

    def _find_best_window(self, title_query: str):
        backend = self._pygetwindow()
        query = title_query.strip().lower()
        if not query:
            return None

        try:
            windows = [window for window in backend.getAllWindows() if str(getattr(window, "title", "")).strip()]
        except Exception as exc:
            raise DesktopControlError(f"Couldn't inspect the current windows: {exc}") from exc

        exact = [window for window in windows if window.title.strip().lower() == query]
        if exact:
            return exact[0]

        prefix = [window for window in windows if window.title.strip().lower().startswith(query)]
        if prefix:
            return prefix[0]

        contains = [window for window in windows if query in window.title.strip().lower()]
        if contains:
            contains.sort(key=lambda item: (len(item.title), item.title.lower()))
            return contains[0]

        ranked: list[tuple[float, object]] = []
        for window in windows:
            score = difflib.SequenceMatcher(None, query, window.title.strip().lower()).ratio()
            if score >= 0.45:
                ranked.append((score, window))

        if not ranked:
            return None

        ranked.sort(key=lambda item: item[0], reverse=True)
        return ranked[0][1]
