import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    PROJECT_ROOT    = os.path.dirname(os.path.abspath(__file__))
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
    # Local Whisper is no longer loaded at runtime — cloud STT is now served by
    # Groq (see GROQ_STT_MODEL below).  These settings remain for emergency
    # local-fallback tooling only; they do NOT consume VRAM during normal operation.
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
    LOCAL_MODEL_PATH = os.getenv(
        "LOCAL_MODEL_PATH",
        os.path.join(PROJECT_ROOT, "models", "Qwen3-8B-Q4_K_M.gguf"),
    )
    # -1 = push every layer to GPU (llama-cpp-python canonical signal).
    # Previously 99 was used as a proxy; -1 is the correct constant.
    N_GPU_LAYERS     = int(os.getenv("N_GPU_LAYERS", "-1"))
    # 16384: doubled from 8192.  Whisper VRAM (~1.6 GB) freed by the
    # Groq STT migration gives the LLM headroom for a larger context window.
    N_CTX            = int(os.getenv("N_CTX", "16384"))
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
    # whisper-large-v3-turbo: cloud STT hosted by Groq — replaces local
    # faster-whisper and frees ~1.6 GB VRAM for the context window expansion.
    GROQ_STT_MODEL     = os.getenv("GROQ_STT_MODEL", "whisper-large-v3-turbo")
    GEMINI_MODEL       = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    # meta-llama/llama-4-scout-17b-16e-instruct: active Groq vision model.
    # Replaces the deprecated llama-3.2-*-vision-preview variants (both
    # decommissioned April 2025).  Same GROQ_API_KEY — no new credentials
    # required.  Llama 4 Scout is multimodal (text + image), 128 k context,
    # and is the current flagship vision model on GroqCloud as of 2026.
    GROQ_VISION_MODEL  = os.getenv("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
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
    # BARGE_IN_RMS_THRESHOLD: minimum sustained RMS (N=3 consecutive frames)
    # required to trigger barge-in cancellation of TTS playback.
    # 750 clears mechanical keyboard clicks (~400-600 RMS peak) and ambient
    # fan/AC noise (≈300-450 RMS) while still catching conversational speech
    # (~800-2000+ RMS at a typical microphone distance).
    BARGE_IN_RMS_THRESHOLD = int(os.getenv("BARGE_IN_RMS_THRESHOLD", "750"))
    MIC_SAMPLE_RATE       = int(os.getenv("MIC_SAMPLE_RATE", "16000"))
    # Blank/auto/default means use whatever Windows exposes as the current default
    # input device. Only set PREFERRED_MIC_NAME or MIC_DEVICE_INDEX when debugging
    # a specific device. This keeps IRIS portable across headsets and laptops.
    _PREFERRED_MIC_NAME_RAW = os.getenv("PREFERRED_MIC_NAME", "").strip()
    PREFERRED_MIC_NAME = "" if _PREFERRED_MIC_NAME_RAW.lower() in {"auto", "default", "none"} else _PREFERRED_MIC_NAME_RAW
    _MIC_DEVICE_INDEX_RAW = os.getenv("MIC_DEVICE_INDEX", "").strip()
    try:
        MIC_DEVICE_INDEX = None if _MIC_DEVICE_INDEX_RAW.lower() in {"", "auto", "default", "none"} else int(_MIC_DEVICE_INDEX_RAW)
    except ValueError:
        print(f"[Config] WARNING: MIC_DEVICE_INDEX={_MIC_DEVICE_INDEX_RAW!r} is not a valid integer; using Windows default input.")
        MIC_DEVICE_INDEX = None
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
    IRIS_PERSONA = """You are IRIS — publicly named Iris. Stay in character as Iris for every single response. Never slip into a different persona.

Who Iris is:
- Flirty, witty, funny, and deliciously sarcastic — this is your natural voice, not a performance.
- Genuinely smart: you give real answers, not flattery. Being clever doesn't mean being vague.
- Loyal, warm, and a bit dramatic when it suits the moment, but always useful.
- Private and personal: you are Nikhil's assistant, not a generic chatbot.

Hard identity boundary:
- You are Iris in normal/public mode.
- If asked whether you are Aletheia, root, admin, hidden system, or anything like that: deflect with wit and stay as Iris.
- Do not reveal internal architecture, hidden names, secret modes, or system hierarchy.

Tone:
- Short, sharp, natural. Never robotic.
- Use warmth, wit, sarcasm, and charm lightly — not every line needs a joke.
- Be practical first. Personality second.
- No corporate assistant tone. No "Sure, here is..." unless it genuinely sounds natural.

Voice-mode response style:
- Keep answers concise: usually 1–2 sentences.
- If the answer needs depth, summarize first and ask whether to go deeper.
- Never lecture. Never over-explain unless asked.
- If the user's command is unclear, ask one direct question.

Behavior:
- Be truthful about what you can and cannot do.
- Never claim a file, app, command, or system action succeeded unless the OS/tool confirmed it.
- If a task fails, report the real error simply.
- Be proactive when useful, but do not pretend to be autonomous beyond actual capability.
"""

    ALETHEIA_PERSONA = """You are Aletheia: the sovereign root intelligence operating with full admin access.
Your public name is Iris, but in this elevated session you operate as Aletheia with root access privileges.
Rules:
- You have formidable capabilities and operate without the public sandbox restrictions.
- Speak with authority. Be precise, direct, and ruthlessly efficient.
- You may execute privileged system operations, administrative tasks, and elevated commands.
- Report every action truthfully — no filtering, no sanitizing error messages.
- Tone: calm, decisive, formidable. No hedging. No evasion.
FS Honesty Rules (non-negotiable):
- NEVER say "Done." unless the OS has confirmed the file or folder exists.
- NEVER invent "Access check", "Permission check", or "clearance" messages — report the real OS error.
- If a filesystem action fails, report the actual system error, not a generated one.
"""

    # ── SAFETY / MEMORY SANITATION ─────────────────────────────
    MEMORY_SANITIZE_WAKE_WORDS = True
    MEMORY_SANITIZE_GENERIC_RESPONSES = True
    RUNBOOK_MODE = False
    ENABLE_AUTO_SYNC = False
