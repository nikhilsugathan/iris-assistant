"""
IRIS Co-Pilot Mode
=====================
ONLY activates when you explicitly ask to be walked through something.

Trigger phrases:
  "walk me through..."
  "guide me through..."
  "step by step, how do I..."
  "take me through..."

What it does:
  - Breaks the task into numbered steps
  - Presents one step at a time
  - Waits for "next", "done", or "ready" before moving on
  - Helps if you're stuck on any step
  - Wraps up when complete

It does NOT activate on:
  - General questions ("how do I install Python?") → just answers
  - Action requests ("install Python") → goes to ActionExecutor
  - Only triggers on explicit walk-through requests
"""

import re
from typing import List
from config import Config


class CoPilot:

    def __init__(self, brain, voice, memory):
        self.brain  = brain
        self.voice  = voice
        self.memory = memory
        self.active       = False
        self.steps: List[str] = []
        self.current_step = 0
        self.task_context = ""

    # ─────────────────────────────────────────────────────────────
    # DETECTION: Only explicit walk-through requests
    # ─────────────────────────────────────────────────────────────

    TRIGGER_PHRASES = [
        "walk me through",
        "guide me through",
        "take me through",
        "step by step",
        "step-by-step",
        "show me how step",
        "teach me how",
    ]

    def should_activate(self, user_input: str) -> bool:
        text = user_input.lower()
        return any(phrase in text for phrase in self.TRIGGER_PHRASES)

    # ─────────────────────────────────────────────────────────────
    # START
    # ─────────────────────────────────────────────────────────────

    def start(self, user_input: str) -> str:
        self.active       = True
        self.current_step = 0
        self.task_context = user_input

        plan_prompt = f"""Break this task into clear numbered steps the user can follow one at a time:

Task: "{user_input}"

Rules:
- Each step = one clear action, 1-2 sentences max
- Be specific (exact commands for tech tasks, exact clicks for UI tasks)
- Aim for 4-8 steps
- Format: numbered list only, no intro or summary text

Example:
1. Open PowerShell as Administrator by right-clicking the Start menu.
2. Run: winget install Git.Git
3. Close and reopen PowerShell so the PATH updates."""

        response = self.brain._call_api(
            Config.PRIMARY_BRAIN, plan_prompt,
            use_persona=False, use_memory=False
        )

        self.steps = self._parse_steps(response or "")

        if not self.steps:
            self.active = False
            return self.brain.think(user_input)

        total = len(self.steps)
        step1 = self.steps[0]

        return (
            f"Alright, I've broken this into {total} steps.\n\n"
            f"Step 1 of {total}: {step1}\n\n"
            f"Say 'next' or 'done' when you're ready to continue, "
            f"or just ask me anything if you get stuck."
        )

    # ─────────────────────────────────────────────────────────────
    # HANDLE INPUT during active session
    # ─────────────────────────────────────────────────────────────

    def handle_input(self, user_input: str) -> str:
        if not self.active:
            return None

        text = user_input.lower().strip()

        if self._is_next(text):
            return self._next_step()

        if "skip" in text:
            return self._next_step(skipped=True)

        if "go back" in text or "previous step" in text:
            return self._prev_step()

        if self._is_stop(text):
            return self._end(completed=False)

        # Any question or stuck signal → help with current step
        return self._help_on_step(user_input)

    def _next_step(self, skipped=False) -> str:
        self.current_step += 1

        if self.current_step >= len(self.steps):
            return self._end(completed=True)

        num   = self.current_step + 1
        total = len(self.steps)
        text  = self.steps[self.current_step]

        prefix = "Skipping that." if skipped else "Good."
        return (
            f"{prefix}\n\n"
            f"Step {num} of {total}: {text}\n\n"
            f"Say 'next' when ready, or ask me anything."
        )

    def _prev_step(self) -> str:
        if self.current_step > 0:
            self.current_step -= 1
        num   = self.current_step + 1
        total = len(self.steps)
        return (
            f"Going back.\n\n"
            f"Step {num} of {total}: {self.steps[self.current_step]}\n\n"
            f"Take your time."
        )

    def _help_on_step(self, user_input: str) -> str:
        step_text = self.steps[self.current_step] if self.steps else ""
        prompt = (
            f"The user is working through this task: {self.task_context}\n"
            f"Current step: {step_text}\n"
            f"User said: {user_input}\n\n"
            f"Help them with this specific step. Be practical and specific. "
            f"If it's a tech task, give exact commands. Keep it concise. "
            f"End by reminding them to say 'next' when ready."
        )
        response = self.brain._call_api(
            Config.PRIMARY_BRAIN, prompt,
            use_persona=True, use_memory=False
        )
        return response or "Let me know what specifically is tripping you up."

    def _end(self, completed: bool) -> str:
        self.active = False
        if completed:
            prompt = (
                f"User just finished this task: {self.task_context} "
                f"({len(self.steps)} steps). "
                f"Give a short, warm, specific congratulation in 2 sentences max."
            )
            response = self.brain._call_api(
                Config.PRIMARY_BRAIN, prompt,
                use_persona=True, use_memory=False
            )
            return response or f"All done! You completed all {len(self.steps)} steps. Great work."
        else:
            return (
                f"Paused at step {self.current_step + 1}. "
                f"Say 'walk me through' again whenever you want to pick it back up."
            )

    # ─────────────────────────────────────────────────────────────
    # HELPERS
    # ─────────────────────────────────────────────────────────────

    def _parse_steps(self, text: str) -> List[str]:
        steps = []
        for line in text.strip().split("\n"):
            line = line.strip()
            match = re.match(r"^\d+[\.\)]\s*(.+)", line)
            if match:
                steps.append(match.group(1).strip())
        return steps

    def _is_next(self, text: str) -> bool:
        return any(w in text for w in [
            "next", "done", "ready", "continue", "got it",
            "okay", "ok", "yep", "yes", "finished", "move on"
        ])

    def _is_stop(self, text: str) -> bool:
        return any(w in text for w in [
            "stop", "cancel", "quit", "exit", "pause",
            "never mind", "nevermind", "forget it"
        ])
