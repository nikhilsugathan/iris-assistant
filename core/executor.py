# -*- coding: utf-8 -*-
"""
IRIS Action Executor
=======================
When you ask IRIS to DO something - install, create, delete, run -
it plans the action, tells you exactly what it's about to do,
and waits for your voice/text permission before executing.

PERMISSION GATE FLOW:
  You: "Iris, install Python"
  IRIS: "I'll run: winget install Python.Python.3 - shall I go ahead?"
  You: "yes" / "go ahead" / "do it"
  IRIS: [runs the command, reports result]
  IRIS: "Done. Python installed. Want me to verify it worked?"

SUPPORTED ACTION TYPES:
  - manage_package   : winget / pip / npm install
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
from datetime import datetime
from typing import Optional, Tuple

from rich.progress import Progress, SpinnerColumn, TextColumn

from config import Config
from core.security import SecurityGuard, SAFE, WARNING, BLOCKED, NEED_ADMIN
from core.autocorrect import AutoCorrector
from core.browser import BrowserAutomation
from core.improv import ImprovEngine
from core.tools_registry import (
    tool_union_for,
    tool_schema_for,
    ACTIVE_TOOL_NAMES,
    ADMIN_TOOL_NAMES,
)


# -- Phrases that mean YES --
YES_WORDS = [
    "yes", "yeah", "yep", "yup", "sure", "go ahead", "do it",
    "proceed", "confirm", "ok", "okay", "affirmative", "correct",
    "go for it", "run it", "execute", "do that", "sounds good"
]

# -- Phrases that mean NO --
NO_WORDS = [
    "no", "nope", "cancel", "stop", "don't", "abort", "wait",
    "hold on", "negative", "never mind", "nevermind", "skip"
]

# -- Phrases that are DANGEROUS (need double confirm) --
DANGEROUS_PATTERNS = [
    r"del\s", r"rm\s", r"rmdir", r"format", r"delete",
    r"drop\s", r"uninstall", r"--force", r"-rf"
]


class ActionExecutor:

    def __init__(self, voice, brain):
        self.voice    = voice
        self.brain    = brain
        self.security = SecurityGuard(brain)
        self.log_file    = os.path.join(Config.PROJECT_ROOT, "iris_actions.log")
        self.is_windows  = platform.system() == "Windows"
        self.pending_action         = None
        self.pending_verdict        = None
        self.follow_up              = None
        self.autocorrect            = AutoCorrector(brain)
        self.improv                 = ImprovEngine(brain)
        self.pending_plans          = None
        self.last_action_path       = None
        self._clarification_options = []
        self._browser = None

    @property
    def browser(self):
        """Create browser automation only when first needed."""
        if self._browser is None:
            self._browser = BrowserAutomation()
        return self._browser

    def _build_security_header(self, verdict: str) -> str:
        if verdict == BLOCKED:
            return "Security refusal."
        if verdict == NEED_ADMIN:
            return "Admin confirmation required."
        if verdict == WARNING:
            return "Security warning."
        return "Security check."

    # ------------------------------------------------------------------
    # DETECTION: Does this input want an action?
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # PERMISSION CHECK: Are we waiting for yes/no?
    # ------------------------------------------------------------------

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

        return None

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
        """User responded to a permission or security request.
        Override is allowed for WARNING and NEED_ADMIN verdicts only.
        BLOCKED verdicts cannot be overridden - they are hard security limits.
        """
        text = user_input.lower().strip()

        # -- Admin override - only for WARNING and NEED_ADMIN, never BLOCKED --
        if "override" in text:
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

        # -- Yes - proceed (but not for BLOCKED) --
        if any(word in text for word in YES_WORDS):
            if self.pending_verdict == BLOCKED:
                return "That action is blocked. Say 'cancel' to dismiss."
            return self._execute_pending()

        # -- No - cancel --
        if any(word in text for word in NO_WORDS):
            self.pending_action  = None
            self.pending_verdict = None
            return "Cancelled."

        # -- Anything else - ask once more plainly --
        return "Go ahead, or cancel?"

    # ------------------------------------------------------------------
    # SIMPLE TASK DETECTION: These run without asking permission
    # ------------------------------------------------------------------

    SIMPLE_ACTIONS = [
        "create_file", "create_folder", "open_app",
        "search_web", "write_to_file", "play_music", "delete_item"
    ]

    def _is_simple_task(self, plan: dict, verdict: str) -> bool:
        """Only actions in SIMPLE_ACTIONS auto-execute when verdict is SAFE.
        run_command and manage_package always ask for permission first,
        even when the security check passes - because those actions run
        shell commands that could come from AI-generated plans.
        """
        if verdict in (BLOCKED, WARNING, NEED_ADMIN):
            return False
        action_type = plan.get("action_type", "")
        return action_type in self.SIMPLE_ACTIONS

    # ------------------------------------------------------------------
    # COGNITIVE FILE NAMING: auto-rename if file already exists
    # ------------------------------------------------------------------

    def _resolve_filename(self, filepath: str) -> tuple:
        """If the file already exists, auto-generate a new name cognitively.
        Returns (final_path, message_about_rename_or_None)"""
        if not os.path.exists(filepath):
            return filepath, None

        base    = os.path.splitext(filepath)[0]
        ext     = os.path.splitext(filepath)[1]
        counter = 2

        while True:
            new_path = f"{base}{counter}{ext}"
            if not os.path.exists(new_path):
                original_name = os.path.basename(filepath)
                new_name      = os.path.basename(new_path)
                return new_path, (
                    f"'{original_name}' already exists - "
                    f"I've created '{new_name}' instead."
                )
            counter += 1

    def plan_action(self, user_input: str, admin_unlocked: bool = False) -> str:
        """Interpret the request, run security assessment.
        Simple safe tasks execute immediately.
        Risky tasks ask for permission first.
        """
        # -- Try direct pattern matching first (fast, reliable) --
        plan = self._pattern_match(user_input)

        # -- Fall back to AI JSON planning if no pattern matched --
        if not plan:
            plan = self._ai_plan(user_input, admin_unlocked=admin_unlocked)

        if not plan:
            return "I couldn't figure out how to do that. Could you rephrase it?"

        if plan.get("action_type") == "unsupported":
            return "I'm not sure how to do that safely. Could you describe it differently?"

        # -- Expand environment variables BEFORE security assessment --
        if "command" in plan and isinstance(plan["command"], str):
            plan["command"] = os.path.expandvars(plan["command"])

        # -- Run security assessment --
        verdict, security_msg = self.security.assess(plan, admin_unlocked=admin_unlocked)
        header = self._build_security_header(verdict)

        if verdict == BLOCKED:
            self._log(f"BLOCKED: {plan.get('command','?')} - {security_msg}")
            self.pending_action  = None
            self.pending_verdict = None
            return f"{header}\n{security_msg}\n\nThis action has been blocked and cannot be executed."

        # -- Simple safe task - execute with verification --
        if self._is_simple_task(plan, verdict):
            self._log(f"AUTO-EXECUTE: {plan.get('action_type')} - {plan.get('description','')}")
            self.pending_action  = plan
            self.pending_verdict = verdict
            return self._execute_pending()

        # -- Everything else - ask for permission --
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

        # -- Permanent delete (security gate - ask for confirmation) --
        perm_delete_match = re.search(
            r"(?:permanently\s+delete|force\s+delete|delete\s+forever|wipe)\s+['\"]?([^'\"]+?)['\"]?"
            r"(?:\s+(?:from|in|on|at)\s+(?:my\s+)?(.+))?$",
            user_input,
            re.IGNORECASE
        )
        if perm_delete_match:
            item_name = perm_delete_match.group(1).strip()
            location  = perm_delete_match.group(2).strip() if perm_delete_match.group(2) else "desktop"
            item_path = self._resolve_location(location, item_name)
            if os.path.exists(item_path) and os.path.isdir(item_path):
                del_cmd = f'rd /s /q "{item_path}"'
            else:
                del_cmd = f'del /f /q "{item_path}"'
            return {
                "action_type": "run_command",
                "description": f"permanently delete '{item_name}'",
                "command": del_cmd,
                "filename": item_path,
                "is_dangerous": True
            }

        # -- Standard delete - Recycle Bin --
        std_delete_match = re.search(
            r"(?:delete|remove|trash)\s+['\"]?([^'\"]+?)['\"]?"
            r"(?:\s+(?:from|in|on|at)\s+(?:my\s+)?(.+))?$",
            user_input,
            re.IGNORECASE
        )
        if std_delete_match:
            item_name = std_delete_match.group(1).strip()
            location  = std_delete_match.group(2).strip() if std_delete_match.group(2) else "desktop"
            item_path = self._resolve_location(location, item_name)
            if self.last_action_path and item_name.lower() in os.path.basename(self.last_action_path).lower():
                item_path = self.last_action_path
            return {
                "action_type": "delete_item",
                "description": f"move '{item_name}' to Recycle Bin",
                "filename": item_path,
                "is_dangerous": False
            }

        # -- Create file --
        file_match = re.search(
            r"(?:create|make|new)\s+(?:a\s+)?file\s+(?:called|named|as|named as)\s*['\"]?([^'\"]+?)['\"]?"
            r"(?:\s+(?:in|on|at|inside)\s+(?:my\s+)?(.+))?$",
            user_input,
            re.IGNORECASE
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

        # -- Create file (bare name, no "called/named" keyword required) --
        bare_file_match = re.search(
            r"(?:create|make|new)\s+(?:a\s+)?file\s+"
            r"(?!(?:on|in|at|inside|called|named|as)\b)"
            r"['\"]?([A-Za-z0-9 _\-\.]+?)['\"]?"
            r"(?:\s+(?:in|on|at|inside)\s+(?:my\s+)?(.+))?$",
            user_input,
            re.IGNORECASE
        )
        if bare_file_match:
            filename = bare_file_match.group(1).strip()
            location = bare_file_match.group(2).strip() if bare_file_match.group(2) else "desktop"
            filepath = self._resolve_location(location, filename)
            return {
                "action_type": "create_file",
                "description": f"create file '{filename}'",
                "filename": filepath,
                "content": "",
                "is_dangerous": False
            }

        # -- Create subfolder inside existing folder --
        subfolder_match = re.search(
            r"(?:create|make)\s+(?:a\s+)?sub.?folder\s+"
            r"(?:called|named|as)?\s*['\"]?([^'\"]+)['\"]?"
            r"(?:\s+(?:in|inside|within|under)\s+(.+))?",
            user_input,
            re.IGNORECASE
        )
        if subfolder_match:
            subfoldername = subfolder_match.group(1).strip()
            parent        = subfolder_match.group(2).strip() if subfolder_match.group(2) else ""

            if parent:
                desktop = self._get_desktop_path()
                parent_path = os.path.join(desktop, parent)
                if not os.path.isdir(parent_path):
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

        # -- Create folder (bare name, no "called/named" keyword required) --
        bare_folder_match = re.search(
            r"(?:create|make|new)\s+(?:a\s+)?(?:new\s+)?folder\s+"
            r"(?!(?:on|in|at|inside|called|named|as)\b)"
            r"['\"]?([A-Za-z0-9 _\-]+?)['\"]?"
            r"(?:\s+(?:in|on|at|inside)\s+(?:my\s+)?(.+))?$",
            user_input,
            re.IGNORECASE
        )
        if bare_folder_match:
            foldername = bare_folder_match.group(1).strip()
            location   = bare_folder_match.group(2).strip() if bare_folder_match.group(2) else "desktop"
            folderpath = self._resolve_location(location, foldername)
            return {
                "action_type": "create_folder",
                "description": f"create folder '{foldername}'",
                "filename": folderpath,
                "is_dangerous": False
            }

        # -- Create folder --
        folder_match = re.search(
            r"(?:create|make|new)\s+(?:a\s+)?(?:new\s+)?folder"
            r"(?:\s+(?:on|in|at)\s+(?:my\s+)?\w+)?"
            r"\s+(?:called|named|as|named as)\s+"
            r"['\"]?([A-Za-z0-9 _\-]+?)['\"]?"
            r"(?:\s+(?:in|on|at|inside)\s+(?:my\s+)?(.+))?$",
            user_input,
            re.IGNORECASE
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

        # -- Create unnamed folder --
        unnamed_folder = re.search(
            r"(?:create|make)\s+(?:a\s+)?(?:new\s+)?folder"
            r"(?:\s+(?:in|on|at)\s+(?:my\s+)?(.+))?$",
            user_input,
            re.IGNORECASE
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

        # -- Rename File/Folder (Context-Aware) --
        rename_match = re.search(
            r"rename\s+(?:the\s+)?(?:folder|file\s+)?(?:from\s+)?['\"]?([^'\"]+)['\"]?\s+(?:to|as)\s+['\"]?([^'\"]+)['\"]?",
            user_input,
            re.IGNORECASE
        )
        if rename_match:
            old_name = rename_match.group(1).strip()
            new_name = rename_match.group(2).strip()

            target_path = ""
            if self.last_action_path and old_name.lower() in os.path.basename(self.last_action_path).lower():
                target_path = self.last_action_path
            else:
                target_path = self._resolve_location("desktop", old_name)

            return {
                "action_type": "run_command",
                "description": f"rename '{os.path.basename(target_path)}' to '{new_name}'",
                "command": f'ren "{target_path}" "{new_name}"',
                "old_path": target_path,
                "new_name": new_name,
                "is_dangerous": False
            }

        # -- Play specific song / music --
        song_match = re.search(
            r"(?:play|stream|listen to|put on)\s+(.+?)(?:\s+(?:on|from|via|using)\s+\w+)?$",
            user_input,
            re.IGNORECASE
        )
        if song_match:
            query = song_match.group(1).strip()
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

        # -- Open app --
        open_match = re.search(r"(?:open|launch|start)\s+(.+)", user_input, re.IGNORECASE)
        if open_match:
            app = open_match.group(1).strip()
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

        # -- Search web --
        search_match = re.search(r"(?:search for|search|look up|google)\s+(.+)", user_input, re.IGNORECASE)
        if search_match:
            query = search_match.group(1).strip()
            return {
                "action_type": "search_web",
                "description": f"search for '{query}'",
                "search_query": query,
                "is_dangerous": False
            }

        return None

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

        best = difflib.get_close_matches(location, location_map.keys(), n=1, cutoff=0.6)
        folder = location_map.get(best[0] if best else "desktop", self._get_desktop_path())

        return os.path.join(folder, filename)

    def _ai_plan(self, user_input: str, admin_unlocked: bool = False) -> Optional[dict]:
        """AI JSON planner - fallback when pattern matching fails."""
        system = platform.system()
        tool_set = ADMIN_TOOL_NAMES if admin_unlocked else ACTIVE_TOOL_NAMES
        persona = "admin" if admin_unlocked else "public"
        tool_schema = tool_schema_for(tool_set)

        context = ""
        if self.last_action_path:
            context = f'\nLast action path: "{self.last_action_path}" - use this if the user refers to "it", "that folder", "that file", or "the one I just created".\n'

        plan_prompt = f"""The user wants IRIS to take a real action on their computer.
System: {system}
Persona mode: {persona}
Allowed tools for this persona:
{tool_schema}

{context}
User request: "{user_input}"

Respond ONLY with valid JSON in this exact format:
{{
  "action_type": "{tool_union_for(tool_set)}",
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
- Only choose action_type values from the allowed tools above
- For installs use winget (apps) or pip (python packages)
- is_dangerous only true for delete/format/uninstall
- For rename: use command like: ren "full\\path\\oldname" "newname"
- Return unsupported only if truly impossible to determine

Respond with ONLY the JSON object. No markdown, no explanation."""

        response = self.brain._call_api(
            getattr(Config, "PRIMARY_BRAIN", "groq"), plan_prompt
        )

        if not response:
            return None

        try:
            clean = response.strip()
            clean = re.sub(r"```(?:json)?", "", clean).strip()
            return json.loads(clean)
        except Exception:
            return None

    def _build_permission_request(self, plan: dict) -> str:
        """Direct, no-nonsense permission request using basenames for clean voice output."""
        description  = plan.get("description", "perform this action")
        command      = plan.get("command", "")
        is_dangerous = plan.get("is_dangerous", False)

        display_command = command
        if command:
            display_command = re.sub(
                r'"([A-Za-z]:\\[^"\\]+)"',
                lambda m: f'"{os.path.basename(m.group(1))}"',
                command
            )

        msg = f"I'll {description}."
        if display_command and display_command != command:
            msg += f" Command: {display_command}."
        if is_dangerous:
            msg += " This is destructive and can't be undone."
        msg += " Go ahead?"
        return msg

    # ------------------------------------------------------------------
    # EXECUTE: Run the approved action
    # ------------------------------------------------------------------

    def waiting_for_plan_choice(self) -> bool:
        return self.pending_plans is not None

    def handle_plan_choice(self, user_input: str) -> str:
        """User is choosing between Plan A, B, C."""
        plans = self.pending_plans
        if not plans:
            return None

        if any(w in user_input.lower() for w in ["cancel", "never mind", "forget it", "no"]):
            self.pending_plans = None
            return "Cancelled."

        selected = self.improv.select_plan(plans, user_input)

        if not selected:
            a = plans.get("plan_a", {}).get("description", "?")
            b = plans.get("plan_b", {}).get("description", "?")
            c = plans.get("plan_c", {}).get("description", "?")
            return f"Which one - A: {a}, B: {b}, or C: {c}?"

        if selected.get("requires_permission"):
            self.pending_action  = selected
            self.pending_verdict = WARNING
            self.pending_plans   = None
            desc = selected.get("description", "this action")
            cmd  = selected.get("command", "")
            msg  = f"Plan C: {desc}."
            if cmd:
                msg += f" Command: {cmd}."
            msg += " This one has real side effects - go ahead?"
            return msg

        self.pending_plans   = None
        self.pending_action  = selected
        self.pending_verdict = SAFE
        return self._execute_pending()

    def _execute_pending(self) -> str:
        """Execute with verification + improv fallback on failure.

        Flow:
          1. Execute
          2. Verify it worked
          3. If failed - generate Plan A/B/C via improv engine
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

        result, success = self._execute_with_verify(plan)

        if success:
            return result

        self._log(f"FAILED: {result} - generating improv plans")
        original_request = plan.get("description", "that action")
        plans = self.improv.generate_plans(original_request, plan, result)

        if not plans:
            return result

        self.pending_plans = plans
        spoken = self.improv.format_spoken_options(plans)
        return spoken

    def _execute_with_verify(self, plan: dict) -> tuple:
        """Execute an action and verify it actually worked.
        Returns (message, success_bool)"""
        action_type = plan.get("action_type")

        try:
            if action_type in ("manage_package", "run_command"):
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
                success = result == "Done."

            elif action_type == "search_web":
                result  = self._search_web(plan)
                success = result == "Done."

            elif action_type == "write_to_file":
                result  = self._write_to_file(plan)
                success = "Done." in result

            elif action_type == "delete_item":
                result  = self._delete_item(plan)
                success = "Moved" in result or "Recycle Bin" in result

            else:
                return "I don't know how to execute that type of action.", False

            return result, success

        except Exception as e:
            self._log(f"EXCEPTION: {action_type} - {e}")
            return f"That didn't work: {str(e)[:100]}", False

    def _ai_retry_plan(self, original_plan: dict, error_msg: str) -> dict:
        """Ask the AI to generate an alternative approach when the first attempt fails."""
        prompt = f"""An action failed on Windows. Generate an alternative approach.

Original action: {json.dumps(original_plan, indent=2)}
Error/result: {error_msg}

Generate a different plan to achieve the same goal.
Use a completely different method - if mkdir failed, try os.makedirs via python;
if start command failed, try webbrowser; if one path failed, try a different path.

Respond ONLY with valid JSON in this exact format:
{{
  "action_type": "{tool_union_for(ADMIN_TOOL_NAMES)}",
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
                self._log(f"EXCEPTION running command: {command} - {e}")
                return f"Couldn't run that command: {str(e)[:150]}"

        final_output = "\n".join(output_lines[-4:])
        if process.returncode == 0:
            self._log(f"SUCCESS: {command}")
            return "Done. " + final_output
        else:
            self._log(f"FAILED: {command} - {final_output}")
            fix = self._think_of_fix(command, final_output)
            return f"That didn't work. {fix}"

    def _run_command(self, plan: dict) -> str:
        """Run a shell command with defense-in-depth security re-check."""
        command = os.path.expandvars(plan.get("command", ""))
        if not command:
            return "No command to run."

        from core.security import BLOCKED_COMMANDS
        cmd_lower = command.lower()
        for pattern in BLOCKED_COMMANDS:
            if re.search(pattern, cmd_lower, re.IGNORECASE):
                self._log(f"EXECUTION BLOCKED: {command}")
                return "Blocked - this matches a hard security rule."

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
            old_path     = plan.get("old_path", "")
            new_name_val = plan.get("new_name", "")
            if old_path and new_name_val:
                new_path = os.path.join(os.path.dirname(old_path), new_name_val)
                if os.path.exists(new_path):
                    self.last_action_path = new_path
                    self._log(f"RENAME VERIFIED: {new_path}")
                    return "Done."
                else:
                    return f"Failed: rename command succeeded but '{new_name_val}' was not found at the expected path. Check the path or try again."
            msg = "Done." + (f" {output}" if output and len(output) < 300 else "")
            self._log(f"SUCCESS: {command}")
            return msg
        else:
            err = result.stderr.strip()
            self._log(f"FAILED: {command} - {err}")
            fix = self._think_of_fix(command, err)
            return f"That didn't work. {fix}"

    def _think_of_fix(self, command: str, error: str) -> str:
        """Cognitively suggest a fix when a command fails."""
        prompt = f"""A command failed on Windows. Think like a smart IT assistant.

Command: {command}
Error: {error[:300]}

In one sentence, what's the most likely cause and fix?
Be specific and practical. No preamble."""

        response = self.brain._call_api("groq", prompt)
        return response or f"Error: {error[:150]}"

    def _get_desktop_path(self) -> str:
        """Get the correct Desktop path - checks OneDrive first (most common on Win10/11)."""
        home = os.path.expanduser("~")

        onedrive = os.path.join(home, "OneDrive", "Desktop")
        if os.path.exists(onedrive):
            return onedrive

        standard = os.path.join(home, "Desktop")
        if os.path.exists(standard):
            return standard

        return home

    def _prepare_target_path(self, raw_path: str) -> tuple[str, Optional[str]]:
        """Normalize a target path and ensure its parent directory exists when needed."""
        if "desktop" in raw_path.lower():
            bare_name = os.path.basename(raw_path)
            target_path = os.path.join(self._get_desktop_path(), bare_name)
        elif not os.path.dirname(raw_path):
            target_path = os.path.join(self._get_desktop_path(), raw_path)
        else:
            target_path = raw_path

        target_dir = os.path.dirname(target_path)
        if target_dir:
            os.makedirs(target_dir, exist_ok=True)
        return target_path, target_dir or None

    def _create_file(self, plan: dict) -> str:
        """Create a file - cognitively corrects extension, auto-renames if exists."""
        filename = plan.get("filename", "iris_output.txt")
        content  = plan.get("content", "")
        context  = plan.get("description", "")

        filename, path_note = self.autocorrect.correct_path(filename)

        filename, ext_note, needs_clarification, options = \
            self.autocorrect.correct_extension(filename, context)

        if needs_clarification:
            self.pending_action = plan
            self.pending_action["filename"] = filename
            self.pending_verdict = SAFE
            self._clarification_options = options
            opts_str = " or ".join(options)
            return (
                f"Did you mean '{opts_str}'? "
                f"Say the extension you want and I'll create it."
            )

        try:
            filepath, _ = self._prepare_target_path(filename)
            filepath, rename_msg = self._resolve_filename(filepath)
            target_dir = os.path.dirname(filepath)
            if target_dir:
                os.makedirs(target_dir, exist_ok=True)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
        except OSError as e:
            self._log(f"ERROR creating file: {filename} - {e}")
            return f"Couldn't create the file safely: {str(e)[:120]}"

        if not os.path.isfile(filepath):
            self._log(f"FILE CREATION FAILED: {filepath}")
            return "Failed: file was not created. Check permissions or path."

        self._log(f"CREATED FILE: {filepath}")
        self.last_action_path = filepath
        self.follow_up = {"action": "open_file", "path": filepath}

        notes = []
        if path_note:  notes.append(path_note)
        if ext_note:   notes.append(ext_note)
        if rename_msg: notes.append(rename_msg)

        prefix = " ".join(notes) + " " if notes else ""
        return f"{prefix}Done. '{os.path.basename(filepath)}' created. Want me to open it?"

    def _create_folder(self, plan: dict) -> str:
        """Create a folder using os.makedirs - reliable across all Windows paths."""
        filename = plan.get("filename", "")
        command  = plan.get("command", "")

        if filename:
            folder = filename
        elif command:
            match = re.search(r'mkdir\s+"?([^"\']+)"?', command, re.IGNORECASE)
            folder = match.group(1).strip() if match else None
        else:
            folder = None

        if not folder:
            return "I couldn't determine where to create the folder."

        if "desktop" in folder.lower():
            folder = os.path.join(self._get_desktop_path(), os.path.basename(folder))

        try:
            os.makedirs(folder, exist_ok=True)
            if os.path.isdir(folder):
                self._log(f"CREATED FOLDER: {folder}")
                self.last_action_path = folder
                return "Done."
            else:
                return f"Failed: folder '{os.path.basename(folder)}' was not created. Check permissions."
        except OSError as e:
            self._log(f"ERROR creating folder: {e}")
            return f"Couldn't create the folder: {str(e)[:100]}"

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

        if url and url.startswith("http"):
            import webbrowser
            webbrowser.open(url)
            self._log(f"OPENED URL: {url}")
            return "Done."

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

        if target and target.startswith("http"):
            return self.browser.open_url(target)

        if command:
            try:
                subprocess.Popen(command, shell=True)
                self._log(f"OPENED: {command}")
                return "Done."
            except Exception as e:
                return f"Couldn't open that: {e}"

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

        try:
            filepath, _ = self._prepare_target_path(filename)
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(content + "\n")
        except OSError as e:
            self._log(f"ERROR writing file: {filename} - {e}")
            return f"Couldn't write to the file safely: {str(e)[:120]}"

        self.last_action_path = filepath
        self._log(f"WROTE TO: {filepath}")
        return "Done."

    def _delete_item(self, plan: dict) -> str:
        """Move an item to the Recycle Bin using send2trash."""
        import send2trash
        path = plan.get("filename", "")
        if not path or not os.path.exists(path):
            return f"Can't find '{os.path.basename(path)}' - nothing deleted."
        try:
            send2trash.send2trash(path)
            if not os.path.exists(path):
                self._log(f"TRASHED: {path}")
                return f"Moved '{os.path.basename(path)}' to Recycle Bin."
            else:
                return f"Failed: '{os.path.basename(path)}' could not be moved to Recycle Bin."
        except Exception as e:
            return f"Delete failed: {str(e)[:150]}"

    # ------------------------------------------------------------------
    # LOGGING
    # ------------------------------------------------------------------

    def _log(self, message: str):
        """Log every action to file for transparency."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not getattr(self, "log_file", None):
            self.log_file = os.path.join(Config.PROJECT_ROOT, "iris_actions.log")
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(f"[{timestamp}] {message}\n")
        except OSError:
            pass
