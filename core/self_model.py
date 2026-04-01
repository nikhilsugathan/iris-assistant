"""
IRIS Self Model
===============
Tracks internal state so IRIS can reason about how she should respond,
how cautious she should be, and when she should escalate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class SelfModel:
    confidence: float = 0.68
    urgency: float = 0.28
    caution: float = 0.42
    warmth: float = 0.44
    initiative_budget: float = 0.50
    emotional_load: float = 0.20
    cognitive_mode: str = "idle"
    last_reason: str = "startup"
    active_roles: List[str] = field(default_factory=list)
    recent_friction: List[str] = field(default_factory=list)
    admin_unlocked: bool = False

    def observe_user_input(self, text: str, decision) -> None:
        lowered = (text or "").lower()
        self.cognitive_mode = getattr(decision, "mode", "chat")
        self.last_reason = getattr(decision, "reason", "general conversation")

        if getattr(decision, "high_stakes", False):
            self.caution = self._clamp(self.caution + 0.15)
            self.confidence = self._clamp(self.confidence - 0.06)

        if getattr(decision, "emotionally_weighted", False):
            self.emotional_load = self._clamp(self.emotional_load + 0.18)
            self.warmth = self._clamp(self.warmth + 0.10)
        else:
            self.emotional_load = self._clamp(self.emotional_load - 0.03)

        if any(word in lowered for word in ["urgent", "now", "asap", "immediately", "quickly"]):
            self.urgency = self._clamp(self.urgency + 0.20)
        else:
            self.urgency = self._clamp(self.urgency - 0.02)

        if getattr(decision, "mode", "") == "action":
            self.initiative_budget = self._clamp(self.initiative_budget - 0.04)
        else:
            self.initiative_budget = self._clamp(self.initiative_budget + 0.01)

    def apply_council(self, roles: List[str]) -> None:
        self.active_roles = roles[:]

    def note_response(self, response: str, source: str | None = None) -> None:
        text = (response or "").strip()
        if not text:
            self.confidence = self._clamp(self.confidence - 0.08)
            self.recent_friction.append("empty-response")
            self.recent_friction = self.recent_friction[-6:]
            return

        if source in {"fallback", "error"}:
            self.confidence = self._clamp(self.confidence - 0.10)
            self.recent_friction.append(f"response:{source}")
            self.recent_friction = self.recent_friction[-6:]
        else:
            self.confidence = self._clamp(self.confidence + 0.03)

        self.urgency = self._clamp(self.urgency - 0.05)

    def note_failure(self, summary: str) -> None:
        self.caution = self._clamp(self.caution + 0.12)
        self.confidence = self._clamp(self.confidence - 0.10)
        self.recent_friction.append(summary[:80])
        self.recent_friction = self.recent_friction[-6:]

    def note_success(self, summary: str) -> None:
        self.confidence = self._clamp(self.confidence + 0.05)
        self.recent_friction = [item for item in self.recent_friction if item != summary[:80]][-6:]

    def snapshot(self) -> dict:
        return {
            "confidence": round(self.confidence, 2),
            "urgency": round(self.urgency, 2),
            "caution": round(self.caution, 2),
            "warmth": round(self.warmth, 2),
            "initiative_budget": round(self.initiative_budget, 2),
            "emotional_load": round(self.emotional_load, 2),
            "cognitive_mode": self.cognitive_mode,
            "last_reason": self.last_reason,
            "active_roles": self.active_roles[:],
            "recent_friction": self.recent_friction[-3:],
        }

    def summary(self) -> str:
        if self.admin_unlocked:
            return (
                f"[Aletheia admin mode] mode={self.cognitive_mode}, "
                f"confidence={self.confidence:.2f}, caution={self.caution:.2f}, "
                f"urgency={self.urgency:.2f}"
            )
        return (
            f"IRIS mode={self.cognitive_mode}, confidence={self.confidence:.2f}, "
            f"caution={self.caution:.2f}, urgency={self.urgency:.2f}"
        )

    def _clamp(self, value: float, low: float = 0.0, high: float = 1.0) -> float:
        return max(low, min(high, value))
