import json
import os
import re
from datetime import datetime
from config import Config
from core.logger import get_logger

logger = get_logger("Autonomist")

class Autonomist:
    def __init__(self, brain):
        self.brain = brain
        # FIX: Anchor kb_path to an absolute path so it always lands in the
        # project root regardless of the working directory at launch time.
        _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.kb_path = os.path.join(_root, "knowledge_base.json")

    def learn_from_session(self, history_file: str):
        """Analyzes session logs to extract new facts and preferences."""
        if not os.path.exists(history_file):
            return

        with open(history_file, 'r', encoding='utf-8') as f:
            content = f.read()

        learning_prompt = f"""
        Analyze the following conversation history:
        ---
        {content[-4000:]} 
        ---
        Extract new facts about the user (Nikhil), the IRIS project, or coding preferences.
        Respond ONLY with a JSON object of key-value pairs. 
        Example: {{"user_preference": "prefers rich panels", "project_goal": "RTX 5050 optimization"}}
        """

        # require_json=True: the prompt demands a bare JSON object.
        # Grammar armor engages on the llama_cpp path; cloud APIs ignore the flag.
        # Low temperature (0.2) suppresses creative drift in key-value extraction.
        response = self.brain._call_api_with_settings(
            Config.PRIMARY_BRAIN,
            learning_prompt,
            settings={"require_json": True, "max_tokens": 512, "temperature": 0.2},
        )

        if not response:
            return

        try:
            json_str = re.search(r"\{.*\}", response, re.DOTALL).group()
            new_knowledge = json.loads(json_str)
            self._update_kb(new_knowledge)
        except Exception as _learn_err:
            logger.warning("[Autonomist] learn_from_session parse/update failed: %s", _learn_err)

    def _update_kb(self, data: dict):
        kb = {}
        if os.path.exists(self.kb_path):
            with open(self.kb_path, 'r', encoding='utf-8') as f: kb = json.load(f)

        kb.update(data)
        with open(self.kb_path, 'w', encoding='utf-8') as f:
            json.dump(kb, f, indent=4)