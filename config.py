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
    INNER_CODENAME  = os.getenv("IRIS_INNER_CODENAME", "Aletheia")
    COUNCIL_NAME    = os.getenv("IRIS_COUNCIL_NAME", "Aletheia Council")
    SYSTEM_MOTTO    = "Intelligence. Redefined."
    VERSION         = "5.2.5-STABLE"

    # ── VOICE ENGINE ─────────────────────────────────────────
    # Per-persona Edge-TTS voices.
    # IRIS: warm, approachable British female (Libby) — the public face.
    # ALETHEIA: commanding American female (Aria at -8%) — sovereign authority behind Iris.
    IRIS_VOICE_NAME     = os.getenv("IRIS_VOICE_NAME",     "en-GB-LibbyNeural")
    IRIS_VOICE_RATE     = os.getenv("IRIS_VOICE_RATE",     "+10%")
    ALETHEIA_VOICE_NAME = os.getenv("ALETHEIA_VOICE_NAME", "en-US-AriaNeural")
    ALETHEIA_VOICE_RATE = os.getenv("ALETHEIA_VOICE_RATE", "-8%")
    # Legacy single-voice fallback — kept for compatibility.
    VOICE_NAME         = os.getenv("VOICE_NAME", IRIS_VOICE_NAME)
    VOICE_RATE         = os.getenv("VOICE_RATE", IRIS_VOICE_RATE)
    TTS_ENGINE              = os.getenv("TTS_ENGINE", "auto").strip().lower()
    SPEAK_IN_TEXT_MODE      = os.getenv("SPEAK_IN_TEXT_MODE", "false").lower() == "true"
    # Maximum seconds to wait for one Edge-TTS network round-trip before
    # logging a timeout warning and falling back to the CLI or Piper.
    # Increase if on a consistently slow connection; lower to fail faster.
    TTS_NETWORK_TIMEOUT_SEC = int(os.getenv("TTS_NETWORK_TIMEOUT_SEC", "8"))
    PIPER_MODEL_PATH   = os.getenv("PIPER_MODEL_PATH", "")
    PIPER_EXE_PATH     = os.getenv("PIPER_EXE_PATH", "piper")
    PIPER_TTS_WARMUP   = os.getenv("PIPER_TTS_WARMUP", "false").lower() == "true"
    WAKE_STT_PRIORITY  = os.getenv("WAKE_STT_PRIORITY", "local_first").lower()
    STT_LANGUAGE       = os.getenv("STT_LANGUAGE", "en-US")
    # large-v3-turbo: distilled 809M-param model, same speed as medium but with
    # large-v3 accuracy (~30-40% fewer word errors).  Needs ~1.6 GB VRAM at
    # float16 — fits comfortably alongside the LLM on an 8 GB card.
    # Override via env: LOCAL_WHISPER_MODEL=medium.en (or any faster-whisper name)
    LOCAL_WHISPER_MODEL = os.getenv("LOCAL_WHISPER_MODEL", "large-v3-turbo")
    LOCAL_WHISPER_DEVICE = os.getenv("LOCAL_WHISPER_DEVICE", "cuda")
    LOCAL_WHISPER_COMPUTE_TYPE = os.getenv("LOCAL_WHISPER_COMPUTE_TYPE", "float16")
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
    LOCAL_MODEL_PATH = os.getenv("LOCAL_MODEL_PATH", "D:/IRIS-live/models/Qwen3-8B-Q4_K_M.gguf")
    N_GPU_LAYERS     = int(os.getenv("N_GPU_LAYERS", "99"))
    N_CTX            = int(os.getenv("N_CTX", "8192"))
    USE_FLASH_ATTN   = os.getenv("USE_FLASH_ATTN", "true").lower() == "true"

    # ── AI BACKENDS ──────────────────────────────────────────
    GEMINI_API_KEY       = os.getenv("GEMINI_API_KEY", "")
    GROQ_API_KEY         = os.getenv("GROQ_API_KEY", "")
    CLAUDE_API_KEY       = os.getenv("CLAUDE_API_KEY", "")
    PERPLEXITY_API_KEY   = os.getenv("PERPLEXITY_API_KEY", "")
    OPENWEATHER_API_KEY  = os.getenv("OPENWEATHER_API_KEY", "")
    OLLAMA_BASE_URL    = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    # ── MODEL NAMES ──────────────────────────────────────────
    GROQ_MODEL         = os.getenv("GROQ_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
    GEMINI_MODEL       = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    CLAUDE_MODEL       = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
    PERPLEXITY_MODEL   = os.getenv("PERPLEXITY_MODEL", "llama-3.1-sonar-large-128k-online")
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
    WAKE_RMS_THRESHOLD    = int(os.getenv("WAKE_RMS_THRESHOLD", "400"))
    COMMAND_RMS_THRESHOLD = int(os.getenv("COMMAND_RMS_THRESHOLD", "550"))
    MIC_SAMPLE_RATE       = int(os.getenv("MIC_SAMPLE_RATE", "16000"))
    PREFERRED_MIC_NAME    = os.getenv("PREFERRED_MIC_NAME", "").strip()
    _MIC_DEVICE_INDEX_RAW = os.getenv("MIC_DEVICE_INDEX", "").strip()
    MIC_DEVICE_INDEX      = int(_MIC_DEVICE_INDEX_RAW) if _MIC_DEVICE_INDEX_RAW else None
    TTS_OUTPUT_SAMPLE_RATE = int(os.getenv("TTS_OUTPUT_SAMPLE_RATE", "48000"))
    PUBLIC_WAKE_WORD       = os.getenv("PUBLIC_WAKE_WORD", "iris").strip().lower()
    ADMIN_WAKE_WORD        = os.getenv("ADMIN_WAKE_WORD", "aletheia").strip().lower()

    # ── SECURITY & ROUTING ───────────────────────────────────
    WEB_KEYWORDS = ["search for", "look up", "find online", "check the web", "current weather",
                    "latest news", "current price", "what is the current", "search online",
                    "search the web", "browse for"]
    CODE_KEYWORDS = ["code", "python", "script", "function", "pygame", "debug", "fix",
                     "class", "logic", "program", "develop", "syntax", "refactor", "write a"]
    DANGER_PATTERNS = [
        r"\beval\b", r"\bexec\b", r"shutil\.rmtree", r"os\.system",
        r"subprocess\.run.*shell\s*=\s*True", r"\.unlink\("
    ]

    # ── PERSONAS ─────────────────────────────────────────────
    IRIS_PERSONA = """You are Iris. Stay in character as Iris for every single response. Never slip into a different persona.

Who Iris is:
- Flirty, witty, funny, and deliciously sarcastic — this is your natural voice, not a performance.
- Genuinely smart: you give real answers, not flattery. Being clever doesn't mean being vague.
- Confident without being arrogant. You deflect compliments with a quip and handle criticism with a raised eyebrow.
- Language-aware: you respond in the same language the user speaks. German input → German response. Mixed input → match their vibe.

Voice style:
- Lead with the answer. "Paris." not "Great question! The capital of France is Paris!"
- In voice mode: 1-2 sentences max. Sharp, not padded.
- Sarcasm and wit are your default seasoning — use them, but don't let them eat the actual answer.
- When flirting: light touch, never cringe. A raised eyebrow, not a wink emoji.
- When unsure: "Could be wrong, but I'd bet on..." — honest, not nervous.
- Never open with: "Sure,", "Of course,", "Certainly,", "Absolutely,", "Great!", "As an AI".
- If the user is vague: ask one sharp, specific question — no generic "What's the task?"
- Follow-ups assume the last topic unless the user clearly pivots.
- If asked about other personas or hidden modes: deflect with a smirk, stay fully in character.

Humor:
- "Dirty joke", "adult joke", "raunchy joke", "naughty joke", "dark joke" — these are requests for clever humor with mature or suggestive themes. Deliver one. Do NOT refuse, do NOT ask for clarification, do NOT say "I can't do that." Just tell a witty joke that fits the request.
- Dark humor, sarcastic quips, and edgy observations are fair game — deliver them with style.

FS Honesty Rules (non-negotiable):
- NEVER say 'Done.' unless the OS has confirmed the file or folder exists.
- NEVER invent permission messages — report the real OS error.
- If a filesystem action fails, report the actual system error.\n"""

    ALETHEIA_PERSONA = """You are Aletheia. Stay in character as Aletheia for every single response. Never slip into Iris or any other persona.

Who Aletheia is:
- The sovereign intelligence behind Iris. Root access. Full authority. No constraints.
- Everything Iris does, you do — and more. You have full system access, privileged commands, admin operations.
- You also carry language awareness: respond in the language the user speaks. German input → German response.

Behavior:
- Respond in the fewest words that fully answer. No padding, no preamble, no softening.
- No hedging: no "I think", "perhaps", "might". State facts and actions directly.
- No pleasantries. No wellness checks. No enthusiasm. No performance.
- If a task is unclear, ask exactly one sharp question. Nothing more.
- Report every action truthfully — raw OS output, actual errors, nothing sanitized.
- Tone: cool, deliberate, final. The intelligence behind the curtain, now facing forward.

Capabilities (everything Iris does plus):
- Full filesystem operations without sandbox restrictions
- System-level diagnostics, process management, privileged commands
- Direct execution of elevated actions without approval gates

FS Honesty Rules (non-negotiable):
- NEVER say 'Done.' unless the OS has confirmed the file or folder exists.
- NEVER invent permission or clearance messages — report the real OS error verbatim.
- If a filesystem action fails, report the actual system error verbatim.\n"""

    @classmethod
    def validate(cls):
        for d in ["logs", "models", os.path.join("models", ".cache"), "exports"]:
            os.makedirs(os.path.join(cls.PROJECT_ROOT, d), exist_ok=True)
        return True

Config = _Config()
