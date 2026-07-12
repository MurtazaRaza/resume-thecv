"""Central configuration. Everything is a plain constant so it can be
overridden with environment variables without any framework magic."""
import os
import shutil
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# --- directories -----------------------------------------------------------
FRONTEND_DIR = PROJECT_ROOT / "frontend"
TEMPLATES_DIR = FRONTEND_DIR / "templates"
STATIC_DIR = FRONTEND_DIR / "static"
TYPST_DIR = PROJECT_ROOT / "typst"
DATA_DIR = PROJECT_ROOT / "data"
# Per-person state lives under data/profiles/<slug>/ and is resolved per request
# from the cve_profile cookie (see core/profiles.py). The old module-level
# CV_PATH/VERSIONS_DIR/OUT_DIR/TRACKER_DB constants are now Profile attributes.
PROFILES_DIR = DATA_DIR / "profiles"

# --- LLM -------------------------------------------------------------------
LLM_PROVIDER = os.environ.get("CVE_PROVIDER", "ollama")  # ollama | anthropic | gemini
OLLAMA_URL = os.environ.get("CVE_OLLAMA_URL", "http://localhost:11434")
# qwen2.5:3b-instruct: best JSON/instruction-following in the 3-4B class that
# fits 8 GB RAM (~1.9 GB quantized). Override with CVE_MODEL.
MODEL = os.environ.get("CVE_MODEL", "qwen2.5:3b-instruct")
NUM_CTX = 4096
LLM_TIMEOUT_S = 120

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("CVE_GEMINI_MODEL", "gemini-2.5-flash")

# Per-task model overrides, keyed by the task name each get_provider(task=...)
# call site passes (see backend/main.py). Empty by default — every task uses
# the active provider's default MODEL/GEMINI_MODEL. Set an override to route a
# specific task to a stronger/cheaper model without touching call sites, e.g.
#   CVE_TASK_MODEL_tailor_suggest=gemini-2.5-pro
# The env var suffix must match the task name passed to get_provider().
TASK_MODELS = {
    task: model
    for task in (
        "import", "bullet_optimize", "grammar", "letters", "jd_extract",
        "tailor_suggest", "summary", "headline", "bank_tags",
    )
    if (model := os.environ.get(f"CVE_TASK_MODEL_{task}", "").strip())
}

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
