"""
IRIS Action Executor
====================
When you ask IRIS to do something — install, create, delete, run —
it plans the action, tells you exactly what it's about to do,
and waits for your voice/text permission before executing when required.

PERMISSION GATE FLOW:
  You: "Iris, install Python"
  IRIS: "I'll run: winget install Python.Python.3 — shall I go ahead?"
  You: "yes" / "go ahead" / "do it"
  IRIS: [runs the command, reports result]
  IRIS: "Done. Python installed. Want me to verify it worked?"

SUPPORTED ACTION TYPES:
  - install_package  : winget / pip / npm install
  - run_command      : any shell command
  - manage_package   : install / uninstall / upgrade / list app packages
  - create_file      : create a file with content
  - create_folder    : make a directory
  - open_app         : launch an application
  - search_web       : open browser search
  - write_to_file    : append/write content to existing file
  - type_text        : type into the currently focused window
  - type_in_window   : focus a named window, then type into it
  - press_hotkey     : send a shortcut to the currently focused window
  - press_hotkey_in_window : focus a named window, then send a shortcut
  - click_at         : click absolute screen coordinates
  - click_window     : click inside a named window
  - focus_window     : bring a named window to the front
  - window_state     : minimize / maximize / restore / close a named window

SAFETY:
  - IRIS always announces what it will do before doing it when confirmation is required
  - Destructive actions (delete, format, rm -rf) require DOUBLE confirmation
  - Every action and result is logged to iris_actions.log
"""

import subprocess
import os
import platform
import re
import json
import difflib
import logging
import shlex
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from typing import Optional, Tuple

from config import Config
from core.security import SecurityGuard, SAFE, WARNING, BLOCKED, NEED_ADMIN
from core.autocorrect import AutoCorrector
from core.browser import BrowserAutomation
from core.desktop_control import DesktopController, DesktopControlError, normalize_key_token
from core.improv import ImprovEngine


# ── Phrases that mean YES ──────────────────────────────────────
YES_WORDS = [
    "yes", "yeah", "yep", "yup", "sure", "go ahead", "do it",
    "proceed", "confirm", "ok", "okay", "affirmative", "correct",
    "go for it", "run it", "execute", "do that", "sounds good"
]

# ── Phrases that mean NO ───────────────────────────────────────
NO_WORDS = [
    "no", "nope", "cancel", "stop", "don't", "abort", "wait",
    "hold on", "negative", "never mind", "nevermind", "skip"
]

SESSION_APPROVAL_WORDS = [
    "always for this session",
    "approve for this session",
    "allow for this session",
    "remember for this session",
    "yes for this session",
]

OVERDRIVE_CONTROL_PHRASES = {
    "activate overdrive",
    "overdrive on",
    "turn on overdrive",
    "enable overdrive",
    "start overdrive",
    "deactivate overdrive",
    "overdrive off",
    "turn off overdrive",
    "disable overdrive",
    "stop overdrive",
    "overdrive status",
    "is overdrive on",
    "status overdrive",
}

# ── Phrases that are DANGEROUS (need double confirm) ───────────
DANGEROUS_PATTERNS = [
    r"del\s", r"rm\s", r"rmdir", r"format", r"delete",
    r"drop\s", r"uninstall", r"--force", r"-rf"
]


class ActionExecutor:
    WINDOWS_SHELL_BUILTINS = {
        "assoc", "break", "call", "cd", "chcp", "cls", "copy", "date", "del",
        "dir", "echo", "erase", "exit", "for", "ftype", "md", "mkdir", "move",
        "path", "pause", "popd", "prompt", "pushd", "rd", "ren", "rename",
        "rmdir", "set", "shift", "start", "time", "title", "type", "ver",
        "verify", "vol",
    }
    VOICE_CONFIRM_ACTIONS = {
        "create_file",
        "create_folder",
        "write_to_file",
    }
    ALWAYS_CONFIRM_ACTIONS = {
        "run_command",
    }

    def __init__(self, voice, brain):
        self.voice   = voice
        self.brain   = brain
        self.security = SecurityGuard(brain)
        self.log_file    = "iris_actions.log"
        self.audit_file  = "iris_audit.log"
        self.is_windows  = platform.system() == "Windows"
        self.pending_action         = None
        self.pending_verdict        = None
        self.pending_action_source  = "unknown"
        self.pending_security_reason = ""
        self.pending_presence_check = False
        self.follow_up              = None
        self.autocorrect            = AutoCorrector(brain)
        self.improv                 = ImprovEngine(brain)
        self.pending_plans          = None   # stores A/B/C plans waiting for user choice
        self.last_action_path       = None
        self.current_input_source   = "text" if getattr(voice, "text_mode", False) else "unknown"
        self.auto_action_timestamps = []
        self.recent_action_history  = []
        self.session_approvals      = {}
        self._audit_logger          = None
        self._audit_logger_path     = None
        self._clarification_options = []
        self._browser = None   # lazy — created only when needed
        self._desktop = None   # lazy — created only when needed

    @property
    def browser(self):
        """Create browser automation only when first needed."""
        if self._browser is None:
            self._browser = BrowserAutomation()
        return self._browser

    @property
    def desktop(self):
        """Create desktop automation only when first needed."""
        if self._desktop is None:
            self._desktop = DesktopController()
        return self._desktop

    def set_input_source(self, source: str | None) -> None:
        normalized = (source or "").strip().lower()
        if normalized not in {"voice", "text"}:
            normalized = "unknown"
        self.current_input_source = normalized

    def _matches_any_phrase(self, text: str, phrases: list[str]) -> bool:
        lowered = (text or "").strip().lower()
        if not lowered:
            return False
        for phrase in phrases:
            pattern = r"(?<!\w)" + re.escape(phrase.lower()) + r"(?!\w)"
            if re.search(pattern, lowered):
                return True
        return False

    def _approval_fingerprint(self, plan: dict, verdict: str) -> str:
        relevant = {
            "action_type": plan.get("action_type", ""),
            "command": plan.get("command", ""),
            "filename": plan.get("filename", ""),
            "content": plan.get("content", ""),
            "app_name": plan.get("app_name", ""),
            "package_operation": plan.get("package_operation", ""),
            "package_name": plan.get("package_name", ""),
            "search_query": plan.get("search_query", ""),
            "url": plan.get("url", ""),
            "text_to_type": plan.get("text_to_type", ""),
            "keys": plan.get("keys", []),
            "x": plan.get("x", 0),
            "y": plan.get("y", 0),
            "button": plan.get("button", ""),
            "clicks": plan.get("clicks", 0),
            "window_title": plan.get("window_title", ""),
            "window_state": plan.get("window_state", ""),
            "verdict": verdict,
        }
        return json.dumps(relevant, sort_keys=True)

    def _desktop_context_title(self) -> str:
        try:
            return self.desktop.get_active_window_title()
        except Exception:
            return ""

    def _can_remember_approval(self, plan: dict, verdict: str, security_reason: str = "") -> bool:
        if verdict not in {WARNING, NEED_ADMIN}:
            return False
        if plan.get("is_dangerous", False):
            return False

        lowered_reason = (security_reason or "").lower()
        if "recent action touched a potentially sensitive path" in lowered_reason:
            return False
        if "references the same path" in lowered_reason:
            return False

        action_type = plan.get("action_type", "")
        if action_type in {"click_at", "type_text", "press_hotkey"}:
            return True

        if action_type in {"click_window", "type_in_window", "press_hotkey_in_window"}:
            return bool(str(plan.get("window_title", "") or "").strip())

        if action_type == "window_state" and str(plan.get("window_state", "") or "").strip().lower() in {
            "minimize",
            "maximize",
            "restore",
        }:
            return True

        return True

    def _remember_session_approval(self, plan: dict, verdict: str, source: str | None = None) -> bool:
        security_reason = self.pending_security_reason
        if not self._can_remember_approval(plan, verdict, security_reason):
            return False

        now = datetime.now()
        expires_at = now + timedelta(hours=8)
        entry = {
            "verdict": verdict,
            "approved_at": now.isoformat(timespec="seconds"),
            "expires_at": expires_at.isoformat(timespec="seconds"),
            "source": (source or self.pending_action_source or self.current_input_source or "unknown"),
            "security_reason": security_reason,
            "action_type": plan.get("action_type", ""),
        }

        action_type = plan.get("action_type", "")
        if action_type in {"click_at", "type_text", "press_hotkey"}:
            active_window_title = self._desktop_context_title()
            if not active_window_title:
                return False
            entry["active_window_title"] = active_window_title
        elif action_type in {"click_window", "type_in_window", "press_hotkey_in_window"}:
            target_window_title = str(plan.get("window_title", "") or "").strip()
            if not target_window_title:
                return False
            entry["target_window_title"] = target_window_title
        elif action_type == "window_state":
            target_window_title = str(plan.get("window_title", "") or "").strip()
            window_state = str(plan.get("window_state", "") or "").strip().lower()
            if not target_window_title or window_state not in {"minimize", "maximize", "restore"}:
                return False
            entry["target_window_title"] = target_window_title
            entry["window_state"] = window_state

        self.session_approvals[self._approval_fingerprint(plan, verdict)] = entry
        return True

    def _get_session_approval(self, plan: dict, verdict: str) -> dict | None:
        self._purge_expired_session_approvals()
        key = self._approval_fingerprint(plan, verdict)
        entry = self.session_approvals.get(key)
        if not entry:
            return None

        required_window = entry.get("active_window_title", "")
        if required_window:
            current_title = self._desktop_context_title()
            if not current_title or current_title.strip().lower() != required_window.strip().lower():
                return None

        return entry

    def _purge_expired_session_approvals(self) -> None:
        if not self.session_approvals:
            return
        now = datetime.now()
        expired = []
        for key, entry in self.session_approvals.items():
            try:
                expires_at = datetime.fromisoformat(entry.get("expires_at", ""))
            except Exception:
                expired.append(key)
                continue
            if expires_at <= now:
                expired.append(key)
        for key in expired:
            self.session_approvals.pop(key, None)

    # ─────────────────────────────────────────────────────────────
    # DETECTION: Does this input want an action?
    # ─────────────────────────────────────────────────────────────

    ACTION_TRIGGERS = [
        "install", "uninstall", "download", "setup", "set up",
        "create", "make", "build", "generate", "write",
        "delete", "remove", "clean",
        "run", "execute", "launch", "open", "start",
        "update", "upgrade", "configure", "enable", "disable",
        "move", "copy", "rename",
        "search for", "look up", "find",
        "hotkey", "shortcut", "switch to", "bring to front",
    ]

    DESKTOP_ACTION_PATTERNS = [
        r"^(?:type|enter)\s+.+",
        r"^(?:type|enter)\s+.+\s+(?:in|into)\s+.+",
        r"^(?:press|hit|use|send)\s+.+\s+(?:in|into)\s+.+",
        r"^(?:press|hit|use)\s+(?:the\s+)?(?:hotkey|shortcut|key(?: combo)?)\s+.+",
        r"^(?:press|hit)\s+(?:ctrl|control|alt|shift|win|windows|enter|tab|escape|esc|space|backspace|delete|left|right|up|down|f\d+)\b.*",
        r"^(?:click|double click|right click)\s+(?:at\s+)?\d+\s*(?:,|\s)\s*\d+",
        r"^(?:click|double click|right click)\s+(?:the\s+)?(?:center\s+of|inside|in)\s+.+",
        r"^(?:minimize|maximize|restore|close)\s+.+",
        r"^(?:focus|activate|switch to|bring(?:\s+the)?(?:\s+window)?(?:\s+for)?|bring .+ to front)\s+.+",
        r"^(?:what(?:'s| is)|which)\s+(?:window|app)\s+is\s+active\??$",
        r"^active window\??$",
        r"^(?:list|show|what(?:'s| is))\s+(?:open\s+)?windows?\??$",
    ]

    ACTION_INFO_PATTERNS = [
        r"^(?:what(?:'s| is)|which)\s+(?:window|app)\s+is\s+active\??$",
        r"^active window\??$",
        r"^(?:list|show|what(?:'s| is))\s+(?:open\s+)?windows?\??$",
        r"^(?:list|show|what(?:'s| is))\s+(?:my\s+)?(?:installed\s+apps?|installed\s+programs?|apps\s+installed)\??$",
        r"^what apps are installed\??$",
    ]

    ACTION_ADVICE_PREFIXES = (
        "should i ",
        "should we ",
        "how do i ",
        "how can i ",
        "what happens if i ",
        "is it safe to ",
        "is it okay to ",
        "do you think i should ",
        "can i ",
        "could i ",
        "would it be better to ",
    )

    def should_handle(self, user_input: str) -> bool:
        """Detect if user wants IRIS to take a real action."""
        text = user_input.lower().strip()
        if text.strip() in OVERDRIVE_CONTROL_PHRASES:
            return False
        if any(re.search(pattern, text) for pattern in self.ACTION_INFO_PATTERNS):
            return True
        if any(text.startswith(prefix) for prefix in self.ACTION_ADVICE_PREFIXES):
            return False
        return any(trigger in text for trigger in self.ACTION_TRIGGERS) or any(
            re.search(pattern, text) for pattern in self.DESKTOP_ACTION_PATTERNS
        )

    # ─────────────────────────────────────────────────────────────
    # PERMISSION CHECK: Are we waiting for yes/no?
    # ─────────────────────────────────────────────────────────────

    def waiting_for_permission(self) -> bool:
        return self.pending_action is not None and not self.waiting_for_clarification()

    def waiting_for_presence_check(self) -> bool:
        return self.pending_presence_check

    def waiting_for_followup(self) -> bool:
        return self.follow_up is not None

    def waiting_for_clarification(self) -> bool:
        return bool(self.pending_action and self._clarification_options)

    def handle_followup_response(self, user_input: str) -> str:
        """Handle yes/no response to a post-execution follow-up question."""
        text = user_input.lower().strip()
        followup = self.follow_up
        self.follow_up = None

        if self._matches_any_phrase(text, YES_WORDS):
            action = followup.get("action")
            if action == "open_file":
                path = followup.get("path", "")
                try:
                    os.startfile(path)
                    return f"Opened '{os.path.basename(path)}'."
                except Exception as e:
                    return f"Couldn't open it: {e}"
            elif action == "open_app":
                app = followup.get("app", "")
                try:
                    subprocess.Popen([app], shell=False)
                    return f"Opening {app}."
                except Exception as e:
                    return f"Couldn't open it: {e}"
        elif self._matches_any_phrase(text, NO_WORDS):
            return "No problem."

        return None  # Unrecognised — fall through to brain

    def handle_presence_check_response(self, user_input: str) -> Optional[str]:
        if not self.waiting_for_presence_check():
            return None

        text = (user_input or "").lower().strip()
        if self._matches_any_phrase(text, YES_WORDS):
            self.pending_presence_check = False
            self.auto_action_timestamps = []
            self._audit(
                "PRESENCE_CHECK_CONFIRMED",
                {"action_type": "presence_check", "description": "rapid auto sequence"},
                source=self.current_input_source,
            )
            return "All right. Continuing."

        if self._matches_any_phrase(text, NO_WORDS):
            self.pending_presence_check = False
            self.auto_action_timestamps = []
            self._audit(
                "PRESENCE_CHECK_CANCELLED",
                {"action_type": "presence_check", "description": "rapid auto sequence"},
                source=self.current_input_source,
            )
            return "Paused. Tell me when you want to continue."

        return "Still with you? Say go ahead or cancel."

    def handle_clarification_response(self, user_input: str) -> Optional[str]:
        """Resolve a pending clarification, usually a file extension choice."""
        if not self.waiting_for_clarification():
            return None

        text = (user_input or "").lower().strip()
        if not text:
            return "Say the extension you want, or cancel."

        if self._matches_any_phrase(text, NO_WORDS):
            self.pending_action = None
            self.pending_verdict = None
            self.pending_security_reason = ""
            self._clarification_options = []
            return "Cancelled."

        selected_ext = None
        for option in self._clarification_options:
            normalized = option.lower().lstrip(".")
            if option.lower() in text or normalized in text:
                selected_ext = option
                break

        if not selected_ext:
            opts_str = " or ".join(self._clarification_options)
            return f"Say {opts_str}, or cancel."

        plan = self.pending_action or {}
        root, _ = os.path.splitext(plan.get("filename", ""))
        plan["filename"] = f"{root}{selected_ext}"
        self.pending_action = plan
        self._clarification_options = []

        return self._execute_pending()

    def handle_permission_response(self, user_input: str) -> str:
        """
        User responded to a permission or security request.
        Confirmation is allowed only for actions that are not hard-blocked.
        """
        text = user_input.lower().strip()
        plan = self.pending_action
        verdict = self.pending_verdict

        # ── Yes — proceed ──
        if self._matches_any_phrase(text, SESSION_APPROVAL_WORDS):
            if plan and verdict and self._remember_session_approval(
                plan,
                verdict,
                source=self.current_input_source,
            ):
                self._audit_pending("CONFIRM_ONCE_SESSION_APPROVED", source=self.current_input_source)
                return self._execute_pending()
            return "I can only remember exact safe-to-repeat actions for this session. Say go ahead to run it once."

        if self._matches_any_phrase(text, YES_WORDS):
            self._audit_pending("CONFIRM_ONCE_APPROVED", source=self.current_input_source)
            return self._execute_pending()

        # ── No — cancel ──
        if self._matches_any_phrase(text, NO_WORDS):
            self._audit_pending("CONFIRM_ONCE_CANCELLED", source=self.current_input_source)
            self.pending_action  = None
            self.pending_verdict = None
            self.pending_action_source = "unknown"
            self.pending_security_reason = ""
            return "Cancelled."

        # ── Anything else — ask once more plainly ──
        return "Go ahead, or cancel?"

    # ─────────────────────────────────────────────────────────────
    # PLAN: Figure out what action to take
    # ─────────────────────────────────────────────────────────────

    # ─────────────────────────────────────────────────────────────
    # SIMPLE TASK DETECTION: These run without asking permission
    # ─────────────────────────────────────────────────────────────

    SIMPLE_ACTIONS = [
        "create_file", "create_folder", "open_app",
        "search_web", "write_to_file"
    ]

    def _approval_level(self, plan: dict, verdict: str) -> int:
        if verdict == BLOCKED:
            return 3
        if verdict in {WARNING, NEED_ADMIN}:
            return 2

        action_type = str(plan.get("action_type", "") or "").strip()
        if action_type in self.ALWAYS_CONFIRM_ACTIONS:
            return 2

        if action_type == "manage_package":
            operation = str(plan.get("package_operation", "") or "").strip().lower()
            return 0 if operation == "list" else 2

        if (
            self.current_input_source == "voice"
            and action_type in self.VOICE_CONFIRM_ACTIONS
        ):
            return 1

        return 0

    def _approval_guard_message(self, plan: dict, verdict: str) -> str:
        level = self._approval_level(plan, verdict)
        if level == 0 or verdict == BLOCKED:
            return ""

        action_type = str(plan.get("action_type", "") or "").strip()
        if action_type == "run_command":
            return "This runs a shell command directly. I need explicit confirmation before I execute it."

        if action_type == "manage_package":
            operation = str(plan.get("package_operation", "") or "").strip().lower()
            if operation == "install":
                return "This installs a package on the machine. I need explicit confirmation before I continue."
            if operation == "uninstall":
                return "This removes a package from the machine. I need explicit confirmation before I continue."
            if operation == "upgrade":
                return "This updates a package on the machine. I need explicit confirmation before I continue."

        if level == 1 and self.current_input_source == "voice":
            return (
                "This changes local files, and the request came from voice input. "
                "I want explicit confirmation before I make that change."
            )

        return ""

    def _is_simple_task(self, plan: dict, verdict: str) -> bool:
        """
        Everything that isn't a security/ethical issue executes automatically.
        IRIS thinks and acts like a human assistant — no permission needed
        for normal tasks. Only BLOCKED, WARNING, NEED_ADMIN stop for auth.
        """
        if verdict in (BLOCKED, WARNING, NEED_ADMIN):
            return False
        return self._approval_level(plan, verdict) == 0

    # ─────────────────────────────────────────────────────────────
    # COGNITIVE FILE NAMING: auto-rename if file already exists
    # ─────────────────────────────────────────────────────────────

    def _resolve_filename(self, filepath: str) -> tuple:
        """
        If the file already exists, auto-generate a new name cognitively.
        Returns (final_path, message_about_rename_or_None)
        """
        if not os.path.exists(filepath):
            return filepath, None

        # File exists — generate a new name
        base  = os.path.splitext(filepath)[0]
        ext   = os.path.splitext(filepath)[1]
        counter = 2

        while True:
            new_path = f"{base}{counter}{ext}"
            if not os.path.exists(new_path):
                original_name = os.path.basename(filepath)
                new_name      = os.path.basename(new_path)
                return new_path, (
                    f"'{original_name}' already exists — "
                    f"I've created '{new_name}' instead."
                )
            counter += 1

    def plan_action(self, user_input: str) -> str:
        """
        Interpret the request, run security assessment.
        Simple safe tasks execute immediately.
        Risky tasks ask for permission first.
        """
        # ── Try direct pattern matching first (fast, reliable) ──
        plan = self._pattern_match(user_input)

        # ── Fall back to AI JSON planning if no pattern matched ──
        if not plan:
            plan = self._ai_plan(user_input)

        if not plan:
            return "I couldn't figure out how to do that. Could you rephrase it?"

        if plan.get("action_type") == "unsupported":
            return "I'm not sure how to do that safely. Could you describe it differently?"

        # ── Run security assessment ──────────────────────────
        verdict, security_msg = self.security.assess(plan)
        approval_guard = self._approval_guard_message(plan, verdict)
        if approval_guard and verdict == SAFE:
            verdict = WARNING
            security_msg = approval_guard
        chain_warning = self._check_action_chain(plan)
        if chain_warning and verdict == SAFE:
            verdict = WARNING
            security_msg = chain_warning
        header = self.security.format_security_header(verdict)

        if verdict == BLOCKED:
            self._log(f"BLOCKED: {plan.get('command','?')} — {security_msg}")
            self._audit("BLOCKED", plan, source=self.current_input_source)
            self.pending_action = None
            self.pending_verdict = None
            self.pending_action_source = "unknown"
            self.pending_security_reason = ""
            self._clarification_options = []
            return f"{header}\n{security_msg}"

        if verdict in {WARNING, NEED_ADMIN}:
            remembered = self._get_session_approval(plan, verdict)
            if remembered:
                self._log(
                    f"SESSION-AUTO-EXECUTE [{verdict}]: {plan.get('command') or plan.get('description','?')}"
                )
                self._audit("SESSION_APPROVAL_REUSED", plan, source=self.current_input_source)
                self.pending_action = plan
                self.pending_verdict = verdict
                self.pending_action_source = self.current_input_source
                self.pending_security_reason = security_msg
                return self._execute_pending()

        # ── Simple safe task — execute with verification ─────
        if self._is_simple_task(plan, verdict):
            self._log(f"AUTO-EXECUTE: {plan.get('action_type')} — {plan.get('description','')}")
            self.pending_action  = plan
            self.pending_verdict = verdict
            self.pending_security_reason = security_msg
            return self._execute_pending()

        # ── Everything else — ask for permission ─────────────
        self.pending_action  = plan
        self.pending_verdict = verdict
        self.pending_action_source = self.current_input_source
        self.pending_security_reason = security_msg
        permission_msg = self._build_permission_request(plan)

        if verdict in (WARNING, NEED_ADMIN):
            return f"{header}\n{security_msg}\n\n{permission_msg}"

        return permission_msg

    def _shell_quote(self, value: str) -> str:
        text = str(value or "")
        return '"' + text.replace('"', '\\"') + '"'

    def _build_package_command(self, operation: str, package_name: str = "") -> str:
        op = (operation or "").strip().lower()
        pkg = str(package_name or "").strip()
        quoted = self._shell_quote(pkg) if pkg else ""

        if op == "list":
            return "winget list"
        if op == "install":
            return f"winget install --name {quoted} --accept-package-agreements --accept-source-agreements"
        if op == "uninstall":
            return f"winget uninstall --name {quoted}"
        if op == "upgrade":
            return f"winget upgrade --name {quoted} --accept-package-agreements --accept-source-agreements"
        return ""

    def _pattern_match(self, user_input: str) -> Optional[dict]:
        """
        Fast pattern-based action detection for common requests.
        Handles the most frequent actions without needing AI JSON parsing.
        """
        raw = (user_input or "").strip()
        text = raw.lower()

        click_match = re.search(
            r"^(right click|double click|click)\s+(?:at\s+)?(\d+)\s*(?:,|\s)\s*(\d+)$",
            text,
        )
        if click_match:
            click_kind = click_match.group(1)
            button = "right" if click_kind == "right click" else "left"
            clicks = 2 if click_kind == "double click" else 1
            x = int(click_match.group(2))
            y = int(click_match.group(3))
            return {
                "action_type": "click_at",
                "description": f"{click_kind} at {x},{y}",
                "x": x,
                "y": y,
                "button": button,
                "clicks": clicks,
                "is_dangerous": False,
            }

        window_type_match = re.search(
            r"^(?:type|enter)\s+(.+?)\s+(?:in|into)\s+(?:the\s+)?(.+?)(?:\s+window)?$",
            raw,
            re.IGNORECASE,
        )
        if window_type_match:
            text_to_type = window_type_match.group(1).strip()
            window_title = window_type_match.group(2).strip(" \"'")
            if (text_to_type.startswith('"') and text_to_type.endswith('"')) or (
                text_to_type.startswith("'") and text_to_type.endswith("'")
            ):
                text_to_type = text_to_type[1:-1]
            if text_to_type and window_title:
                return {
                    "action_type": "type_in_window",
                    "description": f"type text into '{window_title}': {text_to_type[:60]}",
                    "text_to_type": text_to_type,
                    "window_title": window_title,
                    "is_dangerous": False,
                }

        type_match = re.search(r"^(?:type|enter)\s+(.+)$", raw, re.IGNORECASE)
        if type_match:
            text_to_type = type_match.group(1).strip()
            if (text_to_type.startswith('"') and text_to_type.endswith('"')) or (
                text_to_type.startswith("'") and text_to_type.endswith("'")
            ):
                text_to_type = text_to_type[1:-1]
            if text_to_type:
                return {
                    "action_type": "type_text",
                    "description": f"type text into the active window: {text_to_type[:60]}",
                    "text_to_type": text_to_type,
                    "is_dangerous": False,
                }

        window_click_match = re.search(
            r"^(right click|double click|click)\s+(?:the\s+)?(?:center\s+of|inside|in)\s+(.+?)(?:\s+at\s+(\d+)\s*(?:,|\s)\s*(\d+))?$",
            raw,
            re.IGNORECASE,
        )
        if window_click_match:
            click_kind = window_click_match.group(1)
            button = "right" if click_kind == "right click" else "left"
            clicks = 2 if click_kind == "double click" else 1
            window_title = window_click_match.group(2).strip(" \"'")
            rel_x = window_click_match.group(3)
            rel_y = window_click_match.group(4)
            if window_title:
                return {
                    "action_type": "click_window",
                    "description": (
                        f"{click_kind} in '{window_title}'"
                        if rel_x is None or rel_y is None
                        else f"{click_kind} in '{window_title}' at relative {rel_x},{rel_y}"
                    ),
                    "window_title": window_title,
                    "x": int(rel_x) if rel_x is not None else None,
                    "y": int(rel_y) if rel_y is not None else None,
                    "button": button,
                    "clicks": clicks,
                    "is_dangerous": False,
                }

        if re.search(r"^(?:what(?:'s| is)|which)\s+(?:window|app)\s+is\s+active\??$|^active window\??$", text):
            return {
                "action_type": "active_window",
                "description": "report the active desktop window",
                "is_dangerous": False,
            }

        if re.search(r"^(?:list|show|what(?:'s| is))\s+(?:open\s+)?windows?\??$|^what apps are open\??$", text):
            return {
                "action_type": "list_windows",
                "description": "list the currently open desktop windows",
                "is_dangerous": False,
            }

        if re.search(
            r"^(?:list|show|what(?:'s| is))\s+(?:my\s+)?(?:installed\s+apps?|installed\s+programs?|apps\s+installed)\??$|^what apps are installed\??$",
            text,
        ):
            return {
                "action_type": "manage_package",
                "description": "list installed applications",
                "package_operation": "list",
                "package_name": "",
                "command": "winget list",
                "is_dangerous": False,
            }

        hotkey_window_match = re.search(
            r"^(?:press|hit|use|send)\s+(?:the\s+)?(?:(?:hotkey|shortcut|key(?: combo)?)\s+)?(.+?)\s+(?:in|into)\s+(?:the\s+)?(.+?)(?:\s+window)?$",
            raw,
            re.IGNORECASE,
        )
        if hotkey_window_match:
            keys = self._parse_key_sequence(hotkey_window_match.group(1))
            window_title = hotkey_window_match.group(2).strip(" \"'")
            if keys and window_title:
                rendered = " + ".join(keys)
                return {
                    "action_type": "press_hotkey_in_window",
                    "description": f"send keyboard shortcut {rendered} to '{window_title}'",
                    "keys": keys,
                    "window_title": window_title,
                    "is_dangerous": False,
                }

        hotkey_match = re.search(
            r"^(?:press|hit|use)\s+(?:the\s+)?(?:(?:hotkey|shortcut|key(?: combo)?)\s+)?(.+)$",
            raw,
            re.IGNORECASE,
        )
        if hotkey_match:
            keys = self._parse_key_sequence(hotkey_match.group(1))
            if keys:
                rendered = " + ".join(keys)
                return {
                    "action_type": "press_hotkey",
                    "description": f"send keyboard shortcut {rendered}",
                    "keys": keys,
                    "is_dangerous": False,
                }

        window_state_match = re.search(
            r"^(minimize|maximize|restore|close)\s+(?:the\s+)?(?:window\s+)?(?:for\s+)?(.+?)(?:\s+window)?$",
            raw,
            re.IGNORECASE,
        )
        if window_state_match:
            action = window_state_match.group(1).lower()
            window_title = window_state_match.group(2).strip(" \"'")
            if window_title and window_title.lower() not in {"overdrive", "iris", "the app"}:
                return {
                    "action_type": "window_state",
                    "description": f"{action} the '{window_title}' window",
                    "window_title": window_title,
                    "window_state": action,
                    "is_dangerous": action == "close",
                }

        focus_match = re.search(
            r"^(?:focus|activate|switch to|bring(?:\s+the)?(?:\s+window)?(?:\s+for)?|bring)\s+(.+?)(?:\s+to\s+front)?$",
            raw,
            re.IGNORECASE,
        )
        if focus_match:
            window_title = focus_match.group(1).strip(" \"'")
            if window_title and window_title.lower() not in {"overdrive", "iris", "the app"}:
                return {
                    "action_type": "focus_window",
                    "description": f"focus the '{window_title}' window",
                    "window_title": window_title,
                    "is_dangerous": False,
                }

        install_match = re.search(
            r"^(?:install|set up|add)\s+(?:the\s+)?(?:app|application|program|package)?\s*(.+)$",
            raw,
            re.IGNORECASE,
        )
        if install_match:
            package_name = install_match.group(1).strip(" \"'")
            if package_name:
                return {
                    "action_type": "manage_package",
                    "description": f"install '{package_name}'",
                    "package_operation": "install",
                    "package_name": package_name,
                    "command": self._build_package_command("install", package_name),
                    "is_dangerous": False,
                }

        uninstall_match = re.search(
            r"^(?:uninstall|remove)\s+(?:the\s+)?(?:app|application|program|package)?\s*(.+)$",
            raw,
            re.IGNORECASE,
        )
        if uninstall_match:
            package_name = uninstall_match.group(1).strip(" \"'")
            if package_name:
                return {
                    "action_type": "manage_package",
                    "description": f"uninstall '{package_name}'",
                    "package_operation": "uninstall",
                    "package_name": package_name,
                    "command": self._build_package_command("uninstall", package_name),
                    "is_dangerous": True,
                }

        upgrade_match = re.search(
            r"^(?:upgrade|update)\s+(?:the\s+)?(?:app|application|program|package)?\s*(.+)$",
            raw,
            re.IGNORECASE,
        )
        if upgrade_match:
            package_name = upgrade_match.group(1).strip(" \"'")
            if package_name and package_name.lower() not in {"windows", "the system"}:
                return {
                    "action_type": "manage_package",
                    "description": f"update '{package_name}'",
                    "package_operation": "upgrade",
                    "package_name": package_name,
                    "command": self._build_package_command("upgrade", package_name),
                    "is_dangerous": False,
                }

        # ── Create file ───────────────────────────────────────
        # "create a file called X in Y" / "create file named X in Y" / "make a file X"
        file_match = re.search(
            r"(?:create|make|new)\s+(?:a\s+)?file\s+(?:called|named|as|named as)?\s*['\"]?([^\s'\"]+)['\"]?"
            r"(?:\s+(?:in|on|at|inside)\s+(?:my\s+)?(.+))?",
            text
        )
        if file_match:
            filename = file_match.group(1).strip()
            location = file_match.group(2).strip() if file_match.group(2) else "desktop"
            filepath = self._resolve_location(location, filename)
            return {
                "action_type": "create_file",
                "description": f"create '{filename}' in {location}",
                "filename": filepath,
                "content": "",
                "is_dangerous": False
            }

        # ── Create subfolder inside existing folder ───────────
        subfolder_match = re.search(
            r"(?:create|make)\s+(?:a\s+)?sub.?folder\s+"
            r"(?:called|named|as)?\s*['\"]?([^\s'\"]+)['\"]?"
            r"(?:\s+(?:in|inside|within|under)\s+(.+))?",
            text
        )
        if subfolder_match:
            subfoldername = subfolder_match.group(1).strip()
            parent        = subfolder_match.group(2).strip() if subfolder_match.group(2) else ""

            # Resolve parent folder — check desktop first
            if parent:
                desktop = self._get_desktop_path()
                parent_path = os.path.join(desktop, parent)
                if not os.path.isdir(parent_path):
                    # Try as absolute path
                    parent_path = parent if os.path.isdir(parent) else desktop
            elif self.last_action_path and os.path.isdir(self.last_action_path):
                parent_path = self.last_action_path
            else:
                parent_path = self._get_desktop_path()

            folderpath = os.path.join(parent_path, subfoldername)
            return {
                "action_type": "create_folder",
                "description": f"create subfolder '{subfoldername}' inside '{os.path.basename(parent_path)}'",
                "filename": folderpath,
                "is_dangerous": False
            }
        folder_match = re.search(
            r"(?:create|make|new)\s+(?:a\s+)?folder\s+"
            r"(?:called|named|as|named as)\s+"
            r"['\"]?([^\s'\"]+)['\"]?"
            r"(?:\s+(?:in|on|at|inside)\s+(?:my\s+)?(.+))?",
            text
        )
        if folder_match:
            foldername = folder_match.group(1).strip()
            location   = folder_match.group(2).strip() if folder_match.group(2) else "desktop"
            folderpath = self._resolve_location(location, foldername)
            return {
                "action_type": "create_folder",
                "description": f"create folder '{foldername}'",
                "filename": folderpath,
                "is_dangerous": False
            }

        # ── Create unnamed folder ─────────────────────────────
        unnamed_folder = re.search(
            r"(?:create|make)\s+(?:a\s+)?(?:new\s+)?folder"
            r"(?:\s+(?:in|on|at)\s+(?:my\s+)?(.+))?$",
            text
        )
        if unnamed_folder:
            location   = unnamed_folder.group(1).strip() if unnamed_folder.group(1) else "desktop"
            folderpath = self._resolve_location(location, "New Folder")
            return {
                "action_type": "create_folder",
                "description": "create a new folder",
                "filename": folderpath,
                "is_dangerous": False
            }

        # ── Play specific song / music ────────────────────────
        song_match = re.search(
            r"(?:play|stream|listen to|put on)\s+(.+?)(?:\s+(?:on|from|via|using)\s+\w+)?$",
            text
        )
        if song_match:
            query = song_match.group(1).strip()
            # Remove filler words
            for filler in ["me a song", "some music", "music", "something", "a song"]:
                if query == filler:
                    query = ""
                    break
            return {
                "action_type": "play_music",
                "description": f"play {query or 'music'}",
                "search_query": query or "popular music",
                "is_dangerous": False
            }

        # ── Open app ──────────────────────────────────────────
        open_match = re.search(r"(?:open|launch|start)\s+(.+)", text)
        if open_match:
            app = open_match.group(1).strip()
            # Map common app names to commands
            app_map = {
                "notepad": "notepad.exe",
                "calculator": "calc.exe",
                "explorer": "explorer.exe",
                "file explorer": "explorer.exe",
                "chrome": "chrome",
                "firefox": "firefox",
                "edge": "msedge",
                "powershell": "powershell",
                "cmd": "cmd",
                "command prompt": "cmd",
                "word": "winword",
                "excel": "excel",
                "paint": "mspaint",
                "task manager": "taskmgr",
            }
            cmd = app_map.get(app, app)
            return {
                "action_type": "open_app",
                "description": f"open {app}",
                "app_name": app,
                "command": f'start "" "{cmd}"',
                "is_dangerous": False
            }

        # ── Search web ────────────────────────────────────────
        search_match = re.search(r"(?:search for|search|look up|google)\s+(.+)", text)
        if search_match:
            query = search_match.group(1).strip()
            return {
                "action_type": "search_web",
                "description": f"search for '{query}'",
                "search_query": query,
                "is_dangerous": False
            }

        return None  # No pattern matched — fall through to AI

    def _resolve_location(self, location: str, filename: str) -> str:
        """Resolve a natural language location to a real path."""
        location = location.lower().strip()
        home = os.path.expanduser("~")

        location_map = {
            "desktop":   self._get_desktop_path(),
            "documents": os.path.join(home, "Documents"),
            "downloads": os.path.join(home, "Downloads"),
            "pictures":  os.path.join(home, "Pictures"),
            "music":     os.path.join(home, "Music"),
            "videos":    os.path.join(home, "Videos"),
            "onedrive":  os.path.join(home, "OneDrive"),
        }

        # Fuzzy match location name
        best = difflib.get_close_matches(location, location_map.keys(), n=1, cutoff=0.6)
        folder = location_map.get(best[0] if best else "desktop", self._get_desktop_path())

        return os.path.join(folder, filename)

    def _parse_key_sequence(self, raw_keys: str) -> list[str]:
        candidate = (raw_keys or "").strip().lower()
        if not candidate:
            return []

        candidate = candidate.replace(" plus ", "+")
        candidate = candidate.replace(" then ", "+")
        candidate = candidate.replace("-", "+")

        parts = [normalize_key_token(part) for part in re.split(r"\s*\+\s*|\s+", candidate) if part.strip()]
        parts = [part for part in parts if part]
        if not parts:
            return []

        supported_tokens = {
            "ctrl", "alt", "shift", "win", "enter", "tab", "space", "esc", "delete",
            "backspace", "left", "right", "up", "down", "home", "end",
            "pageup", "pagedown", "insert",
        }
        supported_tokens.update({f"f{idx}" for idx in range(1, 13)})
        supported_tokens.update({chr(code) for code in range(ord("a"), ord("z") + 1)})
        supported_tokens.update({str(num) for num in range(10)})

        if not all(part in supported_tokens for part in parts):
            return []

        return parts

    def _ai_plan(self, user_input: str) -> Optional[dict]:
        """AI JSON planner — fallback when pattern matching fails."""
        system = platform.system()

        # Inject context about last action so follow-up commands work
        context = ""
        if self.last_action_path:
            context = f'\nLast action path: "{self.last_action_path}" — use this if the user refers to "it", "that folder", "that file", or "the one I just created".\n'

        plan_prompt = f"""The user wants IRIS to take a real action on their computer.
System: {system}
{context}
User request: "{user_input}"

Respond ONLY with valid JSON in this exact format:
{{
  "action_type": "install_package | manage_package | run_command | create_file | create_folder | open_app | search_web | write_to_file | type_text | type_in_window | press_hotkey | press_hotkey_in_window | click_at | click_window | focus_window | window_state | active_window | list_windows | unsupported",
  "description": "what will happen in plain English",
  "command": "exact shell command if needed",
  "filename": "full file path if creating a file",
  "content": "",
  "app_name": "app name if opening",
  "package_operation": "",
  "package_name": "",
  "search_query": "query if searching",
  "url": "",
  "text_to_type": "",
  "keys": [],
  "x": 0,
  "y": 0,
  "button": "left",
  "clicks": 1,
  "window_title": "",
  "window_state": "",
  "is_dangerous": false
}}

Rules:
- Windows paths use backslashes
- For installs use winget (apps) or pip (python packages)
- Use manage_package for winget-backed install, uninstall, upgrade, or installed-app listing
- is_dangerous only true for delete/format/uninstall
- Use type_text for typing into the currently focused app
- Use type_in_window for typing into a specific named window
- Use press_hotkey for keyboard shortcuts and single key presses
- Use press_hotkey_in_window for keyboard shortcuts targeted at a specific named window
- Use click_at only when the request explicitly provides coordinates
- Use click_window when the user wants to click inside a named window
- Use focus_window when the user wants a specific window brought to the front
- Use window_state when the user wants to minimize, maximize, restore, or close a named window
- Use active_window to report the currently focused desktop window
- Use list_windows to report visible titled windows
- For rename: use command like: ren "full\\path\\oldname" "newname"
- Return unsupported only if truly impossible to determine

Respond with ONLY the JSON object. No markdown, no explanation."""

        response = self.brain._call_api(
            getattr(Config, "PRIMARY_BRAIN", "groq"), plan_prompt,
            use_persona=False, use_memory=False
        )

        if not response:
            return None

        try:
            clean = response.strip()
            # Strip markdown code fences if present
            clean = re.sub(r"```(?:json)?", "", clean).strip()
            return json.loads(clean)
        except Exception:
            return None

        # SAFE — just ask
        return permission_msg

    def _build_permission_request(self, plan: dict) -> str:
        """Direct, no-nonsense permission request."""
        description = plan.get("description", "perform this action")
        command     = plan.get("command", "")
        is_dangerous = plan.get("is_dangerous", False)
        approval_level = self._approval_level(plan, self.pending_verdict or WARNING)

        msg = f"I'll {description}."
        if command:
            msg += f" Command: {command}."
        if approval_level == 1:
            msg += " This is a voice-confirmed file change."
        elif approval_level >= 2:
            msg += " This needs explicit approval."
        if is_dangerous:
            msg += " ⚠ This is destructive and can't be undone."
        if self._can_remember_approval(plan, self.pending_verdict or WARNING, self.pending_security_reason):
            msg += " Say 'always for this session' if you want me to remember this exact action."
        msg += " Go ahead?"
        return msg

    # ─────────────────────────────────────────────────────────────
    # EXECUTE: Run the approved action
    # ─────────────────────────────────────────────────────────────

    def waiting_for_plan_choice(self) -> bool:
        return self.pending_plans is not None

    def handle_plan_choice(self, user_input: str) -> str:
        """User is choosing between Plan A, B, C."""
        plans = self.pending_plans
        if not plans:
            return None

        # Cancel
        if self._matches_any_phrase(user_input, ["cancel", "never mind", "forget it", "no"]):
            self.pending_plans = None
            return "Cancelled."

        selected = self.improv.select_plan(plans, user_input)

        if not selected:
            a = plans.get("plan_a", {}).get("description", "?")
            b = plans.get("plan_b", {}).get("description", "?")
            c = plans.get("plan_c", {}).get("description", "?")
            return f"Which one — A: {a}, B: {b}, or C: {c}?"

        # Plan C needs explicit permission
        if selected.get("requires_permission"):
            self.pending_action  = selected
            self.pending_verdict = WARNING
            self.pending_action_source = self.current_input_source
            self.pending_plans   = None
            desc = selected.get("description", "this action")
            cmd  = selected.get("command", "")
            msg  = f"Plan C: {desc}."
            if cmd:
                msg += f" Command: {cmd}."
            msg += " This one has real side effects — go ahead?"
            return msg

        # Plans A and B — just execute
        self.pending_plans   = None
        self.pending_action  = selected
        self.pending_verdict = SAFE
        self.pending_action_source = self.current_input_source
        return self._execute_pending()

    def _execute_pending(self) -> str:
        """
        Execute with verification + improv fallback on failure.

        Flow:
          1. Execute
          2. Verify it worked
          3. If failed → generate Plan A/B/C via improv engine
          4. Present options to user
        """
        plan    = self.pending_action
        verdict = self.pending_verdict
        self.pending_action  = None
        self.pending_verdict = None
        self.pending_action_source = "unknown"
        self.pending_security_reason = ""
        self._clarification_options = []

        if not plan:
            return "There isn't anything pending right now."

        action_type = plan.get("action_type")
        self._log(f"EXECUTE [{verdict}]: {plan.get('command') or plan.get('description','?')}")

        # ── Execute and verify ────────────────────────────────
        result, success = self._execute_with_verify(plan)

        if success:
            self._record_executed_action(plan, verdict)
            if self._should_count_for_presence_check(plan, verdict):
                presence_prompt = self._note_auto_action()
                if presence_prompt:
                    return f"{result} {presence_prompt}"
            return result

        # ── Failed — use improv engine ────────────────────────
        self._log(f"FAILED: {result} — generating improv plans")
        original_request = plan.get("description", "that action")
        plans = self.improv.generate_plans(original_request, plan, result)

        if not plans:
            return result  # Improv also failed to generate plans

        # Store plans for user to choose
        self.pending_plans = plans
        spoken = self.improv.format_spoken_options(plans)
        return spoken

    def _command_requires_shell(self, command: str) -> bool:
        text = str(command or "").strip()
        if not text:
            return False

        if any(token in text for token in ["&&", "||", "|", ">", "<", "%", "^"]):
            return True

        try:
            first = shlex.split(text, posix=False)[0].strip().lower()
        except Exception:
            first = text.split()[0].strip().lower()

        return first in self.WINDOWS_SHELL_BUILTINS

    def _split_command_args(self, command: str) -> list[str]:
        text = str(command or "").strip()
        if not text:
            return []
        try:
            return [arg for arg in shlex.split(text, posix=False) if arg]
        except ValueError:
            return [text]

    def _run_subprocess_command(
        self,
        command: str,
        timeout: int = 120,
        force_shell: bool | None = None,
    ):
        use_shell = self._command_requires_shell(command) if force_shell is None else bool(force_shell)
        args = command if use_shell else self._split_command_args(command)
        return subprocess.run(
            args,
            shell=use_shell,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def _spawn_subprocess_command(self, command: str, force_shell: bool | None = None):
        use_shell = self._command_requires_shell(command) if force_shell is None else bool(force_shell)
        args = command if use_shell else self._split_command_args(command)
        return subprocess.Popen(args, shell=use_shell)

    def _build_package_args(self, operation: str, package_name: str = "") -> list[str]:
        op = (operation or "").strip().lower()
        pkg = str(package_name or "").strip()
        if op == "list":
            return ["winget", "list"]
        if op == "install" and pkg:
            return ["winget", "install", "--name", pkg, "--accept-package-agreements", "--accept-source-agreements"]
        if op == "uninstall" and pkg:
            return ["winget", "uninstall", "--name", pkg]
        if op == "upgrade" and pkg:
            return ["winget", "upgrade", "--name", pkg, "--accept-package-agreements", "--accept-source-agreements"]
        return []

    def _execute_with_verify(self, plan: dict) -> tuple:
        """
        Execute an action and verify it actually worked.
        Returns (message, success_bool)
        """
        action_type = plan.get("action_type")

        try:
            if action_type == "install_package":
                result = self._run_command(plan)
                success = "didn't work" not in result.lower() and "error" not in result.lower()

            elif action_type == "manage_package":
                result, success = self._manage_package(plan)

            elif action_type == "run_command":
                result = self._run_command(plan)
                success = "didn't work" not in result.lower() and "error" not in result.lower()

            elif action_type == "create_file":
                result  = self._create_file(plan)
                success = self.last_action_path is not None and os.path.isfile(self.last_action_path)

            elif action_type == "create_folder":
                result  = self._create_folder(plan)
                success = self.last_action_path is not None and os.path.isdir(self.last_action_path)

            elif action_type == "play_music":
                result  = self._play_music(plan)
                success = result == "Done."

            elif action_type == "open_app":
                result  = self._open_app(plan)
                # Can't easily verify app opened — assume success if no exception
                success = result == "Done."

            elif action_type == "search_web":
                result  = self._search_web(plan)
                success = result == "Done."

            elif action_type == "write_to_file":
                result  = self._write_to_file(plan)
                success = "Done." in result

            elif action_type == "type_text":
                result = self._type_text(plan)
                success = result == "Done."

            elif action_type == "type_in_window":
                result = self._type_in_window(plan)
                success = result == "Done."

            elif action_type == "press_hotkey":
                result = self._press_hotkey(plan)
                success = result == "Done."

            elif action_type == "press_hotkey_in_window":
                result = self._press_hotkey_in_window(plan)
                success = result == "Done."

            elif action_type == "click_at":
                result = self._click_at(plan)
                success = result == "Done."

            elif action_type == "click_window":
                result = self._click_window(plan)
                success = result == "Done."

            elif action_type == "focus_window":
                result = self._focus_window(plan)
                success = result.startswith("Focused ")

            elif action_type == "window_state":
                result = self._window_state(plan)
                success = any(
                    result.startswith(prefix)
                    for prefix in ("Minimized ", "Maximized ", "Restored ", "Closed ")
                )

            elif action_type == "active_window":
                result = self._active_window(plan)
                success = bool(result)

            elif action_type == "list_windows":
                result = self._list_windows(plan)
                success = bool(result)

            else:
                return "I don't know how to execute that type of action.", False

            return result, success

        except Exception as e:
            self._log(f"EXCEPTION: {action_type} — {e}")
            return f"That didn't work: {str(e)[:100]}", False

    def _ai_retry_plan(self, original_plan: dict, error_msg: str) -> dict:
        """
        Ask the AI to generate an alternative approach when the first attempt fails.
        """
        prompt = f"""An action failed on Windows. Generate an alternative approach.

Original action: {json.dumps(original_plan, indent=2)}
Error/result: {error_msg}

Generate a different plan to achieve the same goal.
Use a completely different method — if mkdir failed, try os.makedirs via python; 
if start command failed, try webbrowser; if one path failed, try a different path.

Respond ONLY with valid JSON in this exact format:
{{
  "action_type": "install_package | manage_package | run_command | create_file | create_folder | open_app | search_web | write_to_file | type_text | type_in_window | press_hotkey | press_hotkey_in_window | click_at | click_window | focus_window | window_state | active_window | list_windows",
  "description": "alternative approach in plain English",
  "command": "alternative shell command if needed",
  "filename": "full file path if needed",
  "content": "",
  "app_name": "app name if opening",
  "package_operation": "",
  "package_name": "",
  "search_query": "",
  "url": "direct URL if opening browser",
  "text_to_type": "",
  "keys": [],
  "x": 0,
  "y": 0,
  "button": "left",
  "clicks": 1,
  "window_title": "",
  "window_state": "",
  "is_dangerous": false
}}

Respond with ONLY the JSON. No explanation."""

        response = self.brain._call_api(
            getattr(Config, "PRIMARY_BRAIN", "groq"), prompt,
            use_persona=False, use_memory=False
        )

        if not response:
            return None

        try:
            clean = response.strip().replace("```json", "").replace("```", "").strip()
            return json.loads(clean)
        except Exception:
            return None

    def _run_command(self, plan: dict) -> str:
        """Run a shell command with cognitive thinking."""
        command = plan.get("command", "")
        if not command:
            return "No command to run."

        self._log(f"RUN: {command}")
        try:
            result = self._run_subprocess_command(str(command), timeout=120)
        except subprocess.TimeoutExpired:
            self._log(f"FAILED: {command} — timed out")
            return "That command timed out."
        except Exception as exc:
            self._log(f"FAILED: {command} — {exc}")
            return f"That didn't work. {exc}"

        if result.returncode == 0:
            output = result.stdout.strip()
            msg = "Done."
            if output and len(output) < 300:
                msg += f" {output}"
            self._log(f"SUCCESS: {command}")
            return msg
        else:
            err = result.stderr.strip()
            self._log(f"FAILED: {command} — {err}")
            # Cognitive thinking — try to suggest a fix
            fix = self._think_of_fix(command, err)
            return f"That didn't work. {fix}"

    def _manage_package(self, plan: dict) -> tuple[str, bool]:
        operation = str(plan.get("package_operation", "") or "").strip().lower()
        package_name = str(plan.get("package_name", "") or "").strip()
        command = str(plan.get("command", "") or "").strip() or self._build_package_command(operation, package_name)
        args = self._build_package_args(operation, package_name)
        if not command and not args:
            return "I couldn't determine the package command to run.", False

        try:
            if args:
                result = subprocess.run(
                    args,
                    shell=False,
                    capture_output=True,
                    text=True,
                    timeout=240,
                )
            else:
                result = self._run_subprocess_command(command, timeout=240)
        except Exception as exc:
            return f"Package management didn't work: {exc}", False

        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()
        output = stdout or stderr
        self._log(f"PACKAGE {operation.upper()}: {package_name or '(all)'} :: rc={result.returncode}")

        if result.returncode != 0:
            detail = output[:500] if output else "winget returned a non-zero exit code."
            return f"Package management didn't work: {detail}", False

        if operation == "list":
            return self._summarize_package_list(output), True

        if operation == "install":
            return f"Installed '{package_name}'.", True

        if operation == "uninstall":
            return f"Uninstalled '{package_name}'.", True

        if operation == "upgrade":
            return f"Updated '{package_name}'.", True

        return (output[:500] if output else "Done."), True

    def _summarize_package_list(self, output: str) -> str:
        lines = [line.rstrip() for line in (output or "").splitlines() if line.strip()]
        if not lines:
            return "I couldn't find any installed apps from winget."

        filtered = []
        for line in lines:
            stripped = line.strip()
            lowered = stripped.lower()
            if lowered.startswith("name ") or lowered.startswith("name\t"):
                continue
            if set(stripped) <= {"-", " ", "\t"}:
                continue
            filtered.append(stripped)

        preview = filtered[:10] if filtered else lines[:10]
        if not preview:
            return "I couldn't find any installed apps from winget."

        body = "\n".join(f"- {line}" for line in preview)
        suffix = ""
        if filtered and len(filtered) > len(preview):
            suffix = f"\n...and {len(filtered) - len(preview)} more."
        return f"Installed apps:\n{body}{suffix}"

    def _think_of_fix(self, command: str, error: str) -> str:
        """Cognitively suggest a fix when a command fails."""
        prompt = f"""A command failed on Windows. Think like a smart IT assistant.

Command: {command}
Error: {error[:300]}

In one sentence, what's the most likely cause and fix?
Be specific and practical. No preamble."""

        response = self.brain._call_api(
            "groq", prompt,
            use_persona=False, use_memory=False
        )
        return response or f"Error: {error[:150]}"

    def _get_desktop_path(self) -> str:
        """Get the correct Desktop path — checks OneDrive first (most common on Win10/11)."""
        home = os.path.expanduser("~")

        # OneDrive Desktop first — most common on Windows 10/11
        onedrive = os.path.join(home, "OneDrive", "Desktop")
        if os.path.exists(onedrive):
            return onedrive

        # Standard desktop
        standard = os.path.join(home, "Desktop")
        if os.path.exists(standard):
            return standard

        return home

    def _create_file(self, plan: dict) -> str:
        """Create a file — cognitively corrects extension, auto-renames if exists."""
        filename = plan.get("filename", "iris_output.txt")
        content  = plan.get("content", "")
        context  = plan.get("description", "")

        # ── Step 1: Auto-correct path typos ──────────────────
        filename, path_note = self.autocorrect.correct_path(filename)

        # ── Step 2: Cognitively correct the extension ─────────
        filename, ext_note, needs_clarification, options = \
            self.autocorrect.correct_extension(filename, context)

        if needs_clarification:
            # Store plan so we can resume after user answers
            self.pending_action = plan
            self.pending_action["filename"] = filename
            self.pending_verdict = SAFE
            self._clarification_options = options
            opts_str = " or ".join(options)
            return (
                f"Did you mean '{opts_str}'? "
                f"Say the extension you want and I'll create it."
            )

        # ── Step 3: Resolve correct folder path ──────────────
        if "desktop" in filename.lower():
            bare_name = os.path.basename(filename)
            filepath  = os.path.join(self._get_desktop_path(), bare_name)
        elif not os.path.dirname(filename):
            filepath  = os.path.join(self._get_desktop_path(), filename)
        else:
            filepath  = filename

        # ── Step 4: Cognitive rename if file already exists ───
        filepath, rename_msg = self._resolve_filename(filepath)

        os.makedirs(os.path.dirname(filepath), exist_ok=True)

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

        self._log(f"CREATED FILE: {filepath}")
        self.last_action_path = filepath   # remember for follow-up commands
        self.follow_up = {"action": "open_file", "path": filepath}

        # Build response noting any corrections made
        notes = []
        if path_note:   notes.append(path_note)
        if ext_note:    notes.append(ext_note)
        if rename_msg:  notes.append(rename_msg)

        prefix = " ".join(notes) + " " if notes else ""
        return f"{prefix}Done. '{os.path.basename(filepath)}' created at {filepath}. Want me to open it?"

    def _create_folder(self, plan: dict) -> str:
        """Create a folder using os.makedirs — reliable across all Windows paths."""
        filename = plan.get("filename", "")
        command  = plan.get("command", "")

        # Resolve the folder path
        if filename:
            folder = filename
        elif command:
            # Extract path from mkdir command
            match = re.search(r'mkdir\s+"?([^"]+)"?', command, re.IGNORECASE)
            folder = match.group(1).strip() if match else None
        else:
            folder = None

        if not folder:
            return "I couldn't determine where to create the folder."

        # Fix desktop path — handle OneDrive
        if "desktop" in folder.lower():
            folder = os.path.join(self._get_desktop_path(), os.path.basename(folder))

        try:
            os.makedirs(folder, exist_ok=True)
            # Verify it actually exists
            if os.path.isdir(folder):
                self._log(f"CREATED FOLDER: {folder}")
                self.last_action_path = folder
                return "Done."
            else:
                return "Something went wrong — folder wasn't created."
        except Exception as e:
            self._log(f"ERROR creating folder: {e}")
            return f"Couldn't create the folder: {str(e)[:100]}"

    def _play_music(self, plan: dict) -> str:
        """Play music using browser automation."""
        query = plan.get("search_query", "") or plan.get("description", "music")
        query = query.replace("play ", "").replace("music", "").strip() or "popular songs"
        return self.browser.play_music(query)

    def _open_app(self, plan: dict) -> str:
        """Open an application or URL with minimal shell usage."""
        app     = (plan.get("app_name") or "").strip()
        command = (plan.get("command") or "").strip()
        url     = (plan.get("url") or "").strip()

        # Direct URL — open in browser
        if url and url.startswith("http"):
            import webbrowser
            webbrowser.open(url)
            self._log(f"OPENED URL: {url}")
            return "Done."

        # Known app name map → exact executable or URL
        app_map = {
            "notepad":          "notepad.exe",
            "calculator":       "calc.exe",
            "explorer":         "explorer.exe",
            "file explorer":    "explorer.exe",
            "chrome":           "chrome",
            "google chrome":    "chrome",
            "firefox":          "firefox",
            "edge":             "msedge",
            "microsoft edge":   "msedge",
            "powershell":       "powershell",
            "cmd":              "cmd",
            "command prompt":   "cmd",
            "word":             "winword",
            "excel":            "excel",
            "paint":            "mspaint",
            "task manager":     "taskmgr",
            "spotify":          "https://open.spotify.com",
            "youtube":          "https://www.youtube.com",
            "netflix":          "https://www.netflix.com",
            "whatsapp":         "https://web.whatsapp.com",
            "gmail":            "https://mail.google.com",
        }

        target = app_map.get(app.lower(), app)

        # If it's a URL (from app_map or direct) — use browser automation
        if target and target.startswith("http"):
            return self.browser.open_url(target)

        # Shell command provided directly
        if command:
            try:
                self._spawn_subprocess_command(command)
                self._log(f"OPENED: {command}")
                return "Done."
            except Exception as e:
                return f"Couldn't open that: {e}"

        # Launch known executable or file target directly when possible
        if target:
            try:
                if self.is_windows and os.path.exists(target):
                    os.startfile(target)  # type: ignore[attr-defined]
                else:
                    subprocess.Popen([target], shell=False)
                self._log(f"OPENED: {target}")
                return "Done."
            except Exception as e:
                return f"Couldn't open {app}: {e}"

        return "I'm not sure what to open."

    def _search_web(self, plan: dict) -> str:
        """Open browser with a search."""
        import webbrowser
        query = plan.get("search_query", "")
        if not query:
            return "No search query provided."
        url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
        webbrowser.open(url)
        self._log(f"SEARCHED: {query}")
        return "Done."

    def _write_to_file(self, plan: dict) -> str:
        """Append or write content to an existing file."""
        filename = plan.get("filename", "")
        content  = plan.get("content", "")
        if not filename:
            return "No filename specified."
        with open(filename, "a", encoding="utf-8") as f:
            f.write(content + "\n")
        self._log(f"WROTE TO: {filename}")
        self.last_action_path = filename
        return "Done."

    def _type_text(self, plan: dict) -> str:
        text_to_type = str(plan.get("text_to_type", "") or "")
        try:
            self.desktop.type_text(text_to_type)
        except DesktopControlError as exc:
            return f"Desktop typing didn't work: {exc}"
        self._log(f"TYPED TEXT: {text_to_type[:120]}")
        return "Done."

    def _type_in_window(self, plan: dict) -> str:
        text_to_type = str(plan.get("text_to_type", "") or "")
        window_title = str(plan.get("window_title", "") or "")
        try:
            self.desktop.type_in_window(window_title, text_to_type)
        except DesktopControlError as exc:
            return f"Window typing didn't work: {exc}"
        self._log(f"TYPED IN WINDOW: {window_title} :: {text_to_type[:120]}")
        return "Done."

    def _press_hotkey(self, plan: dict) -> str:
        keys = plan.get("keys", []) or []
        try:
            self.desktop.press_hotkey(keys)
        except DesktopControlError as exc:
            return f"Keyboard shortcut didn't work: {exc}"
        self._log(f"PRESSED HOTKEY: {' + '.join(keys)}")
        return "Done."

    def _press_hotkey_in_window(self, plan: dict) -> str:
        keys = plan.get("keys", []) or []
        window_title = str(plan.get("window_title", "") or "")
        try:
            self.desktop.press_hotkey_in_window(window_title, keys)
        except DesktopControlError as exc:
            return f"Window shortcut didn't work: {exc}"
        self._log(f"PRESSED HOTKEY IN WINDOW: {window_title} :: {' + '.join(keys)}")
        return "Done."

    def _click_at(self, plan: dict) -> str:
        x = plan.get("x", 0)
        y = plan.get("y", 0)
        button = plan.get("button", "left")
        clicks = plan.get("clicks", 1)
        try:
            self.desktop.click_at(x=x, y=y, button=button, clicks=clicks)
        except DesktopControlError as exc:
            return f"Desktop click didn't work: {exc}"
        self._log(f"CLICKED: {button} at {x},{y} ({clicks}x)")
        return "Done."

    def _click_window(self, plan: dict) -> str:
        window_title = str(plan.get("window_title", "") or "")
        x = plan.get("x")
        y = plan.get("y")
        button = plan.get("button", "left")
        clicks = plan.get("clicks", 1)
        try:
            self.desktop.click_window(window_title, x=x, y=y, button=button, clicks=clicks)
        except DesktopControlError as exc:
            return f"Window click didn't work: {exc}"
        self._log(
            f"CLICKED WINDOW: {window_title} ({button}, {clicks}x, {x if x is not None else 'center'},{y if y is not None else 'center'})"
        )
        return "Done."

    def _focus_window(self, plan: dict) -> str:
        window_title = str(plan.get("window_title", "") or "")
        try:
            result = self.desktop.focus_window(window_title)
        except DesktopControlError as exc:
            return f"Window focus didn't work: {exc}"
        self._log(f"FOCUSED WINDOW: {window_title}")
        return result.message

    def _window_state(self, plan: dict) -> str:
        window_title = str(plan.get("window_title", "") or "")
        window_state = str(plan.get("window_state", "") or "")
        try:
            result = self.desktop.set_window_state(window_title, window_state)
        except DesktopControlError as exc:
            return f"Window control didn't work: {exc}"
        self._log(f"WINDOW STATE: {window_state} :: {window_title}")
        return result.message

    def _active_window(self, plan: dict) -> str:
        try:
            return self.desktop.describe_active_window()
        except DesktopControlError as exc:
            return f"Desktop inspection didn't work: {exc}"

    def _list_windows(self, plan: dict) -> str:
        try:
            windows = self.desktop.list_windows(limit=8)
        except DesktopControlError as exc:
            return f"Desktop inspection didn't work: {exc}"

        if not windows:
            return "I couldn't find any visible titled windows."

        entries = []
        for item in windows:
            prefix = "* " if item.active else "- "
            entries.append(f"{prefix}{item.title} ({item.width}x{item.height} at {item.left},{item.top})")
        return "Visible windows:\n" + "\n".join(entries)

    # ─────────────────────────────────────────────────────────────
    # LOGGING
    # ─────────────────────────────────────────────────────────────

    def _log(self, message: str):
        """Log every action to file for transparency."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not getattr(self, "log_file", None):
            self.log_file = "iris_actions.log"
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {message}\n")

    def _audit(self, verdict: str, plan: dict | None, source: str | None = None) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logger = self._get_audit_logger()
        action_type = (plan or {}).get("action_type", "unknown")
        command = (plan or {}).get("command") or (plan or {}).get("description", "?")
        normalized_source = (source or "unknown").strip().lower() or "unknown"
        logger.info(f"[{timestamp}] {verdict} | {action_type} | {command} | SOURCE({normalized_source})")

    def _audit_pending(self, verdict: str, source: str | None = None) -> None:
        self._audit(
            verdict,
            self.pending_action,
            source=source or self.pending_action_source or self.current_input_source,
        )

    def _get_audit_logger(self):
        if not getattr(self, "audit_file", None):
            self.audit_file = "iris_audit.log"

        if self._audit_logger and self._audit_logger_path == self.audit_file:
            return self._audit_logger

        logger = logging.getLogger(f"iris.audit.{id(self)}")
        logger.setLevel(logging.INFO)
        logger.propagate = False
        logger.handlers.clear()

        handler = RotatingFileHandler(
            self.audit_file,
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)

        self._audit_logger = logger
        self._audit_logger_path = self.audit_file
        return logger

    def _note_auto_action(self) -> str | None:
        now = datetime.now()
        self.auto_action_timestamps.append(now)
        cutoff = now - timedelta(seconds=60)
        self.auto_action_timestamps = [ts for ts in self.auto_action_timestamps if ts >= cutoff]

        if len(self.auto_action_timestamps) >= 4 and not self.follow_up:
            self.pending_presence_check = True
            self._audit(
                "PRESENCE_CHECK_REQUESTED",
                {"action_type": "presence_check", "description": "rapid auto sequence"},
                source=self.current_input_source,
            )
            return "Still with you? Say go ahead or cancel."

        return None

    def _should_count_for_presence_check(self, plan: dict, verdict: str) -> bool:
        if verdict != SAFE:
            return False
        action_type = plan.get("action_type", "")
        return action_type not in {"active_window", "list_windows"}

    def _record_executed_action(self, plan: dict, verdict: str) -> None:
        record = {
            "timestamp": datetime.now(),
            "action_type": plan.get("action_type", ""),
            "path": self._resolve_plan_path(plan),
            "sensitive_path": self._plan_touches_sensitive_path(plan),
            "network_or_browser": self._plan_is_network_or_browser(plan),
            "verdict": verdict,
        }
        self.recent_action_history.append(record)
        self.recent_action_history = self.recent_action_history[-6:]

    def _check_action_chain(self, plan: dict) -> Optional[str]:
        recent = self.recent_action_history[-3:]
        if not recent:
            return None

        latest = recent[-1]
        current_is_network = self._plan_is_network_or_browser(plan)

        if (
            latest.get("action_type") in {"create_file", "write_to_file"}
            and latest.get("path")
            and current_is_network
            and (
                self._plan_references_path(plan, latest["path"])
                or latest.get("sensitive_path")
            )
        ):
            return (
                "This next step follows a file write with a browser or network-capable action "
                "that references the same path. Confirm before IRIS continues."
            )

        if current_is_network and any(item.get("sensitive_path") for item in recent):
            return (
                "A recent action touched a potentially sensitive path, and this next step uses "
                "a browser or network-capable action. Confirm before IRIS continues."
            )

        return None

    def _resolve_plan_path(self, plan: dict) -> str:
        action_type = plan.get("action_type", "")
        if action_type in {"create_file", "create_folder", "write_to_file"} and self.last_action_path:
            return str(self.last_action_path)
        return str(plan.get("filename", "") or "")

    def _plan_touches_sensitive_path(self, plan: dict) -> bool:
        values = [
            str(plan.get("filename", "") or ""),
            str(plan.get("command", "") or ""),
            str(plan.get("description", "") or ""),
            str(plan.get("text_to_type", "") or ""),
        ]
        keywords = getattr(self.security, "SENSITIVE_PATH_KEYWORDS", [])
        lowered_values = " ".join(values).lower()
        return any(keyword in lowered_values for keyword in keywords)

    def _plan_is_network_or_browser(self, plan: dict) -> bool:
        action_type = plan.get("action_type", "")
        if action_type == "search_web":
            return True

        url = str(plan.get("url", "") or "")
        if url.startswith("http://") or url.startswith("https://"):
            return True

        app_name = str(plan.get("app_name", "") or "").lower()
        if app_name in {"chrome", "google chrome", "firefox", "edge", "microsoft edge"}:
            return True

        command = str(plan.get("command", "") or "").lower()
        network_tokens = [
            "http://", "https://", "curl ", "wget ", "invoke-webrequest",
            "start https", "start http",
        ]
        return any(token in command for token in network_tokens)

    def _plan_references_path(self, plan: dict, path: str) -> bool:
        target = str(path or "").lower()
        if not target:
            return False

        basename = os.path.basename(target)
        candidate_values = [
            str(plan.get("filename", "") or ""),
            str(plan.get("command", "") or ""),
            str(plan.get("search_query", "") or ""),
            str(plan.get("description", "") or ""),
            str(plan.get("url", "") or ""),
            str(plan.get("app_name", "") or ""),
        ]
        lowered = " ".join(candidate_values).lower()
        return target in lowered or (basename and basename in lowered)
