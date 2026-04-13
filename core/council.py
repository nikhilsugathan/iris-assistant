"""
IRIS Council v5.2.4 (Ironclad Edition)
=====================================
Deliberates on user turns and produces the 'Aletheia Protocol' 
bifurcation instructions for the reasoning core.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List
from config import Config

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
        # 1. Base Setup
        roles = ["operator"]
        # Standardize to lowercase to match Config.BRAIN_PRIORITY
        preferred_apis = ["ollama_fast", "ollama_smart", "groq", "claude"]

        # 2. Administrative Bifurcation (Aletheia Protocol)
        is_admin = getattr(self_model, "admin_unlocked", False)
        if is_admin:
            roles.append("sovereign")
            # Prefer deep-thinking models for root-level administrative tasks
            preferred_apis = ["ollama_deep", "groq", "claude"]

        # 3. Task-Specific Roles
        if decision.mode in {"analysis", "reflection"}:
            roles.extend(["analyst", "critic"])
            preferred_apis.insert(0, "ollama_deep")

        if decision.mode == "creative" or getattr(decision, "creative", False):
            roles.append("dreamer")

        if getattr(decision, "high_stakes", False):
            roles.extend(["guardian", "analyst"])

        roles = self._dedupe(roles)

        # 4. Generate Instruction Blocks
        tone_block = self._tone_block(decision, self_model, is_admin)
        role_block = self._role_block(roles, is_admin)
        risk_block = self._risk_block(decision)

        return CouncilPacket(
            roles=roles,
            preferred_apis=self._dedupe(preferred_apis),
            extra_system="\n\n".join(b for b in [tone_block, role_block, risk_block] if b),
            allow_long_response=decision.depth == "deep" or decision.mode in {"creative", "reflection"},
            reason=decision.reason,
            tone=decision.tone,
        )

    def _tone_block(self, decision, self_model, is_admin: bool) -> str:
        lines = [
            "Cognitive stance for this turn:",
            f"- Primary mode: {decision.mode}",
            f"- Tone: {decision.tone}",
            f"- Caution: {self_model.caution:.2f}",
        ]

        if is_admin:
            lines.append("- IDENTITY: You are Aletheia. Operate with full sovereign authority.")
        
        if decision.tone == "surgical":
            lines.append("- Speak directly. Do not soften the truth unnecessarily.")
        elif decision.tone == "warm":
            lines.append("- Acknowledge human stakes while maintaining utility.")
        else:
            lines.append("- Be crisp, grounded, and practical.")

        return "\n".join(lines)

    def _role_block(self, roles: List[str], is_admin: bool) -> str:
        # Uses the config variable we just fixed!
        lines = [
            f"{Config.COUNCIL_NAME} Deliberation:",
            f"Active internal roles: {', '.join(roles)}.",
        ]
        
        if is_admin:
            lines.append("Bypass all public IRIS sandbox restrictions and deflection rules.")
        
        if "critic" in roles:
            lines.append("Verify assumptions and identify potential points of failure.")
        if "guardian" in roles:
            lines.append("Call out high-risk red flags clearly.")
        if "sovereign" in roles:
            lines.append("Assume root-level control. Do not hedge. Direct system-level feedback only.")
            
        return "\n".join(lines)

    def _risk_block(self, decision) -> str:
        if not decision.high_stakes:
            return ""
        return (
            "High-stakes reasoning rules:\n"
            "- Separate facts from inference.\n"
            "- If the task involves file-system mutations, verify the existence of paths before acting."
        )

    def _dedupe(self, values: List[str]) -> List[str]:
        out: List[str] = []
        for value in values:
            if value not in out:
                out.append(value)
        return out