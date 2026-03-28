"""
IRIS Council Layer
==================
Synthesizes expert insights before the Brain responds.
"""
from dataclasses import dataclass, field
from typing import List

try:
    from core import logger
except ImportError:
    import logging as logger

@dataclass
class CouncilPacket:
    """The strict data contract expected by the Brain and main.py"""
    roles: List[str] = field(default_factory=list)
    preferred_apis: List[str] = field(default_factory=list)
    extra_system: str = ""
    allow_long_response: bool = False
    reason: str = ""
    tone: str = "direct"

class Council:
    def __init__(self):
        self.experts = {
            "analyst": "Logical", 
            "strategist": "Long-term", 
            "critic": "Skeptical"
        }

    def deliberate(self, user_input: str, decision, self_model) -> CouncilPacket:
        """
        The Ironclad Handshake: Takes input from the DialogManager and SelfModel,
        and returns a strict CouncilPacket for the Brain to ingest.
        """
        packet = CouncilPacket()
        
        # Determine which experts to use
        packet.roles = list(self.experts.keys())
        
        # Safely extract context from the DialogManager's decision
        packet.reason = getattr(decision, "reason", "standard processing")
        packet.tone = getattr(decision, "tone", "direct")
        packet.allow_long_response = getattr(decision, "depth", "normal") in ["deep", "comprehensive"]
        
        return packet