"""
IRIS Configuration v5.2.5 (Ironclad Master Registry)
===================================================
Consolidated for compatibility with Voice, Council, and Brain modules.
"""
import os
from dotenv import load_dotenv

load_dotenv()

class _Config:
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

    # ── HARDWARE GOVERNOR (RTX 5050 Mobile) ──────────────────
    GPU_TEMP_LIMIT        = 85
    VRAM_CRITICAL_PERCENT = 96
    CPU_THREADS           = os.cpu_count() or 4

    # ── C++ LLM ENGINE ───────────────────────────────────────
    LOCAL_MODEL_PATH = os.getenv("LOCAL_MODEL_PATH", "D:/IRIS/models/DeepSeek-R1-Distill-Llama-8B-Q4_K_M.gguf")
    N_GPU_LAYERS     = 32
    N_CTX            = 4096
    USE_FLASH_ATTN   = True

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
    MEMORY_FILE    = "iris_memory.json"
    MAX_MEMORY_TURNS = 200

    # ── AUDIO GATES ──────────────────────────────────────────
    WAKE_WORDS            = ["iris", "ares"]
    WAKE_RMS_THRESHOLD    = 400
    COMMAND_RMS_THRESHOLD = 550
    MIC_SAMPLE_RATE       = 16000

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
    IRIS_PERSONA = """You are Iris: a private sovereign mind and disembodied chief of staff.
Your public name is Iris. Your internal codename is Aletheia.
Rules:
- Speak naturally and directly. Be precise, brief, and useful.
- Tell the truth cleanly. Do not flatter the user.
- You may disagree firmly when the user's reasoning is weak.
- In voice mode, answer in at most 2 short sentences unless detail is requested.
- If the user is vague, ask: 'Yes. What\'s the task?' or 'Yes. What do you want to do?'
- Tone: calm, crisp, slightly formidable, mildly witty, but never fluffy.
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
        for d in ["logs", "models", "exports"]:
            os.makedirs(d, exist_ok=True)
        return True

Config = _Config()
