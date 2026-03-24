"""
JARVIS Action Executor
=======================
When you ask JARVIS to DO something — install, create, delete, run —
it plans the action, tells you exactly what it's about to do,
and waits for your voice/text permission before executing.

PERMISSION GATE FLOW:
  You: "Jarvis, install Python"
  JARVIS: "I'll run: winget install Python.Python.3 — shall I go ahead?"
  You: "yes" / "go ahead" / "do it"
  JARVIS: [runs the command, reports result]
  JARVIS: "Done. Python installed. Want me to verify it worked?"

SUPPORTED ACTION TYPES:
  - install_package  : winget / pip / npm install
  - run_command      : any shell command
  - create_file      : create a file with content
  - create_folder    : make a directory
  - open_app         : launch an application
  - search_web       : open browser search
  - write_to_file    : append/write content to existing file

SAFETY:
  - JARVIS ALWAYS announces what it will do before doing it
  - Destructive actions (delete, format, rm -rf) require DOUBLE confirmation
  - Every action and result is logged to jarvis_actions.log
"""

import subprocess
import os
import platform
import re
import json
import difflib
from datetime import datetime
from typing import Optional, Tuple

from config import Config
from core.security import SecurityGuard, SAFE, WARNING, BLOCKED, NEED_ADMIN
from core.autocorrect import AutoCorrector


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
        self.pending_action         = None
        self.pending_verdict        = None
        self.follow_up              = None
        self.autocorrect            = AutoCorrector(brain)
        self._clarification_options = []
        self.log_file    = "iris_actions.log"
        self.is_windows  = platform.system() == "Windows"

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
    ]

    def should_handle(self, user_input: str) -> bool:
        """Detect if user wants JARVIS to take a real action."""
        text = user_input.lower()
        return any(trigger in text for trigger in self.ACTION_TRIGGERS)

    # ─────────────────────────────────────────────────────────────
    # PERMISSION CHECK: Are we waiting for yes/no?
    # ─────────────────────────────────────────────────────────────

    def waiting_for_permission(self) -> bool:
        return self.pending_action is not None

    def waiting_for_followup(self) -> bool:
        return self.follow_up is not None

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
                    os.startfile(path)
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

    def handle_permission_response(self, user_input: str) -> str:
        """
        User responded to a permission or security request.
        No filtering — you're the admin, your word is final.
        Say 'override' to bypass any security warning or block.
        """
        text = user_input.lower().strip()

        # ── Admin override — bypasses everything including hard blocks ──
        if "override" in text:
            cmd = self.pending_action.get("command") or self.pending_action.get("description", "?")
            self._log(f"ADMIN OVERRIDE: {cmd}")
            return self._execute_pending()

        # ── Yes — proceed ──
        if any(word in text for word in YES_WORDS):
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
        "search_web", "write_to_file"
    ]

    def _is_simple_task(self, plan: dict, verdict: str) -> bool:
        """
        Everything that isn't a security/ethical issue executes automatically.
        JARVIS thinks and acts like a human assistant — no permission needed
        for normal tasks. Only BLOCKED, WARNING, NEED_ADMIN stop for auth.
        """
        if verdict in (BLOCKED, WARNING, NEED_ADMIN):
            return False
        return True  # SAFE verdict = just do it

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
        header = self.security.format_security_header(verdict)

        if verdict == BLOCKED:
            self._log(f"BLOCKED: {plan.get('command','?')} — {security_msg}")
            self.pending_action  = plan
            self.pending_verdict = verdict
            return f"{header}\n{security_msg}\n\nSay 'override' to run it anyway, or 'cancel' to drop it."

        # ── Simple safe task — just do it ────────────────────
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
        """
        Fast pattern-based action detection for common requests.
        Handles the most frequent actions without needing AI JSON parsing.
        """
        text = user_input.lower().strip()

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

        # ── Create folder ─────────────────────────────────────
        folder_match = re.search(
            r"(?:create|make|new)\s+(?:a\s+)?folder\s+(?:called|named|as)?\s*['\"]?([^\s'\"]+)['\"]?"
            r"(?:\s+(?:in|on|at|inside)\s+(?:my\s+)?(.+))?",
            text
        )
        if folder_match:
            foldername = folder_match.group(1).strip()
            location   = folder_match.group(2).strip() if folder_match.group(2) else "desktop"
            folderpath = self._resolve_location(location, foldername)
            return {
                "action_type": "create_folder",
                "description": f"create folder '{foldername}' in {location}",
                "command": f'mkdir "{folderpath}"',
                "filename": folderpath,
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
        plan_prompt = f"""The user wants JARVIS to take a real action on their computer.
System: {system}

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
- Return unsupported only if truly impossible to determine

Respond with ONLY the JSON object. No markdown, no explanation."""

        response = self.brain._call_api(
            Config.PRIMARY_BRAIN, plan_prompt,
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

        msg = f"I'll {description}."
        if command:
            msg += f" Command: {command}."
        if is_dangerous:
            msg += " ⚠ This is destructive and can't be undone."
        msg += " Go ahead?"
        return msg

    # ─────────────────────────────────────────────────────────────
    # EXECUTE: Run the approved action
    # ─────────────────────────────────────────────────────────────

    def _execute_pending(self) -> str:
        """Execute the stored pending action."""
        plan    = self.pending_action
        verdict = self.pending_verdict
        self.pending_action  = None
        self.pending_verdict = None

        action_type = plan.get("action_type")
        self._log(f"USER APPROVED [{verdict}]: {plan.get('command') or plan.get('description','?')}")

        try:
            if action_type in ("install_package", "run_command"):
                return self._run_command(plan)

            elif action_type == "create_file":
                return self._create_file(plan)

            elif action_type == "create_folder":
                return self._create_folder(plan)

            elif action_type == "open_app":
                return self._open_app(plan)

            elif action_type == "search_web":
                return self._search_web(plan)

            elif action_type == "write_to_file":
                return self._write_to_file(plan)

            else:
                return "I don't know how to execute that type of action yet."

        except Exception as e:
            self._log(f"ERROR: {action_type} — {e}")
            return f"Something went wrong while executing that: {e}. Want me to try a different approach?"

    def _run_command(self, plan: dict) -> str:
        """Run a shell command with cognitive thinking."""
        command = plan.get("command", "")
        if not command:
            return "No command to run."

        self._log(f"RUN: {command}")

        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=120
        )

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

    def _think_of_fix(self, command: str, error: str) -> str:
        """Cognitively suggest a fix when a command fails."""
        prompt = f"""A command failed on Windows. Think like a smart IT assistant.

Command: {command}
Error: {error[:300]}

In one sentence, what's the most likely cause and fix?
Be specific and practical. No preamble."""

        response = self.brain._call_api(
            Config.PRIMARY_BRAIN, prompt,
            use_persona=False, use_memory=False
        )
        return response or f"Error: {error[:150]}"

    def _get_desktop_path(self) -> str:
        """Get the correct Desktop path — handles OneDrive Desktop on Windows."""
        # Standard desktop
        standard = os.path.join(os.path.expanduser("~"), "Desktop")
        if os.path.exists(standard):
            return standard

        # OneDrive desktop (very common on Windows 10/11)
        onedrive = os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop")
        if os.path.exists(onedrive):
            return onedrive

        # Fallback — just use home directory
        return os.path.expanduser("~")

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
        self.follow_up = {"action": "open_file", "path": filepath}

        # Build response noting any corrections made
        notes = []
        if path_note:   notes.append(path_note)
        if ext_note:    notes.append(ext_note)
        if rename_msg:  notes.append(rename_msg)

        prefix = " ".join(notes) + " " if notes else ""
        return f"{prefix}Done. '{os.path.basename(filepath)}' created at {filepath}. Want me to open it?"

    def _create_folder(self, plan: dict) -> str:
        """Create a directory."""
        command = plan.get("command", "")
        if command:
            return self._run_command(plan)
        folder = plan.get("filename", "new_folder")
        os.makedirs(folder, exist_ok=True)
        self._log(f"CREATED FOLDER: {folder}")
        return f"Done. Created the folder '{folder}'."

    def _open_app(self, plan: dict) -> str:
        """Open an application."""
        app = plan.get("app_name", "")
        command = plan.get("command", "")

        if command:
            subprocess.Popen(command, shell=True)
        elif app:
            subprocess.Popen(f'start "" "{app}"', shell=True)
        else:
            return "I'm not sure which app to open."

        self._log(f"OPENED: {app or command}")
        return f"Done. Opening {app or 'the application'} now."

    def _search_web(self, plan: dict) -> str:
        """Open browser with a search."""
        import webbrowser
        query = plan.get("search_query", "")
        if not query:
            return "No search query provided."
        url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
        webbrowser.open(url)
        self._log(f"SEARCHED: {query}")
        return f"Done. Opened a search for '{query}' in your browser."

    def _write_to_file(self, plan: dict) -> str:
        """Append or write content to an existing file."""
        filename = plan.get("filename", "")
        content  = plan.get("content", "")
        if not filename:
            return "No filename specified."
        with open(filename, "a", encoding="utf-8") as f:
            f.write(content + "\n")
        self._log(f"WROTE TO: {filename}")
        return f"Done. Added content to '{filename}'."

    # ─────────────────────────────────────────────────────────────
    # LOGGING
    # ─────────────────────────────────────────────────────────────

    def _log(self, message: str):
        """Log every action to file for transparency."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {message}\n")
