"""
IRIS Co-Pilot Mode
==================
Activates only for explicit walk-through requests and keeps one walkthrough state
until the user advances, goes back, skips, pauses, or completes it.
"""

from __future__ import annotations

import re
from typing import List

from config import Config


class CoPilot:
    TRIGGER_PHRASES = [
        "walk me through",
        "guide me through",
        "take me through",
        "step by step",
        "step-by-step",
        "show me how step",
        "teach me how",
    ]

    _NEXT_PHRASES = {
        "next",
        "done",
        "ready",
        "continue",
        "got it",
        "okay",
        "ok",
        "yep",
        "yes",
        "finished",
        "move on",
        "next step",
        "continue please",
    }
    _STOP_PHRASES = {
        "stop",
        "cancel",
        "quit",
        "exit",
        "pause",
        "never mind",
        "nevermind",
        "forget it",
        "stop the walkthrough",
        "pause the walkthrough",
        "not now",
        "not ready",
        "not done",
        "do not continue",
        "don't continue",
        "dont continue",
    }

    def __init__(self, brain, voice, memory):
        self.brain = brain
        self.voice = voice
        self.memory = memory
        self.active = False
        self.steps: List[str] = []
        self.current_step = 0
        self.task_context = ""

    @staticmethod
    def _normalize(text: str) -> str:
        value = str(text or "").lower().replace("’", "'")
        value = re.sub(r"[^a-z0-9']+", " ", value)
        value = value.replace("'", " ")
        return re.sub(r"\s+", " ", value).strip()

    @staticmethod
    def _contains_phrase(text: str, phrase: str) -> bool:
        return f" {phrase} " in f" {text} "

    def should_activate(self, user_input: str) -> bool:
        text = (user_input or "").lower()
        return any(phrase in text for phrase in self.TRIGGER_PHRASES)

    def start(self, user_input: str) -> str:
        # DialogManager intentionally keeps routing an active Copilot session back
        # to mode="copilot". Main calls start() for that mode, so start() must act
        # as the stable integration entry point and delegate active turns instead
        # of resetting the walkthrough on every "next"/question.
        if self.active:
            return self.handle_input(user_input)

        self.active = True
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

        response = self.brain._call_api(Config.PRIMARY_BRAIN, plan_prompt)
        self.steps = self._parse_steps(response or "")

        if not self.steps:
            self.active = False
            return self.brain.think(user_input)

        total = len(self.steps)
        step1 = self.steps[0]
        return (
            f"Alright, I've broken this into {total} steps.\n\n"
            f"Step 1 of {total}: {step1}\n\n"
            "Say 'next' or 'done' when you're ready to continue, "
            "or just ask me anything if you get stuck."
        )

    def handle_input(self, user_input: str) -> str:
        if not self.active:
            return None

        text = self._normalize(user_input)

        # Negative/stop intent wins over words such as "continue" or "done".
        if self._is_stop(text):
            return self._end(completed=False)
        if self._contains_phrase(text, "go back") or self._contains_phrase(text, "previous step"):
            return self._prev_step()
        if self._contains_phrase(text, "skip"):
            return self._next_step(skipped=True)
        if self._is_next(text):
            return self._next_step()

        return self._help_on_step(user_input)

    def _next_step(self, skipped=False) -> str:
        self.current_step += 1

        if self.current_step >= len(self.steps):
            return self._end(completed=True)

        num = self.current_step + 1
        total = len(self.steps)
        text = self.steps[self.current_step]
        prefix = "Skipping that." if skipped else "Good."
        return (
            f"{prefix}\n\n"
            f"Step {num} of {total}: {text}\n\n"
            "Say 'next' when ready, or ask me anything."
        )

    def _prev_step(self) -> str:
        if self.current_step > 0:
            self.current_step -= 1
        num = self.current_step + 1
        total = len(self.steps)
        return (
            "Going back.\n\n"
            f"Step {num} of {total}: {self.steps[self.current_step]}\n\n"
            "Take your time."
        )

    def _help_on_step(self, user_input: str) -> str:
        step_text = self.steps[self.current_step] if self.steps else ""
        prompt = (
            f"The user is working through this task: {self.task_context}\n"
            f"Current step: {step_text}\n"
            f"User said: {user_input}\n\n"
            "Help them with this specific step. Be practical and specific. "
            "If it's a tech task, give exact commands. Keep it concise. "
            "End by reminding them to say 'next' when ready."
        )
        response = self.brain._call_api(Config.PRIMARY_BRAIN, prompt)
        return response or "Let me know what specifically is tripping you up."

    def _end(self, completed: bool) -> str:
        completed_steps = len(self.steps)
        completed_task = self.task_context
        paused_step = self.current_step + 1
        self.active = False

        if completed:
            prompt = (
                f"User just finished this task: {completed_task} "
                f"({completed_steps} steps). "
                "Give a short, warm, specific congratulation in 2 sentences max."
            )
            response = self.brain._call_api(Config.PRIMARY_BRAIN, prompt)
            return response or f"All done! You completed all {completed_steps} steps. Great work."

        return (
            f"Paused at step {paused_step}. "
            "Say 'walk me through' again whenever you want to pick it back up."
        )

    def _parse_steps(self, text: str) -> List[str]:
        steps = []
        for line in text.strip().split("\n"):
            line = line.strip()
            match = re.match(r"^\d+[\.)]\s*(.+)", line)
            if match:
                steps.append(match.group(1).strip())
        return steps

    def _is_next(self, text: str) -> bool:
        normalized = self._normalize(text)
        if not normalized:
            return False
        if self._is_stop(normalized):
            return False
        return normalized in self._NEXT_PHRASES or any(
            self._contains_phrase(normalized, phrase)
            for phrase in {"next step", "move on", "got it"}
        )

    def _is_stop(self, text: str) -> bool:
        normalized = self._normalize(text)
        if not normalized:
            return False
        return normalized in self._STOP_PHRASES or any(
            self._contains_phrase(normalized, phrase)
            for phrase in {"never mind", "forget it", "do not continue", "dont continue"}
        )
