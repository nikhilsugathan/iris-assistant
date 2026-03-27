import logging
import sys
from pathlib import Path

# --- PATH ANCHORING ---
# Resolves the project root to ensure logs aren't scattered
BASE_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = BASE_DIR / "build" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# THE CRITICAL OBJECT: This is the 'logger' name the error was looking for
logger = logging.getLogger("iris")
logger.setLevel(logging.INFO)

# Formatting: Makes the logs readable
formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

# File Handler: Saves logs to build/logs/iris_runtime.log
file_handler = logging.FileHandler(LOG_DIR / "iris_runtime.log")
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# Stream Handler: Allows IRIS to print status updates to your terminal
stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(formatter)
# logger.addHandler(stream_handler) # Keep disabled if you only want 'Rich' console output