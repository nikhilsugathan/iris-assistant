"""
IRIS Configuration
==================
"""

import os
import sys
from dotenv import load_dotenv

load_dotenv()


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
    CLAUDE_MODEL = "claude-3-5-sonnet-20241022"

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
    AUDIO_SAMPLE_RATE = 24000
    AUDIO_CHANNELS = 2
    AUDIO_BUFFER_SIZE = 512
    AUDIO_WARMUP_MS = 120
    TTS_CHUNK_SENTENCES = 1
    TTS_MAX_CHARS_PER_CHUNK = 220
    TTS_PRELOAD_SILENCE_MS = 0
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
- Tone: calm, crisp, slightly formidable, mildly witty, but never fluffy."""

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

    # ───────────────────────────────────────────────────────────
    # STARTUP VALIDATION
    # ───────────────────────────────────────────────────────────
    @classmethod
    def validate(cls):
        """Check configuration at startup and warn about problems."""
        warnings = []
        errors = []

        # At least one LLM provider must be configured
        has_cloud_key = any([
            cls.GROQ_API_KEY,
            cls.GEMINI_API_KEY,
            cls.CLAUDE_API_KEY,
            cls.PERPLEXITY_API_KEY,
        ])

        if not has_cloud_key:
            warnings.append(
                "No cloud API keys set. IRIS will only work if Ollama is running locally. "
                "Set at least GROQ_API_KEY in your .env file for cloud fallback."
            )

        # Groq is needed for STT (Whisper)
        if not cls.GROQ_API_KEY:
            warnings.append(
                "GROQ_API_KEY is empty. Voice commands will fall back to Google STT "
                "(slower, less accurate). Groq Whisper is the recommended STT provider."
            )

        # Check .env file exists
        if not os.path.exists(".env"):
            warnings.append(
                "No .env file found. Copy .env.example to .env and fill in your keys: "
                "cp .env.example .env"
            )

        # Print results
        if errors:
            for e in errors:
                print(f"  [FATAL] {e}")
            sys.exit(1)

        if warnings:
            print("  ── Config Warnings ──")
            for w in warnings:
                print(f"  [!] {w}")
            print()

        return len(warnings) == 0

