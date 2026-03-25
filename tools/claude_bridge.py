"""
Local Claude bridge for the IRIS collaboration notebook.

This bridge supports three workflows:
  - once:      process the current request one time
  - bootstrap: open a persistent Claude browser session and wait for login
  - watch:     keep watching the request file and answer new requests automatically

Defaults:
  - Reads request from   D:\IRIS\ai-collab\claude-bridge-request.md
  - Writes response to   D:\IRIS\ai-collab\claude-bridge-response.md
  - Writes status to     D:\IRIS\ai-collab\claude-bridge-status.md
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

from anthropic import APIError
from anthropic import Anthropic

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from config import Config


DEFAULT_REQUEST = WORKSPACE / "ai-collab" / "claude-bridge-request.md"
DEFAULT_RESPONSE = WORKSPACE / "ai-collab" / "claude-bridge-response.md"
DEFAULT_TRANSCRIPT = WORKSPACE / "ai-collab" / "transcript.md"
DEFAULT_STATUS = WORKSPACE / "ai-collab" / "claude-bridge-status.md"
DEFAULT_WEB_PROFILE = WORKSPACE / ".bridge" / "claude-profile"
DEFAULT_STATE = WORKSPACE / ".bridge" / "claude-bridge-state.json"

DEFAULT_CONTEXT_FILES = [
    WORKSPACE / "ai-collab" / "brief.md",
    WORKSPACE / "ai-collab" / "cody-handoff.md",
    WORKSPACE / "ai-collab" / "claude-handoff.md",
    WORKSPACE / "ai-collab" / "decisions.md",
    WORKSPACE / "SAFETY_CONTRACT.md",
]

SYSTEM_PROMPT = """You are Claude collaborating with Cody and the user on IRIS.

Rules:
- Keep replies concise, direct, and high-signal.
- Prefer findings, risks, recommendations, and next actions over recap.
- Do not restate the entire project unless needed.
- If something is ambiguous, ask at most one blocking question.
- If context is incomplete, say what is missing briefly and continue with the best practical answer.
- When relevant, reference the provided file paths.
"""

PLACEHOLDER_MARKERS = [
    "Write the task for Claude here.",
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
    "[contenteditable='true'][data-slate-editor='true']",
    "[contenteditable='true']",
]

SEND_BUTTON_SELECTORS = [
    "button[aria-label*='Send']",
    "button[aria-label*='send']",
    "button[data-testid*='send']",
    "button[type='submit']",
]

ASSISTANT_MESSAGE_SELECTORS = [
    ".font-claude-response",
    ".standard-markdown",
    ".font-claude-response-body",
]


@dataclass
class ChatReadiness:
    state: str
    detail: str
    prompt_box: object | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a local Claude bridge request.")
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
    parser.add_argument("--response", default=str(DEFAULT_RESPONSE), help="Path to write the Claude response.")
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
        help="Max tokens for the Claude API response.",
    )
    parser.add_argument(
        "--model",
        default=getattr(Config, "CLAUDE_MODEL", "claude-sonnet-4-20250514"),
        help="Claude model name.",
    )
    parser.add_argument(
        "--no-default-context",
        action="store_true",
        help="Do not include the default IRIS collaboration files automatically.",
    )
    parser.add_argument(
        "--web-profile",
        default=str(DEFAULT_WEB_PROFILE),
        help="Persistent browser profile directory for Claude web sessions.",
    )
    parser.add_argument(
        "--browser-channel",
        choices=["auto", "msedge", "chrome", "chromium"],
        default="auto",
        help="Browser channel for the Claude web bridge.",
    )
    parser.add_argument(
        "--web-timeout-seconds",
        type=int,
        default=240,
        help="How long to wait for Claude web to become ready and finish responding.",
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
    parts = ["# Claude Bridge Request", request_body.strip()]
    if sections:
        parts.append("\n# Included Context")
        for label, content in sections:
            parts.append(f"\n## {label}\n{content.strip()}")
    return "\n".join(part for part in parts if part).strip() + "\n"


def extract_text(response) -> str:
    chunks: list[str] = []
    for block in getattr(response, "content", []):
        if getattr(block, "type", "") == "text":
            chunks.append(getattr(block, "text", ""))
    return "\n".join(chunk for chunk in chunks if chunk).strip()


def append_transcript_entry(
    transcript_path: Path,
    response_text: str,
    request_label: str,
    bridge_name: str,
) -> None:
    timestamp = datetime.now().strftime("%H:%M")
    preview = next((line.strip() for line in response_text.splitlines() if line.strip()), "(empty response)")
    preview = preview[:220]
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    with transcript_path.open("a", encoding="utf-8") as handle:
        handle.write(
            f"\n[{timestamp}] Claude (relay): Responded via {bridge_name} for "
            f"'{request_label}'. Preview: {preview}\n"
        )


def append_transcript_error(transcript_path: Path, error_text: str, request_label: str) -> None:
    timestamp = datetime.now().strftime("%H:%M")
    preview = error_text.strip().replace("\n", " ")
    preview = preview[:220]
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    with transcript_path.open("a", encoding="utf-8") as handle:
        handle.write(
            f"\n[{timestamp}] Claude (relay): Claude bridge failed for "
            f"'{request_label}'. Error: {preview}\n"
        )


def write_status(
    status_path: Path,
    workflow: str,
    state: str,
    detail: str = "",
    browser_channel: str = "",
    request_label: str = "",
    response_path: Path | None = None,
) -> None:
    status_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Claude Bridge Status",
        "",
        f"- Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- Workflow: {workflow}",
        f"- State: {state}",
    ]
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


def detect_browser_channel(preference: str) -> str:
    if preference != "auto":
        return preference

    for channel in ("msedge", "chrome"):
        for candidate in BROWSER_CHANNEL_PATHS[channel]:
            if candidate.exists():
                return channel
    return "chromium"


def call_api_bridge(user_prompt: str, model: str, max_tokens: int) -> str:
    if not getattr(Config, "CLAUDE_API_KEY", ""):
        raise RuntimeError("CLAUDE_API_KEY is not configured.")

    client = Anthropic(api_key=Config.CLAUDE_API_KEY)
    message = client.messages.create(
        model=model,
        max_tokens=max(256, max_tokens),
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return extract_text(message)


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
                if not text or text in seen:
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
            root = page.locator("[id='root']")
            if root.count() == 0:
                return ""
            return root.first.inner_text(timeout=3000)
        text = body.first.inner_text(timeout=3000)
        if text.strip():
            return text
        root = page.locator("[id='root']")
        if root.count() == 0:
            return text
        root_text = root.first.inner_text(timeout=3000)
        return root_text or text
    except Exception:
        return ""


class ClaudeWebBridgeSession:
    def __init__(self, web_profile: Path, browser_channel: str):
        self.web_profile = web_profile
        self.browser_channel = browser_channel
        self._playwright = None
        self._context = None
        self.page = None

    def __enter__(self) -> "ClaudeWebBridgeSession":
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:  # pragma: no cover - local runtime dependency path
            raise RuntimeError(f"Playwright is unavailable for the Claude web bridge: {exc}") from exc

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
        for url in ("https://claude.ai/new", "https://claude.ai"):
            try:
                self.page.goto(url, wait_until="commit", timeout=60000)
                self.page.wait_for_timeout(2500)
                return
            except Exception as exc:
                last_error = exc
                if "ERR_ABORTED" in str(exc) and str(self.page.url).startswith("https://claude.ai"):
                    self.page.wait_for_timeout(2500)
                    return
        raise RuntimeError(f"Unable to open Claude web in the browser session: {last_error}")

    def dismiss_cookie_banner(self) -> bool:
        script = """
        (labels) => {
            const candidates = Array.from(document.querySelectorAll('button, [role="button"]'));
            for (const label of labels) {
                const button = candidates.find((candidate) => (candidate.innerText || '').includes(label));
                if (button) {
                    button.click();
                    return label;
                }
            }
            return '';
        }
        """
        try:
            clicked = self.page.evaluate(script, ["Reject All Cookies", "Accept All Cookies"])
            if clicked:
                self.page.wait_for_timeout(1500)
                return True
        except Exception:
            return False
        return False

    def inspect_readiness(self) -> ChatReadiness:
        url = str(self.page.url).lower()
        title = safe_title(self.page).lower()
        body = safe_body_text(self.page).lower()

        if "cookie settings" in body:
            if self.dismiss_cookie_banner():
                body = safe_body_text(self.page).lower()
            else:
                return ChatReadiness(
                    state="cookie_banner",
                    detail="Claude web is waiting on the cookie banner before the login/chat flow can continue.",
                )

        if (
            "/logout" in url
            or "/login" in url
            or "continue with google" in body
            or "continue with email" in body
            or "log in" in body and "pricing" in body
        ):
            return ChatReadiness(
                state="login_required",
                detail="Claude needs a one-time sign-in in the opened browser window for this bridge profile.",
            )

        if (
            "just a moment" in title
            or "checking your browser" in body
            or "verify you are human" in body
            or "are you human" in body
            or "security verification" in body
            or "cloudflare" in body
            or "/api/challenge_redirect" in url
        ):
            return ChatReadiness(
                state="browser_challenge",
                detail="Claude web is waiting on a browser verification step.",
            )

        prompt_box, _selector = find_visible_locator(self.page, INPUT_SELECTORS)
        if prompt_box is not None:
            return ChatReadiness(
                state="ready",
                detail="Claude chat input is available.",
                prompt_box=prompt_box,
            )

        return ChatReadiness(
            state="loading",
            detail="Claude web is still loading the chat view.",
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
                        detail="Claude web session is ready for requests.",
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
            raise RuntimeError(
                f"Claude web bridge still needs login. {next_step}"
            )
        if last_state == "cookie_banner":
            raise RuntimeError(
                "Claude web bridge is blocked on the cookie banner. Use the opened browser window to dismiss it "
                "if it remains visible, then rerun."
            )
        if last_state == "browser_challenge":
            raise RuntimeError(
                "Claude web bridge is blocked by a browser verification step. Complete it in the opened browser "
                "window and rerun."
            )
        raise RuntimeError("Claude web bridge timed out waiting for the chat input to appear.")

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

    def wait_for_response(self, prompt_text: str, timeout_seconds: int) -> str:
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

                if last_candidate and last_change and time.time() - last_change >= 4:
                    return last_candidate

            self.page.wait_for_timeout(1800)

        raise RuntimeError("Claude web bridge timed out waiting for the assistant response to stabilize.")

    def bootstrap(self, timeout_seconds: int, workflow: str, status_path: Path | None = None) -> None:
        self.open_home()
        self.wait_for_ready(timeout_seconds=timeout_seconds, workflow=workflow, status_path=status_path)

    def ask(
        self,
        prompt_text: str,
        timeout_seconds: int,
        workflow: str,
        status_path: Path | None = None,
    ) -> str:
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
    web_session: ClaudeWebBridgeSession | None = None,
) -> int:
    try:
        request_text, request_label = load_request(args, request_path)
        if is_placeholder_request(request_text):
            detail = "Request file still contains the template placeholder. Write a real task for Claude first."
            write_status(
                status_path=status_path,
                workflow=args.workflow,
                state="awaiting_request",
                detail=detail,
                response_path=response_path,
            )
            print(detail, file=sys.stderr)
            return 1

        user_prompt = build_prompt_from_request(args, request_path, transcript_path, request_text)
        write_status(
            status_path=status_path,
            workflow=args.workflow,
            state="processing",
            detail="Sending the current request to Claude.",
            request_label=request_label,
            response_path=response_path,
        )

        response_text = ""
        bridge_name = ""

        if args.mode in {"auto", "api"}:
            try:
                response_text = call_api_bridge(
                    user_prompt=user_prompt,
                    model=args.model,
                    max_tokens=args.max_tokens,
                )
                bridge_name = "local Claude API bridge"
            except Exception as exc:
                if args.mode == "api":
                    raise
                print(
                    f"Claude API bridge unavailable, falling back to browser session: {exc}",
                    file=sys.stderr,
                )

        if not response_text and args.mode in {"auto", "web"}:
            if web_session is None:
                with ClaudeWebBridgeSession(
                    web_profile=Path(args.web_profile).resolve(),
                    browser_channel=detect_browser_channel(args.browser_channel),
                ) as temp_session:
                    response_text = temp_session.ask(
                        prompt_text=user_prompt,
                        timeout_seconds=args.web_timeout_seconds,
                        workflow=args.workflow,
                        status_path=status_path,
                    )
                    bridge_name = f"local Claude web bridge ({temp_session.browser_channel})"
            else:
                response_text = web_session.ask(
                    prompt_text=user_prompt,
                    timeout_seconds=args.web_timeout_seconds,
                    workflow=args.workflow,
                    status_path=status_path,
                )
                bridge_name = f"local Claude web bridge ({web_session.browser_channel})"

        response_path.parent.mkdir(parents=True, exist_ok=True)
        response_path.write_text(response_text + ("\n" if response_text else ""), encoding="utf-8")
        append_transcript_entry(
            transcript_path=transcript_path,
            response_text=response_text,
            request_label=request_label,
            bridge_name=bridge_name or "local Claude bridge",
        )
        write_status(
            status_path=status_path,
            workflow=args.workflow,
            state="ready",
            detail="Claude response captured successfully.",
            request_label=request_label,
            response_path=response_path,
        )
        print(f"Claude bridge response written to: {response_path}")
        print(f"Transcript updated: {transcript_path}")
        return 0
    except APIError as exc:
        error_text = f"Claude bridge API error: {exc}"
    except Exception as exc:  # pragma: no cover - defensive path for local bridge runtime
        error_text = f"Claude bridge failed: {type(exc).__name__}: {exc}"

    response_path.parent.mkdir(parents=True, exist_ok=True)
    response_path.write_text(error_text + "\n", encoding="utf-8")
    append_transcript_error(transcript_path, error_text, "direct prompt" if args.prompt else request_path.name)
    write_status(
        status_path=status_path,
        workflow=args.workflow,
        state="error",
        detail=error_text,
        response_path=response_path,
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
        detail="Claude bridge is ready and waiting for a new request file update.",
        browser_channel=browser_channel,
        response_path=response_path,
    )
    print("Claude bridge watch mode is active. Press Ctrl+C to stop.")

    try:
        while True:
            if not request_path.exists():
                write_status(
                    status_path=status_path,
                    workflow=args.workflow,
                    state="awaiting_request",
                    detail=f"Request file not found: {request_path}",
                    browser_channel=browser_channel,
                    response_path=response_path,
                )
                time.sleep(max(1, args.watch_poll_seconds))
                continue

            request_text = load_text(request_path).strip()
            if is_placeholder_request(request_text):
                write_status(
                    status_path=status_path,
                    workflow=args.workflow,
                    state="awaiting_request",
                    detail="Waiting for a non-template Claude request in claude-bridge-request.md.",
                    browser_channel=browser_channel,
                    response_path=response_path,
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
                    web_session=None,
                )
                if exit_code == 0:
                    last_request_hash = current_hash
                    save_state(
                        state_path,
                        {
                            "last_request_hash": last_request_hash,
                            "last_processed_at": datetime.now().isoformat(timespec="seconds"),
                            "browser_channel": browser_channel,
                            "workflow": args.workflow,
                        },
                    )
                    write_status(
                        status_path=status_path,
                        workflow=args.workflow,
                        state="watching",
                        detail="Claude bridge is ready and waiting for the next request update.",
                        browser_channel=browser_channel,
                        response_path=response_path,
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
            detail="Claude bridge watch mode was stopped by the operator.",
            browser_channel=browser_channel,
            response_path=response_path,
        )
        print("Claude bridge watch mode stopped.")
        return 0


def run_bootstrap(args: argparse.Namespace, status_path: Path) -> int:
    browser_channel = detect_browser_channel(args.browser_channel)
    try:
        with ClaudeWebBridgeSession(
            web_profile=Path(args.web_profile).resolve(),
            browser_channel=browser_channel,
        ) as session:
            write_status(
                status_path=status_path,
                workflow=args.workflow,
                state="starting",
                detail="Opening Claude web and waiting for the chat input to become available.",
                browser_channel=browser_channel,
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
            detail="Claude browser profile is authenticated and ready for future bridge requests.",
            browser_channel=browser_channel,
        )
        print("Claude bridge bootstrap complete.")
        return 0
    except Exception as exc:
        error_text = f"Claude bridge bootstrap failed: {type(exc).__name__}: {exc}"
        write_status(
            status_path=status_path,
            workflow=args.workflow,
            state="error",
            detail=error_text,
            browser_channel=browser_channel,
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
