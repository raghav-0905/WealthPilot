import os
from pathlib import Path
from dotenv import load_dotenv

# Project Root
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Load .env if it exists, otherwise fall back to .env.example values
env_path = PROJECT_ROOT / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    load_dotenv(dotenv_path=PROJECT_ROOT / ".env.example")

# Mode
WEALTHPILOT_MODE = os.getenv("WEALTHPILOT_MODE", "dummy").lower()

# Apify Config
APIFY_TOKEN = os.getenv("APIFY_TOKEN", "")
APIFY_USERNAME = os.getenv("APIFY_USERNAME", "")

# LLM Config
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "apify-openrouter")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "meta-llama/llama-3.3-70b-instruct")
LLM_MAX_TOKENS_PER_CALL = int(os.getenv("LLM_MAX_TOKENS_PER_CALL", "1500"))
LLM_MAX_TOKENS_PER_RUN = int(os.getenv("LLM_MAX_TOKENS_PER_RUN", "50000"))

# Directory Paths
DATA_DIR = PROJECT_ROOT / "data"
SCHEMAS_DIR = PROJECT_ROOT / "schemas"
RULES_DIR = PROJECT_ROOT / "rules"
ACTORS_DIR = PROJECT_ROOT / "actors"
LOCAL_STORAGE_DIR = PROJECT_ROOT / "apify_storage"
