"""Central configuration. Everything is a plain constant so it can be
overridden with environment variables without any framework magic."""
import os
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# --- directories -----------------------------------------------------------
FRONTEND_DIR = PROJECT_ROOT / "frontend"
TEMPLATES_DIR = FRONTEND_DIR / "templates"
STATIC_DIR = FRONTEND_DIR / "static"
TYPST_DIR = PROJECT_ROOT / "typst"
DATA_DIR = PROJECT_ROOT / "data"
CV_PATH = DATA_DIR / "cv.yaml"
VERSIONS_DIR = DATA_DIR / "versions"
LETTERS_DIR = DATA_DIR / "letters"
OUT_DIR = DATA_DIR / "out"
TRACKER_DB = DATA_DIR / "tracker.db"

# --- LLM -------------------------------------------------------------------
LLM_PROVIDER = os.environ.get("CVE_PROVIDER", "ollama")  # ollama | anthropic
OLLAMA_URL = os.environ.get("CVE_OLLAMA_URL", "http://localhost:11434")
# qwen2.5:3b-instruct: best JSON/instruction-following in the 3-4B class that
# fits 8 GB RAM (~1.9 GB quantized). Override with CVE_MODEL.
MODEL = os.environ.get("CVE_MODEL", "qwen2.5:3b-instruct")
NUM_CTX = 4096
LLM_TIMEOUT_S = 120

# --- rendering -------------------------------------------------------------
def find_typst() -> "str | None":
    """Prefer the project-local binary in tools/, fall back to PATH."""
    local = PROJECT_ROOT / "tools" / "typst"
    if local.is_file() and os.access(local, os.X_OK):
        return str(local)
    return shutil.which("typst")

TYPST_BIN = find_typst()

HOST = "127.0.0.1"
PORT = 8877
