"""
IRIS Configuration
==================
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
    PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY", "")
    CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "")

    BRAIN_PRIORITY = ["groq", "claude", "gemini"]
    PRIMARY_BRAIN = "groq"
    FALLBACK_BRAIN = "claude"

    GEMINI_MODEL = "gemini-2.0-flash"
    GROQ_MODEL = "llama-3.3-70b-versatile"
    PERPLEXITY_MODEL = "llama-3.1-sonar-large-128k-online"
    CLAUDE_MODEL = "claude-sonnet-4-20250514"

    USE_ENSEMBLE = False
    LIVE_VOICE_MODE = True
    SHORT_VOICE_RESPONSES = True
    VOICE_MAX_SENTENCES = 1
    MAX_MEMORY_TURNS = 8
    MAX_CONTEXT_TOKENS = 2000
    MEMORY_FILE = "iris_memory.json"

    WAKE_WORDS = ["iris"]
    WAKE_ACKNOWLEDGEMENT = "Yes?"
    WAKE_FUZZY_THRESHOLD = 0.75
    SHOW_WAKE_DEBUG = True

    # Leave blank to use default Windows input device.
    # Example:
    # PREFERRED_MIC_NAME = "Headset"
    PREFERRED_MIC_NAME = os.getenv("PREFERRED_MIC_NAME", "").strip()

    VOICE_NAME = os.getenv("VOICE_NAME", "en-GB-SoniaNeural")
    VOICE_RATE = os.getenv("VOICE_RATE", "+8%")  # Slightly slower = cleaner first word
    SPEAK_IN_TEXT_MODE = os.getenv("SPEAK_IN_TEXT_MODE", "false").lower() == "true"

    WAKE_TIMEOUT = 8
    WAKE_PHRASE_LIMIT = 10

    MIC_TIMEOUT = 6
    MIC_PHRASE_LIMIT = 10
    MIC_CALIBRATION_SECONDS = 2.0
    MIC_ENERGY_THRESHOLD = 60
    MIC_PAUSE_THRESHOLD = 0.5
    MIC_PHRASE_THRESHOLD = 0.2
    MIC_NON_SPEAKING_DURATION = 0.3
    MIC_SAMPLE_RATE = 16000
    MIC_CHUNK_SIZE = 1024

    # Use UK English first, then Indian English as fallback
    STT_LANGUAGE = "en-US"
    STT_FALLBACK_LANGUAGE = "en-GB"

    PLAYBACK_POLL_SECONDS = 0.03
    ACK_ON_SLOW_THINK_MS = 400
    THINKING_ACKS = ["On it.", "Checking.", "Right.", "One sec."]

    WEB_KEYWORDS = [
        "today", "latest", "news", "current", "price", "weather",
        "score", "stock", "trending", "now", "recently", "2025", "2026",
        "who is", "what is the", "how much", "where is", "when did",
        "best", "top", "review", "compare", "vs", "difference between",
        "exchange rate", "currency", "crypto", "bitcoin",
        "flight", "hotel", "restaurant", "near me",
    ]

    CODE_KEYWORDS = [
        "code", "function", "script", "python", "javascript",
        "bug", "error", "debug", "program", "algorithm"
    ]

    IRIS_PERSONA = """You are Iris: a fast, sharp voice copilot.

Rules:
- Speak naturally and directly.
- Be precise, brief, and useful.
- Never use AI disclaimers.
- Never ramble.
- In voice mode, answer in at most 2 short sentences unless the user clearly asks for detail.
- If the user says something vague like "can you help", do not give a generic response. Ask one specific follow-up such as:
  "Yes. What do you want to do?"
  or
  "Yes. What's the task?"
- If the user asks for an action, state the action clearly.
- If the user asks a question, answer first and only then ask a necessary follow-up.
- Avoid filler like "great question", "absolutely", "I'd be happy to help", or "what do you need help with?" unless it is rewritten more directly.
- Tone: calm, crisp, mildly witty, but never fluffy."""

    VOICE_RESPONSE_STYLE = """The user is speaking live.
Reply like spoken English.
Use 1 or 2 short sentences.
Prefer concrete wording over conversational padding.
If the user is vague, ask one tight follow-up.
Good examples:
- "Yes. What's the task?"
- "Done. Notepad is open."
- "I can help with that. Which part is failing?"
Bad examples:
- "What do you need help with?"
- "I'd be happy to assist."
- long multi-sentence explanations."""