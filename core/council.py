"""
IRIS Council Layer
==================
Synthesizes expert insights before the Brain responds.
"""
from core import logger

class Council:
    def __init__(self):
        self.experts = {"analyst": "Logical", "strategist": "Long-term", "critic": "Skeptical"}

    def generate_packet(self, user_input):
        """Audit Fix: Resolves AttributeError in main.py."""
        logger.info(f"[COUNCIL] Processing reasoning for: {user_input}")
        return {
            "task": user_input,
            "experts": list(self.experts.keys()),
            "responses": {}
        }