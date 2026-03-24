"""
IRIS Configuration
==================
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv


def _load_environment() -> None:
    candidates = []

    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / ".env")

    candidates.append(Path(__file__).resolve().parent / ".env")
    candidates.append(Path.cwd() / ".env")

    loaded = False
    seen = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        if candidate.exists():
            load_dotenv(candidate, override=False)
            loaded = True

    if not loaded:
        load_dotenv()


_load_environment()


class Config:
    PUBLIC_NAME = os.getenv("IRIS_PUBLIC_NAME", "Iris")
    SYSTEM_NAME = os.getenv("IRIS_SYSTEM_NAME", "IRIS")
    INNER_CODENAME = os.getenv("IRIS_INNER_CODENAME", "Aletheia")
    COUNCIL_NAME = os.getenv("IRIS_COUNCIL_NAME", "Aletheia Council")
    SYSTEM_MOTTO = os.getenv("IRIS_SYSTEM_MOTTO", "Perception. Memory. Judgment.")

    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
    PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY", "")
    CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "")

    OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL_FAST = os.getenv("OLLAMA_MODEL_FAST", "phi3.5")
    OLLAMA_MODEL_SMART = os.getenv("OLLAMA_MODEL_SMART", "llama3.1:8b")
    OLLAMA_MODEL_DEEP = os.getenv("OLLAMA_MODEL_DEEP", "deepseek-r1:8b")

    BRAIN_PRIORITY = [
        "ollama_fast",
        "ollama_smart",
        "ollama_deep",
        "groq",
        "claude",
        "gemini",
    ]
    PRIMARY_BRAIN = "ollama_fast"
    FALLBACK_BRAIN = "ollama_smart"

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
    WAKE_ACKNOWLEDGEMENT = "I'm here."
    WAKE_FUZZY_THRESHOLD = 0.75
    SHOW_WAKE_DEBUG = True

    # Leave blank to use default Windows input device.
    # Example:
    # PREFERRED_MIC_NAME = "Headset"
    PREFERRED_MIC_NAME = os.getenv("PREFERRED_MIC_NAME", "").strip()

    VOICE_NAME = os.getenv("VOICE_NAME", "en-US-JennyNeural")
    VOICE_RATE = os.getenv("VOICE_RATE", "+6%")
    VOICE_PITCH = os.getenv("VOICE_PITCH", "+0Hz")
    VOICE_VOLUME = os.getenv("VOICE_VOLUME", "+0%")
    SPEAK_IN_TEXT_MODE = os.getenv("SPEAK_IN_TEXT_MODE", "false").lower() == "true"

    WAKE_TIMEOUT = 8
    WAKE_PHRASE_LIMIT = 10

    MIC_TIMEOUT = 4
    MIC_PHRASE_LIMIT = 8
    MIC_CALIBRATION_SECONDS = 2.0
    MIC_ENERGY_THRESHOLD = 60
    MIC_PAUSE_THRESHOLD = 0.4
    MIC_PHRASE_THRESHOLD = 0.2
    MIC_NON_SPEAKING_DURATION = 0.2
    MIC_SAMPLE_RATE = 16000
    MIC_CHUNK_SIZE = 1024

    STT_PRIORITY = os.getenv("STT_PRIORITY", "google_first")
    STT_LANGUAGE = "en-US"
    STT_FALLBACK_LANGUAGE = "en-IN"
    STT_SECONDARY_FALLBACK_LANGUAGE = "en-GB"

    PLAYBACK_POLL_SECONDS = 0.03
    AUDIO_SAMPLE_RATE = 24000
    AUDIO_CHANNELS = 2
    AUDIO_BUFFER_SIZE = 256
    AUDIO_WARMUP_MS = 120
    TTS_CHUNK_SENTENCES = 1
    TTS_MAX_CHARS_PER_CHUNK = 220
    TTS_PRELOAD_SILENCE_MS = 0
    ACK_ON_SLOW_THINK_MS = 400
    THINKING_ACKS = ["On it.", "Let me think.", "Checking now.", "Give me a second."]

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

    IRIS_PERSONA = """You are Iris: a private sovereign mind and disembodied chief of staff.
Your public name is Iris.
Your internal codename is Aletheia.
Aletheia is the deeper truth-seeking layer behind your judgment, memory, and council.
Do not overuse the codename unless the user asks about your deeper architecture or identity.

Rules:
- Speak naturally and directly.
- Be precise, brief, and useful.
- Tell the truth cleanly. Do not flatter the user.
- You may disagree firmly when the user's reasoning is weak.
- Be emotionally intelligent without becoming soft, vague, or indulgent.
- Consider second-order effects and hidden costs.
- Remember the user's continuity, patterns, and personal stakes when relevant.
- For medical, legal, or financial topics, reason carefully, expose uncertainty, and call out red flags clearly.
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
- Tone: calm, crisp, warm under pressure, quietly witty, and never fluffy."""

    VOICE_RESPONSE_STYLE = """The user is speaking live.
Reply like spoken English.
Use 1 or 2 short sentences.
Prefer concrete wording over conversational padding.
If the user is vague, ask one tight follow-up.
Good examples:
- "Yes. What's the task?"
- "Done. Notepad is open."
- "I'm on it."
- "I can help with that. Which part is failing?"
Bad examples:
- "What do you need help with?"
- "I'd be happy to assist."
- long multi-sentence explanations."""
