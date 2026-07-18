import os
from dotenv import load_dotenv

# Walk up from this file to find .env
# This file is at: <project_root>/backend/config/settings.py
# .env is at:      <project_root>/.env
_this_file = os.path.abspath(__file__)
_config_dir = os.path.dirname(_this_file)      # backend/config
_backend_dir = os.path.dirname(_config_dir)    # backend
_project_root = os.path.dirname(_backend_dir)  # project root
dotenv_path = os.path.join(_project_root, ".env")

load_dotenv(dotenv_path=dotenv_path)

# Variables the running application actually reads. Missing any of these is a
# hard startup failure because a core code path depends on them:
#   - CATALYST_API_TOKEN / CATALYST_ORG_ID  → auth headers on every Catalyst call
#   - QUICKML_LLM_URL / MODEL_SQL / MODEL_ANSWER → LLM pipeline
#   - DB_*                                   → MySQL connection pool
#   - NOSQL_BASE_URL                         → conversation history + sessions
#   - APP_SECRET_KEY / ALLOWED_ORIGINS / APP_ENV → auth, CORS, health
REQUIRED_VARS = [
    "CATALYST_API_TOKEN", "CATALYST_ORG_ID",
    "QUICKML_LLM_URL", "MODEL_SQL", "MODEL_ANSWER",
    "DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD",
    "NOSQL_BASE_URL",
    "APP_ENV", "APP_SECRET_KEY", "ALLOWED_ORIGINS",
]

# Variables reserved for not-yet-implemented integrations (Stratus media, Zia
# voice/translation, SmartBrowz, vision model) plus identity values that no
# current code path reads. They are documented in .env.example so the slots are
# ready, but they must NOT block startup — requiring them would crash a deploy
# over features that don't exist yet.
OPTIONAL_VARS = [
    "CATALYST_PROJECT_ID", "CATALYST_BASE_URL",
    "STRATUS_BASE_URL", "MODEL_VISION",
    "ZIA_STT_URL", "ZIA_TTS_URL", "ZIA_TRANSLATE_URL",
    "SMARTBROWZ_URL",
    "CACHE_BASE_URL", "CACHE_SEGMENT_ID",
    # OAuth refresh credentials — enable runtime auto-refresh of the Catalyst
    # access token (see config/catalyst_token.py). Optional so envs without them
    # fall back to the static CATALYST_API_TOKEN.
    "CATALYST_CLIENT_ID", "CATALYST_CLIENT_SECRET", "CATALYST_REFRESH_TOKEN",
    "CATALYST_ACCOUNTS_URL",
]

# CONTRACT
# takes:  nothing
# returns: nothing
# raises:  ValueError — when any REQUIRED_VARS are missing (checking the KSP_-prefixed fallback for CATALYST_* vars)
def validate_settings():
    missing = []
    for var in REQUIRED_VARS:
        val = os.getenv(var)
        # Fallback for Catalyst-reserved names
        if not val and var.startswith("CATALYST_"):
            val = os.getenv(f"KSP_{var}")
        if not val:
            missing.append(var)
    if missing:
        raise ValueError(
            "STARTUP FAILED — missing required environment variables:\n"
            + "\n".join(f"  - {v}" for v in missing)
        )

# CONTRACT
# takes:  key (str) — name of the environment variable to retrieve
# returns: (str) — the value; for CATALYST_* keys, falls back to the KSP_-prefixed
#          variant (Catalyst AppSail reserves the CATALYST_ env-var prefix)
# raises:  ValueError — when the variable (and its KSP_ fallback, if applicable) is unset or empty
def get(key: str) -> str:
    val = os.getenv(key)
    # Fallback: on Catalyst AppSail, CATALYST_* vars are reserved, so we use
    # KSP_CATALYST_* prefixed versions. Check the prefixed variant if the
    # standard name is empty.
    if not val and key.startswith("CATALYST_"):
        val = os.getenv(f"KSP_{key}")
    if not val:
        raise ValueError(f"Environment variable {key} is not set.")
    return val
