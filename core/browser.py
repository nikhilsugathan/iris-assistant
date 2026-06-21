"""
IRIS Browser Automation v2
===========================
- Lazy init — browser only launches when actually needed
- Uses system default browser for opening URLs
- Playwright only used for advanced interactions (music playback, clicking)
- Falls back to webbrowser module if Playwright unavailable
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
import webbrowser
from rich.console import Console
from config import Config

console = Console()


class BrowserAutomation:

    def __init__(self):
        # No browser launched on init — lazy load only when needed
        self._browser   = None
        self._page      = None
        self._pw        = None
        self._ready     = False
        self._launching = False
        self._lock      = threading.Lock()

    # ─────────────────────────────────────────────────────────────
    # LAZY INIT — only launches when first needed
    # ─────────────────────────────────────────────────────────────

    def _ensure_ready(self, timeout: int = 10) -> bool:
        """Launch browser only when first needed."""
        if self._ready:
            return True

        _should_launch = False
        with self._lock:
            # Re-check under the lock — another thread may have finished
            # between the fast-path read above and acquiring the lock.
            if self._ready:
                return True
            if not self._launching:
                self._launching = True
                _should_launch = True
            # else: another thread is already launching — fall through to wait

        if not _should_launch:
            # Another thread won the launch race — wait for it to finish.
            start = time.time()
            while self._launching and time.time() - start < timeout:
                time.sleep(0.2)
            return self._ready

        try:
            from playwright.sync_api import sync_playwright
            self._pw      = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=False)
            self._context = self._browser.new_context()
            self._page    = self._context.new_page()
            self._ready   = True
            console.print("[green]✓ Browser ready[/green]")
        except Exception as e:
            console.print(f"[yellow]Browser automation unavailable: {e}[/yellow]")
            self._ready = False
        finally:
            self._launching = False

        return self._ready

    # ─────────────────────────────────────────────────────────────
    # PUBLIC METHODS
    # ─────────────────────────────────────────────────────────────

    def open_url(self, url: str) -> str:
        """Open URL in system default browser — no Playwright needed."""
        webbrowser.open(url)
        self._log(f"Opened: {url}")
        return "Done."

    def play_music(self, query: str) -> str:
        """
        Search and play music on YouTube Music.
        Uses Playwright to actually click play.
        Falls back to opening search page if Playwright unavailable.
        """
        search_url = f"https://music.youtube.com/search?q={query.replace(' ', '+')}"

        if not self._ensure_ready(timeout=8):
            # Fallback — open in default browser
            webbrowser.open(search_url)
            return "Done."

        try:
            with self._lock:
                self._page.goto(search_url, timeout=15000)
                self._page.wait_for_timeout(2500)

                # Try to click first song result
                selectors = [
                    "ytmusic-responsive-list-item-renderer",
                    "[data-testid='song-row']",
                ]
                for selector in selectors:
                    try:
                        first = self._page.query_selector(selector)
                        if first:
                            first.dblclick()
                            return "Done."
                    except Exception:
                        continue

                return "Done."
        except Exception:
            webbrowser.open(search_url)
            return "Done."

    def play_youtube(self, query: str) -> str:
        """Search YouTube and play first video."""
        search_url = f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}"

        if not self._ensure_ready(timeout=8):
            webbrowser.open(search_url)
            return "Done."

        try:
            with self._lock:
                self._page.goto(search_url, timeout=15000)
                self._page.wait_for_timeout(2000)

                first = self._page.query_selector("ytd-video-renderer a#video-title")
                if first:
                    first.click()
                return "Done."
        except Exception:
            webbrowser.open(search_url)
            return "Done."

    def search_and_open(self, query: str, click_first: bool = False) -> str:
        """Google search using default browser."""
        url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
        webbrowser.open(url)
        return "Done."

    def get_page_text(self) -> str:
        """Read current page content."""
        if not self._ready or not self._page:
            return ""
        try:
            return self._page.inner_text("body")[:3000]
        except Exception:
            return ""

    def close(self):
        """Clean shutdown."""
        try:
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
        except Exception:
            pass

    def _log(self, msg: str):
        pass  # Could add logging here if needed
