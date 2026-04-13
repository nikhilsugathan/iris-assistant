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

    # Web-search intent — must fire BEFORE executor.should_handle() to avoid
    # "search for" / "look up" being hijacked as OS-level shell actions.
    WEB_SEARCH_KEYWORDS = [
        "search for", "look up", "google", "find online", "search online",
        "search the web", "browse for", "search web", "look online",
    ]

    def analyze(self, text: str, executor, copilot, diagnostics, self_model) -> DialogueDecision:
        lowered = (text or "").lower().strip()

        high_stakes = any(word in lowered for word in self.HIGH_STAKES_KEYWORDS)
        emotionally_weighted = any(word in lowered for word in self.EMOTIONAL_KEYWORDS)
        analytical = any(word in lowered for word in self.ANALYTICAL_KEYWORDS)
        creative = any(word in lowered for word in self.CREATIVE_KEYWORDS)
        reflective = any(word in lowered for word in self.REFLECTIVE_KEYWORDS)

        # 1. State Interception: Is the Action Executor waiting for a response?
        is_waiting = False
        for state_check in ["waiting_for_permission", "waiting_for_followup", "waiting_for_clarification", "waiting_for_plan_choice"]:
            if hasattr(executor, state_check) and getattr(executor, state_check)():
                is_waiting = True
                break

        if is_waiting:
            return DialogueDecision(
                mode="action_pending",
                depth="shallow",
                tone="direct",
                reason="routing user response back to waiting action executor",
                high_stakes=high_stakes,
                emotionally_weighted=False,
                analytical=False,
                creative=False,
                reflective=False
            )

        # 2. Diagnostics
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

        # 3. Copilot
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

        # 3.5. Web Search — must precede action check so "search for" / "look up"
        # are not hijacked as OS-level shell actions by executor.should_handle().
        if any(kw in lowered for kw in self.WEB_SEARCH_KEYWORDS):
            return DialogueDecision(
                mode="search",
                depth="shallow",
                tone="direct",
                reason="user is requesting a web search",
                high_stakes=high_stakes,
                emotionally_weighted=emotionally_weighted,
                analytical=analytical,
                creative=creative,
                reflective=reflective,
            )

        # 4. Action Initialization
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

        # 5. Reflection
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

        # 6. Analysis
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

        # 7. Creative
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

        # 8. Chat Fallback
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