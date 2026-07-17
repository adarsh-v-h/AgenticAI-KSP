#!/usr/bin/env python3
"""
Generate backend/app-config.json for a Catalyst AppSail deploy from the
project's .env file plus the committed template.

Secrets NEVER live in git. The committed file is
`backend/app-config.template.json` (placeholders only). This script fills the
placeholders with real values read from `.env` and writes the gitignored
`backend/app-config.json` that `catalyst deploy` actually consumes.

Usage:
    python3 scripts/gen_app_config.py

Environment overrides (optional):
    APP_ENV_OVERRIDE        -> value for APP_ENV        (default "production")
    ALLOWED_ORIGINS_OVERRIDE -> value for ALLOWED_ORIGINS (default the live
                               frontend URL below)

The mapping below defines which .env key feeds which AppSail env variable.
Note the Catalyst-reserved rename: CATALYST_* -> KSP_CATALYST_* (Catalyst
rejects env variables that start with the reserved CATALYST_ prefix).
"""

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_ENV_PATH = os.path.join(_ROOT, ".env")
_TEMPLATE_PATH = os.path.join(_ROOT, "backend", "app-config.template.json")
_OUTPUT_PATH = os.path.join(_ROOT, "backend", "app-config.json")

# Default production frontend origin used for CORS (ALLOWED_ORIGINS).
_DEFAULT_ALLOWED_ORIGINS = "https://datathon-60074122671.development.catalystserverless.in"

# REQUIRED AppSail env variable  ->  .env key it is sourced from.
# Deploy fails if any of these are missing from .env.
# CATALYST_* are renamed to KSP_CATALYST_* because Catalyst reserves the
# CATALYST_ prefix for its own injected variables.
_REQUIRED_ENV_VAR_SOURCES = {
    "QUICKML_LLM_URL": "QUICKML_LLM_URL",
    "MODEL_SQL": "MODEL_SQL",
    "MODEL_ANSWER": "MODEL_ANSWER",
    "DB_HOST": "DB_HOST",
    "DB_PORT": "DB_PORT",
    "DB_NAME": "DB_NAME",
    "DB_USER": "DB_USER",
    "DB_PASSWORD": "DB_PASSWORD",
    "NOSQL_BASE_URL": "NOSQL_BASE_URL",
    "APP_SECRET_KEY": "APP_SECRET_KEY",
    "KSP_CATALYST_API_TOKEN": "CATALYST_API_TOKEN",
    "KSP_CATALYST_ORG_ID": "CATALYST_ORG_ID",
}

# OPTIONAL AppSail env variable  ->  .env key it is sourced from.
# Injected when present in .env; skipped silently when absent (they back
# not-yet-critical integrations: Zia voice, Stratus media, SmartBrowz export,
# vision model). The voice feature (STT/TTS/translate) needs the ZIA_* URLs.
_OPTIONAL_ENV_VAR_SOURCES = {
    "ZIA_STT_URL": "ZIA_STT_URL",
    "ZIA_TTS_URL": "ZIA_TTS_URL",
    "ZIA_TRANSLATE_URL": "ZIA_TRANSLATE_URL",
    "STRATUS_BASE_URL": "STRATUS_BASE_URL",
    "SMARTBROWZ_URL": "SMARTBROWZ_URL",
    "CACHE_BASE_URL": "CACHE_BASE_URL",
    "MODEL_VISION": "MODEL_VISION",
    "KSP_CATALYST_PROJECT_ID": "CATALYST_PROJECT_ID",
    "KSP_CATALYST_BASE_URL": "CATALYST_BASE_URL",
}


# CONTRACT
# takes:  path (str) — path to a dotenv file
# returns: (dict[str, str]) — parsed key/value pairs (quotes stripped, comments/blank lines ignored)
# raises:  SystemExit — when the file does not exist
def _parse_env(path: str) -> dict:
    if not os.path.exists(path):
        sys.exit(f"ERROR: {path} not found. Cannot generate app-config.json without it.")
    values: dict[str, str] = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            values[key.strip()] = val.strip().strip('"').strip("'")
    return values


# CONTRACT
# takes:  nothing
# returns: nothing (writes backend/app-config.json)
# raises:  SystemExit — on missing .env, missing template, or missing required keys
def main() -> None:
    env = _parse_env(_ENV_PATH)

    if not os.path.exists(_TEMPLATE_PATH):
        sys.exit(f"ERROR: template {_TEMPLATE_PATH} not found.")

    with open(_TEMPLATE_PATH, encoding="utf-8") as fh:
        config = json.load(fh)

    env_variables = {
        "APP_ENV": os.getenv("APP_ENV_OVERRIDE", "production"),
        "ALLOWED_ORIGINS": os.getenv("ALLOWED_ORIGINS_OVERRIDE", _DEFAULT_ALLOWED_ORIGINS),
    }

    # Required vars — fail the deploy if any are missing.
    missing = []
    for appsail_key, env_key in _REQUIRED_ENV_VAR_SOURCES.items():
        value = env.get(env_key)
        if not value:
            missing.append(env_key)
            continue
        env_variables[appsail_key] = value

    if missing:
        sys.exit(
            "ERROR: the following required keys are missing from .env:\n"
            + "\n".join(f"  - {k}" for k in missing)
        )

    # Optional vars — inject when present, skip silently when absent.
    skipped_optional = []
    for appsail_key, env_key in _OPTIONAL_ENV_VAR_SOURCES.items():
        value = env.get(env_key)
        if value:
            env_variables[appsail_key] = value
        else:
            skipped_optional.append(env_key)

    config["env_variables"] = env_variables

    with open(_OUTPUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2)
        fh.write("\n")

    print(f"Generated {_OUTPUT_PATH} with {len(env_variables)} env variables (secrets from .env).")
    if skipped_optional:
        print(f"  Optional keys not set in .env (skipped): {', '.join(skipped_optional)}")


if __name__ == "__main__":
    main()
