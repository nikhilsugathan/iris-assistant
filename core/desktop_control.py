"""
IRIS desktop control helpers.

This module keeps desktop automation optional and lazy-loaded so IRIS can
still boot on machines where the automation dependency is not installed.
"""

from __future__ import annotations

from dataclasses import dataclass


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
    def __init__(self):
        self._backend = None

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

    def screen_size(self) -> tuple[int, int]:
        backend = self._pyautogui()
        size = backend.size()
        return int(size.width), int(size.height)

    def type_text(self, text: str, interval: float = 0.02) -> DesktopActionResult:
        if not text:
            raise DesktopControlError("There is no text to type.")

        backend = self._pyautogui()
        backend.write(text, interval=max(0.0, float(interval)))
        return DesktopActionResult(True, "Done.")

    def press_hotkey(self, keys: list[str]) -> DesktopActionResult:
        normalized = [normalize_key_token(key) for key in (keys or []) if str(key).strip()]
        if not normalized:
            raise DesktopControlError("There is no key or shortcut to press.")

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
