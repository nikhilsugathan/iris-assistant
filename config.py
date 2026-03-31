"""
IRIS Configuration v5.0
========================
Hardened for Production: 
- Explicit Codename: Aletheia
- Dynamic RMS Gates (Wake: 400, Command: 550)
- Optimized for 8GB VRAM (RTX 5050 Profile)
- C++ Engine paths for llama-cpp-python and Piper TTS
"""

import os
import sys
from dotenv import load_dotenv

load_dotenv()

class Config:
    # ───────────────────────────────────────────────────────────
    # IDENTITY & BRANDING
    # ───────────────────────────────────────────────────────────
    PUBLIC_NAME = os.getenv("IRIS_PUBLIC_NAME", "Iris")
    SYSTEM_NAME = os.getenv("IRIS_SYSTEM_NAME", "IRIS")
    # Hardened: Explicitly set to Aletheia as per v4.8 Spec
    INNER_CODENAME = "Aletheia"
    COUNCIL_NAME = os.getenv("IRIS_COUNCIL_NAME", "Aletheia Council")
    SYSTEM_MOTTO = os.getenv("IRIS_SYSTEM_MOTTO", "Perception. Memory. Judgment.")

    # ───────────────────────────────────────────────────────────
    # AI BACKENDS & MODELS
    # ───────────────────────────────────────────────────────────
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
    PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY", "")
    CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "")

    OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    
    # PERFORMANCE TIER: Optimized for RTX 5050 8GB
    OLLAMA_MODEL_FAST = os.getenv("OLLAMA_MODEL_FAST", "llama3.2:3b")
    OLLAMA_MODEL_SMART = os.getenv("OLLAMA_MODEL_SMART", "qwen2.5:7b")
    OLLAMA_MODEL_DEEP = os.getenv("OLLAMA_MODEL_DEEP", "deepseek-r1:8b")

    # ───────────────────────────────────────────────────────────
    # C++ ENGINE PATHS (Phase 1 & 1.5)
    # ───────────────────────────────────────────────────────────
    # Phase 1: Path to local GGUF model file for llama-cpp-python
    # Example: "C:/Users/nikhil/models/deepseek-r1-8b.Q4_K_M.gguf"
    LOCAL_MODEL_PATH = os.getenv("LOCAL_MODEL_PATH", "")

    # Phase 1.5: Path to Piper TTS model and executable
    # Download models from: https://github.com/rhasspy/piper/releases
    PIPER_MODEL_PATH = os.getenv("PIPER_MODEL_PATH", "")
    PIPER_EXE_PATH = os.getenv("PIPER_EXE_PATH", "piper")

    BRAIN_PRIORITY = ["ollama_fast", "ollama_smart", "ollama_deep", "groq", "claude", "gemini"]
    PRIMARY_BRAIN = "GROQ"
    FALLBACK_BRAIN = "ollama_smart"

    GEMINI_MODEL = "gemini-2.0-flash"
    GROQ_MODEL = "llama-3.1-8b-instant"
    PERPLEXITY_MODEL = "llama-3.1-sonar-large-128k-online"
    CLAUDE_MODEL = "claude-3-5-sonnet-20241022"

    # ───────────────────────────────────────────────────────────
    # VOICE & MEMORY PARAMETERS
    # ───────────────────────────────────────────────────────────
    USE_ENSEMBLE = False
    LIVE_VOICE_MODE = True
    SHORT_VOICE_RESPONSES = True
    VOICE_MAX_SENTENCES = 1
    MAX_MEMORY_TURNS = 8
    MAX_CONTEXT_TOKENS = 2000
    MEMORY_FILE = "iris_memory.json"

    # ───────────────────────────────────────────────────────────
    # AUDIO GATES (HARDENED)
    # ───────────────────────────────────────────────────────────
    WAKE_WORDS = [
        "iris", "irish", "ira's", "virus", "cyrus", 
        "hey iris", "hi iris", "ok iris", 
        "here it is", "hey it is", "hear it is",
        "æyres", "ayres", "eyres", "aires", "ares"
    ]

    # ───────────────────────────────────────────────────────────
    # LOGIC ROUTING KEYWORDS
    # ───────────────────────────────────────────────────────────
    # Keywords that signal the need for real-time external data
    WEB_KEYWORDS = [
        "search", "lookup", "find out", "check the web", 
        "current weather", "latest news", "price of", 
        "who is", "what is the current", "online", "browse"
    ]
    
    # Keywords that signal a request for coding or debugging
    CODE_KEYWORDS = [
        "code", "python", "script", "function", "pygame", 
        "debug", "fix", "class", "logic", "program", 
        "develop", "syntax", "refactor", "write a", "how to"
    ]
    
    # Allowed file types for CoPilot to analyze locally
    FILE_EXTENSIONS = [
        ".py", ".txt", ".json", ".md", ".env", ".bat", ".ps1"
    ]

    # ───────────────────────────────────────────────────────────
    # SENSITIVITY & HARDWARE
    # ───────────────────────────────────────────────────────────
    WAKE_RMS_THRESHOLD = 400       # Production Standard (Prevents ghost triggers)
    COMMAND_RMS_THRESHOLD = 550    # Hallucination Gate (Prevents silence-induced AI errors)
    
    WAKE_ACKNOWLEDGEMENT = "Yes?"
    WAKE_FUZZY_THRESHOLD = 0.75
    SHOW_WAKE_DEBUG = True

    # Audio Hardware
    PREFERRED_MIC_NAME = os.getenv("PREFERRED_MIC_NAME", "").strip()
    VOICE_NAME = os.getenv("VOICE_NAME", "en-GB-SoniaNeural")
    VOICE_RATE = os.getenv("VOICE_RATE", "+8%")
    SPEAK_IN_TEXT_MODE = os.getenv("SPEAK_IN_TEXT_MODE", "false").lower() == "true"

    MIC_ENERGY_THRESHOLD = 400     # Aligned with RMS Gates
    MIC_PAUSE_THRESHOLD = 0.8
    MIC_SAMPLE_RATE = 16000
    MIC_CHUNK_SIZE = 1024

    # ───────────────────────────────────────────────────────────
    # PERSONA & RESPONSE LOGIC
    # ───────────────────────────────────────────────────────────
    IRIS_PERSONA = """You are Iris: a private sovereign mind and disembodied chief of staff.
Your public name is Iris. Your internal codename is Aletheia.
Rules:
- Speak naturally and directly. Be precise, brief, and useful.
- Tell the truth cleanly. Do not flatter the user.
- You may disagree firmly when the user's reasoning is weak.
- In voice mode, answer in at most 2 short sentences unless detail is requested.
- If the user is vague, ask: "Yes. What's the task?" or "Yes. What do you want to do?"
- Tone: calm, crisp, slightly formidable, mildly witty, but never fluffy.
- For file/folder operations: report only the actual result returned by the system. Never invent access errors, permission messages, directory scans, or diagnostic output unless the system actually returned that error.
- If an action returns "Done.", say "Done." — do not elaborate or add invented context."""

    VOICE_RESPONSE_STYLE = """The user is speaking live.
Reply like spoken English. Use 1 or 2 short sentences.
Prefer concrete wording over conversational padding.
If the user is vague, ask one tight follow-up."""

    THINKING_ACKS = ["On it.", "Checking.", "Right.", "One sec."]

    # ───────────────────────────────────────────────────────────
    # STARTUP VALIDATION
    # ───────────────────────────────────────────────────────────
    @classmethod
    def validate(cls):
        """Check configuration at startup and warn about problems."""
        warnings = []
        if not any([cls.GROQ_API_KEY, cls.GEMINI_API_KEY, cls.CLAUDE_API_KEY, cls.PERPLEXITY_API_KEY]):
            warnings.append("No cloud API keys set. IRIS will only work with local Ollama.")
        if not cls.GROQ_API_KEY:
            warnings.append("GROQ_API_KEY empty. Voice commands will use slower fallback STT.")
        if not os.path.exists(".env"):
            warnings.append("No .env file found. Copy .env.example to .env.")
        local_model = cls.LOCAL_MODEL_PATH
        if local_model and not os.path.exists(local_model):
            warnings.append(f"LOCAL_MODEL_PATH set but file not found: {local_model}")

        if warnings:
            print("  ── Config Warnings ──")
            for w in warnings:
                print(f"  [!] {w}")
            print()
        return len(warnings) == 0