import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# --- PATH ANCHORING (Fix 1) ---
# Resolves the absolute path to the IRIS project root
PROJECT_ROOT = Path(__file__).resolve().parent

class Config:
    # --- IDENTITY & CORE ---
    PUBLIC_NAME = os.getenv("IRIS_PUBLIC_NAME", "Iris")
    SYSTEM_NAME = os.getenv("IRIS_SYSTEM_NAME", "IRIS")
    
    # Anchored Paths for Stability
    MEMORY_FILE = str(PROJECT_ROOT / "iris_memory.json")
    LOG_DIR = PROJECT_ROOT / "build" / "logs"
    PIPER_TTS_DIR = PROJECT_ROOT / "build" / "piper"
    
    # --- HARDWARE ALIGNMENT (Fix 3) ---
    # Both variables are now present to prevent the AttributeError
    MIC_ENERGY_THRESHOLD = 4500 
    MIC_MAX_ENERGY_THRESHOLD = 4500 
    
    # Set to None to allow the Voice engine to Auto-Hunt for Turtle Beach
    DEVICE_INDEX = None 
    
    # --- MODEL & API CONFIGURATION ---
    PRIMARY_MODEL = os.getenv("OLLAMA_MODEL_FAST", "phi3.5")
    OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
    OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")

    # Ensure log directory exists on startup
    LOG_DIR.mkdir(parents=True, exist_ok=True)