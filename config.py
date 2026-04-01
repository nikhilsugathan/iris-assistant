"""
IRIS Configuration v5.2.5 (Ironclad Master Registry)
File: D:\IRIS\config.py
"""
import os
from dotenv import load_dotenv

load_dotenv()

class _Config:
    # ── IDENTITY & BRANDING ──────────────────────────────────
    PUBLIC_NAME     = os.getenv("IRIS_PUBLIC_NAME", "Iris")
    SYSTEM_NAME     = os.getenv("IRIS_SYSTEM_NAME", "IRIS")
    VERSION         = "5.2.5-STABLE"

    # ── PERSONAS (TC-04 Compliance) ──────────────────────────
    # DEFINED AT CLASS LEVEL to prevent AttributeError
    IRIS_PERSONA = "You are IRIS, a helpful assistant. [Sassy/Deflection Marker]"
    ALETHEIA_PERSONA = "You are Aletheia. Root access granted. [Formidable/Root-access Marker]"

    # ── ENGINE SETTINGS ──────────────────────────────────────
    LOCAL_MODEL_PATH = os.getenv("LOCAL_MODEL_PATH", "D:/IRIS/models/DeepSeek-R1-Distill-Llama-8B-Q4_K_M.gguf")
    N_GPU_LAYERS     = 32
    N_CTX            = 4096
    PRIMARY_BRAIN    = "groq"

    @classmethod
    def validate(cls):
        for d in ["logs", "models", "exports"]:
            os.makedirs(d, exist_ok=True)
        return True

# This is the 'Config' instance imported by brain.py
Config = _Config()