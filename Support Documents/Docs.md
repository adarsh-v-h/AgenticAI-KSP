# Technical Documentation — KSP Crime Intelligence Chatbot

> This document describes the **implemented** codebase. Every file, function, data structure, and end-to-end flow is documented from the actual source code.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Backend Architecture](#2-backend-architecture)
3. [File-by-File Reference](#3-file-by-file-reference)
4. [End-to-End Feature Flows](#4-end-to-end-feature-flows)
5. [Frontend Architecture](#5-frontend-architecture)
6. [Frontend File-by-File Reference](#6-frontend-file-by-file-reference)
7. [Data Flow Diagrams](#7-data-flow-diagrams)
8. [Error Handling Patterns](#8-error-handling-patterns)
9. [Removed / Deprecated Stuff](#9-removed--deprecated-stuff)

---

## 1. System Overview

The application is a **natural-language-to-SQL chatbot** for Karnataka State Police. An officer types a question in plain English; the system first **routes** the message — deciding whether it needs a fresh database query or can be answered directly from the recent conversation — then either converts it to a MySQL SELECT query via an LLM, executes it against a crime database, and formats the raw results into a human-readable answer via a second LLM, OR answers it directly from context. The response streams back token-by-token over SSE.

**Two LLMs are used:**
1. **Qwen 2.5-7B Coder** (`MODEL_SQL`) — generates SQL from natural language
2. **Qwen 2.5-14B Instruct** (`MODEL_ANSWER`) — three jobs: (a) **intent routing** (SQL vs DIRECT), (b) formatting raw DB results into a natural-language answer, and (c) **direct conversational answers** for follow-ups/insights/general questions that need no SQL

Both are called via the Catalyst QuickML HTTP API. No external LLM providers (OpenAI, Anthropic, etc.) are used.

**Two answer paths (see [Section 4.6](#46-intent-routing--direct-answers)):**
- **SQL path** — fresh data requests run the full NL→SQL→execute→format chain.
- **DIRECT path** — follow-ups about already-retrieved data ("which of those is open?"), requests for insight, greetings, and general questions are answered straight from the conversation + the most recent result set, with **no SQL and no DB hit**. The most recent answer's table is cached in conversation history (a bounded snapshot) so the model can discuss the data instead of re-querying it.

**Key constraints enforced in code:**
- Every SQL query must be a SELECT — validated before execution
- Maximum 2 SQL generation attempts (self-correction loop)
- Conversation history limited to 10 turns per session
- Sessions and messages are persisted to MySQL (Catalyst Data Store); rich result data goes to NoSQL — see [Section 4.7](#47-persistent-chat-storage)
- All secrets loaded from `.env`, never hardcoded

---

## 2. Backend Architecture

```
backend/
├── main.py                    # FastAPI app, lifespan, CORS, health check
├── Dockerfile                 # Container for Catalyst AppSail
├── config/
│   └── settings.py            # Environment variable loading and validation
├── db/
│   ├── connection.py          # MySQL connection pool (aiomysql) + execute_query / execute_write
│   ├── schema.sql             # DDL for all tables (incl. chat_sessions, chat_messages)
│   ├── seed.py                # Synthetic data generator (200+ FIRs)
│   ├── chat_store.py          # Persistent sessions + messages (MySQL) + rich data (NoSQL)
│   └── schema_catalog.py      # Table metadata, schema builder, few-shot bank
├── llm/
│   ├── client.py              # HTTP client for Catalyst QuickML
│   ├── sql_generator.py       # SQL generation with retry loop
│   ├── answer_formatter.py    # Result-to-text formatting + intent router + direct answers
│   └── prompts.py             # All prompts and prompt builders
├── pipeline/
│   ├── query_pipeline.py      # Main orchestrator (route → NL → SQL → answer, or DIRECT)
│   ├── sql_validator.py       # SQL safety validation
│   ├── media_resolver.py      # Evidence media lookup
│   └── schema_linker.py       # Keyword-based table selector
├── conversation/
│   ├── history.py             # Conversation history + recent-table snapshot (NoSQL + in-memory fallback)
│   └── session_store.py       # Session metadata + title generation (NoSQL + fallback)
├── auth/
│   └── simple_auth.py         # JWT auth (dev) with Catalyst Auth swap path
└── routers/
    ├── chat.py                # /api/chat, /api/chat/stream (SSE), /api/chat/sessions*
    ├── export.py              # POST /api/chat/sessions/{id}/export (PDF via SmartBrowz)
    └── auth.py                # POST /api/auth/login + /api/auth/logout
```

---

## 3. File-by-File Reference

### 3.1 `backend/main.py`

**Purpose:** FastAPI application entry point. Manages startup/shutdown lifecycle, registers routers, configures CORS, and exposes a health check endpoint.

**sys.path manipulation:** Lines 9-11 add the `backend/` directory to `sys.path` so that imports like `from config.settings import get` resolve correctly when the app is run via `uvicorn backend.main:app` from the project root.

**Functions:**

| Function | Lines | Description |
|----------|-------|-------------|
| `lifespan(app)` | 20-50 | Async context manager. On startup: (1) calls `validate_settings()` to crash if any env var is missing, (2) creates the MySQL connection pool via `create_pool()`, (3) runs a `SELECT 1` probe to confirm DB reachability (stores result in `app.state.db_ok`), (4) calls `init_nosql_table()` to probe Catalyst NoSQL. On shutdown: calls `close_pool()`. |
| `health_check()` | 74-123 | `GET /health` — returns `{"status": "ok"|"degraded", "db": ..., "llm_coder": ..., "llm_answer": ..., "env": ...}`. Runs LLM pings in parallel via `asyncio.gather`. Always returns HTTP 200, even if degraded. |

**Startup sequence:**
1. `validate_settings()` → crash if `.env` incomplete
2. `create_pool()` → MySQL connection pool (minsize=3, maxsize=10)
3. DB probe → `SELECT 1`, sets `app.state.db_ok`
4. NoSQL probe → confirms Catalyst NoSQL reachable
5. Register `auth_router`, `chat_router`, and `export_router`

**App metadata:**
- `title`: `"KSP Crime Intelligence API"`
- `version`: `"0.4.0-step4"`
- `docs_url`: `"/docs"` (Swagger UI available during dev)
- `redoc_url`: `None` (ReDoc disabled)

**Registered routers:** `auth_router`, `chat_router`, and `export_router` (PDF export).

**CORS config:** Only allows the single origin from `ALLOWED_ORIGINS` env var. Methods: GET, POST. Headers: Authorization, Content-Type.

---

### 3.2 `backend/config/settings.py`

**Purpose:** Loads `.env` from project root and provides validated access to all environment variables.

**Constants:**

| Name | Description |
|------|-------------|
| `REQUIRED_VARS` | Environment variable names that must be present at startup (a core code path depends on each). Missing any raises a startup error. |
| `OPTIONAL_VARS` | Variable names reserved for not-yet-implemented integrations (Stratus, Zia, SmartBrowz, vision model, and identity values like `CATALYST_PROJECT_ID`/`CATALYST_BASE_URL`). Documented in `.env.example` but **not** required — they never block startup. |

**Functions:**

| Function | Description |
|----------|-------------|
| `validate_settings()` | Iterates `REQUIRED_VARS`, collects any that are empty/missing, raises `ValueError` with a clear list if any are missing. Called once at startup in `main.py`. |
| `get(key: str) -> str` | Returns the value of a single env var. Raises `ValueError` if not set. Used everywhere instead of `os.getenv()` to enforce "fail loud" behavior. |

**Loading mechanism:** Uses `python-dotenv` with an explicit path calculated by walking up from `config/settings.py` → `backend/` → project root → `.env`. This ensures `.env` is found regardless of the working directory.

---

### 3.3 `backend/db/connection.py`

**Purpose:** Manages a global MySQL connection pool and provides a query execution function that enforces SELECT-only safety.

**Module-level state:** `_pool` — the global `aiomysql.Pool` instance, created once at startup.

**Functions:**

| Function | Description |
|----------|-------------|
| `create_pool() -> aiomysql.Pool` | Creates the connection pool with `host`, `port`, `user`, `password`, `db` from env vars. Settings: `minsize=3`, `maxsize=10`, `autocommit=True`, `connect_timeout=5`. Stores in `_pool`. Called once during FastAPI lifespan. |
| `get_pool() -> aiomysql.Pool` | Returns the existing pool. Raises `RuntimeError` if called before `create_pool()`. |
| `execute_query(sql, params) -> list[dict]` | **Security-critical function.** (1) Checks `sql.strip().upper().startswith("SELECT")` — raises `ValueError` if not. (2) Acquires a connection from the pool. (3) Executes with `aiomysql.DictCursor` (returns dicts, not tuples). (4) Uses `asyncio.wait_for` with a 5-second timeout. (5) Releases connection in `finally` block. Returns `list[dict]` where keys are column names. |
| `execute_write(sql, params) -> int` | INSERT/UPDATE counterpart to `execute_query`. Refuses anything starting with `SELECT` (raises `ValueError` — use `execute_query` for reads). Commits and returns `cur.lastrowid` for INSERTs or `cur.rowcount` for UPDATEs. Same pool, 5-second timeout. Added in Step 4 for persistent chat storage (`chat_store.py`). |
| `close_pool()` | Closes all connections in the pool. Called during FastAPI shutdown. |

**Security enforcement:** `execute_query` is the second line of defense (after `sql_validator.py`). Even if validation is bypassed, this function refuses to run anything that doesn't start with `SELECT`.

---

### 3.4 `backend/db/schema.sql`

**Purpose:** DDL statements for all database tables. Idempotent (`CREATE TABLE IF NOT EXISTS`). Run once against the Catalyst Data Store. The original 13 domain tables plus 2 chat-persistence tables added in Step 4 (`chat_sessions`, `chat_messages`).

**Tables defined:**

| Table | Purpose | Key columns |
|-------|---------|-------------|
| `officers` | Station officers | `officer_id` (PK), `badge_number` (UNIQUE), `rank` (ENUM), `is_active` |
| `fir_master` | Central FIR registry — parent record for all cases | `fir_id` (PK), `fir_number` (UNIQUE), `case_type` (ENUM of 11 types), `status` (ENUM), `investigating_officer_id` (FK→officers) |
| `accused` | Accused persons linked to FIRs | `accused_id` (PK), `fir_id` (FK→fir_master), `prior_fir_count` (denormalized), `arrest_status` (ENUM) |
| `victims` | Victims linked to FIRs | `victim_id` (PK), `fir_id` (FK→fir_master), `injury_description` |
| `cases_theft` | Theft-specific details | `theft_id` (PK), `fir_id` (FK, UNIQUE), `stolen_items` (JSON text), `estimated_value`, `recovered` |
| `cases_assault` | Assault details | `assault_id` (PK), `fir_id` (FK, UNIQUE), `weapon_used`, `injury_severity` (ENUM) |
| `cases_vehicle_theft` | Vehicle theft details | `vt_id` (PK), `fir_id` (FK, UNIQUE), `vehicle_type` (ENUM), `registration_no` |
| `cases_fraud` | Fraud details | `fraud_id` (PK), `fir_id` (FK, UNIQUE), `fraud_type` (ENUM), `amount_defrauded` |
| `cases_cybercrime` | Cybercrime details | `cyber_id` (PK), `fir_id` (FK, UNIQUE), `cyber_type` (ENUM), `platform` |
| `cases_missing_person` | Missing person details | `mp_id` (PK), `fir_id` (FK, UNIQUE), `found`, `found_condition` (ENUM) |
| `cases_drug_offense` | Drug offense details | `drug_id` (PK), `fir_id` (FK, UNIQUE), `drug_type`, `quantity_seized` |
| `case_relationships` | Links between entities for network graph | `rel_id` (PK), `entity_a_type`/`entity_a_id`, `entity_b_type`/`entity_b_id`, `relationship_type` (ENUM of 6 types) |
| `evidence_media` | Media files attached to FIRs (Stratus) | `media_id` (PK), `fir_id` (FK), `media_type` (ENUM), `stratus_folder_id`, `stratus_file_id` |
| `chat_sessions` | One row per conversation (Step 4) | `session_id` (PK, VARCHAR 36), `officer_id` (FK→officers), `title`, `created_at`, `updated_at` (auto-update), `message_count`, `is_active`; INDEX `(officer_id, updated_at)` |
| `chat_messages` | One row per turn — user OR assistant (Step 4) | `message_id` (PK, AUTO_INCREMENT), `session_id` (FK→chat_sessions), `role` (ENUM `user`/`assistant`), `content`, `sql_generated`, `has_table`, `has_media`, `graph_available`, `created_at`; INDEX `(session_id, created_at)` |

**Design rationale:** Case-type tables are separate (not one giant table) because: (1) smaller tables mean faster queries without full-scan WHERE clauses on type, (2) the schema linker can inject only the relevant table, (3) each case type has distinct columns.

**Note on missing case-type tables:** The `fir_master.case_type` ENUM defines 11 types, but only 7 have dedicated child tables: `theft`, `assault`, `vehicle_theft`, `fraud`, `cybercrime`, `missing_person`, `drug_offense`. The remaining 4 types — `robbery`, `murder`, `domestic_violence`, `other` — have no child detail tables. FIRs with these types exist in `fir_master` and have rows in `accused` and `victims`, but no case-specific detail records. This is a deliberate simplification: these case types either don't have distinct attributes worth separating, or were deprioritized during implementation.

---

### 3.5 `backend/db/seed.py`

**Purpose:** Generates realistic synthetic crime data for a single Bengaluru police station. Run standalone (`python backend/db/seed.py`) or imported. Uses `random.seed(42)` for deterministic, reproducible output.

**Execution model:** The file includes `sys.path` manipulation at both the top level (lines 4-6) and inside the `if __name__ == "__main__"` guard (lines 810-813). This allows it to work both as an imported module and as a standalone script. When run standalone, it appends the `backend/` directory to `sys.path` so imports like `from config.settings import get` resolve correctly.

**Key data:**
- 10 officers with Karnataka names and realistic ranks
- 220 FIRs across 11 case types (2022-2025), distributed: theft 50, assault 35, vehicle_theft 30, fraud 25, cybercrime 20, missing_person 15, drug_offense 15, robbery 10, murder 5, domestic_violence 10, other 5
- 5 named repeat offenders: Mahesh Gowda (8 FIRs — the "demo star"), Ravi Kumar (5), Suresh Nayak (4), Pavan Reddy (3), Anand Shetty (3)
- 35 case_relationships forming network clusters (gang, same MO, repeat location)
- 25 evidence_media records (15 images, 6 videos, 4 audio)
- All data geographically coherent to real Bengaluru areas

**Functions:**

| Function | Description |
|----------|-------------|
| `random_date(start, end)` | Returns a random date between start and end |
| `random_time()` | Returns a random HH:MM:SS string |
| `seed_officers(conn)` | Inserts 10 officers. Returns list of `officer_id`s. |
| `seed_fir_master(conn, officer_ids)` | Inserts 220 FIRs. Returns `(fir_records, fir_ids_by_type)` — a list of dicts and a dict mapping case_type to lists of fir_ids. Status distribution: 60% open, 25% under_investigation, 10% closed, 5% chargesheeted. The 220 total comes from `case_type_counts` dict: theft 50 + assault 35 + vehicle_theft 30 + fraud 25 + cybercrime 20 + missing_person 15 + drug_offense 15 + robbery 10 + murder 5 + domestic_violence 10 + other 5. |
| `seed_accused(conn, fir_records, fir_ids_by_type)` | Inserts accused persons. First inserts 5 named repeat offenders across their assigned FIRs, then distributes random accused across remaining FIRs (10 with 3 accused, 30 with 2, rest with 1). |
| `seed_victims(conn, fir_records)` | Inserts one victim per FIR with gender-appropriate names and case-type-appropriate injury descriptions. |
| `seed_case_type_tables(conn, fir_ids_by_type)` | Populates all 7 `cases_*` tables with type-specific details (stolen items, weapons, vehicle info, fraud amounts, cyber platforms, missing person details, drug types). |
| `seed_case_relationships(conn)` | Inserts 35 relationship records across 4 clusters: (1) Bullet Mahesh gang — 3 co_accused + 5 related_case links, (2) Ravi Thief network — 4 related_case + 1 co_accused, (3) Online fraud ring — 1 co_accused + N same_modus_operandi links between Suresh/Pavan, (4) Koramangala repeat location — 3 repeat_location links. |
| `seed_evidence_media(conn, fir_records)` | Picks 25 random FIRs and attaches evidence records with placeholder Stratus IDs. |
| `main()` | Entry point. Creates pool, checks if already seeded (skips if `fir_master` has rows), runs all seed functions in sequence. |

---

### 3.6 `backend/db/schema_catalog.py`

**Purpose:** The metadata layer that powers the schema linker and prompt builder. Contains the `SCHEMA_CATALOG` dict (table descriptions, columns, keywords), the few-shot example bank, and functions to build compact schema strings for LLM prompts.

**Constants:**

| Name | Value | Description |
|------|-------|-------------|
| `_MAX_SCHEMA_CHARS` | 3000 | Maximum characters for the schema string injected into LLM prompts |

**Data structures:**

`SCHEMA_CATALOG` — dict keyed by table name. Each entry has:
- `description` — human-readable table purpose
- `columns` — dict of `{column_name: type_and_description}`
- `keywords` — list of words that should trigger this table's inclusion
- `always_include` — (optional) if `True`, table is always in the schema (only `fir_master`)

`_FEW_SHOT_BANK` — list of 15 dicts, each with:
- `tables` — set of table names this example is relevant to
- `q` — example natural-language question
- `sql` — the expected SQL query

`ALLOWED_TABLES` — exported list of all valid table names (used by the SQL validator).

**Functions:**

| Function | Description |
|----------|-------------|
| `_format_table(name, meta, max_col_chars)` | Builds a text block for one table: name, description, columns with types. Optionally truncates column descriptions to `max_col_chars`. |
| `get_schema_for_tables(table_names) -> str` | Builds a compact schema string for LLM prompt injection. Always includes `fir_master` first. If total output exceeds `_MAX_SCHEMA_CHARS`, progressively truncates column descriptions (80→60→40→30 chars) until it fits. Last resort: hard-truncates at 3000 chars. |
| `get_few_shot_examples(table_names) -> str` | Selects the 3 most relevant few-shot examples for the given tables. Scoring: +1 per shared table, -1 per table in the example that isn't in the selected set. Returns formatted `-- Q: ... -- SQL: ...` blocks. |

---

### 3.7 `backend/llm/client.py`

**Purpose:** HTTP client for Catalyst QuickML LLM API. All LLM calls go through this module.

**Custom exceptions:**

| Exception | When raised |
|-----------|-------------|
| `LLMError` | Any LLM call failure — network error, non-200 status, empty/missing response field |

**Functions:**

| Function | Description |
|----------|-------------|
| `_llm_headers() -> dict` | Returns `{"Authorization": "Zoho-oauthtoken ...", "Content-Type": "application/json", "CATALYST-ORG": "..."}` — required on every Catalyst API call. |
| `ping_model(model_key) -> bool` | Sends `"Say OK."` to the given model. Returns `True` on non-empty 200 response, `False` otherwise. Never raises — used by health check. Timeout: 120s. |
| `call_llm(model_key, prompt, system_prompt, max_tokens) -> str` | **Core LLM call.** Sends a POST to `QUICKML_LLM_URL` with payload: `{model, prompt, system_prompt, max_tokens, temperature: 0.1, top_p: 0.95, top_k: 40}`. Returns the `response` field from JSON. Raises `LLMError` on: missing config, timeout (180s), HTTP error, non-200 status, invalid JSON, or empty response. |

**Catalyst QuickML API format (different from OpenAI):**
```json
{
  "model": "crm-di-qwen_coder_7b-it",
  "prompt": "user message here",
  "system_prompt": "system instruction here",
  "max_tokens": 4000,
  "temperature": 0.1
}
```
Response: `{"response": "generated text"}`

**Key difference from standard chat APIs:** Uses `prompt`/`system_prompt` fields, NOT a `messages` array. Uses `Zoho-oauthtoken` auth, NOT `Bearer`. Requires `CATALYST-ORG` header.

---

### 3.8 `backend/llm/sql_generator.py`

**Purpose:** Generates SQL from natural language using Qwen Coder with a self-correction retry loop.

**Constants:** `MAX_ATTEMPTS = 2`

**Custom exceptions:**

| Exception | When raised |
|-----------|-------------|
| `SQLGenerationError` | Validation failed on all retry attempts |
| `CannotAnswerError` | LLM returned the `CANNOT_ANSWER` sentinel |

**Functions:**

| Function | Description |
|----------|-------------|
| `_log(msg)` | stderr logger |
| `generate_sql(question, table_names, history) -> str` | **The SQL generation chain.** Steps: (1) Get compact schema via `get_schema_for_tables(table_names)`. (2) Get few-shot examples via `get_few_shot_examples(table_names)`. (3) Loop up to `MAX_ATTEMPTS`: attempt 1 builds the initial prompt via `build_sql_prompt()`; attempt 2 builds a correction prompt via `build_correction_prompt()` with the failed SQL and validation error. (4) Each attempt: call `call_llm("MODEL_SQL", ...)`, sanitize output, check for `CANNOT_ANSWER`, validate. (5) If valid, return the SQL. (6) If all attempts fail, raise `SQLGenerationError`. |

**Retry logic:**
```
Attempt 1:
  → build_sql_prompt(question, schema, few_shots, history)
  → call_llm("MODEL_SQL", ...)
  → sanitize_sql()
  → validate_sql()
  → if valid: return SQL
  → if invalid: save error, continue

Attempt 2:
  → build_correction_prompt(bad_sql, error, schema)
  → call_llm("MODEL_SQL", ...)
  → sanitize_sql()
  → validate_sql()
  → if valid: return SQL
  → if invalid: raise SQLGenerationError
```

---

### 3.9 `backend/llm/answer_formatter.py`

**Purpose:** Wraps the Qwen 14B Instruct model for three jobs: formatting DB results into prose, the intent router, and direct conversational answers.

**Functions:**

| Function | Description |
|----------|-------------|
| `format_answer(question, results, media_attachments, history) -> str` | Builds the answer prompt via `build_answer_prompt()`, calls `call_llm("MODEL_ANSWER", ...)` with `max_tokens=8000` (QuickML counts input+output against this, and up to 50 result rows are embedded). Returns the formatted text. Empty results are still sent to the LLM so it produces a clean "no records" response. Bubbles `LLMError` up to the pipeline. |
| `route_intent(question, history, has_recent_data) -> str` | **Intent router.** Tiny 14B classification call returning `"SQL"` or `"DIRECT"`. `max_tokens=2048` (the one-word answer is small, but QuickML counts the prompt against the budget). **Never raises** — defaults to `"SQL"` on any failure, so routing degrades to the original always-SQL behavior. |
| `generate_direct_answer(question, history, recent_table) -> str` | **Direct-answer path.** Answers WITHOUT SQL using the recent conversation + the most recent result set. `max_tokens=8000`. Bubbles `LLMError` up to the pipeline for fallback handling. |

> **Note:** `format_answer` previously used `max_tokens=1500`; it is now `8000` so the prompt (which can embed up to 50 result rows) plus the generated summary both fit within QuickML's combined input+output budget.

---

### 3.10 `backend/llm/prompts.py`

**Purpose:** All system prompts and prompt-building functions. Central place for prompt engineering.

**System prompts (constants):**

| Name | Used by | Key rules |
|------|---------|-----------|
| `SQL_SYSTEM_PROMPT` | SQL generation | Only SELECT; only provided schema; use JOINs with fir_master; return raw SQL only (no markdown/backticks); `CANNOT_ANSWER` if unanswerable; LIMIT 50; escape `rank` with backticks |
| `ANSWER_SYSTEM_PROMPT` | Answer formatting | Be concise; **never** emit a markdown table (the UI renders rows separately) — prose summary only; mention media; never speculate; "case" not "row" |
| `CORRECTION_SYSTEM_PROMPT` | SQL correction | Fix the broken SQL; return only corrected SQL; no explanation |
| `ROUTER_SYSTEM_PROMPT` | Intent router | Reply with exactly one word — `SQL` or `DIRECT`. DIRECT for follow-ups about already-shown data (referential words: "those", "them", "that", "the third one"…), filtering/ranking/insight over results already in context, greetings, and general questions. SQL when fresh crime data is needed. |
| `DIRECT_ANSWER_SYSTEM_PROMPT` | Direct answers | Answer from conversation + provided results only; **never fabricate** facts/numbers/trends/percentages not present in the data (explicit anti-hallucination rule); no markdown tables; concise professional prose. |

**Functions:**

| Function | Description |
|----------|-------------|
| `_format_history_for_prompt(history, max_turns=2, max_chars=100)` | Compresses conversation history into a short context block. Pairs user/assistant turns. Truncates assistant responses to `max_chars`. Returns empty string if no history. |
| `_format_history_for_sql_prompt(history, max_turns=2)` | History block for the SQL generator. Includes the prior turn's stored SQL so follow-ups can preserve filter clauses. |
| `_format_officer_for_prompt(officer)` | Builds the officer-identity block so first-person questions ("cases I am handling") resolve to `investigating_officer_id`. |
| `build_sql_prompt(question, schema, few_shots, history, officer=None) -> (system_prompt, user_prompt)` | Builds the two-tuple for the SQL LLM call. System prompt kept short (7B Coder struggles with long system prompts). Includes schema, few-shots, optional officer block, and (with history) a "Previous context" block. |
| `_truncate_for_answer(results, max_rows=50, max_field_chars=200)` | Trims result set to `max_rows` and clips long string fields. Non-string values pass through unmodified. Reused by both the answer prompt and the direct-answer prompt. |
| `_summarize_media(media_refs)` | Builds a summary string like "3 attachment(s): 2 image, 1 video". |
| `build_answer_prompt(question, results, media_refs, history) -> (system_prompt, user_prompt)` | Builds the answer prompt: optional history, question, truncated results as JSON, media summary. |
| `build_correction_prompt(original_sql, error, schema, officer=None) -> (system_prompt, user_prompt)` | Builds the correction prompt: the bad SQL, the error message, optional officer block, and schema. |
| `build_router_prompt(question, history, has_recent_data) -> (system_prompt, user_prompt)` | Builds the tiny router prompt: a compressed history slice, a flag stating whether recent results are in context, and the latest message. Kept small for a fast decision. |
| `build_direct_answer_prompt(question, history, recent_table) -> (system_prompt, user_prompt)` | Builds the direct-answer prompt: a richer history slice (`max_turns=4`, `max_chars=400`) plus the most recent result set (up to 30 rows as JSON) when available. |

---

### 3.11 `backend/pipeline/query_pipeline.py`

**Purpose:** The main orchestrator. Runs the full NL→SQL→answer chain. This is the function called by the chat routes.

**Data structures:**

`PipelineResponse` — dataclass with fields:
- `answer_text: str` — the formatted natural-language answer
- `table_data: list[dict]` — raw query results (for table rendering)
- `media_attachments: list[dict]` — evidence media references
- `sql_generated: str` — the SQL that was executed
- `graph_available: bool` — whether network graph data exists for the FIRs in results
- `error: str | None` — error message if something went wrong

**Functions:**

| Function | Description |
|----------|-------------|
| `_has_fir_id(results)` | Checks if the first result row contains a `fir_id` key |
| `collect_fir_ids(results)` | Imported from `media_resolver` — extracts unique integer `fir_id` values from all result rows. Shared so the extraction logic lives in one place. |
| `_check_graph_available(fir_ids)` | Runs a COUNT query against `case_relationships` to check if any of the given FIRs have relationship data. Returns `True` if count > 0. |
| `_most_recent_table(history)` | Walks history newest-first and returns the most recent assistant turn's stored table snapshot (or `[]`). Lets a follow-up be answered from the last result set without re-querying. |
| `_run_direct(question, history, recent_table)` | Runs the DIRECT path — calls `generate_direct_answer()` and returns a `PipelineResponse` with only `answer_text` filled. On `LLMError`/exception, returns a friendly error response (never raises). |
| `run_pipeline(question, history, officer=None) -> PipelineResponse` | **The main pipeline.** Never raises — every error is caught and converted to a user-friendly `answer_text` + `error` field. |

**Pipeline steps (in `run_pipeline`):**

0. **Intent routing** — `_most_recent_table(history)` recovers the last result set. **Optimization:** the router only runs when there *is* prior history (a brand-new chat with no history skips the router LLM call and goes straight to SQL — there's nothing to answer "directly" from yet). When history exists, `route_intent()` returns `SQL` or `DIRECT`; a `DIRECT` decision calls `_run_direct()` and returns immediately (no SQL, no DB).
1. **Schema linker** — `select_relevant_tables(question)` → list of table names
2. **SQL generation** — `generate_sql(question, tables, history, officer)` → `(SQL, attempts_used)` (with retry loop)
3. **Execute SQL** — `execute_query(sql)` → `list[dict]` (one corrective retry on MySQL error, within the shared `MAX_ATTEMPTS` budget)
4. **Media resolver** — `resolve_media(results)` → only if results have `fir_id` column
5. **Graph probe** — `_check_graph_available(fir_ids)` → boolean
6. **Answer formatting** — `format_answer(question, results, media, history)` → text

**Error handling in pipeline:**
- `CannotAnswerError` → **falls back to the DIRECT path** (`_run_direct`) so general questions and insights still get a real conversational answer instead of a canned error
- `SQLGenerationError` → "couldn't translate to valid query" message
- `LLMError` → "service unavailable" message
- DB errors → generic "couldn't run that query" message (raw MySQL details are logged, never surfaced)
- Answer formatter failure → fallback to "Found N records"

---

### 3.12 `backend/pipeline/sql_validator.py`

**Purpose:** The security gatekeeper. Validates every SQL query before execution.

**Constants:**

`FORBIDDEN_KEYWORDS` — list of 24 patterns: `drop`, `delete`, `update`, `insert`, `create`, `alter`, `truncate`, `replace`, `merge`, `grant`, `revoke`, `--`, `;/*`, `/*`, `*/`, `xp_`, `exec(`, `execute(`, `union select`, `1=1`, ` or 1`, `'; `, `load_file`, `into outfile`

`_BENIGN_TOKENS_PATTERN` — regex that strips `created_at`, `updated_at`, etc. before keyword checking to avoid false positives on legitimate column names.

**Data structures:**

`ValidationResult` — dataclass: `is_valid: bool`, `error: str | None`

**Functions:**

| Function | Description |
|----------|-------------|
| `sanitize_sql(sql) -> str` | Cleans raw LLM output: strips whitespace, removes markdown code fences (` ```sql `), removes surrounding backticks, drops trailing semicolons. Preserves internal backticks (e.g., `` `rank` ``). |
| `_extract_tables(sql) -> list[str]` | Regex-based extraction of table names after `FROM` and `JOIN` clauses. Handles backtick-quoted identifiers. Not a full parser — catches simple cases, MySQL catches the rest. |
| `validate_sql(sql, allowed_tables=None) -> ValidationResult` | **The validation chain.** Checks in order: (1) Not None/empty. (2) Not `CANNOT_ANSWER`. (3) Starts with `SELECT` or `WITH`. (4) No semicolons inside (blocks multi-statement injection). (5) No forbidden keywords (after stripping benign column-name patterns). (6) All referenced tables are in `ALLOWED_TABLES`. Returns `ValidationResult`. Never raises. |

**Self-test:** When run directly (`python sql_validator.py`), executes 12 test cases covering valid SQL, injection attempts, markdown-wrapped SQL, false-positive prevention, and unknown tables.

---

### 3.13 `backend/pipeline/media_resolver.py`

**Purpose:** Looks up evidence media records for any FIRs present in query results.

**Functions:**

| Function | Description |
|----------|-------------|
| `collect_fir_ids(results) -> list[int]` | Extracts unique integer `fir_id` values from result rows. **Shared** with `query_pipeline.py` (imported there) so the logic exists in exactly one place. |
| `resolve_media(results) -> list[dict]` | (1) Collects `fir_id`s from results. (2) Builds a parameterized `IN` query against `evidence_media`. (3) Executes one DB query. (4) Returns list of `{media_type, url, description, fir_id}`. URLs are placeholders (`/api/media/{stratus_file_id}`) until real Stratus integration in Step 5. Returns `[]` if no `fir_id` column or no matches. |

---

### 3.14 `backend/pipeline/schema_linker.py`

**Purpose:** Selects the most relevant tables for a given question using keyword matching.

**Constants:** `_MAX_TABLES = 5` — maximum tables returned (fir_master + up to 4 others)

**Functions:**

| Function | Description |
|----------|-------------|
| `_keyword_matches(question_lower, keyword) -> bool` | Matches a keyword against the lowercased question. Multi-word keywords (containing space, hyphen, or underscore) use substring match. Single-word keywords use word-boundary regex (`\b`) so "si" doesn't match inside "missing" or "phishing". |
| `select_relevant_tables(question) -> list[str]` | **The table selection algorithm.** (1) Lowercase the question. (2) For each table in `SCHEMA_CATALOG`, skip if `always_include: True` (collect separately). (3) Otherwise, score by counting keyword matches. (4) Sort by score descending, then alphabetically. (5) Build result: `fir_master` first, then other always-include tables, then top-scoring keyword matches up to `_MAX_TABLES`. |

**Example behavior:**
- "How many theft cases are open?" → `["fir_master", "cases_theft"]`
- "Show CCTV footage for FIR 2024" → `["fir_master", "evidence_media"]`
- "Who is Mahesh Gowda" → `["fir_master", "accused"]` (name matches accused keywords)

---

### 3.15 `backend/conversation/history.py`

**Purpose:** Persists conversation history per session in Catalyst NoSQL, with an in-memory fallback for local development.

**Constants:**
- `MAX_TURNS = 10` — last 10 messages (~5 user + 5 assistant turns)
- `_NOSQL_TIMEOUT = 5.0` — seconds
- `_TABLE_SNAPSHOT_ROWS = 30` — max rows of an assistant turn's result set kept in history for DIRECT follow-up answers (bounds the stored NoSQL document size)

**Module-level state:**
- `_local_history: dict[str, list[dict]]` — in-memory fallback dict, keyed by session_id
- `_local_lock: asyncio.Lock` — guards concurrent access to `_local_history` in async context

**Functions:**

| Function | Description |
|----------|-------------|
| `_nosql_headers()` | Returns Bearer + CATALYST-ORG headers |
| `_nosql_url(session_id)` | Builds `{NOSQL_BASE_URL}/table/conversation_history/document/{session_id}` |
| `_nosql_collection_url()` | Builds `{NOSQL_BASE_URL}/table/conversation_history/document` |
| `_local_get(session_id)` | Thread-safe read from `_local_history`, returns last `MAX_TURNS` |
| `_local_set(session_id, turns)` | Thread-safe write to `_local_history`, trims to `MAX_TURNS` |
| `_local_clear(session_id)` | Thread-safe delete from `_local_history` |
| `get_history(session_id) -> list[dict]` | Fetches history. Tries NoSQL first. On success: parses JSON from `data.history` field. On 404 or error: falls back to `_local_get()`. Never raises. |
| `save_turn(session_id, user_message, assistant_message, assistant_sql=None, assistant_table=None)` | Appends a user+assistant turn. Updates in-memory first (always). Then PUTs to NoSQL. If PUT returns 404 (document doesn't exist), POSTs to create it. `assistant_sql` is stored on the assistant turn so follow-up SQL generation can preserve filter clauses; `assistant_table` stores a bounded (`_TABLE_SNAPSHOT_ROWS`) snapshot of the result set so the next turn can answer follow-ups via the DIRECT path **without re-querying**. Never raises. |
| `clear_history(session_id)` | Deletes from both NoSQL and in-memory. Never raises. |
| `init_nosql_table()` | Probes NoSQL by fetching a non-existent document (`__probe__`). Status 200 or 404 means the service is alive. Called once at startup. Never raises. |

**Fallback pattern:** Every function tries the remote service first, catches all exceptions, and falls back to `_local_history`. This ensures the chat works even when Catalyst NoSQL is misconfigured.

---

### 3.16 `backend/conversation/session_store.py`

**Purpose:** Stores per-session metadata (title, timestamps, message count) in a Catalyst NoSQL `session_metadata` collection, with an in-memory fallback that mirrors `conversation/history.py`. Also owns session-title generation. Backs the chat-history sidebar.

**Constants:**
- `_NOSQL_TIMEOUT = 5.0` — seconds
- `_TITLE_STOP_WORDS` — common words stripped before picking title keywords
- `_TITLE_MAX_WORDS = 8`, `_TITLE_MAX_LENGTH = 60`, `_TITLE_FALLBACK = "New chat"`

**Module-level state:**
- `_local_sessions: dict[str, dict]` — in-memory fallback keyed by session_id
- `_local_lock: asyncio.Lock` — guards concurrent access

**Functions:**

| Function | Description |
|----------|-------------|
| `create_session(document) -> dict` | Persists a new `session_metadata` document (writes in-memory first, then POSTs to NoSQL). Never raises. |
| `get_session(session_id) -> dict \| None` | Fetches one session document; falls back to in-memory on NoSQL error. Never raises. |
| `update_session(session_id, updates) -> dict \| None` | Merges `updates` into an existing document and PUTs it (creating it on 404). Returns `None` when no session exists. Never raises. |
| `list_sessions(officer_id) -> list[dict]` | Returns all of an officer's sessions ordered by `updated_at` DESC. Filters/sorts in Python since NoSQL may not support filtered queries. Never raises. |
| `generate_title(message) -> str` | Derives a 3–8 word, ≤60-char human-readable title from the first user message; falls back to `"New chat"`. |

> **Step 4 note:** As of Step 4, **MySQL (`chat_store.py`) is the source of truth** for the session list and message history. `session_store.py` (NoSQL `session_metadata`) is still written to by `history.py`'s metadata sync but is no longer the primary read path for the sidebar. See [Section 9.8](#98-nosql-session_metadata--superseded-by-mysql).

---

### 3.16b `backend/db/chat_store.py`

**Purpose:** Persistent chat storage added in Step 4. Sessions and per-message metadata live in **MySQL** (Catalyst Data Store); rich result data (table snapshots, media) for a message lives in **NoSQL**, keyed by message id. All functions are non-fatal — they log and return a safe default on error so a storage outage never breaks the chat.

**Functions:**

| Function | Description |
|----------|-------------|
| `create_session(session_id, officer_id, title) -> bool` | `INSERT IGNORE` a new `chat_sessions` row (title clipped to 60 chars). Returns `True`/`False`. |
| `update_session_timestamp(session_id, increment_count=True)` | Touches `updated_at` and (by default) bumps `message_count` by 2 (one user + one assistant turn). Called after every successful pipeline run. |
| `get_sessions_for_officer(officer_id, limit=30) -> list[dict]` | Loads the officer's active sessions newest-first (`ORDER BY updated_at DESC`), datetimes serialized to ISO strings. Backs the sidebar. Returns `[]` on error. |
| `verify_session_owner(session_id, officer_id) -> bool` | Ownership check used before loading messages or exporting. Returns `False` if not found or owned by another officer. |
| `save_message_pair(session_id, question, answer_text, sql_generated, has_table, has_media, graph_available, table_data, media_attachments) -> int \| None` | Inserts the user row + assistant row; when the assistant turn has a table/media, saves the rich data to NoSQL keyed by the assistant `message_id`. Returns the assistant `message_id`. |
| `get_messages_for_session(session_id) -> list[dict]` | Loads all messages oldest-first (cap 100); hydrates `table_data`/`media_attachments` from NoSQL for assistant messages that carry them. |
| `save_rich_data(message_id, table_data, media_attachments)` | Writes `{table_data, media_attachments}` to NoSQL `message_rich_data` under key `msg_rich_{message_id}`. Non-fatal. |
| `load_rich_data(message_id) -> dict \| None` | Reads and parses the rich-data document for a message. Returns `None` on miss/error. |

> **Environment note:** The NoSQL `message_rich_data` round-trip depends on a reachable Catalyst NoSQL endpoint + valid token. When NoSQL is unavailable the MySQL persistence still works fully; only the rich table/media hydration on reload degrades (rows come back empty until NoSQL is reachable).

---

### 3.17 `backend/auth/simple_auth.py`

**Purpose:** JWT-based authentication for local development. Designed so swapping to Catalyst Authentication in production requires changing only `get_current_officer`, not any routes.

**Constants:**
- `TOKEN_EXPIRE_HOURS = 24`
- `ALGORITHM = "HS256"`

**Module-level state:** `_security = HTTPBearer(auto_error=False)` — `auto_error=False` so custom 401 messages are possible and SSE routes can fall back to query params.

**Functions:**

| Function | Description |
|----------|-------------|
| `create_access_token(officer_id, badge_number) -> str` | Creates a JWT with `officer_id`, `badge_number`, and `exp` (24h from now). Signed with `APP_SECRET_KEY`. |
| `_unauthorized(detail)` | Helper that returns an `HTTPException(401)` with the given detail message. |
| `verify_token(token) -> dict` | Decodes and verifies JWT. Returns payload dict. Raises HTTP 401 on any failure (expired, invalid signature, missing). |
| `get_current_officer(credentials) -> dict` | **FastAPI dependency for header-based auth.** Extracts Bearer token from `Authorization` header. Returns decoded payload. Raises 401 if missing. |
| `get_current_officer_sse(request, credentials, token) -> dict` | **FastAPI dependency for SSE auth.** Accepts token from: (1) `Authorization: Bearer` header, OR (2) `?token=` query parameter. Needed because browser `EventSource` can't set custom headers. |
| `login(badge_number, password) -> dict` | Queries `officers` table by `badge_number`. Validates password = `badge_number + "123"`. Returns `{access_token, officer: {officer_id, badge_number, full_name, rank}}`. Raises HTTP 401 on failure. |

---

### 3.18 `backend/routers/chat.py`


**Purpose:** Chat API endpoints — the main user-facing routes.

**Pydantic models:**

| Model | Fields |
|-------|--------|
| `ChatRequest` | `question: str` (1-500 chars), `session_id: str` (1-128 chars) |
| `ChatResponse` | `answer_text`, `table_data`, `media_attachments`, `sql_generated`, `graph_available`, `error` |
| `SessionMetadata` | `session_id`, `title`, `created_at`, `updated_at`, `message_count` |
| `SessionListResponse` | `sessions: list[SessionMetadata]` |
| `Message` | `message_id` (int\|str), `role`, `content`, `sql_generated`, `has_table`, `has_media`, `graph_available`, `table_data`, `media_attachments`, `created_at` |
| `MessagesResponse` | `messages: list[Message]` |

**Functions:**

| Function | Description |
|----------|-------------|
| `_sse(event) -> str` | Formats a dict as an SSE `data:` line with `\n\n` terminator |
| `_persist_turn(session_id, officer, question, result)` | **Step 4 persistence helper.** Creates the `chat_sessions` row on a session's first message, saves the user+assistant pair via `chat_store.save_message_pair` (rich data to NoSQL when present), then bumps `updated_at`/`message_count`. Never raises — logs and continues on failure. Called after `save_turn` in both chat endpoints. |
| `list_chat_sessions(officer)` | `GET /api/chat/sessions` — lists the officer's sessions newest-first **from MySQL** (`chat_store.get_sessions_for_officer`). Always HTTP 200 (returns `[]` on DB error). |
| `create_chat_session(officer)` | `POST /api/chat/sessions` — creates a NoSQL `session_metadata` doc and returns `SessionMetadata` (HTTP 201). **Currently unused by the UI** (see [9.5](#95-backend-created-sessions-on-new-chat--deprecated-flow-change)). |
| `get_session_messages(session_id, officer)` | `GET /api/chat/sessions/{id}/messages` — verifies ownership via `chat_store.verify_session_owner` (404 on mismatch/not-found), then returns all messages oldest-first from MySQL + NoSQL rich data. **No pagination** (the prior `limit`/`before_message_id` cursor flow was removed — see [9.9](#99-message-pagination--removed)). |
| `chat(request, officer)` | `POST /api/chat` — non-streaming endpoint (testing/fallback). Fetches history, runs pipeline, `save_turn` (with `assistant_table`), then `_persist_turn`. Always returns HTTP 200 with `ChatResponse`. |
| `chat_stream(question, session_id, officer)` | `GET /api/chat/stream` — SSE streaming endpoint. Protected by `get_current_officer_sse` (header or query param). After the pipeline, `save_turn` (with `assistant_table`) then `_persist_turn`. Returns `StreamingResponse` with `text/event-stream`. |
| `_tokenize(text) -> list[str]` | Splits text into space-preserving tokens for word-by-word streaming. Each token (except last) includes trailing space. |

**SSE event types emitted by `chat_stream`:**

| Type | When | Payload |
|------|------|---------|
| `status` | During pipeline execution | `{"content": "Analyzing..."}` |
| `sql` | After SQL generation | `{"content": "SELECT ..."}` |
| `error` | On pipeline failure | `{"message": "..."}` |
| `token` | During answer streaming | `{"content": "word "}` |
| `table` | If results exist | `{"data": [...]}` |
| `media` | If media attachments exist | `{"attachments": [...]}` |
| `graph_available` | If graph data exists | `{}` |
| `done` | Always at end | `{}` |

**Simulated streaming:** Catalyst QuickML doesn't support true streaming (returns full response). The route simulates it by: (1) emitting status events during pipeline execution, (2) running the full pipeline (60-120s), (3) splitting the answer into words and yielding each with a 30ms delay.

**Error handling in SSE:** On pipeline error, the route emits an `error` event followed by token events containing the user-friendly `answer_text` (so the user sees an explanation, not just an error). On client disconnect (`asyncio.CancelledError`), the generator exits cleanly without logging an error. On unexpected exceptions, an `error` event + `done` event are emitted.

---

### 3.19 `backend/routers/auth.py`

**Purpose:** Authentication routes.

**Pydantic models:**

| Model | Fields |
|-------|--------|
| `LoginRequest` | `badge_number: str`, `password: str` |
| `OfficerInfo` | `officer_id: int`, `badge_number: str`, `full_name: str`, `rank: str` |
| `LoginResponse` | `access_token: str`, `token_type: "bearer"`, `officer: OfficerInfo` |

**Functions:**

| Function | Description |
|----------|-------------|
| `login_route(request)` | `POST /api/auth/login` — calls `login()` from auth layer. Returns `LoginResponse` with token + officer info. HTTP 401 on bad credentials, HTTP 503 on infrastructure error. |
| `logout_route()` | `POST /api/auth/logout` — stateless, returns `{"message": "Logged out successfully."}`. Frontend drops the token. |

---

### 3.20 `backend/routers/export.py`

**Purpose:** PDF export of a chat session (Step 4). Renders the conversation as print-ready HTML and converts it to PDF via Catalyst SmartBrowz, with a graceful HTML fallback.

**Functions:**

| Function | Description |
|----------|-------------|
| `_build_html(officer_name, badge_number, title, messages) -> str` | Builds a styled, self-contained HTML document: a header (officer + badge + session title + export date), each message (user bubbles right-aligned, assistant blocks with any result table rendered, max 50 rows), and a confidential footer. |
| `export_session_pdf(session_id, officer)` | `POST /api/chat/sessions/{id}/export` — (1) verifies ownership via `verify_session_owner` (404 on mismatch); (2) loads messages via `get_messages_for_session` (400 if none); (3) fetches session title + officer name/badge from MySQL; (4) builds HTML; (5) POSTs to `SMARTBROWZ_URL` for a PDF. On success streams `application/pdf` (`KSP-Chat-{id}.pdf`). **Fallback:** if SmartBrowz returns non-200 or errors, streams the raw HTML as a downloadable `.html` so the export button always works. |

> **Note:** `SMARTBROWZ_URL` was previously a reserved/optional env var; it is now actively read by this router. The exact SmartBrowz request shape should be verified against Catalyst docs before a production demo — the HTML fallback covers the case where it differs.

---

## 4. End-to-End Feature Flows

### 4.1 User Login

```
Frontend LoginPage.jsx
  → api/auth.js: login(badgeNumber, password)
    → POST /api/auth/login {badge_number, password}
      → routers/auth.py: login_route()
        → auth/simple_auth.py: login()
          → db/connection.py: execute_query("SELECT ... FROM officers WHERE badge_number = %s", ...)
          → if password != badge_number + "123": HTTP 401
          → auth/simple_auth.py: create_access_token(officer_id, badge_number)
          → returns {access_token, officer}
    → api/auth.js: setToken(token, officer)  // stored in module-level variable, NOT localStorage
  → hooks/useAuth.js: setIsAuthenticated(true)
  → App.jsx renders ChatWindow
```

**Files involved:** `LoginPage.jsx` → `api/auth.js` → `routers/auth.py` → `auth/simple_auth.py` → `db/connection.py`

---

### 4.2 Ask a Question (Full Pipeline)

```
Frontend ChatWindow.jsx: handleSend()
  → api/chat.js: startChatStream(question, sessionId, callbacks)
    → fetch("GET /api/chat/stream?question=...&session_id=...&token=...")
      → routers/chat.py: chat_stream()
        → auth/simple_auth.py: get_current_officer_sse()  // verify JWT
        → conversation/history.py: get_history(session_id)
          → HTTP GET to Catalyst NoSQL (or in-memory fallback)
        → pipeline/query_pipeline.py: run_pipeline(question, history)
          
          Step 0: Intent Router (only when history exists)
            → llm/answer_formatter.py: route_intent(question, history, has_recent_data)
              → "DIRECT" → generate_direct_answer(...) and RETURN (no SQL, no DB)
              → "SQL"    → continue below
              (a brand-new chat with no history skips this step → straight to SQL)
          
          Step 1: Schema Linker
            → pipeline/schema_linker.py: select_relevant_tables(question)
              → SCHEMA_CATALOG keyword matching
              → returns ["fir_master", "cases_theft", ...]
          
          Step 2: SQL Generation
            → llm/sql_generator.py: generate_sql(question, tables, history)
              → db/schema_catalog.py: get_schema_for_tables(tables)  // compact schema
              → db/schema_catalog.py: get_few_shot_examples(tables)  // 3 examples
              → llm/prompts.py: build_sql_prompt(...)  // assemble prompt
              → llm/client.py: call_llm("MODEL_SQL", prompt, system_prompt)
                → HTTP POST to Catalyst QuickML (Qwen 2.5-7B Coder)
              → pipeline/sql_validator.py: sanitize_sql(raw)
              → pipeline/sql_validator.py: validate_sql(cleaned)
              → if invalid: build_correction_prompt(), retry once
              → returns validated SQL string
        
          Step 3: Execute SQL
            → db/connection.py: execute_query(sql)
              → aiomysql pool → MySQL → returns list[dict]
        
          Step 4: Media Resolution
            → pipeline/media_resolver.py: resolve_media(results)
              → db/connection.py: execute_query("SELECT ... FROM evidence_media WHERE fir_id IN (...)")
              → returns [{media_type, url, description, fir_id}]
        
          Step 5: Graph Probe
            → _check_graph_available(fir_ids)
              → db/connection.py: execute_query("SELECT COUNT(*) FROM case_relationships WHERE ...")
              → returns True/False
        
          Step 6: Answer Formatting
            → llm/answer_formatter.py: format_answer(question, results, media, history)
              → llm/prompts.py: build_answer_prompt(...)
              → llm/client.py: call_llm("MODEL_ANSWER", prompt, system_prompt)
                → HTTP POST to Catalyst QuickML (Qwen 2.5-14B Instruct)
              → returns formatted text
        
          → returns PipelineResponse(answer_text, table_data, media, sql, graph_available, error)
        
        → SSE events streamed back:
          {"type":"status", "content":"Analyzing..."}
          {"type":"status", "content":"Generating database query..."}
          {"type":"sql", "content":"SELECT ..."}
          {"type":"status", "content":"Formatting answer..."}
          {"type":"token", "content":"There "}
          {"type":"token", "content":"are "}
          {"type":"token", "content":"20 "}
          ...
          {"type":"table", "data": [...]}
          {"type":"media", "attachments": [...]}
          {"type":"graph_available"}
          {"type":"done"}
        
        → conversation/history.py: save_turn(session_id, question, answer)
    
    Frontend receives events:
      → onStatus: update status text
      → onToken: append to assistant message (streaming text effect)
      → onTable: set tableData on message → TableRenderer.jsx renders HTML table
      → onMedia: set mediaAttachments → MessageBubble.jsx renders media list
      → onDone: stop streaming, re-enable input
```

**Files involved (in order):** `ChatWindow.jsx` → `api/chat.js` → `routers/chat.py` → `auth/simple_auth.py` → `conversation/history.py` → `pipeline/schema_linker.py` → `llm/sql_generator.py` → `llm/prompts.py` → `db/schema_catalog.py` → `llm/client.py` → `pipeline/sql_validator.py` → `db/connection.py` → `pipeline/media_resolver.py` → `llm/answer_formatter.py` → back to `routers/chat.py` → SSE to `api/chat.js` → `ChatWindow.jsx` + `MessageBubble.jsx` + `TableRenderer.jsx`

---

### 4.3 SSE Streaming (Simulated)

The Catalyst QuickML API does **not** support streaming (one POST returns the full response). The system simulates streaming:

1. Pipeline runs synchronously (60-120 seconds total — 2 LLM calls + 1-2 DB queries)
2. While running, `status` events are emitted to keep the connection alive
3. After the pipeline completes, the answer text is split into whitespace-delimited tokens
4. Each token is yielded as a `token` SSE event with a 30ms delay between tokens
5. This creates a "typewriter" effect in the UI

---

### 4.4 Conversation History (Multi-Turn)

```
Turn 1: "Show me cases in Koramangala"
  → history: [] (empty)
  → pipeline runs, saves turn to NoSQL + in-memory

Turn 2: "Now show only the open ones"
  → history: [{"role":"user","content":"Show me cases in Koramangala"}, 
              {"role":"assistant","content":"Found 15 cases..."}]
  → SQL prompt includes "Previous context: Officer asked: Show me cases in Koramangala\nSystem answered about: Found 15 cases in Koramangala..."
  → LLM generates SQL that references Koramangala (from context) + filters by status='open'
```

**History flow:**
1. `get_history(session_id)` → tries NoSQL, falls back to in-memory
2. History is passed to `generate_sql()` → compressed to last 2 turns in `_format_history_for_prompt()`
3. History is passed to `format_answer()` → same compression
4. After pipeline completes, `save_turn(session_id, question, answer, assistant_sql, assistant_table)` → updates both NoSQL and in-memory; `assistant_table` stores a bounded result snapshot so the next turn's DIRECT path can answer without re-querying. `_persist_turn(...)` then writes the session + message pair to MySQL (see [4.7](#47-persistent-chat-storage))

---

### 4.5 SQL Self-Correction Loop

```
Question: "How many theft cases are open in Koramangala?"

Attempt 1:
  LLM generates: "SELECT COUNT(*) FROM cases_theft WHERE status = 'open'"
  Validator: FAIL — "status" column doesn't exist in cases_theft (it's in fir_master)
  → Save error message

Attempt 2 (correction):
  Prompt: "The following SQL query is invalid: SELECT COUNT(*) FROM cases_theft WHERE status = 'open'\nError: Unknown column 'status'\nSchema: [fir_master schema + cases_theft schema]\nWrite the corrected SQL query only."
  LLM generates: "SELECT COUNT(*) AS open_theft_cases FROM fir_master AS f JOIN cases_theft AS t ON t.fir_id = f.fir_id WHERE f.status = 'open' AND f.incident_location LIKE '%Koramangala%'"
  Validator: PASS
  → Execute and return results
```

---

### 4.6 Intent Routing & Direct Answers

Every turn that has prior conversation history is first classified by the **intent router** (a small 14B call) before any SQL work:

```
Turn 1: "How many theft cases are open?"  (no history)
  → router SKIPPED (no history → nothing to answer directly from)
  → SQL path: generate → execute → format
  → answer + table_data; the table snapshot (≤30 rows) is saved into history

Turn 2: "Which of those are in Koramangala?"  (history present)
  → route_intent() → "DIRECT"  (referential "those" + recent results in context)
  → generate_direct_answer(question, history, recent_table)
  → answered straight from the cached rows — NO SQL, NO DB hit

Turn 3: "Thanks, what else can you help with?"  (history present)
  → route_intent() → "DIRECT"  (general question)
  → conversational answer
```

**Decision rules** (`ROUTER_SYSTEM_PROMPT`): DIRECT for follow-ups that refer to
already-shown data, filtering/ranking/insight over results already in context,
greetings, and general questions; SQL when fresh crime data is needed.

**Why this exists:** (1) avoids regenerating/re-running SQL when the answer is
already in context, (2) lets the assistant give *insight* about retrieved data
rather than just re-displaying a table, and (3) handles general/greeting messages
that previously produced a "can't generate SQL" error.

**Key safeguards:**
- **No-history optimization:** the router is skipped entirely on a brand-new chat's first message (nothing to answer directly from), saving one LLM round-trip on the most common case. Empty-history turns go straight to SQL.
- **Graceful fallback:** `route_intent()` never raises — any router failure defaults to `SQL`, preserving the original behavior.
- **CANNOT_ANSWER → DIRECT:** if the SQL chain decides the question can't be answered from the DB, the pipeline falls back to a direct conversational answer instead of a canned error.
- **Anti-hallucination:** `DIRECT_ANSWER_SYSTEM_PROMPT` forbids inventing facts/numbers/trends not present in the provided data — for a thin result (e.g. a single count) it states what the data shows and asks the officer to request a new query rather than fabricating an "insight".

**Context plumbing:** `save_turn(..., assistant_table=result.table_data)` stores a
bounded snapshot (`_TABLE_SNAPSHOT_ROWS = 30`) of each answer's result set on the
assistant turn. On the next turn, `_most_recent_table(history)` recovers it and
feeds it to the direct-answer prompt, so the model discusses real rows without a
re-query.

---

### 4.7 Persistent Chat Storage

Sessions and messages survive page reloads via MySQL (Step 4):

```
After a successful pipeline run (POST /api/chat or GET /api/chat/stream):
  → save_turn(...)                         # conversation history → NoSQL + in-memory
  → _persist_turn(session_id, officer, question, result)
      → if first message of session: chat_store.create_session(...)   # chat_sessions row
      → chat_store.save_message_pair(...)  # user row + assistant row → chat_messages (MySQL)
          → if has_table/has_media: save_rich_data(...)               # → NoSQL message_rich_data
      → chat_store.update_session_timestamp(...)                      # bump updated_at + message_count

On login / sidebar load:
  → GET /api/chat/sessions      → chat_store.get_sessions_for_officer(officer_id)   # MySQL, newest-first

On opening a past session:
  → GET /api/chat/sessions/{id}/messages
      → verify_session_owner(...)          # 404 if not owned
      → get_messages_for_session(...)      # MySQL rows + NoSQL rich data (table/media)

Export:
  → POST /api/chat/sessions/{id}/export    # build HTML → SmartBrowz PDF (HTML fallback)
```

**Source of truth:** MySQL (`chat_sessions`, `chat_messages`) for the session list
and message history; NoSQL (`message_rich_data`) for per-message table/media
snapshots. Ownership is enforced by `officer_id` on every read/export.

---

## 5. Frontend Architecture

The frontend is a single-page React 18 app (no router) built with Vite 5. The
top-level shell is a **two-panel layout** modeled on Claude.ai: a collapsible
left **sidebar** (new chat, a "Recents" session list, and the officer identity
block) beside a **main content area** that shows either a centered welcome
screen (empty chat) or the scrollable message thread, with the composer below.

```
frontend/
├── index.html                # SPA shell
├── package.json              # React 18, Vite 5, Vitest 2
├── vite.config.js            # Dev proxy: /api → localhost:8000; Vitest (jsdom) config
├── .env                      # VITE_APP_NAME only
└── src/
    ├── main.jsx              # ReactDOM entry point
    ├── App.jsx               # Root: auth state → LoginPage, LandingPage, or ChatWindow
    ├── api/
    │   ├── auth.js           # Token management + login/logout API
    │   └── chat.js           # SSE stream consumer + session/message REST client
    ├── context/
    │   └── LangContext.jsx   # Shared context for active language (English/Kannada)
    ├── components/
    │   ├── PortalShell.jsx   # Header/footer shell for landing and login pages
    │   ├── LandingPage.jsx   # Public landing page with portal features
    │   ├── LoginPage.jsx     # Badge + password form
    │   ├── ChatWindow.jsx    # Two-panel shell: sidebar + main content; owns all chat state
    │   ├── WelcomeScreen.jsx # Centered greeting + suggestion chips (empty chat)
    │   ├── Composer.jsx      # Auto-growing input box, send/attach/voice buttons
    │   ├── MessageBubble.jsx # Single message renderer (+ markdown-table stripping)
    │   ├── TableRenderer.jsx # HTML table from JSON data
    │   ├── SessionList.jsx   # Scrollable session list (loading/empty/error states)
    │   ├── SessionItem.jsx   # One session row (title + timestamp + count + export button)
    │   ├── OfficerRow.jsx    # Sidebar-bottom officer avatar + sign-out popup
    │   └── Icons.jsx         # Inline SVG icon set (no icon library)
    ├── hooks/
    │   ├── useAuth.js        # Auth state management
    │   └── useLang.js        # Language selection state hook
    ├── styles/
    │   └── main.css          # Warm-canvas styling (Design.md) — app shell + components
    └── test/
        └── setup.js          # Vitest/jsdom test setup
```

---

### 5.1 Drag-to-Resize Sidebar

**Feature:** The sidebar can be resized by dragging its right edge, mirroring the smooth, polished feel of Claude.ai's resizable panel. The chosen width persists across reloads.

**Implementation location:** `frontend/src/components/ChatWindow.jsx` + `frontend/src/styles/main.css`

**State:**
- `sidebarWidth` — number (px), lazy-initialized from localStorage (key: `chs.sidebarWidth`), defaults to 260px, clamped to 220–480px range
- `isResizing` — boolean, `true` while actively dragging, used to disable CSS transition and apply global `userSelect: none` + `cursor: col-resize`

**Constants:**
```js
const SIDEBAR_WIDTH_KEY = 'chs.sidebarWidth'
const SIDEBAR_MIN_WIDTH = 220
const SIDEBAR_MAX_WIDTH = 480
const SIDEBAR_DEFAULT_WIDTH = 260
```

**Key functions:**

| Function | Description |
|----------|-------------|
| `readSidebarWidth()` | Lazy initializer. Reads from localStorage, parses as int, clamps to `[220, 480]`. Falls back to 260px if missing/invalid. Guards for SSR (no `window`). |
| `handleResizeStart(e)` | Drag start handler attached to `.sidebar-resize-handle`'s `onMouseDown` and `onTouchStart`. Sets `isResizing: true`, adds window-level `mousemove`/`mouseup` (and `touchmove`/`touchend`) listeners, applies `userSelect: none` + `cursor: col-resize` to `document.body`. The `onMove` callback reads `clientX` (or `touches[0].clientX`), clamps to bounds, calls `setSidebarWidth(next)`. The `onUp` callback removes listeners, resets body styles, sets `isResizing: false`. |
| `handleResizeReset()` | Double-click handler on the resize handle. Resets `sidebarWidth` to 260px. |

**Persistence effect:**
```js
useEffect(() => {
  if (typeof window === 'undefined' || !window.localStorage) return
  try {
    window.localStorage.setItem(SIDEBAR_WIDTH_KEY, String(sidebarWidth))
  } catch {
    // Ignore storage write failures
  }
}, [sidebarWidth])
```

**JSX structure:**
```jsx
<aside
  className={`sidebar ${sidebarOpen ? 'expanded' : 'collapsed'}${isResizing ? ' resizing' : ''}`}
  style={sidebarOpen ? { width: sidebarWidth } : undefined}
>
  {/* sidebar content */}

  {/* Resize handle — only rendered when expanded */}
  {sidebarOpen && (
    <div
      className="sidebar-resize-handle"
      onMouseDown={handleResizeStart}
      onTouchStart={handleResizeStart}
      onDoubleClick={handleResizeReset}
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize sidebar"
      title="Drag to resize"
    />
  )}
</aside>
```

**CSS:**

The sidebar gets `position: relative` so the handle can be positioned absolutely on the right edge. The handle is a thin 6px-wide invisible strip that reveals a coral accent line on hover/drag:

```css
.sidebar {
  position: relative;
  transition: width 0.2s ease;
  /* ... flex, height, background, border, overflow */
}

/* Disable width transition during drag for 1:1 pointer tracking */
.sidebar.resizing {
  transition: none;
}

.sidebar-resize-handle {
  position: absolute;
  top: 0;
  right: 0;
  width: 6px;
  height: 100%;
  cursor: col-resize;
  z-index: 50;
  background: transparent;
  transition: background 0.15s ease;
}

.sidebar-resize-handle:hover,
.sidebar.resizing .sidebar-resize-handle {
  background: var(--primary);
  opacity: 0.5;
}
```

**Behavior:**
1. Hover over the sidebar's right edge → cursor changes to `col-resize`, thin coral line appears
2. Click + drag → sidebar width follows pointer in real-time (no easing lag)
3. Release → width persists to localStorage
4. Double-click the handle → snap back to 260px default
5. Reload page → last chosen width is restored
6. Touch support via `touchstart`/`touchmove`/`touchend`

**Why it feels smooth:**
- `transition: none` during drag (`isResizing` class) ensures instant width updates on every `mousemove`, tracking pointer 1:1 instead of easing behind
- `userSelect: none` on body prevents text selection mid-drag
- `col-resize` cursor applied globally so it stays consistent even when pointer briefly leaves the handle

---

## 6. Frontend File-by-File Reference

### 6.1 `frontend/src/main.jsx`

**Purpose:** React entry point. Renders `<App />` inside `<React.StrictMode>` into the `#root` div. Imports `main.css`.

---

### 6.2 `frontend/src/App.jsx`

**Purpose:** Root component. Manages auth state via `useAuth()` hook.

**Logic:**
- If `isAuthenticated` → renders `<ChatWindow officer={officer} onLogout={logout} />`
- If `!isAuthenticated` → renders `<PortalShell>` which wraps `<LandingPage>` (default home) or `<LoginPage>` (if user requests to enter portal).

No routing library — just conditional rendering based on auth and navigation states.

---

### 6.3 `frontend/src/api/auth.js`

**Purpose:** Token management and auth API calls. Token lives in a module-level variable (`_token`) — **never** in localStorage or sessionStorage.

**Module-level state:**
- `_token: string | null` — the JWT
- `_officer: object | null` — officer info from login response

**Functions:**

| Function | Description |
|----------|-------------|
| `getToken()` | Returns current token |
| `getOfficer()` | Returns current officer info |
| `setToken(token, officer)` | Sets both token and officer |
| `clearToken()` | Clears both to null |
| `isLoggedIn()` | Returns `_token !== null` |
| `login(badgeNumber, password)` | POSTs to `/api/auth/login`. On success: calls `setToken()`, returns `{success: true, officer}`. On 401: returns `{success: false, message}`. On network error: returns `{success: false, message}`. Never throws. |
| `logout()` | Calls `clearToken()` first, then best-effort POST to `/api/auth/logout`. Stateless — server doesn't track sessions. |

---

### 6.4 `frontend/src/api/chat.js`

**Purpose:** Two responsibilities: (1) the SSE stream consumer for sending a
question and receiving the streamed answer, and (2) a small REST client for the
chat-history sidebar (listing sessions, creating sessions, loading paginated
messages). Uses `fetch` with a `ReadableStream` for SSE instead of `EventSource`
because `EventSource` can't set custom headers (needed for JWT auth).

**Streaming functions:**

| Function | Description |
|----------|-------------|
| `startChatStream(question, sessionId, callbacks)` | Opens a `GET` request to `/api/chat/stream?question=...&session_id=...&token=...`. Token is passed both as `Authorization: Bearer` header AND as `?token=` query param (for proxy compatibility). Reads response body as stream, parses SSE frames (`data: {...}\n\n`), routes to callbacks by `event.type`. Handles 401/403 by firing `onAuthExpired`. Returns a cancel function (`() => controller.abort()`). |
| `handleFrame(frame, callbacks)` | Parses a single SSE frame. Concatenates `data:` lines per SSE spec. JSON-parses the payload. Routes to the appropriate callback by `event.type`: `status`, `token`, `table`, `media`, `sql`, `graph_available`, `error`, `done`. |

**Buffer-based SSE parsing:** Since `reader.read()` returns arbitrary chunks that may split mid-frame, the consumer maintains a `buffer` string across iterations. After each chunk, it scans for `\n\n` (the SSE frame delimiter), extracts complete frames from the buffer, and processes them. Any trailing partial frame is drained when the stream closes. This ensures correctness even when TCP segments don't align with SSE boundaries.

**Callback interface:**
```javascript
{
  onStatus: (msg) => void,        // pipeline progress updates
  onToken: (chunk) => void,       // word-by-word answer streaming
  onTable: (rows) => void,        // table data from query results
  onMedia: (refs) => void,        // evidence media attachments
  onSql: (sql) => void,           // generated SQL (for debugging)
  onGraphAvailable: () => void,   // graph data exists
  onError: (msg) => void,         // error message
  onAuthExpired: () => void,      // 401/403 → redirect to login
  onDone: () => void,             // stream complete
}
```

**Session / message REST client:**

| Export | Description |
|--------|-------------|
| `AuthError` (class) | Thrown when the backend rejects a request with HTTP 401, so callers can detect an expired session and trigger logout. |
| `fetchSessions()` | `GET /api/chat/sessions` — returns the officer's sessions (`{session_id, title, created_at, updated_at, message_count}[]`). Throws `AuthError` on 401, `Error` on other failures. |
| `createSession()` | `POST /api/chat/sessions` — creates a backend-owned session. **Currently unused by the UI** (new chats are provisional client-side until the first prompt — see 6.7); retained as a ready API. |
| `fetchMessages(sessionId)` | `GET /api/chat/sessions/{id}/messages` — returns `{messages}` (full list, oldest-first). The earlier `limit`/`before_message_id` pagination args were removed when the backend switched to returning the full message list (see [9.9](#99-message-pagination--removed)). Throws `AuthError` on 401, `Error` on 404 / other failures. |
| `exportSession(sessionId)` | `POST /api/chat/sessions/{id}/export` — fetches the export blob (PDF or HTML fallback) and triggers a browser download, taking the filename from `Content-Disposition`. Throws `AuthError` on 401. |

**Helpers (internal):**

| Function | Description |
|----------|-------------|
| `authHeaders(extra)` | Merges `Authorization: Bearer {token}` (from `getToken()`) with any extra headers. |
| `delay(ms)` | Promise wrapper around `setTimeout` for backoff waits. |
| `fetchWithRetry(doFetch, {retries=2, baseDelayMs=300})` | Exponential-backoff retry for **transient** failures only: a thrown fetch (network down) or a 5xx response. Non-transient responses (<500, including 401/404) return immediately so callers apply their own handling. Backoff is `baseDelayMs * 2^n`, bounded at ~900ms added latency across two retries. |

---

### 6.5 `frontend/src/hooks/useAuth.js`

**Purpose:** React hook that manages authentication state.

**State:**
- `isAuthenticated: boolean`
- `officer: object | null`
- `isLoading: boolean`
- `error: string | null`

**Returned functions:**
- `login(badgeNumber, password)` — calls `apiLogin()`, updates state. Returns `true` on success, `false` on failure. The return value is used by `LoginPage.jsx` to know whether to redirect.
- `logout()` — calls `apiLogout()`, resets all state.

---

### 6.6 `frontend/src/components/LoginPage.jsx`

**Purpose:** Login form. Centered card on warm cream background.

**Props:** `{ onLogin, isLoading, error }`

**State:** `badgeNumber`, `password`

**UI elements:**
- Brand mark (✱) + "Karnataka State Police"
- Title: "Crime Intelligence Platform" (serif font)
- Badge number input (placeholder: `KSP-2019-0042`)
- Password input (type=password)
- Sign in button (shows "Authenticating…" when loading)
- Error message below button

**Validation:** Both fields required (non-empty after trim for badge, non-empty for password). Button is also disabled while `isLoading` is true to prevent double-submission. No other validation. Password format: `badge_number + "123"`.

---

### 6.7 `frontend/src/components/ChatWindow.jsx`

**Purpose:** The main application shell once authenticated. Renders the **two-panel
layout** (collapsible sidebar + main content) and owns all chat state, session
management, and streaming logic. This is the largest frontend file.

**Props:** `{ officer, onLogout }`

**Layout (JSX structure):**

```
.app-shell
├── aside.sidebar (expanded | collapsed)
│   ├── .sidebar-top        → collapse toggle icon button
│   ├── .new-chat-row       → "New chat" (icon + label; icon-only when collapsed)
│   ├── .session-list-container
│   │   ├── .recents-label  → "Recents" (expanded only)
│   │   └── <SessionList />
│   └── .sidebar-bottom     → <OfficerRow />
└── main.main-content
    ├── (collapsed-only) active session title, top-left
    ├── session-creation error toast (if any)
    └── isEmpty?
        ├── YES → .welcome-screen { <WelcomeScreen /> + <Composer /> }  ← centered group
        └── NO  → .chat-area { .messages-scroll[.messages-inner] + <Composer /> }
```

**State:**

| State | Purpose |
|-------|---------|
| `activeSessionId` | Current session id. Initialized client-side via `newSessionId()`. |
| `messages` | Array of `{id, role, content, tableData, mediaAttachments, isStreaming, error}`. |
| `inputValue` | Composer text (lifted up so drafts can be preserved per session). |
| `isStreaming` | True while a stream is active; disables sending. |
| `statusText` | Pipeline progress text shown above the composer. |
| `sessions` | Officer's session list (the "Recents" list), loaded on mount. |
| `isLoadingSessions` / `sessionsError` | Sidebar load state + error (with Retry). |
| `isLoadingMessages` / `messagesError` | Message-load state + error (with Retry). |
| `sessionError` | Transient toast for a failed session operation. |
| `sidebarCollapsed` | Sidebar collapse state, persisted to `localStorage` (`chs.sidebarCollapsed`). Surfaced to JSX as `sidebarOpen = !sidebarCollapsed`. |

**Refs:** `cancelRef` (active stream canceller), `scrollRef` (message scroll container), `textareaRef` (legacy focus target), `topSentinelRef` (IntersectionObserver target for load-older), `paginationRef` (per-session `{hasMore, oldestMessageId}` map), `activeSessionIdRef` (stale-closure-safe mirror of `activeSessionId`), `draftInputsRef` (per-session unsent composer drafts).

**Key behaviors:**

- **New chat (provisional, no backend call):** `handleNewChat()` is UI-only. If the
  current chat is already empty and idle, it's a **no-op** — pressing "New chat"
  repeatedly keeps the officer on the same blank chat instead of spawning
  duplicates. Otherwise it cancels any stream, generates a fresh client-side
  `session_id`, and resets to the blank welcome screen. The session is **not**
  registered in the sidebar until the first prompt runs.
- **First-prompt naming:** when a turn completes, `bumpSessionMetadata()` injects
  the provisional session into the "Recents" list with a title derived from the
  first user message (`deriveTitle()`), bumps `message_count`, refreshes
  `updated_at`, and re-sorts newest-first.
- **Send:** `handleSend(override?)` appends a user + empty assistant message,
  opens the stream via `startChatStream()`, and routes callbacks through
  `updateLastAssistant()` to incrementally update the active assistant message.
- **Suggestion chips:** rendered by `WelcomeScreen`; clicking one calls
  `handleSend(question)` directly, bypassing the input field.
- **Session switching:** `handleSelectSession()` cancels any stream, stashes the
  current draft under the old session and restores the new one, clears messages,
  switches `activeSessionId`, and loads the session's messages.
- **Message loading:** `loadSessionMessages()` fetches the full message list for a
  session (oldest-first) and maps each row into the component shape, carrying
  through `table_data`/`media_attachments` so a past session's tables/media render
  on load. There is no pagination — the backend returns the whole list (see
  [9.9](#99-message-pagination--removed)).
- **Sidebar reconciliation:** after a turn completes, `onDone` optimistically bumps
  the session via `bumpSessionMetadata()` and then re-fetches `fetchSessions()` so
  the sidebar reflects the just-persisted session (real title, id, counts).
- **Export:** each `SessionItem` shows a hover download button calling
  `exportSession()` (PDF/HTML download).
- **Collapsed-state title:** when the sidebar is collapsed, the active session
  title is shown small at the top-left of the main area (Claude.ai behavior).
- **Auto-scroll:** scrolls to the bottom on new content.
- **Cleanup:** cancels the active stream on unmount via `cancelRef`.

**Internal helpers:**
- `newSessionId()` — UUID via `crypto.randomUUID()` (with fallback for older browsers).
- `newMessageId()` — random id for React keys.
- `readSidebarCollapsed()` — lazy initializer reading the persisted collapse flag from `localStorage`.
- `updateLastAssistant(updater)` — finds the last assistant message and applies an updater; the mechanism behind all streaming callbacks.
- `deriveTitle(firstUserMessage)` — client-side title heuristic (≤60 chars) mirroring the backend.
- `bumpSessionMetadata(sessionId, firstUserMessage)` — optimistic sidebar update on turn completion (injects provisional sessions, bumps count, re-sorts).
- `loadSessions` / `loadSessionMessages` / `retryLoadMessages` — data loaders described above.

---

### 6.8 `frontend/src/components/WelcomeScreen.jsx`

**Purpose:** The empty-chat greeting. Returns a fragment with a large serif
heading "Good day, {firstName}." (derived from `officer.full_name`), a subheading
"What would you like to look up today?", and a row of 4 suggestion chips.

**Props:** `{ officer, onSuggestion, isStreaming }`

**Notes:** Returns only the text + chips (not a wrapper). `ChatWindow` places it
inside a centered `.welcome-screen` flex container together with the `Composer`,
so the greeting, chips, and input box form one group centered both vertically and
horizontally. Clicking a chip calls `onSuggestion(text)`; chips are disabled
while `isStreaming`. The 4 suggestions are: "How many theft cases are open?",
"Show me all cases involving Mahesh Gowda", "List all vehicle theft cases with
registration numbers", "Who are the top 5 repeat offenders?".

---

### 6.9 `frontend/src/components/Composer.jsx`

**Purpose:** The message input box. Used in both the welcome state (directly below
the suggestions) and during an active chat (pinned at the bottom).

**Props:** `{ value, onChange, onSend, disabled, statusText }`

**Behavior:**
- Auto-growing textarea: a `useEffect` resizes it on every `value` change, capped at 160px (then scrolls).
- Enter sends, Shift+Enter inserts a newline. Send is suppressed while `disabled` or when the trimmed value is empty.
- `statusText` (pipeline progress) renders in small text above the box while streaming.
- Left actions: **Attach** (paperclip) and **Voice** (mic) buttons are placeholders — visually present but disabled with `.not-yet` styling and "coming soon" tooltips.
- Send button: coral circle with an up-arrow icon; disabled while streaming or when input is empty.

---

### 6.10 `frontend/src/components/MessageBubble.jsx`

**Purpose:** Renders a single chat message.

**Props:** `{ role, content, tableData, mediaAttachments, isStreaming, error }`

**User messages:** Right-aligned bubble with `surface-card` background.

**Assistant messages:**
- "Assistant" label above
- Content as plain text (no markdown rendering)
- Blinking cursor (▍) when `isStreaming` is true
- `<TableRenderer>` if `tableData` is non-empty
- Media attachment list if `mediaAttachments` is non-empty: each item shows a colored pill (image/video/audio), description, and FIR number

---

### 6.11 `frontend/src/components/TableRenderer.jsx`

**Purpose:** Renders query results as a clean HTML table.

**Props:** `{ data: array of objects }`

**Behavior:**
- Extracts column names from `Object.keys(data[0])`
- Renders `<table>` with sticky header row
- Shows max 50 rows (`MAX_ROWS`)
- Cell formatting: null→"—", boolean→"Yes"/"No", objects→JSON (truncated at 100 chars), strings→truncated at 100 chars with "…" and full text in `title` attribute
- Footer shows record count or "Showing first 50 of N records"
- Alternating row backgrounds, hover highlight

---

### 6.12 `frontend/src/components/SessionList.jsx`

**Purpose:** Renders the scrollable list of chat sessions inside the sidebar.

**Props:** `{ sessions, activeSessionId, onSelect, onSelectSession, isLoading, error, onRetry }`

**Behavior:**
- Accepts either `onSelect` (current sidebar) or `onSelectSession` (legacy) as the row-click handler — `handleSelect = onSelect || onSelectSession` for backward compatibility.
- State precedence: **error** (shows the message + a Retry button calling `onRetry`) → **loading** ("Loading conversations…") → **empty** ("No conversations yet. Start a new chat!") → the list.
- Sessions render in the order given (backend orders newest-first by `updated_at`); the component does not re-sort.
- Wrapped in `React.memo`; rows are memoized `SessionItem`s so unrelated `ChatWindow` re-renders (streaming tokens, composer input) don't re-render the whole list.

---

### 6.13 `frontend/src/components/SessionItem.jsx`

**Purpose:** A single session row button in the sidebar list.

**Props:** `{ session, isActive, onClick }`

**Behavior:**
- Shows the session `title` (single line, ellipsis overflow), a relative timestamp, and a message count.
- Renders an **export button** (download icon) that appears on row hover; clicking it calls `exportSession(session_id)` (stopping propagation so it doesn't also select the row) and downloads the conversation as PDF/HTML. The row itself is a `div role="button"` (not a `<button>`) so the export `<button>` can nest legally inside it.
- `formatRelativeTimestamp(iso)` renders: today → time ("12:30 PM"); yesterday → "Yesterday"; this week → weekday name; older → short date ("Jan 15"). Returns empty for missing/unparseable timestamps.
- Active row gets `.session-item--active` (highlight background + coral left border) and `aria-current="true"`.
- Memoized with `React.memo` for list performance.

---

### 6.14 `frontend/src/components/OfficerRow.jsx`

**Purpose:** The officer identity block pinned at the bottom of the sidebar, with a sign-out popup.

**Props:** `{ officer, onSignOut }`

**Behavior:**
- Renders a circular avatar with up to two initials derived from `officer.full_name` (fallback "KP"), plus name and rank (hidden when the sidebar is collapsed).
- Clicking the row toggles a popup that appears **above** it (`bottom: calc(100% + 8px)`), showing the officer's full name, badge number, and a danger-styled "Sign out" button.
- Sign out calls `onSignOut` and closes the popup. A `mousedown` listener closes the popup on any outside click (registered only while open).

---

### 6.15 `frontend/src/components/Icons.jsx`

**Purpose:** A set of inline SVG icon components so the app needs no icon library (keeps the bundle small).

**Exports:** `IconSidebarOpen`, `IconSidebarClose`, `IconNewChat`, `IconLogOut`, `IconPaperclip`, `IconMic`, `IconArrowUp`, `IconDownload` (export button).

**Convention:** Each takes a `size` prop (default 20) and uses `stroke="currentColor"` so color is controlled by CSS `color` on the parent.

---

### 6.16 `frontend/src/styles/main.css`

**Purpose:** All UI styles. Follows Design.md: warm cream canvas, coral primary CTA, serif display headlines (EB Garamond), humanist sans body (Inter), JetBrains Mono for code.

**Design tokens (CSS custom properties):**
- Brand: `--primary: #cc785c` (coral), `--primary-active: #a9583e`
- Surfaces: `--canvas: #faf9f5` (cream), `--surface-card: #efe9de`, `--surface-dark: #181715`
- Typography: `--font-display` (EB Garamond serif), `--font-body` (Inter sans), `--font-mono` (JetBrains Mono)
- Radius: `--r-md: 8px`, `--r-lg: 12px`, `--r-xl: 16px`, `--r-pill: 9999px`
- **Layout aliases** (added for the two-panel shell, mapped onto the brand palette so the theme stays consistent): `--border` → `--hairline`, `--surface-hover` → `rgba(20,20,19,0.05)`, `--text-primary` → `--ink`, `--text-secondary` → `--muted`, `--text-tertiary` → `--muted-soft`.

**Component styles:** the app shell (`.app-shell`, `.sidebar` expanded/collapsed, `.sidebar-top`, `.new-chat-row`, `.recents-label`, `.session-list-container`, `.sidebar-bottom`), officer row + popup, `.main-content`, welcome screen (`.welcome-screen`, `.welcome-heading`, `.welcome-subheading`, `.suggestion-chips`), chat area (`.chat-area`, `.messages-scroll`, `.messages-inner`), composer (`.composer-area`, `.composer-box`, `.composer-textarea`, `.composer-action-btn`, `.send-btn`), buttons, login page, messages (user/assistant), table renderer, media list, session list states (loading/empty/error), the per-session `.session-export-btn` (hover-revealed), and the error toast.

**Font loading:** Google Fonts import for EB Garamond (400, 500), Inter (400, 500, 600), JetBrains Mono (400).

> **Note:** There is no top bar / header anymore — navigation lives entirely in
> the sidebar. The old `.topbar`, `.app-layout`, `.chat-sidebar*`, and
> footer-based `.composer__*` styles were removed (see Section 9).

---

### 6.17 `frontend/src/context/LangContext.jsx`

**Purpose:** React Context Provider that stores the active language (`en` / `kn`) and provides translation and state synchronization helper utilities across the entire component tree.

**Context Values:**
- `lang`: Current language ('en' or 'kn').
- `setLang(newLang)`: Updates language, updates `localStorage` key `ksp_portal_lang`, and updates the `lang` attribute on `html` and `body` elements.
- `t(en, kn)`: Translation helper returning `kn` if language is Kannada, otherwise `en`.

---

### 6.18 `frontend/src/hooks/useLang.js`

**Purpose:** Custom hook that consumes `LangContext` and provides access to `lang`, `setLang`, and the translation helper `t()`. Re-exported to preserve compatibility with existing imports.

---

### 6.19 `frontend/src/components/PortalShell.jsx`

**Purpose:** Layout shell wrapping the unauthenticated views (Landing page and Login page). Contains the official header banner, translation select dropdown, accessibility scaling buttons (`A+`, `A`, `A-`), and the footer banner.

**Key Features:**
- `setFontSize(size)`: Dynamically sets `--font-size-base` CSS variable on the root `html` tag to either `18px` (`large`), `16px` (`normal`), or `14px` (`small`).

---

### 6.20 `frontend/src/components/LandingPage.jsx`

**Purpose:** Home view of the KSP portal for unauthenticated users. Showcases department statistics/features, secure access descriptions, and prompts the officer to enter the secure portal.

---

## 7. Data Flow Diagrams

### 7.1 Request Lifecycle

```
Browser → Vite Proxy (/api/*) → FastAPI (port 8000)
  → Auth middleware (JWT verification)
    → Router (chat.py or auth.py)
      → Pipeline (query_pipeline.py)
        → Schema Linker (keyword matching)
        → SQL Generator (LLM call #1: Qwen 7B Coder)
        → SQL Validator (forbidden keywords, table allow-list)
        → DB Execution (aiomysql pool → MySQL)
        → Media Resolver (optional DB query)
        → Graph Probe (optional DB query)
        → Answer Formatter (LLM call #2: Qwen 14B Instruct)
      → History Save (NoSQL or in-memory)
    → SSE Events → Browser
```

### 7.2 LLM Call Format

```
POST https://api.catalyst.zoho.in/quickml/v2/project/{PROJECT_ID}/llm/chat
Headers:
  Authorization: Bearer {CATALYST_API_TOKEN}
  Content-Type: application/json
  CATALYST-ORG: {CATALYST_ORG_ID}
Body:
  {
    "model": "crm-di-qwen_coder_7b-it",
    "prompt": "DATABASE SCHEMA: ...\n\nQuestion: ...\n\nWrite the MySQL SELECT query:",
    "system_prompt": "You are an expert MySQL query writer...",
    "max_tokens": 4000,
    "temperature": 0.1,
    "top_p": 0.95,
    "top_k": 40
  }
Response:
  {
    "response": "SELECT COUNT(*) AS open_cases FROM fir_master WHERE status = 'open'"
  }
```

### 7.3 Security Layers

```
Layer 1: SQL Validator (sql_validator.py)
  → Starts with SELECT? ✓
  → No forbidden keywords? ✓
  → All tables in allow-list? ✓
  → No multi-statement (;)? ✓

Layer 2: Connection Enforcer (connection.py)
  → sql.strip().upper().startswith("SELECT")?
  → If not: raises ValueError, query never runs

Layer 3: Auth Gate (simple_auth.py)
  → All routes except /api/auth/login require valid JWT
  → Token verified on every request
```

---

## 8. Error Handling Patterns

### 8.1 Pipeline-Level

`run_pipeline()` **never raises**. Every failure path fills `error` and a user-friendly `answer_text` on the `PipelineResponse`. This ensures the frontend always gets a response, even if something goes wrong.

### 8.2 History/Cache Level

All history and cache functions **never raise**. Failures are logged to stderr and the in-memory fallback is used. This ensures the chat keeps working even when Catalyst NoSQL or Cache is misconfigured.

### 8.3 LLM Level

`call_llm()` raises `LLMError` on any failure. Callers in the pipeline catch this and convert to user-friendly messages. `sql_generator.py` differentiates between `LLMError` (infra failure, not retry-worthy) and validation failure (retry-worthy).

### 8.4 Frontend Level

- `api/auth.js`: `login()` never throws — returns `{success, message}` objects
- `api/chat.js`: `startChatStream()` handles network errors, 401/403, and stream errors via callbacks. The session/message client (`fetchSessions`, `createSession`, `fetchMessages`) retries transient failures (network + 5xx) via `fetchWithRetry`, throws `AuthError` on 401 (callers trigger logout), and throws a friendly `Error` on other failures.
- `ChatWindow.jsx`: All callback errors update the message content and re-enable the input. Sidebar session-load failures surface as a Retry affordance in `SessionList`; message-load failures surface a Retry banner in the chat area; a failed session operation shows a dismissable toast.

### 8.5 Logging

All logging goes to `sys.stderr` via `print(..., file=sys.stderr)`. No sensitive data is logged (no officer names, FIR numbers, or query content — only timestamps, route names, latency, and status codes).

**Consistent `_log` pattern:** Most backend files define a module-level `_log(msg)` helper that writes to stderr with `flush=True`. This is used throughout the codebase for non-fatal warnings (history fallbacks, pipeline timing) and keeps logging code DRY. Files that use this pattern: `sql_generator.py`, `query_pipeline.py`, `routers/chat.py`, `routers/auth.py`, `conversation/history.py`, `conversation/session_store.py`.

---

## 9. Removed / Deprecated Stuff

This section tracks code that **used to exist** in the documented architecture or
that has been **superseded** during the frontend redesign. Anything moved here is
either deleted from disk or still present but no longer wired into the app. Each
entry records what it was, its current status, and why it changed — so the rest of
this document only describes the live system.

### 9.1 `frontend/src/components/ChatHistorySidebar.jsx` — DELETED

- **What it was:** The original top-level sidebar container. It composed
  `NewChatButton`, `SessionList`, and `OfficerInfo`, owned the collapse/expand
  toggle, and included responsive overlay behavior for narrow viewports (a
  `position: fixed` panel with a backdrop scrim on screens < 768px).
- **Status:** Deleted from disk.
- **Why removed:** The two-panel redesign (Claude.ai-style) moved the sidebar
  layout directly into `ChatWindow.jsx` as inline JSX. The sidebar's
  responsibilities were split: layout + collapse toggle now live in `ChatWindow`,
  the officer block moved to the new `OfficerRow.jsx`, and the session list stayed
  in `SessionList.jsx`. Keeping a separate container component added indirection
  with no benefit, so it was removed.

### 9.2 `frontend/src/components/NewChatButton.jsx` — DELETED

- **What it was:** A reusable "+ New chat" ghost button used by the old
  `ChatHistorySidebar`.
- **Status:** **Deleted from disk** (post-Step-4 cleanup pass).
- **Why removed:** The redesigned sidebar renders the new-chat control inline
  as a `.new-chat-row` directly in `ChatWindow.jsx`, so the standalone button was
  never imported anywhere. Removed during the dead-code audit.

### 9.3 `frontend/src/components/OfficerInfo.jsx` — DELETED

- **What it was:** The officer identity footer (avatar + name + rank) used by the
  old `ChatHistorySidebar`. Display-only.
- **Status:** **Deleted from disk** (post-Step-4 cleanup pass).
- **Why removed:** Replaced by `OfficerRow.jsx` (which adds the click-to-open
  sign-out popup). Was no longer imported anywhere; removed during the dead-code
  audit.

### 9.4 Top bar / header layout — REMOVED

- **What it was:** A `.topbar` header across the top of the chat shell showing the
  brand mark, "KSP Crime Intelligence" title, a session-id subtitle, and **two
  buttons: "New chat" and "Sign out"**. The overall layout was `.app-layout`
  (sidebar + `.chat-shell` with the topbar, a `.chat-scroll` area, and a footer
  composer).
- **Status:** Removed from `ChatWindow.jsx` and its CSS deleted from `main.css`
  (`.topbar*`, `.app-layout`, `.chat-shell` header usage).
- **Why removed:** The redesign spec ([UIFixes.md](UIFixes.md)) calls for a pure
  two-panel shell with no header — all navigation lives in the sidebar. "New chat"
  moved to the sidebar top; "Sign out" moved into the `OfficerRow` popup at the
  sidebar bottom. This removed the duplicate new-chat/sign-out affordances and
  reclaimed vertical space for the conversation.

### 9.5 Backend-created sessions on "New chat" — DEPRECATED (flow change)

- **What it was:** `handleNewChat()` in `ChatWindow.jsx` used to `await
  createSession()` (`POST /api/chat/sessions`) on every click, prepend the
  backend-owned session to the sidebar, and make it active.
- **Status:** That call path is **no longer used by the UI**. The
  `createSession()` API client in `api/chat.js` is retained but currently unused
  (see 6.4).
- **Why changed:** Two UX problems. (1) Officers could **spam** the New chat button
  and create many empty backend sessions. (2) An empty chat appeared in the sidebar
  before any prompt was sent. The new flow makes a new chat **provisional and
  client-side**: pressing New chat on an already-empty chat is a no-op, and a
  session is only registered (in "Recents", with a title derived from the first
  message) once a prompt actually runs. Server-side persistence of these
  provisional sessions is intentionally deferred — it will be revisited when the
  storage layer is finalized.

### 9.6 Old welcome / empty-state markup (`.chat-empty`) — SUPERSEDED

- **What it was:** A left-aligned empty state (`.chat-empty` with an `<h2>`,
  helper text, and a `.suggestions` chip row) rendered inside the scroll area,
  with the composer fixed separately at the bottom.
- **Status:** Superseded by `WelcomeScreen.jsx` + the centered `.welcome-screen`
  group. The old `.chat-empty` / `.suggestions` CSS rules remain in `main.css` but
  are no longer referenced by any component.
- **Why changed:** The redesign centers the greeting, suggestion chips, and the
  composer together both vertically and horizontally so a new chat doesn't feel
  empty. The greeting also became a personalized, larger serif heading ("Good day,
  {firstName}.").

### 9.7 Footer-based composer (`.composer__*`) — SUPERSEDED

- **What it was:** The original composer was a `<footer className="composer">` with
  `.composer__row`, `.composer__input`, `.composer__status`, and `.composer__hint`,
  plus a text "Send" button and an Enter/Shift+Enter hint line.
- **Status:** Replaced by the `Composer.jsx` component (`.composer-area` /
  `.composer-box` / `.composer-textarea` / `.send-btn`). The old `.composer__*` CSS
  was deleted from `main.css`.
- **Why changed:** Extracting the composer into its own component lets it be reused
  in both the welcome state and the active chat, and the redesign added an
  icon-based send button plus placeholder attach/voice buttons in a single
  rounded input box.

> **Net frontend additions from the redesign** (for cross-reference): `WelcomeScreen.jsx`,
> `Composer.jsx`, `OfficerRow.jsx`, `Icons.jsx` were added; `SessionList.jsx` and
> `SessionItem.jsx` were retained. See [Section 6](#6-frontend-file-by-file-reference).

### 9.8 NoSQL `session_metadata` — SUPERSEDED BY MySQL

- **What it was:** `conversation/session_store.py` stored per-session metadata
  (title, timestamps, message_count) in a Catalyst NoSQL `session_metadata`
  collection, and the sidebar's `GET /api/chat/sessions` read from it.
- **Status:** As of Step 4, **MySQL `chat_sessions` is the source of truth.**
  `GET /api/chat/sessions` now reads from `chat_store.get_sessions_for_officer`.
  `session_store.py` is still written to (via `history.py`'s metadata sync) and
  `POST /api/chat/sessions` still creates a NoSQL doc, but neither is the primary
  read path anymore.
- **Why kept (not deleted):** removing it touches the history metadata sync and the
  unused `POST /api/chat/sessions` endpoint; it was deliberately left in place as a
  fallback pending a decision on whether to fully retire the NoSQL session path.

### 9.9 Message pagination — REMOVED

- **What it was:** `GET /api/chat/sessions/{id}/messages` accepted `limit` +
  `before_message_id` cursor params and returned `{messages, has_more}` (newest
  first). The frontend had a full bottom-to-top pagination apparatus in
  `ChatWindow.jsx`: `loadOlderMessages`, an `IntersectionObserver` top sentinel,
  `paginationRef`/`getPagination`/`setPagination`, `activeHasMore`/`isLoadingOlder`
  state, a "Load older messages" button, and a "No older messages" indicator, plus
  `PAGE_SIZE = 50`.
- **Status:** **Removed end-to-end.** The backend endpoint now returns the full
  message list (oldest-first, capped at 100 in `chat_store.get_messages_for_session`)
  with no `has_more`; the `Message` model dropped `timestamp`/`sql` in favor of the
  rich fields (`table_data`, `media_attachments`, etc.); the frontend pagination
  state/handlers/JSX and the `.load-older-btn` / `.no-older-indicator` /
  `.chat-messages__top-sentinel` CSS were deleted; `fetchMessages` lost its
  `limit`/`beforeMessageId` args.
- **Why removed:** After the Step 4 MySQL migration the endpoint always returned the
  whole list with `has_more=false`, so the entire pagination path was dead code that
  could never trigger. Removing it deleted ~100+ lines of unreachable frontend logic.

### 9.10 Dead code / unused artifacts — REMOVED (audit pass)

A post-feature audit (`POST_FEATURE_AUDIT.md`) removed zero-risk dead weight:
- **`routers/chat.py`:** unused `_error()` helper; unused imports `list_sessions`,
  `get_session` (kept `create_session`).
- **`llm/sql_generator.py`:** unused `LLMError` import.
- **`llm/answer_formatter.py`:** unused `LLMError` import.
- **`db/seed.py`:** unused `datetime` and `get_pool` imports; unused `media_types` local.
- **`db/connection.py`:** three no-op `global _pool` declarations (in `get_pool`,
  `execute_query`, `execute_write`) that only read the variable.
- Confirmed clean via `pyflakes`; full test suite green after each removal.
