"""
IRIS Autonomist
===============
Analyzes session logs at shutdown to extract user preferences
and project facts, persisting them to the knowledge base.
"""

import json
import os
import re
from pathlib import Path

from config import Config


class Autonomist:
    def __init__(self, brain):
        self.brain = brain
        self.kb_path = Path(__file__).resolve().parent.parent / "knowledge_base.json"

    def learn_from_session(self, history_file: str) -> None:
        """Analyzes a session log to extract new facts and preferences."""
        if not history_file or not os.path.exists(history_file):
            return

        with open(history_file, "r", encoding="utf-8") as f:
            content = f.read()

        if not content.strip():
            return

        learning_prompt = f"""Analyze the following conversation history:
---
{content[-4000:]}
---
Extract new facts about the user, the IRIS project, or coding preferences.
Respond ONLY with a JSON object of key-value pairs.
Example: {{"user_preference": "prefers rich panels", "project_goal": "RTX 5050 optimization"}}"""

        try:
            response = self.brain._call_api(Config.OLLAMA_MODEL_DEEP, learning_prompt)
            if not response:
                return
            json_match = re.search(r"\{.*\}", response, re.DOTALL)
            if not json_match:
                return
            new_knowledge = json.loads(json_match.group())
            self._update_kb(new_knowledge)
        except Exception:
            pass

    def _update_kb(self, data: dict) -> None:
        kb: dict = {}
        if self.kb_path.exists():
            try:
                with open(self.kb_path, "r", encoding="utf-8") as f:
                    kb = json.load(f)
            except Exception:
                kb = {}
        kb.update(data)
        with open(self.kb_path, "w", encoding="utf-8") as f:
            json.dump(kb, f, indent=4)