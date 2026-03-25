"""
IRIS desktop control helpers.

This module keeps desktop automation optional and lazy-loaded so IRIS can
still boot on machines where the automation dependency is not installed.
"""

from __future__ import annotations

from dataclasses import dataclass
import difflib
import time


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


@dataclass
class WindowSnapshot:
    title: str
    left: int
    top: int
    width: int
    height: int
    active: bool = False

    @property
    def center(self) -> tuple[int, int]:
        return (self.left + self.width // 2, self.top + self.height // 2)


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
        snapshots = self.list_windows(limit=limit)
        return [item.title for item in snapshots]

    def list_windows(self, limit: int = 24) -> list[WindowSnapshot]:
        windows = self._all_windows()
        active_title = self.get_active_window_title().strip().lower()
        snapshots: list[WindowSnapshot] = []
        for window in windows:
            snapshot = self._snapshot_from_window(window, active=window.title.strip().lower() == active_title)
            if not self._is_displayable_window(snapshot):
                continue
            snapshots.append(
                snapshot
            )
        return snapshots[: max(1, int(limit))]

    def describe_active_window(self) -> str:
        title = self.get_active_window_title()
        if not title:
            return "I couldn't determine the active window."

        window = self._find_best_window(title)
        if window is None:
            return f"The active window is '{title}'."

        snapshot = self._snapshot_from_window(window, active=True)
        return (
            f"Active window: {snapshot.title} "
            f"at {snapshot.left},{snapshot.top} sized {snapshot.width}x{snapshot.height}."
        )

    def focus_window(self, title_query: str) -> DesktopActionResult:
        window = self._require_window(title_query, "focus")
        try:
            self._bring_window_to_front(window)
        except Exception as exc:
            raise DesktopControlError(f"Couldn't focus the '{window.title}' window: {exc}") from exc

        return DesktopActionResult(True, f"Focused '{window.title}'.")

    def click_window(
        self,
        title_query: str,
        x: int | None = None,
        y: int | None = None,
        button: str = "left",
        clicks: int = 1,
    ) -> DesktopActionResult:
        window = self._require_window(title_query, "click")
        try:
            self._bring_window_to_front(window)
        except Exception as exc:
            raise DesktopControlError(f"Couldn't bring '{window.title}' to the front before clicking: {exc}") from exc

        snapshot = self._snapshot_from_window(window, active=True)
        button = (button or "left").strip().lower()
        clicks = max(1, int(clicks or 1))

        if x is None or y is None:
            target_x, target_y = snapshot.center
        else:
            rel_x = int(x)
            rel_y = int(y)
            if rel_x < 0 or rel_y < 0 or rel_x > snapshot.width or rel_y > snapshot.height:
                raise DesktopControlError(
                    f"Relative window coordinates {rel_x},{rel_y} fall outside '{snapshot.title}' sized "
                    f"{snapshot.width}x{snapshot.height}."
                )
            target_x = snapshot.left + rel_x
            target_y = snapshot.top + rel_y

        return self.click_at(target_x, target_y, button=button, clicks=clicks)

    def type_in_window(self, title_query: str, text: str, interval: float = 0.02) -> DesktopActionResult:
        if not text:
            raise DesktopControlError("There is no text to type.")

        window = self._require_window(title_query, "type in")
        try:
            self._bring_window_to_front(window)
        except Exception as exc:
            raise DesktopControlError(f"Couldn't focus the '{window.title}' window before typing: {exc}") from exc

        backend = self._pyautogui()
        backend.write(text, interval=max(0.0, float(interval)))
        return DesktopActionResult(True, "Done.")

    def press_hotkey_in_window(self, title_query: str, keys: list[str]) -> DesktopActionResult:
        normalized = [normalize_key_token(key) for key in (keys or []) if str(key).strip()]
        if not normalized:
            raise DesktopControlError("There is no key or shortcut to press.")

        window = self._require_window(title_query, "send a shortcut to")
        try:
            self._bring_window_to_front(window)
        except Exception as exc:
            raise DesktopControlError(
                f"Couldn't focus the '{window.title}' window before sending a shortcut: {exc}"
            ) from exc

        backend = self._pyautogui()
        if len(normalized) == 1:
            backend.press(normalized[0])
        else:
            backend.hotkey(*normalized)
        return DesktopActionResult(True, "Done.")

    def set_window_state(self, title_query: str, state: str) -> DesktopActionResult:
        desired = (state or "").strip().lower()
        if desired not in {"minimize", "maximize", "restore", "close"}:
            raise DesktopControlError(f"'{state}' is not a supported window action.")

        window = self._require_window(title_query, desired)
        title = str(window.title)

        try:
            if desired == "minimize":
                window.minimize()
                return DesktopActionResult(True, f"Minimized '{title}'.")

            if desired == "maximize":
                if getattr(window, "isMinimized", False):
                    window.restore()
                window.maximize()
                try:
                    window.activate()
                except Exception:
                    pass
                return DesktopActionResult(True, f"Maximized '{title}'.")

            if desired == "restore":
                window.restore()
                try:
                    window.activate()
                except Exception:
                    pass
                return DesktopActionResult(True, f"Restored '{title}'.")

            window.close()
            return DesktopActionResult(True, f"Closed '{title}'.")
        except Exception as exc:
            raise DesktopControlError(f"Couldn't {desired} the '{title}' window: {exc}") from exc

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

    def _require_window(self, title_query: str, verb: str):
        query = (title_query or "").strip()
        if not query:
            raise DesktopControlError(f"There is no window title to {verb}.")

        self._ensure_interactive_session()
        window = self._find_best_window(query)
        if window is None:
            known = self.list_window_titles(limit=8)
            sample = ", ".join(known) if known else "no visible titled windows"
            raise DesktopControlError(
                f"I couldn't find a window matching '{query}'. Available examples: {sample}."
            )
        return window

    def _bring_window_to_front(self, window) -> None:
        if getattr(window, "isMinimized", False):
            window.restore()
        window.activate()
        time.sleep(0.12)

    def _snapshot_from_window(self, window, active: bool = False) -> WindowSnapshot:
        return WindowSnapshot(
            title=str(window.title),
            left=int(window.left),
            top=int(window.top),
            width=int(window.width),
            height=int(window.height),
            active=active,
        )

    def _is_displayable_window(self, snapshot: WindowSnapshot) -> bool:
        if not snapshot.title.strip():
            return False
        if snapshot.width <= 1 or snapshot.height <= 1:
            return False
        if snapshot.left <= -10000 and snapshot.top <= -10000:
            return False
        return True

    def _all_windows(self):
        backend = self._pygetwindow()
        try:
            windows = [window for window in backend.getAllWindows() if str(getattr(window, "title", "")).strip()]
        except Exception as exc:
            raise DesktopControlError(f"Couldn't inspect the current windows: {exc}") from exc

        seen: set[str] = set()
        unique_windows = []
        for window in windows:
            key = window.title.strip().lower()
            if key in seen:
                continue
            seen.add(key)
            unique_windows.append(window)
        return unique_windows

    def _find_best_window(self, title_query: str):
        query = title_query.strip().lower()
        if not query:
            return None

        windows = self._all_windows()

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
