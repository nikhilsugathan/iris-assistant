"""
Local Perplexity bridge for the IRIS collaboration notebook.

This bridge supports three workflows:
  - once:      process the current request one time
  - bootstrap: open a persistent Perplexity browser session and wait for login/challenge completion
  - watch:     keep watching the request file and answer new requests automatically

Defaults:
  - Reads request from   D:\IRIS\ai-collab\perplexity-bridge-request.md
  - Writes response to   D:\IRIS\ai-collab\perplexity-bridge-response.md
  - Writes status to     D:\IRIS\ai-collab\perplexity-bridge-status.md
  - Appends a relay line to D:\IRIS\ai-collab\transcript.md
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import requests

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from config import Config


DEFAULT_REQUEST = WORKSPACE / "ai-collab" / "perplexity-bridge-request.md"
DEFAULT_RESPONSE = WORKSPACE / "ai-collab" / "perplexity-bridge-response.md"
DEFAULT_TRANSCRIPT = WORKSPACE / "ai-collab" / "transcript.md"
DEFAULT_STATUS = WORKSPACE / "ai-collab" / "perplexity-bridge-status.md"
DEFAULT_STATE = WORKSPACE / ".bridge" / "perplexity-bridge-state.json"
DEFAULT_WEB_PROFILE = WORKSPACE / ".bridge" / "perplexity-profile"

DEFAULT_CONTEXT_FILES = [
    WORKSPACE / "ai-collab" / "brief.md",
    WORKSPACE / "ai-collab" / "cody-handoff.md",
    WORKSPACE / "ai-collab" / "decisions.md",
    WORKSPACE / "ai-collab" / "todo.md",
    WORKSPACE / "SAFETY_CONTRACT.md",
]

SYSTEM_PROMPT = """You are Perplexity collaborating with Cody and the user on IRIS.

Rules:
- Keep replies concise, direct, and high-signal.
- Prefer findings, risks, recommendations, and next actions over recap.
- Keep recommendations grounded in the provided repo context, not a greenfield rewrite.
- When current web knowledge materially helps, use it and preserve source links.
- If context is incomplete, say what is missing briefly and continue with the best practical answer.
"""

PLACEHOLDER_MARKERS = [
    "Write the task for Perplexity here.",
    "## Suggested Format",
]

BROWSER_CHANNEL_PATHS = {
    "msedge": [
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    ],
    "chrome": [
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    ],
}

INPUT_SELECTORS = [
    "textarea",
    "[contenteditable='true'][role='textbox']",
    "[contenteditable='true']",
]

SEND_BUTTON_SELECTORS = [
    "button[aria-label*='Submit']",
    "button[aria-label*='Send']",
    "button[aria-label*='send']",
    "button[type='submit']",
]

ASSISTANT_MESSAGE_SELECTORS = [
    "main article",
    "main [class*='prose']",
    "main [data-testid*='answer']",
    "main",
]

PROMPT_ENTRY_SELECTORS = [
    "button:has-text('Ask anything')",
    "[role='button']:has-text('Ask anything')",
]

COOKIE_BUTTON_LABELS = [
    "Necessary Cookies",
    "Accept All Cookies",
]

BODY_STOP_MARKERS = [
    "Ask a follow-up",
    "Model",
    "Cookie Policy",
]


@dataclass
class BridgeResult:
    text: str
    sources: list[tuple[str, str, str]]


@dataclass
class ChatReadiness:
    state: str
    detail: str
    prompt_box: object | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a local Perplexity bridge request.")
    parser.add_argument(
        "--workflow",
        choices=["once", "bootstrap", "watch"],
        default="once",
        help="Bridge workflow. 'watch' keeps processing new requests until stopped.",
    )
    parser.add_argument(
        "--mode",
        choices=["auto", "api", "web"],
        default="auto",
        help="Bridge mode. 'auto' tries the API first, then falls back to a browser session.",
    )
    parser.add_argument("--request", default=str(DEFAULT_REQUEST), help="Path to the request markdown file.")
    parser.add_argument("--response", default=str(DEFAULT_RESPONSE), help="Path to write the Perplexity response.")
    parser.add_argument("--transcript", default=str(DEFAULT_TRANSCRIPT), help="Path to the transcript log.")
    parser.add_argument("--status", default=str(DEFAULT_STATUS), help="Path to the bridge status markdown file.")
    parser.add_argument("--state", default=str(DEFAULT_STATE), help="Path to the bridge watcher state json file.")
    parser.add_argument("--prompt", default="", help="Direct prompt text. If set, skips reading the request file body.")
    parser.add_argument(
        "--include",
        action="append",
        default=[],
        help="Additional file path to include. Can be provided multiple times.",
    )
    parser.add_argument(
        "--transcript-tail-lines",
        type=int,
        default=24,
        help="How many trailing transcript lines to include in the prompt.",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=1400,
        help="Max tokens for the Perplexity response.",
    )
    parser.add_argument(
        "--model",
        default=getattr(Config, "PERPLEXITY_MODEL", "sonar-pro"),
        help="Perplexity model name.",
    )
    parser.add_argument(
        "--no-default-context",
        action="store_true",
        help="Do not include the default IRIS collaboration files automatically.",
    )
    parser.add_argument(
        "--web-profile",
        default=str(DEFAULT_WEB_PROFILE),
        help="Persistent browser profile directory for Perplexity web sessions.",
    )
    parser.add_argument(
        "--browser-channel",
        choices=["auto", "msedge", "chrome", "chromium"],
        default="auto",
        help="Browser channel for the Perplexity web bridge.",
    )
    parser.add_argument(
        "--web-timeout-seconds",
        type=int,
        default=240,
        help="How long to wait for Perplexity web to become ready and finish responding.",
    )
    parser.add_argument(
        "--watch-poll-seconds",
        type=int,
        default=4,
        help="Polling interval for watch mode.",
    )
    return parser.parse_args()


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def resolve_path(raw_path: str, base_dir: Path) -> Path:
    candidate = Path(raw_path.strip())
    if not candidate.is_absolute():
        candidate = (base_dir / candidate).resolve()
    return candidate


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def is_placeholder_request(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    return all(marker in stripped for marker in PLACEHOLDER_MARKERS)


def extract_include_paths(request_text: str, request_path: Path) -> list[Path]:
    lines = request_text.splitlines()
    include_paths: list[Path] = []
    in_section = False

    for line in lines:
        if line.startswith("## "):
            in_section = line.strip().lower() == "## include files"
            continue
        if not in_section:
            continue

        match = re.match(r"^\s*-\s+(.+?)\s*$", line)
        if not match:
            continue
        include_paths.append(resolve_path(match.group(1), request_path.parent))

    return include_paths


def build_context_sections(
    request_path: Path,
    request_text: str,
    transcript_path: Path,
    transcript_tail_lines: int,
    extra_include_paths: list[str],
    include_default_context: bool,
) -> list[tuple[str, str]]:
    seen: set[Path] = set()
    sections: list[tuple[str, str]] = []

    def maybe_add(path: Path) -> None:
        path = path.resolve()
        if path in seen:
            return
        seen.add(path)
        if path == transcript_path.resolve():
            if not path.exists():
                sections.append((str(path), "[Missing transcript file]"))
                return
            lines = load_text(path).splitlines()
            tail = lines[-transcript_tail_lines:] if transcript_tail_lines > 0 else lines
            sections.append((str(path), "\n".join(tail)))
            return
        if not path.exists():
            sections.append((str(path), "[Missing file]"))
            return
        sections.append((str(path), load_text(path)))

    if include_default_context:
        for path in DEFAULT_CONTEXT_FILES:
            maybe_add(path)
        maybe_add(transcript_path)

    for path in extract_include_paths(request_text, request_path):
        maybe_add(path)

    for raw_path in extra_include_paths:
        maybe_add(resolve_path(raw_path, WORKSPACE))

    return sections


def build_user_prompt(request_body: str, sections: list[tuple[str, str]]) -> str:
    parts = ["# Perplexity Bridge Request", request_body.strip()]
    if sections:
        parts.append("\n# Included Context")
        for label, content in sections:
            parts.append(f"\n## {label}\n{content.strip()}")
    return "\n".join(part for part in parts if part).strip() + "\n"


def append_transcript_entry(
    transcript_path: Path,
    result: BridgeResult,
    request_label: str,
    bridge_name: str,
) -> None:
    timestamp = datetime.now().strftime("%H:%M")
    preview = next((line.strip() for line in result.text.splitlines() if line.strip()), "(empty response)")
    preview = preview[:220]
    suffix = f" Sources: {len(result.sources)}." if result.sources else ""
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    with transcript_path.open("a", encoding="utf-8") as handle:
        handle.write(
            f"\n[{timestamp}] Perplexity (relay): Responded via {bridge_name} for "
            f"'{request_label}'. Preview: {preview}{suffix}\n"
        )


def append_transcript_error(transcript_path: Path, error_text: str, request_label: str) -> None:
    timestamp = datetime.now().strftime("%H:%M")
    preview = error_text.strip().replace("\n", " ")
    preview = preview[:220]
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    with transcript_path.open("a", encoding="utf-8") as handle:
        handle.write(
            f"\n[{timestamp}] Perplexity (relay): Perplexity bridge failed for "
            f"'{request_label}'. Error: {preview}\n"
        )


def write_status(
    status_path: Path,
    workflow: str,
    state: str,
    detail: str = "",
    request_label: str = "",
    response_path: Path | None = None,
    model: str = "",
    browser_channel: str = "",
) -> None:
    status_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Perplexity Bridge Status",
        "",
        f"- Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- Workflow: {workflow}",
        f"- State: {state}",
    ]
    if model:
        lines.append(f"- Model: {model}")
    if browser_channel:
        lines.append(f"- Browser: {browser_channel}")
    if request_label:
        lines.append(f"- Request: {request_label}")
    if response_path is not None:
        lines.append(f"- Response File: {response_path}")
    if detail:
        lines.extend(["", "## Detail", detail])
    status_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_state(state_path: Path) -> dict:
    if not state_path.exists():
        return {}
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(state_path: Path, payload: dict) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def extract_sources(payload: dict) -> list[tuple[str, str, str]]:
    seen: set[str] = set()
    sources: list[tuple[str, str, str]] = []

    for item in payload.get("search_results") or []:
        url = str(item.get("url") or "").strip()
        if not url or url in seen:
            continue
        title = str(item.get("title") or url).strip()
        date = str(item.get("date") or "").strip()
        seen.add(url)
        sources.append((title, url, date))

    for raw_url in payload.get("citations") or []:
        url = str(raw_url or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        sources.append((url, url, ""))

    return sources


def format_result_markdown(result: BridgeResult) -> str:
    lines = [result.text.strip()]

    if result.sources:
        lines.extend(["", "## Sources"])
        for title, url, date in result.sources:
            suffix = f" ({date})" if date else ""
            lines.append(f"- [{title}]({url}){suffix}")

    return "\n".join(line for line in lines if line is not None).strip() + "\n"


def detect_browser_channel(preference: str) -> str:
    if preference != "auto":
        return preference

    for channel in ("msedge", "chrome"):
        for candidate in BROWSER_CHANNEL_PATHS[channel]:
            if candidate.exists():
                return channel
    return "chromium"


def call_api_bridge(user_prompt: str, model: str, max_tokens: int) -> BridgeResult:
    if not getattr(Config, "PERPLEXITY_API_KEY", ""):
        raise RuntimeError("PERPLEXITY_API_KEY is not configured.")

    response = requests.post(
        "https://api.perplexity.ai/chat/completions",
        headers={
            "Authorization": f"Bearer {Config.PERPLEXITY_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
            "max_tokens": max(256, max_tokens),
        },
        timeout=120,
    )
    response.raise_for_status()
    payload = response.json()

    content = payload["choices"][0]["message"]["content"].strip()
    return BridgeResult(text=content, sources=extract_sources(payload))


def find_visible_locator(page, selectors: list[str]):
    for selector in selectors:
        locator = page.locator(selector)
        try:
            count = locator.count()
        except Exception:
            continue
        for index in range(count):
            candidate = locator.nth(index)
            try:
                if candidate.is_visible():
                    return candidate, selector
            except Exception:
                continue
    return None, ""


def click_first_visible(page, selectors: list[str]) -> bool:
    locator, _selector = find_visible_locator(page, selectors)
    if locator is None:
        return False
    try:
        locator.click(timeout=5000)
        return True
    except Exception:
        return False


def click_button_by_text(page, labels: list[str]) -> bool:
    script = """
    (labels) => {
        const candidates = Array.from(document.querySelectorAll('button, [role="button"]'));
        for (const label of labels) {
            const button = candidates.find((candidate) => ((candidate.innerText || '').trim() === label));
            if (button) {
                button.click();
                return label;
            }
        }
        return '';
    }
    """
    try:
        clicked = page.evaluate(script, labels)
        return bool(clicked)
    except Exception:
        return False


def normalise_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def snapshot_assistant_messages(page) -> list[str]:
    seen: set[str] = set()
    messages: list[str] = []

    for selector in ASSISTANT_MESSAGE_SELECTORS:
        locator = page.locator(selector)
        try:
            if locator.count() == 0:
                continue
            texts = [normalise_text(text) for text in locator.all_inner_texts()]
            for text in texts:
                if not text or len(text) < 40 or text in seen:
                    continue
                seen.add(text)
                messages.append(text)
        except Exception:
            continue
    return messages


def looks_like_user_echo(candidate: str, request_excerpt: str) -> bool:
    if not candidate or not request_excerpt:
        return False
    return request_excerpt[:120] in candidate[:240]


def safe_title(page) -> str:
    try:
        return page.title()
    except Exception:
        return ""


def safe_body_text(page) -> str:
    try:
        body = page.locator("body")
        if body.count() == 0:
            return ""
        return body.first.inner_text(timeout=3000)
    except Exception:
        return ""


def extract_response_from_body(body_text: str, prompt_text: str) -> str:
    prompt_line = normalise_text(prompt_text)
    if not prompt_line:
        return ""

    raw_lines = [line.strip() for line in body_text.splitlines() if line.strip()]
    if not raw_lines:
        return ""

    def is_prompt_match(line: str) -> bool:
        normalized = normalise_text(line)
        if normalized == prompt_line:
            return True
        if len(prompt_line) > 40 and prompt_line[:80] in normalized:
            return True
        return False

    last_prompt_index = -1
    for index, line in enumerate(raw_lines):
        if is_prompt_match(line):
            last_prompt_index = index

    if last_prompt_index < 0:
        return ""

    collected: list[str] = []
    for line in raw_lines[last_prompt_index + 1:]:
        normalized = normalise_text(line)
        if not normalized:
            continue
        if normalized in {"Answer", "Links", "Images", "Share"}:
            continue
        if is_prompt_match(line):
            continue
        if any(stop_marker in normalized for stop_marker in BODY_STOP_MARKERS):
            break
        collected.append(line)

    return "\n".join(collected).strip()


class PerplexityWebBridgeSession:
    def __init__(self, web_profile: Path, browser_channel: str):
        self.web_profile = web_profile
        self.browser_channel = browser_channel
        self._playwright = None
        self._context = None
        self.page = None

    def __enter__(self) -> "PerplexityWebBridgeSession":
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:  # pragma: no cover - local runtime dependency path
            raise RuntimeError(f"Playwright is unavailable for the Perplexity web bridge: {exc}") from exc

        self.web_profile.mkdir(parents=True, exist_ok=True)
        self._playwright = sync_playwright().start()

        launch_kwargs = {
            "user_data_dir": str(self.web_profile),
            "headless": False,
            "viewport": {"width": 1440, "height": 960},
            "args": ["--disable-blink-features=AutomationControlled"],
        }
        if self.browser_channel != "chromium":
            launch_kwargs["channel"] = self.browser_channel

        self._context = self._playwright.chromium.launch_persistent_context(**launch_kwargs)
        self.page = self._context.pages[0] if self._context.pages else self._context.new_page()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._context is not None:
            try:
                self._context.close()
            except Exception:
                pass
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                pass

    def open_home(self) -> None:
        last_error = None
        for url in ("https://www.perplexity.ai/", "https://www.perplexity.ai/search/new"):
            try:
                self.page.goto(url, wait_until="commit", timeout=60000)
                self.page.wait_for_timeout(2500)
                return
            except Exception as exc:
                last_error = exc
        raise RuntimeError(f"Unable to open Perplexity web in the browser session: {last_error}")

    def inspect_readiness(self) -> ChatReadiness:
        url = str(self.page.url).lower()
        title = safe_title(self.page).lower()
        body = safe_body_text(self.page).lower()

        if "cookie policy" in body:
            if click_button_by_text(self.page, COOKIE_BUTTON_LABELS):
                self.page.wait_for_timeout(1000)
                body = safe_body_text(self.page).lower()

        if (
            "just a moment" in title
            or "performing security verification" in body
            or "verify you are human" in body
            or "checking your browser" in body
            or "cloudflare" in body
        ):
            return ChatReadiness(
                state="browser_challenge",
                detail="Perplexity web is waiting on a browser verification step.",
            )

        if (
            "log in" in body
            or "sign up" in body and "continue with google" in body
            or "/signin" in url
            or "/login" in url
        ):
            return ChatReadiness(
                state="login_required",
                detail="Perplexity needs a one-time sign-in in the opened browser window for this bridge profile.",
            )

        prompt_box, _selector = find_visible_locator(self.page, INPUT_SELECTORS)
        if prompt_box is None:
            click_first_visible(self.page, PROMPT_ENTRY_SELECTORS)
            self.page.wait_for_timeout(1000)
            prompt_box, _selector = find_visible_locator(self.page, INPUT_SELECTORS)

        if prompt_box is not None:
            return ChatReadiness(
                state="ready",
                detail="Perplexity chat input is available.",
                prompt_box=prompt_box,
            )

        return ChatReadiness(
            state="loading",
            detail="Perplexity web is still loading the chat view.",
        )

    def wait_for_ready(
        self,
        timeout_seconds: int,
        workflow: str,
        status_path: Path | None = None,
    ) -> object:
        deadline = time.time() + max(15, timeout_seconds)
        last_state = ""

        while time.time() < deadline:
            readiness = self.inspect_readiness()
            if readiness.state == "ready":
                if status_path is not None:
                    write_status(
                        status_path=status_path,
                        workflow=workflow,
                        state="ready",
                        detail="Perplexity web session is ready for requests.",
                        browser_channel=self.browser_channel,
                    )
                return readiness.prompt_box

            if readiness.state != last_state:
                print(readiness.detail, file=sys.stderr)
                last_state = readiness.state
                if status_path is not None:
                    write_status(
                        status_path=status_path,
                        workflow=workflow,
                        state=readiness.state,
                        detail=readiness.detail,
                        browser_channel=self.browser_channel,
                    )

            self.page.wait_for_timeout(1500)

        if last_state == "login_required":
            next_step = (
                "Complete sign-in in the opened browser window and rerun."
                if workflow == "bootstrap"
                else "Complete sign-in in the opened browser window and rerun or start the bridge with --workflow bootstrap."
            )
            raise RuntimeError(f"Perplexity web bridge still needs login. {next_step}")
        if last_state == "browser_challenge":
            raise RuntimeError(
                "Perplexity web bridge is blocked by a browser verification step. Complete it in the opened browser "
                "window and rerun."
            )
        raise RuntimeError("Perplexity web bridge timed out waiting for the chat input to appear.")

    def send_prompt(self, prompt_text: str, prompt_box) -> None:
        try:
            prompt_box.fill(prompt_text, timeout=10000)
        except Exception:
            prompt_box.click(timeout=5000)
            self.page.keyboard.press("Control+A")
            self.page.keyboard.type(prompt_text)

        self.page.wait_for_timeout(400)
        if click_first_visible(self.page, SEND_BUTTON_SELECTORS):
            return

        try:
            prompt_box.press("Enter")
        except Exception:
            self.page.keyboard.press("Enter")

    def wait_for_response(self, prompt_text: str, timeout_seconds: int) -> BridgeResult:
        before_messages = snapshot_assistant_messages(self.page)
        before_count = len(before_messages)
        request_excerpt = normalise_text(prompt_text)[:180]
        last_candidate = ""
        last_change = 0.0
        deadline = time.time() + max(30, timeout_seconds)

        while time.time() < deadline:
            messages = snapshot_assistant_messages(self.page)
            if messages:
                candidate = ""
                if len(messages) >= before_count + 2:
                    candidate = messages[-1]
                elif len(messages) >= before_count + 1:
                    maybe_candidate = messages[-1]
                    if not looks_like_user_echo(maybe_candidate, request_excerpt):
                        candidate = maybe_candidate

                if candidate and candidate != last_candidate:
                    last_candidate = candidate
                    last_change = time.time()

            if not last_candidate:
                body_candidate = extract_response_from_body(safe_body_text(self.page), prompt_text)
                if body_candidate and not looks_like_user_echo(body_candidate, request_excerpt):
                    if body_candidate != last_candidate:
                        last_candidate = body_candidate
                        last_change = time.time()

            if last_candidate and last_change and time.time() - last_change >= 4:
                return BridgeResult(text=last_candidate, sources=[])

            self.page.wait_for_timeout(1800)

        raise RuntimeError("Perplexity web bridge timed out waiting for the assistant response to stabilize.")

    def bootstrap(self, timeout_seconds: int, workflow: str, status_path: Path | None = None) -> None:
        self.open_home()
        self.wait_for_ready(timeout_seconds=timeout_seconds, workflow=workflow, status_path=status_path)

    def ask(
        self,
        prompt_text: str,
        timeout_seconds: int,
        workflow: str,
        status_path: Path | None = None,
    ) -> BridgeResult:
        self.open_home()
        prompt_box = self.wait_for_ready(
            timeout_seconds=timeout_seconds,
            workflow=workflow,
            status_path=status_path,
        )
        self.send_prompt(prompt_text, prompt_box)
        return self.wait_for_response(prompt_text, timeout_seconds)


def load_request(args: argparse.Namespace, request_path: Path) -> tuple[str, str]:
    if args.prompt:
        return args.prompt.strip(), "direct prompt"

    if not request_path.exists():
        raise FileNotFoundError(f"Request file not found: {request_path}")

    return load_text(request_path).strip(), request_path.name


def build_prompt_from_request(
    args: argparse.Namespace,
    request_path: Path,
    transcript_path: Path,
    request_text: str,
) -> str:
    sections = build_context_sections(
        request_path=request_path,
        request_text=request_text,
        transcript_path=transcript_path,
        transcript_tail_lines=max(0, args.transcript_tail_lines),
        extra_include_paths=args.include,
        include_default_context=not args.no_default_context,
    )
    return build_user_prompt(request_text, sections)


def process_once(
    args: argparse.Namespace,
    request_path: Path,
    response_path: Path,
    transcript_path: Path,
    status_path: Path,
    web_session: PerplexityWebBridgeSession | None = None,
) -> int:
    try:
        request_text, request_label = load_request(args, request_path)
        if is_placeholder_request(request_text):
            detail = "Request file still contains the template placeholder. Write a real task for Perplexity first."
            write_status(
                status_path=status_path,
                workflow=args.workflow,
                state="awaiting_request",
                detail=detail,
                response_path=response_path,
                model=args.model,
            )
            print(detail, file=sys.stderr)
            return 1

        user_prompt = build_prompt_from_request(args, request_path, transcript_path, request_text)
        write_status(
            status_path=status_path,
            workflow=args.workflow,
            state="processing",
            detail="Sending the current request to Perplexity.",
            request_label=request_label,
            response_path=response_path,
            model=args.model,
        )

        result = None
        bridge_name = ""

        if args.mode in {"auto", "api"}:
            try:
                result = call_api_bridge(
                    user_prompt=user_prompt,
                    model=args.model,
                    max_tokens=args.max_tokens,
                )
                bridge_name = f"Perplexity API bridge ({args.model})"
            except Exception as exc:
                if args.mode == "api":
                    raise
                print(
                    f"Perplexity API bridge unavailable, falling back to browser session: {exc}",
                    file=sys.stderr,
                )

        if result is None and args.mode in {"auto", "web"}:
            browser_channel = detect_browser_channel(args.browser_channel)
            if web_session is None:
                with PerplexityWebBridgeSession(
                    web_profile=Path(args.web_profile).resolve(),
                    browser_channel=browser_channel,
                ) as temp_session:
                    result = temp_session.ask(
                        prompt_text=user_prompt,
                        timeout_seconds=args.web_timeout_seconds,
                        workflow=args.workflow,
                        status_path=status_path,
                    )
                    bridge_name = f"Perplexity web bridge ({temp_session.browser_channel})"
            else:
                result = web_session.ask(
                    prompt_text=user_prompt,
                    timeout_seconds=args.web_timeout_seconds,
                    workflow=args.workflow,
                    status_path=status_path,
                )
                bridge_name = f"Perplexity web bridge ({web_session.browser_channel})"

        if result is None:
            raise RuntimeError("No Perplexity bridge mode produced a response.")

        response_path.parent.mkdir(parents=True, exist_ok=True)
        response_path.write_text(format_result_markdown(result), encoding="utf-8")
        append_transcript_entry(
            transcript_path=transcript_path,
            result=result,
            request_label=request_label,
            bridge_name=bridge_name or "Perplexity bridge",
        )
        source_detail = f"Perplexity response captured successfully with {len(result.sources)} source link(s)."
        write_status(
            status_path=status_path,
            workflow=args.workflow,
            state="ready",
            detail=source_detail,
            request_label=request_label,
            response_path=response_path,
            model=args.model,
        )
        print(f"Perplexity bridge response written to: {response_path}")
        print(f"Transcript updated: {transcript_path}")
        return 0
    except requests.HTTPError as exc:
        error_text = f"Perplexity bridge API error: {exc}"
    except Exception as exc:  # pragma: no cover - defensive path for local bridge runtime
        error_text = f"Perplexity bridge failed: {type(exc).__name__}: {exc}"

    response_path.parent.mkdir(parents=True, exist_ok=True)
    response_path.write_text(error_text + "\n", encoding="utf-8")
    append_transcript_error(transcript_path, error_text, "direct prompt" if args.prompt else request_path.name)
    write_status(
        status_path=status_path,
        workflow=args.workflow,
        state="error",
        detail=error_text,
        response_path=response_path,
        model=args.model,
    )
    print(error_text, file=sys.stderr)
    print(f"Failure details written to: {response_path}", file=sys.stderr)
    return 1


def run_watch(
    args: argparse.Namespace,
    request_path: Path,
    response_path: Path,
    transcript_path: Path,
    status_path: Path,
    state_path: Path,
) -> int:
    if args.prompt:
        print("--prompt is not supported with --workflow watch.", file=sys.stderr)
        return 1

    browser_channel = detect_browser_channel(args.browser_channel)
    state = load_state(state_path)
    last_request_hash = state.get("last_request_hash", "")
    write_status(
        status_path=status_path,
        workflow=args.workflow,
        state="watching",
        detail="Perplexity bridge is ready and waiting for a new request file update.",
        response_path=response_path,
        model=args.model,
        browser_channel=browser_channel if args.mode in {"auto", "web"} else "",
    )
    print("Perplexity bridge watch mode is active. Press Ctrl+C to stop.")

    try:
        while True:
            if not request_path.exists():
                write_status(
                    status_path=status_path,
                    workflow=args.workflow,
                    state="awaiting_request",
                    detail=f"Request file not found: {request_path}",
                    response_path=response_path,
                    model=args.model,
                    browser_channel=browser_channel if args.mode in {"auto", "web"} else "",
                )
                time.sleep(max(1, args.watch_poll_seconds))
                continue

            request_text = load_text(request_path).strip()
            if is_placeholder_request(request_text):
                write_status(
                    status_path=status_path,
                    workflow=args.workflow,
                    state="awaiting_request",
                    detail="Waiting for a non-template Perplexity request in perplexity-bridge-request.md.",
                    response_path=response_path,
                    model=args.model,
                    browser_channel=browser_channel if args.mode in {"auto", "web"} else "",
                )
                time.sleep(max(1, args.watch_poll_seconds))
                continue

            current_hash = sha256_text(request_text)
            if current_hash != last_request_hash:
                exit_code = process_once(
                    args=args,
                    request_path=request_path,
                    response_path=response_path,
                    transcript_path=transcript_path,
                    status_path=status_path,
                )
                if exit_code == 0:
                    last_request_hash = current_hash
                    save_state(
                        state_path,
                        {
                            "last_request_hash": last_request_hash,
                            "last_processed_at": datetime.now().isoformat(timespec="seconds"),
                            "model": args.model,
                            "workflow": args.workflow,
                            "mode": args.mode,
                            "browser_channel": browser_channel,
                        },
                    )
                    write_status(
                        status_path=status_path,
                        workflow=args.workflow,
                        state="watching",
                        detail="Perplexity bridge is ready and waiting for the next request update.",
                        response_path=response_path,
                        model=args.model,
                        browser_channel=browser_channel if args.mode in {"auto", "web"} else "",
                    )
                else:
                    time.sleep(max(1, args.watch_poll_seconds))
                    continue

            time.sleep(max(1, args.watch_poll_seconds))
    except KeyboardInterrupt:
        write_status(
            status_path=status_path,
            workflow=args.workflow,
            state="stopped",
            detail="Perplexity bridge watch mode was stopped by the operator.",
            response_path=response_path,
            model=args.model,
            browser_channel=browser_channel if args.mode in {"auto", "web"} else "",
        )
        print("Perplexity bridge watch mode stopped.")
        return 0


def run_bootstrap(args: argparse.Namespace, status_path: Path) -> int:
    browser_channel = detect_browser_channel(args.browser_channel)
    try:
        with PerplexityWebBridgeSession(
            web_profile=Path(args.web_profile).resolve(),
            browser_channel=browser_channel,
        ) as session:
            write_status(
                status_path=status_path,
                workflow=args.workflow,
                state="starting",
                detail="Opening Perplexity web and waiting for the chat input to become available.",
                browser_channel=browser_channel,
                model=args.model,
            )
            session.bootstrap(
                timeout_seconds=args.web_timeout_seconds,
                workflow=args.workflow,
                status_path=status_path,
            )
        write_status(
            status_path=status_path,
            workflow=args.workflow,
            state="ready",
            detail="Perplexity browser profile is authenticated and ready for future bridge requests.",
            browser_channel=browser_channel,
            model=args.model,
        )
        print("Perplexity bridge bootstrap complete.")
        return 0
    except Exception as exc:
        error_text = f"Perplexity bridge bootstrap failed: {type(exc).__name__}: {exc}"
        write_status(
            status_path=status_path,
            workflow=args.workflow,
            state="error",
            detail=error_text,
            browser_channel=browser_channel,
            model=args.model,
        )
        print(error_text, file=sys.stderr)
        return 1


def main() -> int:
    args = parse_args()
    request_path = Path(args.request).resolve()
    response_path = Path(args.response).resolve()
    transcript_path = Path(args.transcript).resolve()
    status_path = Path(args.status).resolve()
    state_path = Path(args.state).resolve()

    if args.workflow == "bootstrap":
        return run_bootstrap(args, status_path)

    if args.workflow == "watch":
        return run_watch(
            args=args,
            request_path=request_path,
            response_path=response_path,
            transcript_path=transcript_path,
            status_path=status_path,
            state_path=state_path,
        )

    return process_once(
        args=args,
        request_path=request_path,
        response_path=response_path,
        transcript_path=transcript_path,
        status_path=status_path,
    )


if __name__ == "__main__":
    raise SystemExit(main())
