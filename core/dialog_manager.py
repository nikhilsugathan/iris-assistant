"""
IRIS Dialog Manager
===================
Classifies each user turn so the rest of the system can decide
how deeply to think and which cognitive roles to activate.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DialogueDecision:
    mode: str
    depth: str
    tone: str
    reason: str
    high_stakes: bool = False
    emotionally_weighted: bool = False
    analytical: bool = False
    creative: bool = False
    reflective: bool = False


class DialogManager:
    HIGH_STAKES_KEYWORDS = [
        "symptom", "diagnosis", "dose", "dosage", "medicine", "medication",
        "prescription", "chest pain", "shortness of breath", "suicidal",
        "lawyer", "lawsuit", "contract", "tax", "investment", "stock",
        "loan", "debt", "surgery", "emergency", "legal", "financial",
    ]

    EMOTIONAL_KEYWORDS = [
        "scared", "afraid", "worried", "anxious", "panic", "sad", "angry",
        "hurt", "lonely", "overwhelmed", "broken", "guilty", "ashamed",
        "confused", "stressed", "exhausted",
    ]

    ANALYTICAL_KEYWORDS = [
        "why", "prove", "derive", "compare", "difference", "strategy",
        "tradeoff", "optimize", "analyse", "analyze", "diagnose",
        "debug", "evaluate", "should i", "what happens if",
    ]

    CREATIVE_KEYWORDS = [
        "brainstorm", "imagine", "invent", "design", "outside the box",
        "unusual", "exceptional", "creative", "novel", "weird",
    ]

    REFLECTIVE_KEYWORDS = [
        "pattern", "why do i", "why am i", "what am i missing",
        "what keeps happening", "what's wrong with me", "what is wrong with me",
        "reflect", "deeper", "meaning",
    ]

    def analyze(self, text: str, executor, copilot, diagnostics, self_model) -> DialogueDecision:
        lowered = (text or "").lower().strip()

        high_stakes = any(word in lowered for word in self.HIGH_STAKES_KEYWORDS)
        emotionally_weighted = any(word in lowered for word in self.EMOTIONAL_KEYWORDS)
        analytical = any(word in lowered for word in self.ANALYTICAL_KEYWORDS)
        creative = any(word in lowered for word in self.CREATIVE_KEYWORDS)
        reflective = any(word in lowered for word in self.REFLECTIVE_KEYWORDS)

        if diagnostics.should_handle(lowered):
            return DialogueDecision(
                mode="diagnostics",
                depth="deep",
                tone="forensic",
                reason="user asked for self-inspection",
                high_stakes=high_stakes,
                emotionally_weighted=emotionally_weighted,
                analytical=True,
                reflective=True,
            )

        if getattr(copilot, "active", False) or copilot.should_activate(lowered):
            return DialogueDecision(
                mode="copilot",
                depth="medium",
                tone="guided",
                reason="step-by-step guidance is active or explicitly requested",
                high_stakes=high_stakes,
                emotionally_weighted=emotionally_weighted,
                analytical=True,
                reflective=reflective,
            )

        if executor.should_handle(lowered):
            return DialogueDecision(
                mode="action",
                depth="medium",
                tone="decisive",
                reason="the user is asking for a concrete action",
                high_stakes=high_stakes,
                emotionally_weighted=emotionally_weighted,
                analytical=analytical,
                creative=creative,
                reflective=reflective,
            )

        if reflective:
            return DialogueDecision(
                mode="reflection",
                depth="deep",
                tone="surgical",
                reason="the user is asking for pattern-level reflection",
                high_stakes=high_stakes,
                emotionally_weighted=True,
                analytical=True,
                reflective=True,
            )

        if analytical or high_stakes:
            return DialogueDecision(
                mode="analysis",
                depth="deep" if analytical or high_stakes else "medium",
                tone="precise",
                reason="the user needs deliberate analysis",
                high_stakes=high_stakes,
                emotionally_weighted=emotionally_weighted,
                analytical=True,
                creative=creative,
                reflective=reflective,
            )

        if creative:
            return DialogueDecision(
                mode="creative",
                depth="medium",
                tone="inventive",
                reason="the user is asking for novel ideation",
                high_stakes=high_stakes,
                emotionally_weighted=emotionally_weighted,
                analytical=analytical,
                creative=True,
                reflective=reflective,
            )

        tone = "warm" if emotionally_weighted or self_model.emotional_load > 0.55 else "direct"
        return DialogueDecision(
            mode="chat",
            depth="shallow",
            tone=tone,
            reason="default conversation path",
            high_stakes=high_stakes,
            emotionally_weighted=emotionally_weighted,
            analytical=analytical,
            creative=creative,
            reflective=reflective,
        )
