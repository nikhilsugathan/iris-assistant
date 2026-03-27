# Iris Core
from rich.console import Console
import logging

# Shared console instance for consistent console printing across modules
console = Console()

# Minimal module-level logger so modules can safely import core.logger
logger = logging.getLogger("iris")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)