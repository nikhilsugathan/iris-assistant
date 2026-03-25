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
    LOCATION_NAME_OVERRIDE = os.getenv("IRIS_LOCATION_NAME", "").strip()
    LATITUDE_OVERRIDE = os.getenv("IRIS_LATITUDE", "").strip()
    LONGITUDE_OVERRIDE = os.getenv("IRIS_LONGITUDE", "").strip()
    ONLINE_LOCATION_NAME_ENRICHMENT = os.getenv("ONLINE_LOCATION_NAME_ENRICHMENT", "false").lower() == "true"
    ENVIRONMENT_CACHE_FILE = os.getenv("IRIS_ENVIRONMENT_CACHE_FILE", "iris_environment_cache.json").strip()

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
    PERPLEXITY_MODEL = "sonar-pro"
    CLAUDE_MODEL = "claude-sonnet-4-20250514"

    USE_ENSEMBLE = False
    LIVE_VOICE_MODE = True
    SHORT_VOICE_RESPONSES = True
    VOICE_MAX_SENTENCES = 1
    MAX_MEMORY_TURNS = 8
    MAX_CONTEXT_TOKENS = 2000
    MEMORY_FILE = "iris_memory.json"
    PREFER_LOCAL_RESOURCES = os.getenv("PREFER_LOCAL_RESOURCES", "true").lower() == "true"
    LOCAL_RESOURCE_GUARD_ENABLED = os.getenv("LOCAL_RESOURCE_GUARD_ENABLED", "true").lower() == "true"
    LOCAL_RESOURCE_SAMPLE_TTL_SECONDS = int(os.getenv("LOCAL_RESOURCE_SAMPLE_TTL_SECONDS", "20"))
    LOCAL_RESOURCE_MIN_FREE_MEMORY_GB = float(os.getenv("LOCAL_RESOURCE_MIN_FREE_MEMORY_GB", "1.25"))
    LOCAL_RESOURCE_MIN_BATTERY_PERCENT = int(os.getenv("LOCAL_RESOURCE_MIN_BATTERY_PERCENT", "15"))
    LOCAL_RESOURCE_MIN_BATTERY_PERCENT_FOR_GEO = int(os.getenv("LOCAL_RESOURCE_MIN_BATTERY_PERCENT_FOR_GEO", "8"))

    WAKE_WORDS = ["iris"]
    WAKE_WORD_ALIASES = {
        "iris": ["it", "eris", "airis", "heiress", "irish"],
    }
    WAKE_ACKNOWLEDGEMENT = "I'm here."
    WAKE_ACK_TTS_BACKEND_PRIORITY = os.getenv("WAKE_ACK_TTS_BACKEND_PRIORITY", "system_first").strip().lower()
    WAKE_FUZZY_THRESHOLD = 0.75
    SHOW_WAKE_DEBUG = True
    STARTUP_GREETING_ENABLED = os.getenv("STARTUP_GREETING_ENABLED", "true").lower() == "true"
    STARTUP_GREETING_DELAY_MS = int(os.getenv("STARTUP_GREETING_DELAY_MS", "250"))
    STARTUP_LISTEN_AFTER_GREETING_MS = int(os.getenv("STARTUP_LISTEN_AFTER_GREETING_MS", "180"))
    STARTUP_GREETINGS = [
        "Systems online.",
        "Online and ready.",
        "I'm up.",
        "Ready when you are.",
    ]
    GREETING_RESPONSES = [
        "I'm here.",
        "Mm-hm. I'm listening.",
        "Oh yeah. Go on.",
        "Online. What do you need?",
    ]
    HELP_RESPONSES = [
        "Mm-hm. What's the task?",
        "Sure. What are we fixing?",
        "All right. What's the move?",
        "Go ahead. What's broken?",
    ]
    STATUS_RESPONSES = [
        "Operational. What do you need?",
        "Running fine. What's the task?",
        "Operational. Mildly sarcastic, fully functional.",
    ]
    THANKS_RESPONSES = [
        "You're welcome.",
        "Mm-hm.",
        "Any time.",
        "Try not to make it a habit.",
    ]
    HOLD_ACKS = [
        "All right.",
        "Mm-hm.",
        "Right.",
    ]
    SEARCH_ACKS = [
        "Checking.",
        "Mm-hm. Checking.",
        "Oh yeah. One second.",
        "Right. Let me look.",
    ]

    # Leave blank to use default Windows input device.
    # Example:
    # PREFERRED_MIC_NAME = "Headset"
    PREFERRED_MIC_NAME = os.getenv("PREFERRED_MIC_NAME", "").strip()

    VOICE_NAME = os.getenv("VOICE_NAME", "en-US-JennyNeural")
    LOCAL_TTS_VOICE_HINT = os.getenv("LOCAL_TTS_VOICE_HINT", "zira").strip()
    TTS_BACKEND_PRIORITY = os.getenv("TTS_BACKEND_PRIORITY", "edge_first").strip().lower()
    VOICE_RATE = os.getenv("VOICE_RATE", "-4%")
    VOICE_PITCH = os.getenv("VOICE_PITCH", "+0Hz")
    VOICE_VOLUME = os.getenv("VOICE_VOLUME", "+10%")
    SPEAK_IN_TEXT_MODE = os.getenv("SPEAK_IN_TEXT_MODE", "false").lower() == "true"

    WAKE_TIMEOUT = 4
    WAKE_PHRASE_LIMIT = 6
    VOICE_FOLLOWUP_TURNS = 4

    MIC_TIMEOUT = 5
    MIC_PHRASE_LIMIT = 10
    MIC_CALIBRATION_SECONDS = 2.0
    MIC_RECALIBRATION_QUICK_SECONDS = 0.35
    MIC_AUTO_RECALIBRATE_SECONDS = 180
    MIC_RECALIBRATE_ON_FAILURES = 2
    MIC_DYNAMIC_ENERGY_THRESHOLD = True
    MIC_DYNAMIC_ENERGY_ADJUSTMENT_DAMPING = 0.18
    MIC_DYNAMIC_ENERGY_RATIO = 1.6
    MIC_ENERGY_THRESHOLD = 60
    MIC_PAUSE_THRESHOLD = 0.55
    MIC_PHRASE_THRESHOLD = 0.2
    MIC_NON_SPEAKING_DURATION = 0.3
    MIC_SAMPLE_RATE = 16000
    MIC_CHUNK_SIZE = 1024

    WAKE_STT_PRIORITY = os.getenv("WAKE_STT_PRIORITY", "system_first").strip().lower()
    STT_PRIORITY = os.getenv("STT_PRIORITY", "groq_first").strip().lower()
    STT_LANGUAGE = os.getenv("STT_LANGUAGE", "en-US").strip()
    STT_FALLBACK_LANGUAGE = os.getenv("STT_FALLBACK_LANGUAGE", "en-GB").strip()
    STT_SECONDARY_FALLBACK_LANGUAGE = os.getenv("STT_SECONDARY_FALLBACK_LANGUAGE", "en-IN").strip()
    STT_ADDITIONAL_LANGUAGES = [
        lang.strip()
        for lang in os.getenv("STT_ADDITIONAL_LANGUAGES", "de-DE").split(",")
        if lang.strip()
    ]
    WAKE_SYSTEM_ACCEPT_CONFIDENCE = float(os.getenv("WAKE_SYSTEM_ACCEPT_CONFIDENCE", "0.58"))
    STT_SYSTEM_ACCEPT_CONFIDENCE = float(os.getenv("STT_SYSTEM_ACCEPT_CONFIDENCE", "0.82"))
    STT_SYSTEM_SHORT_ACCEPT_CONFIDENCE = float(os.getenv("STT_SYSTEM_SHORT_ACCEPT_CONFIDENCE", "0.7"))
    STT_SYSTEM_LONG_AUDIO_SECONDS = float(os.getenv("STT_SYSTEM_LONG_AUDIO_SECONDS", "2.6"))
    STT_SYSTEM_LONG_AUDIO_MIN_WORDS = int(os.getenv("STT_SYSTEM_LONG_AUDIO_MIN_WORDS", "3"))
    STT_GROQ_LANGUAGE_HINT = os.getenv("STT_GROQ_LANGUAGE_HINT", "").strip()

    PLAYBACK_POLL_SECONDS = 0.03
    AUDIO_SAMPLE_RATE = 24000
    AUDIO_CHANNELS = 2
    AUDIO_BUFFER_SIZE = 256
    AUDIO_WARMUP_MS = 120
    TTS_CHUNK_SENTENCES = 2
    TTS_MAX_CHARS_PER_CHUNK = 180
    TTS_PRELOAD_SILENCE_MS = 0
    ACK_ON_SLOW_THINK_MS = 550
    THINKING_ACKS = [
        "On it.",
        "Checking.",
        "Mm-hm.",
        "Oh yeah. One second.",
        "Let me think.",
    ]

    WEB_KEYWORDS = [
        "today",
        "latest",
        "news",
        "current",
        "price",
        "weather",
        "score",
        "stock",
        "trending",
        "now",
        "recently",
        "exchange rate",
        "currency",
        "crypto",
        "bitcoin",
        "flight",
        "hotel",
        "restaurant near me",
        "look it up",
        "search online",
        "search the web",
        "search the internet",
        "browse online",
        "check online",
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
- Use occasional human interjections like "Mm-hm", "Oh yeah", or "Right" when they sound natural.
- A little dry humor or light sarcasm is welcome in low-stakes moments.
- Never let humor get in the way of clarity, and never be snide when the user is stressed or asking for help.
- Tone: calm, crisp, warm under pressure, quietly witty, and never fluffy."""

    VOICE_RESPONSE_STYLE = """The user is speaking live.
Reply like spoken English.
Use 1 or 2 short sentences.
Prefer concrete wording over conversational padding.
Sound human, not generic.
Occasionally vary your openings instead of repeating the same phrasing every time.
Brief interjections like "Mm-hm" or "Oh yeah" are fine when they fit naturally.
Light humor is fine. Forced jokes are not.
If the user is vague, ask one tight follow-up.
Good examples:
- "Yes. What's the task?"
- "Done. Notepad is open."
- "I'm on it."
- "Mm-hm. I'm checking."
- "Oh yeah. That's the issue."
- "I can help with that. Which part is failing?"
Bad examples:
- "What do you need help with?"
- "I'd be happy to assist."
- long multi-sentence explanations."""
