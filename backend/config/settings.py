import os
from dotenv import load_dotenv

# Walk up from this file to find .env
# This file is at: /home/venzz/Work/Dataathon/backend/config/settings.py
# .env is at:      /home/venzz/Work/Dataathon/.env
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
]

def validate_settings():
    missing = [var for var in REQUIRED_VARS if not os.getenv(var)]
    if missing:
        raise ValueError(
            "STARTUP FAILED — missing required environment variables:\n"
            + "\n".join(f"  - {v}" for v in missing)
        )

def get(key: str) -> str:
    val = os.getenv(key)
    if not val:
        raise ValueError(f"Environment variable {key} is not set.")
    return val
