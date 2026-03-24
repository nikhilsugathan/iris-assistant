"""
IRIS Council
============
Selects which internal roles should be active for a given user turn
and produces guidance for the brain.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class CouncilPacket:
    roles: List[str] = field(default_factory=list)
    preferred_apis: List[str] = field(default_factory=list)
    extra_system: str = ""
    allow_long_response: bool = False
    reason: str = ""
    tone: str = "direct"


class Council:
    def deliberate(self, user_input: str, decision, self_model) -> CouncilPacket:
        roles = ["operator"]
        preferred_apis = ["ollama_fast", "ollama_smart", "groq", "claude"]

        if decision.mode in {"analysis", "reflection"}:
            roles.extend(["analyst", "critic"])
            preferred_apis = ["ollama_deep", "ollama_smart", "groq", "claude", "ollama_fast"]

        if decision.mode == "creative" or getattr(decision, "creative", False):
            roles.append("dreamer")
            preferred_apis = ["ollama_smart", "ollama_fast", "groq", "claude"]

        if getattr(decision, "high_stakes", False):
            roles.extend(["guardian", "analyst"])
            preferred_apis = ["ollama_deep", "ollama_smart", "claude", "groq", "ollama_fast"]

        if getattr(decision, "emotionally_weighted", False):
            roles.append("historian")

        roles = self._dedupe(roles)

        tone_block = self._tone_block(decision, self_model)
        role_block = self._role_block(roles)
        risk_block = self._risk_block(decision)

        packet = CouncilPacket(
            roles=roles,
            preferred_apis=self._dedupe(preferred_apis),
            extra_system="\n\n".join(block for block in [tone_block, role_block, risk_block] if block),
            allow_long_response=decision.depth == "deep" or decision.mode in {"creative", "reflection"},
            reason=decision.reason,
            tone=decision.tone,
        )
        return packet

    def _tone_block(self, decision, self_model) -> str:
        lines = [
            "Cognitive stance for this turn:",
            f"- Primary mode: {decision.mode}",
            f"- Tone: {decision.tone}",
            f"- Emotional load: {self_model.emotional_load:.2f}",
            f"- Caution: {self_model.caution:.2f}",
        ]

        if decision.tone == "surgical":
            lines.append("- Speak clearly and directly. Do not soften the truth unnecessarily.")
        elif decision.tone == "warm":
            lines.append("- Acknowledge the human stakes, but stay clear and useful.")
        elif decision.tone == "inventive":
            lines.append("- Prefer original, elegant thinking over generic brainstorming.")
        else:
            lines.append("- Be crisp, grounded, and practical.")

        if decision.reflective:
            lines.append("- Go below the surface issue and identify the underlying pattern.")

        return "\n".join(lines)

    def _role_block(self, roles: List[str]) -> str:
        lines = [f"Active internal roles: {', '.join(roles)}."]
        if "critic" in roles:
            lines.append("Check for weak assumptions and say what could go wrong.")
        if "dreamer" in roles:
            lines.append("Offer at least one non-obvious option if it helps.")
        if "guardian" in roles:
            lines.append("For high-stakes topics, avoid false certainty and call out red flags clearly.")
        if "historian" in roles:
            lines.append("Remember the user's emotional and personal continuity.")
        return "\n".join(lines)

    def _risk_block(self, decision) -> str:
        if not decision.high_stakes:
            return ""

        return (
            "High-stakes reasoning rules:\n"
            "- State likely interpretations, not fake certainty.\n"
            "- Separate facts, inference, and urgency.\n"
            "- If this is medical, legal, or financial, mention when real-world escalation is warranted."
        )

    def _dedupe(self, values: List[str]) -> List[str]:
        out: List[str] = []
        for value in values:
            if value not in out:
                out.append(value)
        return out
