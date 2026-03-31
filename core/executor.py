"""
IRIS Action Executor
=======================
When you ask IRIS to DO something — install, create, delete, run —
it plans the action, tells you exactly what it's about to do,
and waits for your voice/text permission before executing.

PERMISSION GATE FLOW:
  You: "Iris, install Python"
  IRIS: "I'll run: winget install Python.Python.3 — shall I go ahead?"
  You: "yes" / "go ahead" / "do it"
  IRIS: [runs the command, reports result]
  IRIS: "Done. Python installed. Want me to verify it worked?"

SUPPORTED ACTION TYPES:
  - install_package  : winget / pip / npm install
  - run_command      : any shell command
  - create_file      : create a file with content
  - create_folder    : make a directory
  - open_app         : launch an application
  - search_web       : open browser search
  - write_to_file    : append/write content to existing file

SAFETY:
  - IRIS ALWAYS announces what it will do before doing it
  - Destructive actions (delete, format, rm -rf) require DOUBLE confirmation
  - Every action and result is logged to iris_actions.log
"""

import subprocess
import os
import platform
import re
import json
import difflib
try:
    import send2trash as _send2trash
    _HAS_SEND2TRASH = True
except ImportError:
    _HAS_SEND2TRASH = False
from datetime import datetime
from typing import Optional, Tuple

from rich.progress import Progress, SpinnerColumn, TextColumn

from config import Config
from core.security import SecurityGuard, SAFE, WARNING, BLOCKED, NEED_ADMIN
from core.autocorrect import AutoCorrector
from core.browser import BrowserAutomation
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

# ── Phrases that are DANGEROUS (need double confirm) ───────────
DANGEROUS_PATTERNS = [
    r"del\s", r"rm\s", r"rmdir", r"format", r"delete",
    r"drop\s", r"uninstall", r"--force", r"-rf"
]


class ActionExecutor:

    def __init__(self, voice, brain):
        self.voice   = voice
        self.brain   = brain
        self.security = SecurityGuard(brain)
        self.log_file    = "iris_actions.log"
        self.is_windows  = platform.system() == "Windows"
        self.pending_action         = None
        self.pending_verdict        = None
        self.follow_up              = None
        self.autocorrect            = AutoCorrector(brain)
        self.improv                 = ImprovEngine(brain)
        self.pending_plans          = None   # stores A/B/C plans waiting for user choice
        self.last_action_path       = None
        self._clarification_options = []
        self._browser = None   # lazy — created only when needed

    @property
    def browser(self):
        """Create browser automation only when first needed."""
        if self._browser is None:
            self._browser = BrowserAutomation()
        return self._browser

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
        "find",
    ]

    def should_handle(self, user_input: str) -> bool:
        """Detect if user wants IRIS to take a real action."""
        text = user_input.lower()
        return any(trigger in text for trigger in self.ACTION_TRIGGERS)

    # ─────────────────────────────────────────────────────────────
    # PERMISSION CHECK: Are we waiting for yes/no?
    # ─────────────────────────────────────────────────────────────

    def waiting_for_permission(self) -> bool:
        return self.pending_action is not None and not self.waiting_for_clarification()

    def waiting_for_followup(self) -> bool:
        return self.follow_up is not None

    def waiting_for_clarification(self) -> bool:
        return bool(self.pending_action and self._clarification_options)

    def handle_followup_response(self, user_input: str) -> str:
        """Handle yes/no response to a post-execution follow-up question."""
        text = user_input.lower().strip()
        followup = self.follow_up
        self.follow_up = None

        if any(word in text for word in YES_WORDS):
            action = followup.get("action")
            if action == "open_file":
                path = followup.get("path", "")
                try:
                    if platform.system() == "Windows":
                        os.startfile(path)
                    else:
                        subprocess.Popen(["xdg-open", path])
                    return f"Opened '{os.path.basename(path)}'."
                except Exception as e:
                    return f"Couldn't open it: {e}"
            elif action == "open_app":
                app = followup.get("app", "")
                try:
                    subprocess.Popen(f'start "" "{app}"', shell=True)
                    return f"Opening {app}."
                except Exception as e:
                    return f"Couldn't open it: {e}"
        elif any(word in text for word in NO_WORDS):
            return "No problem."

        return None  # Unrecognised — fall through to brain

    def handle_clarification_response(self, user_input: str) -> Optional[str]:
        """Resolve a pending clarification, usually a file extension choice."""
        if not self.waiting_for_clarification():
            return None

        text = (user_input or "").lower().strip()
        if not text:
            return "Say the extension you want, or cancel."

        if any(word in text for word in NO_WORDS):
            self.pending_action = None
            self.pending_verdict = None
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
        Override is allowed for WARNING and NEED_ADMIN verdicts only.
        BLOCKED verdicts cannot be overridden — they are hard security limits.
        """
        text = user_input.lower().strip()

        # ── Admin override — only for WARNING and NEED_ADMIN, never BLOCKED ──
        if "override" in text or "force it" in text:
            if self.pending_verdict == BLOCKED:
                self._log(f"OVERRIDE DENIED (BLOCKED): {self.pending_action.get('command', '?')}")
                self.pending_action = None
                self.pending_verdict = None
                return (
                    "That action is hard-blocked for security reasons. "
                    "Override is not available for blocked commands. Cancelled."
                )
            cmd = self.pending_action.get("command") or self.pending_action.get("description", "?")
            self._log(f"ADMIN OVERRIDE [{self.pending_verdict}]: {cmd}")
            return self._execute_pending()

        # ── Yes — proceed (but not for BLOCKED) ──
        if any(word in text for word in YES_WORDS):
            if self.pending_verdict == BLOCKED:
                return "That action is blocked. Say 'cancel' to dismiss."
            return self._execute_pending()

        # ── No — cancel ──
        if any(word in text for word in NO_WORDS):
            self.pending_action  = None
            self.pending_verdict = None
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
        "search_web", "write_to_file", "play_music", "delete_trash"
    ]

    def _is_simple_task(self, plan: dict, verdict: str) -> bool:
        """
        Only actions in SIMPLE_ACTIONS auto-execute when verdict is SAFE.
        run_command and install_package always ask for permission first,
        even when the security check passes — because those actions run
        shell commands that could come from AI-generated plans.
        """
        if verdict in (BLOCKED, WARNING, NEED_ADMIN):
            return False
        action_type = plan.get("action_type", "")
        return action_type in self.SIMPLE_ACTIONS

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
        """Interpret the request, run security assessment.
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
        header = self.security.format_security_header(verdict)

        if verdict == BLOCKED:
            self._log(f"BLOCKED: {plan.get('command','?')} — {security_msg}")
            self.pending_action  = None
            self.pending_verdict = None
            return f"{header}\n{security_msg}\n\nThis action has been blocked and cannot be executed."

        # ── Simple safe task — execute with verification ─────
        if self._is_simple_task(plan, verdict):
            self._log(f"AUTO-EXECUTE: {plan.get('action_type')} — {plan.get('description','')}")
            self.pending_action  = plan
            self.pending_verdict = verdict
            return self._execute_pending()

        # ── Everything else — ask for permission ─────────────
        self.pending_action  = plan
        self.pending_verdict = verdict
        permission_msg = self._build_permission_request(plan)

        if verdict in (WARNING, NEED_ADMIN):
            return f"{header}\n{security_msg}\n\n{permission_msg}"

        return permission_msg

    def _pattern_match(self, user_input: str) -> Optional[dict]:
        """Fast pattern-based action detection for common requests.
        Handles the most frequent actions without needing AI JSON parsing.
        """
        text = user_input.lower().strip()

        # ── Create file ───────────────────────────────────────
        # Run against original user_input with IGNORECASE to preserve capitalisation.
        file_match = re.search(
            r"(?:create|make|new)\s+(?:a\s+)?file\s+(?:called|named|as|named as)?\s*['\"]?([^'\"\s][^'\"]*?)['\"]?"
            r"(?:\s+(?:in|on|at|inside)\s+(?:my\s+)?(.+))?",
            user_input,
            re.IGNORECASE,
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
            r"(?:called|named|as)?\s*['\"]?([^'\"]+)['\"]?"
            r"(?:\s+(?:in|inside|within|under)\s+(.+))?",
            user_input,
            re.IGNORECASE,
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

        # ── Create folder ─────────────────────────────────────
        # Updated regex: allows an optional location clause BEFORE the name
        # (e.g. "create a folder on my desktop named Bravo").
        # Run against original user_input with IGNORECASE to preserve capitalisation.
        folder_match = re.search(
            r"(?:create|make|new)\s+(?:a\s+)?(?:new\s+)?folder"
            r"(?:\s+(?:on|in|at)\s+(?:my\s+)?\w+)?"   # optional location before name
            r"\s+(?:called|named|as|named as)\s+"
            r"['\"]?([A-Za-z0-9 _\-\.]+?)['\"]?"
            r"(?:\s+(?:in|on|at|inside)\s+(?:my\s+)?(.+))?$",
            user_input,
            re.IGNORECASE,
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

        # ── Rename File/Folder (Context-Aware) ────────────────
        # Run against original user_input with IGNORECASE to preserve capitalisation.
        rename_match = re.search(
            r"rename\s+(?:the\s+)?(?:folder|file\s+)?(?:from\s+)?['\"]?([^'\"]+)['\"]?\s+(?:to|as)\s+['\"]?([^'\"]+)['\"]?",
            user_input,
            re.IGNORECASE,
        )
        if rename_match:
            old_name = rename_match.group(1).strip()
            new_name = rename_match.group(2).strip()

            # Contextual Memory: Did she just interact with this?
            target_path = ""
            if self.last_action_path and old_name.lower() in os.path.basename(self.last_action_path).lower():
                target_path = self.last_action_path
            else:
                target_path = self._resolve_location("desktop", old_name)

            new_path = os.path.join(os.path.dirname(target_path), new_name)
            return {
                "action_type": "run_command",
                "description": f"rename '{old_name}' to '{new_name}'",
                "command": f'ren "{target_path}" "{new_name}"',
                "is_dangerous": False,
                "rename_new_path": new_path,
            }

        # ── Permanent delete (must be checked before standard delete) ──
        perm_delete_match = re.search(
            r"(?:permanently\s+delete|force\s+delete|delete\s+forever|delete\s+permanently)\s+"
            r"(?:the\s+)?['\"]?([A-Za-z0-9 _\-\.]+?)['\"]?"
            r"(?:\s+(?:folder|file|directory))?"
            r"(?:\s+(?:from|on|in)\s+(?:my\s+)?(.+))?$",
            user_input,
            re.IGNORECASE,
        )
        if perm_delete_match:
            item_name = perm_delete_match.group(1).strip()
            location  = perm_delete_match.group(2).strip() if perm_delete_match.group(2) else "desktop"
            if self.last_action_path and item_name.lower() in os.path.basename(self.last_action_path).lower():
                item_path = self.last_action_path
            else:
                item_path = self._resolve_location(location, item_name)
            return {
                "action_type": "run_command",
                "description": f"permanently delete '{item_name}'",
                "command": f'powershell -Command "Remove-Item -Path \'{item_path}\' -Recurse -Force"',
                "is_dangerous": True,
            }

        # ── Standard delete → Recycle Bin (no confirmation needed) ────
        delete_match = re.search(
            r"(?:delete|remove)\s+(?:the\s+)?['\"]?([A-Za-z0-9 _\-\.]+?)['\"]?"
            r"(?:\s+(?:folder|file|directory))?"
            r"(?:\s+(?:from|on|in)\s+(?:my\s+)?(.+))?$",
            user_input,
            re.IGNORECASE,
        )
        if delete_match:
            item_name = delete_match.group(1).strip()
            location  = delete_match.group(2).strip() if delete_match.group(2) else "desktop"
            if self.last_action_path and item_name.lower() in os.path.basename(self.last_action_path).lower():
                item_path = self.last_action_path
            else:
                item_path = self._resolve_location(location, item_name)
            return {
                "action_type": "delete_trash",
                "description": f"move '{item_name}' to Recycle Bin",
                "filename": item_path,
                "is_dangerous": False,
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
  "action_type": "install_package | run_command | create_file | create_folder | open_app | search_web | write_to_file | unsupported",
  "description": "what will happen in plain English",
  "command": "exact shell command if needed",
  "filename": "full file path if creating a file",
  "content": "",
  "app_name": "app name if opening",
  "search_query": "query if searching",
  "url": "",
  "is_dangerous": false
}}

Rules:
- Windows paths use backslashes
- For installs use winget (apps) or pip (python packages)
- is_dangerous only true for delete/format/uninstall
- For rename: use command like: ren "full\path\oldname" "newname"
- Return unsupported only if truly impossible to determine

Respond with ONLY the JSON object. No markdown, no explanation."""

        response = self.brain._call_api(
            getattr(Config, "PRIMARY_BRAIN", "groq"), plan_prompt
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

    def _build_permission_request(self, plan: dict) -> str:
        """Direct, no-nonsense permission request — uses only item basenames, no full paths."""
        description = plan.get("description", "perform this action")
        is_dangerous = plan.get("is_dangerous", False)

        msg = f"I'll {description}."
        if is_dangerous:
            msg += " ⚠ This is destructive and can't be undone."
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
        if any(w in user_input.lower() for w in ["cancel", "never mind", "forget it", "no"]):
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
        return self._execute_pending()

    def _execute_pending(self) -> str:
        """Execute with verification + improv fallback on failure.

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
        self._clarification_options = []

        if not plan:
            return "There isn't anything pending right now."

        action_type = plan.get("action_type")
        self._log(f"EXECUTE [{verdict}]: {plan.get('command') or plan.get('description','?')}")

        # ── Execute and verify ────────────────────────────────
        result, success = self._execute_with_verify(plan)

        if success:
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

    def _execute_with_verify(self, plan: dict) -> tuple:
        """Execute an action and verify it actually worked.
        Returns (message, success_bool)
        """
        action_type = plan.get("action_type")

        try:
            if action_type in ("install_package", "run_command"):
                result = self._run_command(plan)
                success = "didn't work" not in result.lower() and "error" not in result.lower()
                # Update last_action_path after a successful rename
                if success and plan.get("rename_new_path") and os.path.exists(plan["rename_new_path"]):
                    self.last_action_path = plan["rename_new_path"]

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

            elif action_type == "delete_trash":
                result  = self._delete_to_trash(plan)
                success = "Recycle Bin" in result

            elif action_type == "write_to_file":
                result  = self._write_to_file(plan)
                success = "Done." in result

            else:
                return "I don't know how to execute that type of action.", False

            return result, success

        except Exception as e:
            self._log(f"EXCEPTION: {action_type} — {e}")
            return f"That didn't work: {str(e)[:100]}", False

    def _ai_retry_plan(self, original_plan: dict, error_msg: str) -> dict:
        """Ask the AI to generate an alternative approach when the first attempt fails."""
        prompt = f"""An action failed on Windows. Generate an alternative approach.

Original action: {json.dumps(original_plan, indent=2)}
Error/result: {error_msg}

Generate a different plan to achieve the same goal.
Use a completely different method — if mkdir failed, try os.makedirs via python; 
if start command failed, try webbrowser; if one path failed, try a different path.

Respond ONLY with valid JSON in this exact format:
{{
  "action_type": "install_package | run_command | create_file | create_folder | open_app | search_web | write_to_file",
  "description": "alternative approach in plain English",
  "command": "alternative shell command if needed",
  "filename": "full file path if needed",
  "content": "",
  "app_name": "app name if opening",
  "search_query": "",
  "url": "direct URL if opening browser",
  "is_dangerous": false
}}

Respond with ONLY the JSON. No explanation."""

        response = self.brain._call_api(
            getattr(Config, "PRIMARY_BRAIN", "groq"), prompt
        )

        if not response:
            return None

        try:
            clean = response.strip().replace("```json", "").replace("```", "").strip()
            return json.loads(clean)
        except Exception:
            return None

    def _run_with_live_progress(self, command: str) -> str:
        """Executes a command while streaming live shell output to a rich progress bar."""
        output_lines = []
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            transient=True,
        ) as progress:
            task = progress.add_task(f"[cyan]Starting:[/cyan] {command}", total=None)
            try:
                process = subprocess.Popen(
                    command, shell=True, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, text=True, bufsize=1,
                    creationflags=subprocess.CREATE_NO_WINDOW if self.is_windows else 0,
                )
                for line in process.stdout:
                    clean_line = line.strip()
                    if clean_line:
                        output_lines.append(clean_line)
                        short_line = clean_line[:80] + "..." if len(clean_line) > 80 else clean_line
                        progress.update(task, description=f"[cyan]Working:[/cyan] [dim]{short_line}[/dim]")
                process.wait()
            except Exception as e:
                self._log(f"EXCEPTION running command: {command} — {e}")
                return f"Couldn't run that command: {str(e)[:150]}"

        final_output = "\n".join(output_lines[-4:])
        if process.returncode == 0:
            self._log(f"SUCCESS: {command}")
            return "Done. " + final_output
        else:
            self._log(f"FAILED: {command} — {final_output}")
            fix = self._think_of_fix(command, final_output)
            return f"That didn't work. {fix}"

    def _run_command(self, plan: dict) -> str:
        """Run a shell command with defense-in-depth security re-check."""
        command = os.path.expandvars(plan.get("command", ""))  # expand env vars before blocked-commands scan
        if not command: return "No command to run."

        from core.security import BLOCKED_COMMANDS
        cmd_lower = command.lower()
        for pattern in BLOCKED_COMMANDS:
            if re.search(pattern, cmd_lower, re.IGNORECASE):
                self._log(f"EXECUTION BLOCKED: {command}")
                return "Blocked — this matches a hard security rule."

        self._log(f"RUN: {command}")

        is_heavy_task = any(word in cmd_lower for word in ["install", "update", "upgrade", "npm", "pip", "winget"])
        if is_heavy_task:
            return self._run_with_live_progress(command)

        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True, timeout=120,
                creationflags=subprocess.CREATE_NO_WINDOW if self.is_windows else 0,
            )
        except subprocess.TimeoutExpired:
            return "That command timed out after 2 minutes."
        except Exception as e:
            return f"Couldn't run that command: {str(e)[:150]}"

        if result.returncode == 0:
            output = result.stdout.strip()
            msg = "Done." + (f" {output}" if output and len(output) < 300 else "")
            self._log(f"SUCCESS: {command}")
            return msg
        else:
            err = result.stderr.strip()
            self._log(f"FAILED: {command} — {err}")
            fix = self._think_of_fix(command, err)
            return f"That didn't work. {fix}"

    def _think_of_fix(self, command: str, error: str) -> str:
        """Cognitively suggest a fix when a command fails."""
        prompt = f"""A command failed on Windows. Think like a smart IT assistant.

Command: {command}
Error: {error[:300]}

In one sentence, what's the most likely cause and fix?
Be specific and practical. No preamble."""

        response = self.brain._call_api(
            "groq", prompt
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
        return f"{prefix}Done. '{os.path.basename(filepath)}' created. Want me to open it?"

    def _create_folder(self, plan: dict) -> str:
        """Create a folder using os.makedirs — reliable across all Windows paths."""
        filename = plan.get("filename", "")
        command  = plan.get("command", "")

        # Resolve the folder path
        if filename:
            folder = filename
        elif command:
            # Extract path from mkdir command
            match = re.search(r'mkdir\s+"?([^"\']+)"?', command, re.IGNORECASE)
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

    def _delete_to_trash(self, plan: dict) -> str:
        """Move a file or folder to the Recycle Bin using send2trash."""
        path = plan.get("filename", "")
        basename = os.path.basename(path) if path else ""
        if not path or not os.path.exists(path):
            return f"Couldn't find '{basename}'."
        if not _HAS_SEND2TRASH:
            return "send2trash is not installed. Run: pip install send2trash"
        try:
            _send2trash.send2trash(path)
            self._log(f"TRASHED: {path}")
            self.last_action_path = None
            return "Moved to Recycle Bin."
        except Exception as e:
            self._log(f"TRASH FAILED: {path} — {e}")
            return f"Couldn't move to Recycle Bin: {str(e)[:100]}"

    def _play_music(self, plan: dict) -> str:
        """Play music using browser automation."""
        query = plan.get("search_query", "") or plan.get("description", "music")
        query = query.replace("play ", "").replace("music", "").strip() or "popular songs"
        return self.browser.play_music(query)

    def _open_app(self, plan: dict) -> str:
        """Open an application or URL using Windows start command."""
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
                subprocess.Popen(command, shell=True)
                self._log(f"OPENED: {command}")
                return "Done."
            except Exception as e:
                return f"Couldn't open that: {e}"

        # Use Windows start command
        if target:
            try:
                subprocess.Popen(f'start "" "{target}"', shell=True)
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
        return "Done."

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