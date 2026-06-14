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

REQUIRED_VARS = [
    "CATALYST_PROJECT_ID", "CATALYST_API_TOKEN", "CATALYST_BASE_URL",
    "QUICKML_LLM_URL", "MODEL_SQL", "MODEL_ANSWER", "CATALYST_ORG_ID",
    "DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD",
    "NOSQL_BASE_URL", "CACHE_BASE_URL", "STRATUS_BASE_URL",
    "ZIA_STT_URL", "ZIA_TTS_URL", "ZIA_TRANSLATE_URL",
    "SMARTBROWZ_URL", "APP_ENV", "APP_SECRET_KEY", "ALLOWED_ORIGINS",
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
