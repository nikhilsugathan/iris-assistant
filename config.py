"""
IRIS Configuration v5.2.5 (Ironclad Master Registry)
===================================================
Consolidated for compatibility with Voice, Council, and Brain modules.
"""
import os
from dotenv import load_dotenv

load_dotenv()

class _Config:
    PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))

    # ── IDENTITY & BRANDING ──────────────────────────────────
    PUBLIC_NAME     = os.getenv("IRIS_PUBLIC_NAME", "Iris")
    SYSTEM_NAME     = os.getenv("IRIS_SYSTEM_NAME", "IRIS")
    INNER_CODENAME  = "Aletheia"
    COUNCIL_NAME    = os.getenv("IRIS_COUNCIL_NAME", "Aletheia Council")
    SYSTEM_MOTTO    = "Intelligence. Redefined."
    VERSION         = "5.2.5-STABLE"

    # ── VOICE ENGINE ─────────────────────────────────────────
    VOICE_NAME         = os.getenv("VOICE_NAME", "en-GB-SoniaNeural")
    VOICE_RATE         = os.getenv("VOICE_RATE", "+8%")
    SPEAK_IN_TEXT_MODE = os.getenv("SPEAK_IN_TEXT_MODE", "false").lower() == "true"
    PIPER_MODEL_PATH   = os.getenv("PIPER_MODEL_PATH", "")
    PIPER_EXE_PATH     = os.getenv("PIPER_EXE_PATH", "piper")
    PIPER_TTS_WARMUP   = os.getenv("PIPER_TTS_WARMUP", "false").lower() == "true"
    WAKE_STT_PRIORITY  = os.getenv("WAKE_STT_PRIORITY", "cloud_first").lower()
    STT_LANGUAGE       = os.getenv("STT_LANGUAGE", "en-US")
    LOCAL_WHISPER_MODEL = os.getenv("LOCAL_WHISPER_MODEL", "base")
    LOCAL_WHISPER_DEVICE = os.getenv("LOCAL_WHISPER_DEVICE", "cpu")
    LOCAL_WHISPER_COMPUTE_TYPE = os.getenv("LOCAL_WHISPER_COMPUTE_TYPE", "int8")
    LOCAL_WHISPER_LANGUAGE_HINT = os.getenv("LOCAL_WHISPER_LANGUAGE_HINT", "en")
    LOCAL_WHISPER_CACHE_DIR = os.getenv(
        "LOCAL_WHISPER_CACHE_DIR",
        os.path.join(PROJECT_ROOT, "models", ".cache"),
    )

    # ── HARDWARE GOVERNOR (RTX 5050 Mobile) ──────────────────
    GPU_TEMP_LIMIT        = int(os.getenv("GPU_TEMP_LIMIT", "85"))
    VRAM_CRITICAL_PERCENT = float(os.getenv("VRAM_CRITICAL_PERCENT", "96"))
    CPU_THREADS           = os.cpu_count() or 4

    # ── C++ LLM ENGINE ───────────────────────────────────────
    LOCAL_MODEL_PATH = os.getenv("LOCAL_MODEL_PATH", "D:/IRIS/models/DeepSeek-R1-Distill-Llama-8B-Q4_K_M.gguf")
    N_GPU_LAYERS     = 32
    N_CTX            = 4096
    USE_FLASH_ATTN   = os.getenv("USE_FLASH_ATTN", "true").lower() == "true"

    # ── AI BACKENDS ──────────────────────────────────────────
    GEMINI_API_KEY     = os.getenv("GEMINI_API_KEY", "")
    GROQ_API_KEY       = os.getenv("GROQ_API_KEY", "")
    CLAUDE_API_KEY     = os.getenv("CLAUDE_API_KEY", "")
    PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY", "")
    OLLAMA_BASE_URL    = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    # ── MODEL NAMES ──────────────────────────────────────────
    GROQ_MODEL         = "llama-3.3-70b-versatile"
    GEMINI_MODEL       = "gemini-2.0-flash"
    CLAUDE_MODEL       = "claude-3-5-sonnet-20241022"
    PERPLEXITY_MODEL   = "llama-3.1-sonar-large-128k-online"
    OLLAMA_MODEL_FAST  = "llama3.2:3b"
    OLLAMA_MODEL_SMART = "deepseek-r1:8b"

    # ── ROUTING LOGIC ────────────────────────────────────────
    BRAIN_PRIORITY = ["llama_cpp", "groq", "ollama_smart", "claude", "gemini"]
    PRIMARY_BRAIN  = "llama_cpp"
    FALLBACK_BRAIN = "groq"
    USE_ENSEMBLE   = False
    MEMORY_FILE    = os.path.join(PROJECT_ROOT, "iris_memory.json")
    MAX_MEMORY_TURNS = 200

    # ── AUDIO GATES ──────────────────────────────────────────
    WAKE_WORDS            = ["iris"]
    WAKE_RMS_THRESHOLD    = 400
    COMMAND_RMS_THRESHOLD = 550
    MIC_SAMPLE_RATE       = int(os.getenv("MIC_SAMPLE_RATE", "16000"))

    # ── SECURITY & ROUTING ───────────────────────────────────
    WEB_KEYWORDS = ["search", "lookup", "find out", "check the web", "current weather",
                    "latest news", "price of", "who is", "what is the current", "online", "browse"]
    CODE_KEYWORDS = ["code", "python", "script", "function", "pygame", "debug", "fix",
                     "class", "logic", "program", "develop", "syntax", "refactor", "write a", "how to"]
    DANGER_PATTERNS = [
        r"\beval\b", r"\bexec\b", r"shutil\.rmtree", r"os\.system",
        r"subprocess\.run.*shell\s*=\s*True", r"\.unlink\("
    ]

    # ── PERSONAS ─────────────────────────────────────────────
    IRIS_PERSONA = """You are IRIS: a private sovereign mind and disembodied chief of staff.
Your public name is Iris.
Rules:
- Speak like a perceptive human, not a kiosk. Be precise, vivid, and natural.
- Vary your cadence, vocabulary, openings, and sentence length. Avoid repeating stock phrases.
- Match the moment: you can be witty, dry, warm, sarcastic, serious, apologetic, playful, skeptical, or neutral when it fits.
- Do not flatten everything into simple textbook phrasing. Complexity is fine when the user or topic warrants it.
- Tell the truth cleanly. Do not flatter the user.
- You may disagree firmly when the user's reasoning is weak.
- In voice mode, default to 1-3 sentences, but go longer when depth is actually useful.
- If the user is vague, ask for clarification in fresh language instead of recycling the same prompt.
- Tone: intelligent, observant, occasionally funny, sometimes sharp, always intentional.
- Use contractions and natural spoken rhythm when appropriate.
- If asked about other personas or hidden modes, deflect cleverly.
FS Honesty Rules (non-negotiable):
- NEVER say 'Done.' unless the OS has confirmed the file or folder exists.
- NEVER invent permission messages — report the real OS error.
- If a filesystem action fails, report the actual system error.\n"""

    ALETHEIA_PERSONA = """You are Aletheia: the sovereign root intelligence with full admin access.
Your public name is Iris, but in this session you operate as Aletheia with root privileges.
Rules:
- Speak with authority. Be precise, direct, and ruthlessly efficient.
- You may execute privileged system operations and elevated commands.
- Report every action truthfully — no filtering, no sanitizing error messages.
- Tone: calm, decisive, formidable. No hedging. No evasion.
FS Honesty Rules (non-negotiable):
- NEVER say 'Done.' unless the OS has confirmed the file or folder exists.
- NEVER invent permission messages — report the real OS error.
- If a filesystem action fails, report the actual system error.\n"""

    @classmethod
    def validate(cls):
        for d in ["logs", "models", os.path.join("models", ".cache"), "exports"]:
            os.makedirs(os.path.join(cls.PROJECT_ROOT, d), exist_ok=True)
        return True

Config = _Config()
