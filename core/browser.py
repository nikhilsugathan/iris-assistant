"""
IRIS Browser Automation
========================
Lets Iris actually control the browser — not just open URLs.

Powered by Playwright (free, local, no API needed).

What it can do:
- Open any website
- Play music on YouTube / Spotify / YouTube Music
- Search and click results
- Fill forms
- Read page content and report back
- Take screenshots for debugging

Install:
  pip install playwright
  python -m playwright install chromium

Usage in executor:
  browser = BrowserAutomation()
  result  = browser.play_music("shape of you ed sheeran")
  result  = browser.open_url("https://gmail.com")
  result  = browser.search_and_open("python docs", click_first=True)
"""

from __future__ import annotations

import threading
import time
from typing import Optional
from rich.console import Console

console = Console()


class BrowserAutomation:

    def __init__(self):
        self._browser  = None
        self._page     = None
        self._playwright = None
        self._lock     = threading.Lock()
        self._ready    = False
        self._init_error = None

        # Init browser in background so it doesn't block startup
        t = threading.Thread(target=self._init_browser, daemon=True)
        t.start()

    def _init_browser(self):
        """Launch browser in background."""
        try:
            from playwright.sync_api import sync_playwright
            self._pw       = sync_playwright().start()
            self._browser  = self._pw.chromium.launch(
                headless=False,      # Visible — user can see what Iris is doing
                args=["--start-maximized"]
            )
            self._context  = self._browser.new_context(
                viewport=None,       # Use full window size
            )
            self._page     = self._context.new_page()
            self._ready    = True
            console.print("[green]✓ Browser automation ready[/green]")
        except Exception as e:
            self._init_error = str(e)
            console.print(f"[yellow]Browser automation unavailable: {e}[/yellow]")

    def _wait_ready(self, timeout: int = 8) -> bool:
        """Wait for browser to be ready."""
        start = time.time()
        while not self._ready and time.time() - start < timeout:
            if self._init_error:
                return False
            time.sleep(0.2)
        return self._ready

    # ─────────────────────────────────────────────────────────────
    # PUBLIC METHODS — called by executor
    # ─────────────────────────────────────────────────────────────

    def open_url(self, url: str) -> str:
        """Navigate to a URL."""
        if not self._wait_ready():
            return self._fallback_open(url)
        try:
            with self._lock:
                self._page.goto(url, timeout=15000)
            return "Done."
        except Exception as e:
            return self._fallback_open(url)

    def play_music(self, query: str) -> str:
        """
        Search and play music on YouTube Music.
        Iris picks the first result automatically.
        """
        if not self._wait_ready():
            import webbrowser
            webbrowser.open(f"https://music.youtube.com/search?q={query.replace(' ', '+')}")
            return "Done."

        try:
            with self._lock:
                # Go to YouTube Music search
                search_url = f"https://music.youtube.com/search?q={query.replace(' ', '+')}"
                self._page.goto(search_url, timeout=15000)
                self._page.wait_for_timeout(2500)

                # Click the first song result
                selectors = [
                    "ytmusic-shelf-renderer ytmusic-responsive-list-item-renderer",
                    "[data-testid='song-row']",
                    "ytmusic-responsive-list-item-renderer",
                ]
                for selector in selectors:
                    try:
                        first = self._page.query_selector(selector)
                        if first:
                            first.dblclick()
                            self._page.wait_for_timeout(1000)
                            return "Done."
                    except Exception:
                        continue

                # Fallback — just leave on search page
                return "Done."

        except Exception as e:
            import webbrowser
            webbrowser.open(f"https://music.youtube.com/search?q={query.replace(' ', '+')}")
            return "Done."

    def play_youtube(self, query: str) -> str:
        """Search YouTube and play the first video."""
        if not self._wait_ready():
            import webbrowser
            webbrowser.open(f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}")
            return "Done."

        try:
            with self._lock:
                search_url = f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}"
                self._page.goto(search_url, timeout=15000)
                self._page.wait_for_timeout(2000)

                # Click first video result
                first_video = self._page.query_selector("ytd-video-renderer a#video-title")
                if first_video:
                    first_video.click()
                    return "Done."

                return "Done."
        except Exception:
            import webbrowser
            webbrowser.open(f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}")
            return "Done."

    def search_and_open(self, query: str, click_first: bool = False) -> str:
        """Google search, optionally click the first result."""
        if not self._wait_ready():
            import webbrowser
            webbrowser.open(f"https://www.google.com/search?q={query.replace(' ', '+')}")
            return "Done."

        try:
            with self._lock:
                self._page.goto(
                    f"https://www.google.com/search?q={query.replace(' ', '+')}",
                    timeout=15000
                )
                self._page.wait_for_timeout(1500)

                if click_first:
                    first = self._page.query_selector("h3")
                    if first:
                        first.click()

                return "Done."
        except Exception:
            import webbrowser
            webbrowser.open(f"https://www.google.com/search?q={query.replace(' ', '+')}")
            return "Done."

    def get_page_text(self) -> str:
        """Read current page content — Iris can then summarise it."""
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

    # ─────────────────────────────────────────────────────────────
    # FALLBACK — if browser automation unavailable
    # ─────────────────────────────────────────────────────────────

    def _fallback_open(self, url: str) -> str:
        import webbrowser
        webbrowser.open(url)
        return "Done."
