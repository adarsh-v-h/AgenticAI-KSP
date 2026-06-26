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
│   ├── nosql_client.py        # Centralized Catalyst NoSQL client wrapper
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
    ├── export.py              # POST /api/chat/sessions/{id}/export (HTML conversation export)
    ├── reports.py             # POST /api/reports/analyze (Report analysis & upload)
    ├── voice.py               # POST /api/voice/transcribe, /api/voice/speak (Zia STT/TTS)
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
5. Register `auth_router`, `chat_router`, `export_router`, and `reports_router`

**App metadata:**
- `title`: `"KSP Crime Intelligence API"`
- `version`: `"0.4.0-step4"`
- `docs_url`: `"/docs"` (Swagger UI available during dev)
- `redoc_url`: `None` (ReDoc disabled)

**Registered routers:** `auth_router`, `chat_router`, `export_router`, `reports_router`, and `voice_router`.

**CORS config:** Only allows the single origin from `ALLOWED_ORIGINS` env var. Methods: GET, POST. Headers: Authorization, Content-Type.

---

### 3.1a Security — Authorization & BOLA/IDOR Mitigation

**Overview:** All protected routes enforce **authentication** via JWT (the `get_current_officer` or `get_current_officer_sse` dependency). Beyond that, routes that reference a `session_id` must also enforce **object-level authorization** to prevent BOLA (Broken Object Level Authorization) / IDOR (Insecure Direct Object Reference) attacks — OWASP's #1 API security risk (API1:2023).

**The vulnerability:** An authenticated officer could supply another officer's `session_id` (by guessing, brute-forcing, or observing) and read or modify their session if the backend doesn't check ownership.

**The fix — two patterns:**

1. **Read authorization** (GET endpoints that load a session's data):
   - Call `chat_store.verify_session_owner(session_id, officer_id) -> bool` before any query.
   - Returns `False` if the session doesn't exist or belongs to another officer.
   - On `False`, raise `HTTPException(status_code=404)` — never 403, to avoid leaking that another officer's session exists.
   - **Used by:** `GET /api/chat/sessions/{id}/messages`, `POST /api/chat/sessions/{id}/export`

2. **Write authorization** (POST/GET endpoints that persist turns into a session):
   - Check ownership **before any expensive work** (pipeline, LLM call, file decode) so a forged `session_id` is rejected cheaply.
   - **Create-or-append semantics:** the first turn of a brand-new session legitimately targets a `session_id` that doesn't yet exist (the officer will own it on creation). Only reject when the session *exists and is owned by someone else*.
   - The check is a single indexed PK lookup: `SELECT officer_id FROM chat_sessions WHERE session_id = %s`. If rows exist and `officer_id` doesn't match → `HTTPException(status_code=404)`. If no rows → allowed (will be created). If rows match → allowed (owner).
   - Reuse the existence result so `_persist_turn` / `_persist_report_turn` don't run a duplicate query — same query count as before, now also doing auth.
   - **Used by:** `POST /api/chat`, `GET /api/chat/stream`, `POST /api/reports/analyze`

**Performance:** The authorization check is a single primary-key lookup (session_id is the PK) — effectively free — and reusing the existence result means **zero added round-trips** relative to the previous code.

**Error response:** Always return **404** (not 403) when a session exists but belongs to another officer, so we never reveal that the foreign session exists. This is the industry-standard pattern for BOLA/IDOR mitigation.

**Tests:** `backend/tests/test_session_authz.py` covers all three write endpoints: intruder rejection (404, asserting the pipeline/LLM never runs), owner acceptance, and brand-new-session acceptance.

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
| `Employee` | Station employees / officers (replaces `officers`) | `EmployeeID` (PK), `KGID` (UNIQUE badge number), `FirstName`, `RankID` (FK→`Rank`), `role` (ENUM), `is_active` |
| `CaseMaster` | Central case/FIR registry (replaces `fir_master`) | `CaseMasterID` (PK), `CrimeNo` (UNIQUE), `CrimeRegisteredDate`, `PolicePersonID` (FK→Employee), `PoliceStationID` (FK→Unit), `CaseStatusID` (FK→CaseStatusMaster), `CrimeMinorHeadID` (FK→CrimeSubHead), `BriefFacts` (TEXT) |
| `ComplainantDetails` | Complainants who filed cases | `ComplainantID` (PK), `CaseMasterID` (FK→CaseMaster), `ComplainantName`, `GenderID` |
| `Victim` | Victims linked to cases (replaces `victims`) | `VictimMasterID` (PK), `CaseMasterID` (FK→CaseMaster), `VictimName`, `AgeYear`, `GenderID`, `VictimPolice` (BIT) |
| `Accused` | Accused persons linked to cases (replaces `accused`) | `AccusedMasterID` (PK), `CaseMasterID` (FK→CaseMaster), `AccusedName`, `AgeYear`, `GenderID`, `PersonID` |
| `ActSectionAssociation` | Links cases to acts and sections charged | `CaseMasterID` (FK→CaseMaster), `ActID` (FK→Act), `SectionID` (FK→Section) |
| `ArrestSurrender` | Arrest or surrender details of accused | `ArrestSurrenderID` (PK), `CaseMasterID` (FK→CaseMaster), `AccusedMasterID` (FK→Accused), `ArrestSurrenderDate`, `IOID` (FK→Employee) |
| `evidence_media` | Media files attached to cases | `media_id` (PK), `case_master_id` (FK→CaseMaster), `media_type` (ENUM), `stratus_folder_id`, `stratus_file_id`, `description` |
| `chat_sessions` | One row per conversation | `session_id` (PK, VARCHAR 36), `officer_id` (FK→Employee), `title`, `created_at`, `updated_at`, `message_count`, `is_active` |
| `chat_messages` | One row per turn — user OR assistant | `message_id` (PK, AUTO_INCREMENT), `session_id` (FK→chat_sessions), `role` (ENUM `user`/`assistant`), `content`, `sql_generated`, `has_table`, `has_media`, `graph_available`, `table_data_json` (MEDIUMTEXT, nullable), `created_at` |

**Rich data storage migration:** The `table_data_json` column (MEDIUMTEXT) was added to `chat_messages` to co-locate tabular query results with the message they belong to. Previously, this data lived in a separate NoSQL document (`message_rich_data`). The new approach eliminates a round-trip, simplifies recovery logic, and keeps all message data in one indexed query. The `_serialize()` helper in `chat_store.py` handles `date`/`datetime`/`timedelta` objects during JSON serialization.

**Design rationale:** A unified `CaseMaster` table holds all cases, and details like `ComplainantDetails`, `Victim`, `Accused`, `ActSectionAssociation`, and `ArrestSurrender` are separated into distinct tables. This maps directly to the official Karnataka State Police database layout and permits structured, set-based queries (such as checking who is still at large by checking if an accused has no matching `ArrestSurrender` entry).

---

### 3.5 `backend/db/seed.py`

**Purpose:** Generates realistic synthetic crime data for a single Bengaluru police station. Run standalone (`python backend/db/seed.py`) or imported. Uses `random.seed(42)` for deterministic, reproducible output.

**Key data:**
- Lookups populated: 30 Units (stations), 3 Districts, 9 Ranks, 5 Designations, 10 Crime Heads, 20 Crime Sub-Heads (crime types), 4 Case Categories, 2 Gravity lookup values, 4 Case Status lookup values, 10 Acts, 30 Sections, 10 Castes, 4 Religions, 10 Occupations.
- 10 employees / officers with Karnataka names, realistic ranks, and roles.
- 220 CaseMaster records (2022-2025), distributed across crime types: Theft 50, Assault 35, Vehicle Theft 30, Fraud 25, Cybercrime 20, Missing Person 15, Drug Offense 15, Robbery 10, Murder 5, Domestic Violence 10, Other 5.
- 5 named repeat offenders: Mahesh Gowda (8 cases — the "demo star"), Ravi Kumar (5), Suresh Nayak (4), Pavan Reddy (3), Anand Shetty (3).
- 220 ComplainantDetails, 220 Victim, 350 Accused records.
- 60% of accused are marked as arrested (with records in ArrestSurrender); 40% are still at large (no ArrestSurrender records).
- 25 evidence_media records (15 images, 6 videos, 4 audio) attached to CaseMaster records.

**Functions:**

| Function | Description |
|----------|-------------|
| `seed_lookups(conn)` | Inserts all foundational lookup values (State, District, Unit, Court, Rank, Designation, CrimeHead, CrimeSubHead, CaseCategory, GravityOffence, CaseStatusMaster, Act, Section, CasteMaster, ReligionMaster, OccupationMaster). |
| `seed_employees(conn, lookups)` | Inserts 10 employees/officers. Returns list of `EmployeeID`s. |
| `seed_cases(conn, lookups, employee_ids)` | Inserts 220 cases. Returns a list of created `CaseMaster` records. |
| `seed_complainants(conn, lookups, cases)` | Inserts one complainant per case. |
| `seed_victims(conn, lookups, cases)` | Inserts one victim per case with gender-appropriate names. |
| `seed_accused(conn, lookups, cases)` | Inserts accused persons, ensuring the 5 repeat offenders are distributed across their assigned cases, and remaining cases get random accused. |
| `seed_act_sections(conn, cases)` | Associates acts and sections to cases in ActSectionAssociation. |
| `seed_arrest_surrender(conn, cases, accused_records)` | Inserts ArrestSurrender records for 60% of the seeded accused. |
| `main()` | Entry point. Creates pool, checks if already seeded (skips if `CaseMaster` has rows), runs all seed functions in sequence. |

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
- `always_include` — (optional) if `True`, table is always in the schema (only `CaseMaster`)

`_FEW_SHOT_BANK` — list of 15 dicts, each with:
- `tables` — set of table names this example is relevant to
- `q` — example natural-language question
- `sql` — the expected SQL query

`ALLOWED_TABLES` — exported list of all valid table names (used by the SQL validator).

**Functions:**

| Function | Description |
|----------|-------------|
| `_format_table(name, meta, max_col_chars)` | Builds a text block for one table: name, description, columns with types. Optionally truncates column descriptions to `max_col_chars`. |
| `get_schema_for_tables(table_names) -> str` | Builds a compact schema string for LLM prompt injection. Always includes `CaseMaster` first. If total output exceeds `_MAX_SCHEMA_CHARS`, progressively truncates column descriptions (80→60→40→30 chars) until it fits. Last resort: hard-truncates at 3000 chars. |
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
| `SQL_SYSTEM_PROMPT` | SQL generation | Only SELECT; only provided schema; use JOINs with CaseMaster; return raw SQL only (no markdown/backticks); `CANNOT_ANSWER` if unanswerable; LIMIT 50; escape `Rank` with backticks |
| `ANSWER_SYSTEM_PROMPT` | Answer formatting | Be concise; **never** emit a markdown table (the UI renders rows separately) — prose summary only; mention media; never speculate; "case" not "row" |
| `CORRECTION_SYSTEM_PROMPT` | SQL correction | Fix the broken SQL; return only corrected SQL; no explanation |
| `ROUTER_SYSTEM_PROMPT` | Intent router | Reply with exactly one word — `SQL` or `DIRECT`. DIRECT for follow-ups about already-shown data (referential words: "those", "them", "that", "the third one"…), filtering/ranking/insight over results already in context, greetings, and general questions. SQL when fresh crime data is needed. |
| `DIRECT_ANSWER_SYSTEM_PROMPT` | Direct answers | Answer from conversation + provided results only; **never fabricate** facts/numbers/trends/percentages not present in the data (explicit anti-hallucination rule); no markdown tables; concise professional prose. |

**Functions:**

| Function | Description |
|----------|-------------|
| `_format_history_for_prompt(history, max_turns=2, max_chars=100)` | Compresses conversation history into a short context block. Pairs user/assistant turns. Truncates assistant responses to `max_chars`. Returns empty string if no history. |
| `_format_history_for_sql_prompt(history, max_turns=2)` | History block for the SQL generator. Includes the prior turn's stored SQL so follow-ups can preserve filter clauses. |
| `_format_officer_for_prompt(officer)` | Builds the employee-identity block so first-person questions ("cases I am handling") resolve to `PolicePersonID`. |
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
- `graph_available: bool` — whether network graph data exists for the cases in results
- `error: str | None` — error message if something went wrong

**Functions:**

| Function | Description |
|----------|-------------|
| `_has_case_master_id(results)` | Checks if the first result row contains a `CaseMasterID` or `case_master_id` key |
| `collect_case_master_ids(results)` | Imported from `media_resolver` — extracts unique integer `CaseMasterID` or `case_master_id` values from all result rows. |
| `_check_graph_available(case_master_ids)` | Probe that returns `True` if any case IDs are present. The network graph is constructed dynamically on-demand from Accused and CaseMaster linkages. |
| `_most_recent_table(history)` | Walks history newest-first and returns the most recent assistant turn's stored table snapshot (or `[]`). Lets a follow-up be answered from the last result set without re-querying. |
| `_run_direct(question, history, recent_table)` | Runs the DIRECT path — calls `generate_direct_answer()` and returns a `PipelineResponse` with only `answer_text` filled. On `LLMError`/exception, returns a friendly error response (never raises). |
| `run_pipeline(question, history, officer=None) -> PipelineResponse` | **The main pipeline.** Never raises — every error is caught and converted to a user-friendly `answer_text` + `error` field. |

**Pipeline steps (in `run_pipeline`):**

0. **Intent routing** — `_most_recent_table(history)` recovers the last result set. **Optimization:** the router only runs when there *is* prior history (a brand-new chat with no history skips the router LLM call and goes straight to SQL — there's nothing to answer "directly" from yet). When history exists, `route_intent()` returns `SQL` or `DIRECT`; a `DIRECT` decision calls `_run_direct()` and returns immediately (no SQL, no DB).
1. **Schema linker** — `select_relevant_tables(question)` → list of table names
2. **SQL generation** — `generate_sql(question, tables, history, officer)` → `(SQL, attempts_used)` (with retry loop)
3. **Execute SQL** — `execute_query(sql)` → `list[dict]` (one corrective retry on MySQL error, within the shared `MAX_ATTEMPTS` budget)
4. **Media resolver** — `resolve_media(results)` → only if results have `CaseMasterID`/`case_master_id` column
5. **Graph probe** — `_check_graph_available(case_master_ids)` → boolean
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

**Purpose:** Looks up evidence media records for any cases present in query results.

**Functions:**

| Function | Description |
|----------|-------------|
| `collect_case_master_ids(results) -> list[int]` | Extracts unique integer `CaseMasterID` / `case_master_id` values from result rows. Shared with `query_pipeline.py` (imported there) so the logic exists in exactly one place. |
| `resolve_media(results) -> list[dict]` | (1) Collects `CaseMasterID` / `case_master_id` values from results. (2) Builds a parameterized `IN` query against `evidence_media`. (3) Executes one DB query. (4) Returns list of `{media_type, url, description, case_master_id}`. URLs are placeholders using the explicit `/api/media/unavailable?file={stratus_file_id}` format so the frontend can render a clean unavailable-media state instead of a broken file reference. Returns `[]` if no `CaseMasterID` or `case_master_id` column or no matches. |

> **Step 5 note:** `resolve_media()` now returns explicit unavailable preview URLs for placeholder demo data. This is intentional; the frontend renders neutral cards for unavailable media rather than broken media elements.

---

### 3.14 `backend/pipeline/schema_linker.py`

**Purpose:** Selects the most relevant tables for a given question using keyword matching.

**Constants:** `_MAX_TABLES = 5` — maximum tables returned (CaseMaster + up to 4 others)

**Functions:**

| Function | Description |
|----------|-------------|
| `_keyword_matches(question_lower, keyword) -> bool` | Matches a keyword against the lowercased question. Multi-word keywords (containing space, hyphen, or underscore) use substring match. Single-word keywords use word-boundary regex (`\b`) so "si" doesn't match inside "missing" or "phishing". |
| `select_relevant_tables(question) -> list[str]` | **The table selection algorithm.** (1) Lowercase the question. (2) For each table in `SCHEMA_CATALOG`, skip if `always_include: True` (collect separately). (3) Otherwise, score by counting keyword matches. (4) Sort by score descending, then alphabetically. (5) Build result: `CaseMaster` first, then other always-include tables, then top-scoring keyword matches up to `_MAX_TABLES`. |

**Example behavior:**
- "How many theft cases are open?" → `["CaseMaster", "CrimeSubHead", "CaseStatusMaster"]`
- "Show CCTV footage for FIR 2024" → `["CaseMaster", "evidence_media"]`
- "Who is Mahesh Gowda" → `["CaseMaster", "Accused"]` (name matches accused keywords)

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
| `save_turn(session_id, user_message, assistant_message, assistant_sql=None, assistant_table=None)` | Appends a user+assistant turn. Updates in-memory first (always). Then PUTs to NoSQL. If PUT returns 404 (document doesn't exist), POSTs to create it. `assistant_sql` is stored on the assistant turn so follow-up SQL generation can preserve filter clauses; `assistant_table` stores a bounded (`_TABLE_SNAPSHOT_ROWS`) snapshot of the result set so the next turn can answer follow-ups via the DIRECT path **without re-querying**. Uses `json.dumps(..., default=str)` when serializing history payloads so `date`/`datetime`/`timedelta` values persist cleanly. Never raises. |
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

**Local Fallback for Rich Data:**
To handle Zoho Catalyst NoSQL credential limitations in local development environments (which often raise `OAUTH_SCOPE_MISMATCH`), `chat_store.py` incorporates a persistent local JSON file fallback (`local_rich_data.json`).
- Writes and reads to `local_rich_data.json` are synchronized using an `asyncio.Lock` to ensure concurrency/thread safety.
- When NoSQL writes or reads fail, the system transparently falls back to this local file, preserving tables and media attachments across restarts and enabling them to render correctly in exports and conversation loads.

**Functions:**

| Function | Description |
|----------|-------------|
| `create_session(session_id, officer_id, title) -> bool` | `INSERT IGNORE` a new `chat_sessions` row (title clipped to 60 chars). Returns `True`/`False`. |
| `update_session_timestamp(session_id, increment_count=True)` | Touches `updated_at` and (by default) bumps `message_count` by 2 (one user + one assistant turn). Called after every successful pipeline run. |
| `get_sessions_for_officer(officer_id, limit=30) -> list[dict]` | Loads the officer's active sessions newest-first (`ORDER BY updated_at DESC`), datetimes serialized to ISO strings. Backs the sidebar. Returns `[]` on error. |
| `verify_session_owner(session_id, officer_id) -> bool` | **Read authorization:** checks that `session_id` exists and belongs to `officer_id`. Used before loading messages (`GET .../messages`) or exporting. Returns `False` if not found or owned by another officer. Enables BOLA/IDOR mitigation on read paths. |
| `save_message_pair(session_id, question, answer_text, sql_generated, has_table, has_media, graph_available, table_data, media_attachments) -> int \| None` | Inserts the user row + assistant row. When `has_table` is True, serializes `table_data` directly into the `table_data_json` MEDIUMTEXT column (replacing the old NoSQL `save_rich_data` pattern). Returns the assistant `message_id`. |
| `get_messages_for_session(session_id) -> list[dict]` | Loads all messages oldest-first (cap 100); deserializes `table_data` from the `table_data_json` column for assistant messages. |
| `save_rich_data(message_id, table_data, media_attachments)` | Writes `{table_data, media_attachments}` to NoSQL `message_rich_data` under key `msg_rich_{message_id}`. Falls back to `local_rich_data.json` on any NoSQL error. Non-fatal. |
| `load_rich_data(message_id) -> dict \| None` | Reads and parses the rich-data document for a message from NoSQL, or from `local_rich_data.json` if NoSQL is missing/fails. Returns `None` on miss/error. |

> **Environment note:** The NoSQL `message_rich_data` round-trip depends on a reachable Catalyst NoSQL endpoint + valid token. When NoSQL is unavailable the MySQL persistence still works fully; only the rich table/media hydration on reload degrades (rows come back empty unless they exist in the local JSON fallback `local_rich_data.json`).

---

### 3.16c `backend/db/nosql_client.py`

**Purpose:** Centralized Zoho Catalyst NoSQL client. Wraps the raw HTTP requests to Zoho Catalyst NoSQL tables, handling authorization, base URL resolution, and serialization/deserialization of JSON records to and from Catalyst format (e.g. `{"S": "value"}`).

**Key Helpers:**
- `serialize_to_catalyst(val)`: Converts standard Python types (bool, int, float, str, list, dict, None) into the structured nested format required by Catalyst NoSQL.
- `deserialize_from_catalyst(c_val)`: Recursively decodes Catalyst-formatted values back into standard Python primitives.
- `deserialize_item(item_data)`: Converts a full document object from Catalyst format.

**Functions:**

| Function | Description |
|----------|-------------|
| `get_document(table_name, document_id, timeout=5.0)` | POSTs to `/nosqltable/{table_name}/item/fetch` to fetch a document by ID. Returns the deserialized dict, or `None` if it does not exist (404) or fails. |
| `insert_document(table_name, document_id, document_data, timeout=5.0)` | POSTs to `/nosqltable/{table_name}/item` to insert a serialized document. Returns `True` on success; raises `NoSQLError` on failure. |
| `update_document(table_name, document_id, updates, timeout=5.0)` | PUTs to `/nosqltable/{table_name}/item` with update operations. Returns `True` on success; raises `NoSQLError` on failure. |
| `delete_document(table_name, document_id, timeout=5.0)` | Sends a DELETE request to `/nosqltable/{table_name}/item`. Returns `True` on success; raises `NoSQLError` on failure. |
| `list_documents(table_name, timeout=5.0)` | GETs `/nosqltable/{table_name}/item` to retrieve all items. Returns a list of deserialized dicts. |

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
| `_authorize_session_write(session_id, officer_id) -> bool` | **Authorization gate for write paths.** Mitigates BOLA/IDOR (OWASP API1:2023) by verifying that `session_id` either (a) doesn't exist yet (create-or-append: officer will own it), or (b) exists and belongs to `officer_id`. Raises HTTP 404 (not 403) if owned by another officer. Returns the existence flag (True if session exists) so `_persist_turn` avoids a duplicate query. Single indexed PK lookup — negligible cost. |
| `_persist_turn(session_id, officer, question, result, session_exists)` | **Step 4 persistence helper.** Creates the `chat_sessions` row on a session's first message (when `session_exists=False`), saves the user+assistant pair via `chat_store.save_message_pair` (table data serialized to MySQL `table_data_json` column), then bumps `updated_at`/`message_count`. Never raises — logs and continues on failure. Called after `save_turn` in both chat endpoints. |
| `list_chat_sessions(officer)` | `GET /api/chat/sessions` — lists the officer's sessions newest-first **from MySQL** (`chat_store.get_sessions_for_officer`). Always HTTP 200 (returns `[]` on DB error). |
| `create_chat_session(officer)` | `POST /api/chat/sessions` — creates a NoSQL `session_metadata` doc and returns `SessionMetadata` (HTTP 201). **Currently unused by the UI** (see [9.5](#95-backend-created-sessions-on-new-chat--deprecated-flow-change)). |
| `get_session_messages(session_id, officer)` | `GET /api/chat/sessions/{id}/messages` — **read authorization:** verifies ownership via `chat_store.verify_session_owner` (404 on mismatch/not-found), then returns all messages oldest-first from MySQL with `table_data` deserialized from the `table_data_json` column. **No pagination** (the prior `limit`/`before_message_id` cursor flow was removed — see [9.9](#99-message-pagination--removed)). |
| `chat(request, officer)` | `POST /api/chat` — non-streaming endpoint (testing/fallback). **Enforces write authorization** via `_authorize_session_write` before any pipeline work. Fetches history, runs pipeline, `save_turn` (with `assistant_table`), then `_persist_turn`. Always returns HTTP 200 with `ChatResponse`. Returns HTTP 404 if `session_id` belongs to another officer. |
| `chat_stream(question, session_id, officer)` | `GET /api/chat/stream` — SSE streaming endpoint. Protected by `get_current_officer_sse` (header or query param). **Enforces write authorization** via `_authorize_session_write` before opening the stream, so a forged `session_id` returns a clean HTTP 404 instead of an in-stream error. After the pipeline, `save_turn` (with `assistant_table`) then `_persist_turn`. Returns `StreamingResponse` with `text/event-stream`. |
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

**Purpose:** HTML export of a chat session. Renders the conversation as a self-contained, downloadable HTML file. No external dependencies -- pure stdlib. SmartBrowz integration was removed; the export always succeeds.

**Functions:**

| Function | Description |
|----------|-------------|
| `_escape(value) -> str` | HTML-escapes a value (including quotes) so user content, table headers, and cells are safely rendered in the PDF. Returns empty string for `None`. |
| `_merge_history_tables(messages, history) -> list[dict]` | Recovery helper: fills missing assistant `table_data` from conversation history snapshots. The UI can show tables from a live stream even when rich persistence is unavailable; this helper ensures exports recover them from the bounded history snapshot so older/partially-saved turns still include visible DB rows. |
| `_build_html(officer_name, badge_number, title, messages) -> str` | Builds a styled, self-contained HTML document: a header (officer + badge + session title + export date), each message (user bubbles right-aligned, assistant blocks with any result table rendered, max 50 rows, with a record-count footer), and a confidential footer. All content is HTML-escaped. |
| `export_session_pdf(session_id, officer) | POST /api/chat/sessions/{id}/export - **(1) read authorization:** verifies ownership via erify_session_owner (404 on mismatch); **(2)** loads messages via get_messages_for_session (400 if none); merges table snapshots from history via _merge_history_tables; **(3)** fetches session title + officer name/badge from MySQL; **(4)** builds HTML via _build_html; **(5)** streams HTML directly as downloadable .html file (KSP-{id[:8]}.html). Always succeeds - no external service calls.

> Note: SmartBrowz integration removed. SMARTBROWZ_URL is no longer read by this router. Export always returns a self-contained HTML file. The html stdlib module is aliased as html_lib to prevent variable shadowing.

---

### 3.21 `backend/routers/reports.py`

**Purpose:** Handles analysis and intelligence extraction from uploaded report files. Extracts text from base64 data payloads, classifies themes/entities, relates them to existing case/chat context using `MODEL_ANSWER`, and persists the interaction to both conversation history (NoSQL) and database (MySQL).

**Pydantic models:**
- `ReportAnalysisRequest`: Fields: `session_id`, `prompt`, `file_name`, `mime_type`, `data_base64`.
- `ReportAnalysisResponse`: Fields: `answer_text`, `extracted_chars`, `file_name`, `warning`.

**Key helpers:**
- `_decode_file(data_base64)`: Decodes the base64 payload into raw bytes, limiting file size to 5MB.
- `_decode_text(raw)`: Decodes bytes to string trying `utf-8-sig`, `utf-8`, `cp1252`, `latin-1` or ignoring errors.
- `_extract_docx_text(raw)`: Parses DOCX OpenXML ZIP content to extract paragraph text.
- `_extract_html_text(text)`: Strips `<script>` and `<style>` blocks, removes all HTML tags, and unescapes entities.
- `extract_report_text(raw, file_name, mime_type)`: Dispatches text extraction depending on file extension or mime type. Supports: DOCX (unzip + XML parse), text/markdown/HTML/JSON/CSV (decode + optional tag-stripping). **Rejects PDF and unknown binary types** with HTTP 415 and an actionable message; PDF requires a real library (pypdf/pdfminer) and scanned PDFs need OCR. Truncates results to 14,000 characters.
- `build_report_prompt(prompt, file_name, text, history)`: Assembles system and user prompts, blending the officer's request, recent conversation context, and report content.
- `_persist_report_turn(session_id, officer, question, answer, session_exists)`: Persists the report-analysis turn to MySQL (creates session if `session_exists` is False). Non-fatal — logs errors instead of raising.

**Functions:**

| Function | Description |
|----------|-------------|
| `analyze_report(request, officer)` | `POST /api/reports/analyze` — **Enforces session ownership authorization (BOLA/IDOR mitigation)** before any expensive work. Decodes report (max 5MB), extracts text (DOCX/text/markdown/HTML supported; PDF/binary rejected), queries `MODEL_ANSWER` via QuickML (max_tokens=8000), appends turn to NoSQL history + MySQL, and returns the analysis. Returns HTTP 404 if `session_id` belongs to another officer (not 403, to avoid leaking existence). |

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
              → db/connection.py: execute_query("SELECT ... FROM evidence_media WHERE case_master_id IN (...)")
              → returns [{media_type, url, description, case_master_id}]
        
          Step 5: Graph Probe
            → _check_graph_available(case_master_ids)
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
Question: "How many cases are open?"

Attempt 1:
  LLM generates: "SELECT COUNT(*) FROM CaseMaster WHERE CaseStatusName = 'Open'"
  Validator/Execute: FAIL — "CaseStatusName" column doesn't exist in CaseMaster (it's in CaseStatusMaster)
  → Save error message

Attempt 2 (correction):
  Prompt: "The following SQL query is invalid: SELECT COUNT(*) FROM CaseMaster WHERE CaseStatusName = 'Open'\nError: Unknown column 'CaseStatusName'\nSchema: [CaseMaster schema + CaseStatusMaster schema]\nWrite the corrected SQL query only."
  LLM generates: "SELECT COUNT(*) AS open_cases FROM CaseMaster AS cm JOIN CaseStatusMaster AS csm ON csm.CaseStatusID = cm.CaseStatusID WHERE csm.CaseStatusName = 'Open'"
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
  → POST /api/chat/sessions/{id}/export    # build HTML → stream as downloadable .html file
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
    │   ├── MediaViewer.jsx   # Evidence media viewer (lightbox, audio/video, placeholder cards)
    │   ├── TableRenderer.jsx # HTML table from JSON data
    │   ├── SessionList.jsx   # Scrollable session list (loading/empty/error states)
    │   ├── SessionItem.jsx   # One session row (title + timestamp + count + export button)
    │   ├── OfficerRow.jsx    # Sidebar-bottom officer avatar + sign-out popup
    │   └── Icons.jsx         # Inline SVG icon set (no icon library)
    ├── hooks/
    │   └── useAuth.js        # Auth state management
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

**Custom Hook:**
- Exports the `useLang()` custom hook directly, allowing any component inside the provider tree to easily consume the language state and the translation helper.

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

### 9.11 `frontend/src/hooks/useLang.js` — DELETED

- **What it was:** A custom hook that managed the language state locally using `useState`.
- **Status:** Deleted from disk.
- **Why removed:** Replaced by `frontend/src/context/LangContext.jsx` which manages the active language state globally as a single source of truth, synchronizes it with localStorage, and exports the `useLang` hook directly to components.


---

## 10. Recent Changes

### 10.1 Security — BOLA/IDOR Mitigation (Authorization on Session Access)

**Date:** June 19, 2026  
**Issue:** Three write endpoints (`POST /api/chat`, `GET /api/chat/stream`, `POST /api/reports/analyze`) and the reports feature lacked object-level authorization. An authenticated officer could write turns into another officer's session by supplying its `session_id` — a textbook BOLA (Broken Object Level Authorization) / IDOR (Insecure Direct Object Reference) vulnerability (OWASP API1:2023).

**Fix:**
- **Read paths** (already correct): `GET /api/chat/sessions/{id}/messages` and `POST /api/chat/sessions/{id}/export` call `verify_session_owner()` and return HTTP 404 (not 403) on mismatch, to avoid leaking that a foreign session exists.
- **Write paths** (added authorization):
  - `POST /api/chat` and `GET /api/chat/stream` now call `_authorize_session_write()` **before** any pipeline work, returning HTTP 404 if the `session_id` exists and belongs to another officer. Create-or-append semantics are preserved: a not-yet-existing `session_id` is allowed (the officer will own it on creation).
  - `POST /api/reports/analyze` does an inline ownership check before file decode and the LLM call, reusing the existence result to avoid a duplicate query in `_persist_report_turn`.
  - All three write paths reuse the existence flag so `_persist_turn` / `_persist_report_turn` no longer run a separate `SELECT` to check if the session exists — **same query count as before, now also doing authorization.**

**Performance:** Single indexed PK lookup (session_id is the PK) — effectively free. Zero added round-trips.

**Tests:** `backend/tests/test_session_authz.py` (6 tests) covers intruder rejection (404, asserting pipeline/LLM/decode never runs), owner acceptance, and brand-new-session acceptance across all three write endpoints.

**Documentation:** Added [§3.1a Security — Authorization & BOLA/IDOR Mitigation](#31a-security--authorization--bolaidor-mitigation) section explaining the two patterns and why we return 404 instead of 403.

---

### 10.2 Report Text Extraction — Lean & Reliable (Removed Fragile PDF Parser)

**Date:** June 19, 2026  
**Issue:** `routers/reports.py` included a hand-rolled PDF text extractor (`_extract_pdf_text`) that brute-forced `zlib.decompress` on every stream in the PDF and ran multiple regex passes over PDF operators. High compute, unreliable output (garbage on most real PDFs — compressed object streams, custom encodings, scanned pages).

**Fix:**
- **Kept** (cheap, stdlib-only, reliable): DOCX (unzip + XML parse), text/markdown/HTML/JSON/CSV (decode + optional tag-stripping via `_extract_html_text`).
- **Removed**: `_pdf_literal_to_text()`, `_extract_pdf_text()`, and the `zlib` import.
- **PDF and unknown binary types now reject cleanly** with HTTP 415 (`UnsupportedReportFormat`) and an actionable message: *"PDF analysis isn't supported yet. Please upload the report as text, Markdown, or a Word (.docx) file."*
- Proper PDF support, if the feature gets prioritized, should use a real library (pypdf/pdfminer) — a deliberate dependency, not a hack.

**Rationale:** Aligns with the "least compute, enough results" principle. DOCX extraction is a trivial unzip + XML read, and text/markdown/HTML are just decode + optional tag-strip. The PDF brute-forcer was the only compute-heavy, fragile part.

**Tests:** `backend/tests/test_report_extraction.py` (7 tests) covers DOCX by extension + by MIME, plain text, Markdown, HTML tag-stripping + entity unescaping, PDF rejection with helpful message, and unknown-binary rejection.

**Documentation:** Updated [§3.21 `backend/routers/reports.py`](#321-backendreporterspy) key helpers list and function table to reflect the new extraction behavior and the `UnsupportedReportFormat` exception.

---

### 10.3 LLM Token Budget — Report Analysis (12000 → 8000)

**Date:** June 19, 2026  
**Issue:** `POST /api/reports/analyze` called `call_llm(max_tokens=12000)` when assembling the analysis prompt. QuickML treats `max_tokens` as the **total** budget (input + output), not just the output length. The report prompt embeds up to ~3,500 tokens of extracted text plus a short history slice, so 12000 was over-allocated.

**Fix:** Changed to `max_tokens=8000`, matching the existing `answer_formatter` convention. Still comfortably covers the prompt (input) plus a full intelligence note (output), without over-allocating.

**Documentation:** Added an inline comment explaining the QuickML token semantics and the sizing rationale.

---

### 10.4 CSS — Removed Duplicate `.chat-header` Block

**Date:** June 19, 2026  
**Issue:** `frontend/src/styles/main.css` contained two `.chat-header` / `.chat-header__title` / `.chat-header__export-btn` blocks — one at line ~568, another at line ~1925. The second block won the cascade, making the first block dead overridden code (a merge artifact).

**Fix:** Removed the first block (lines 568–616). Rendering is byte-for-byte identical; confirmed by a clean frontend production build.

**Documentation:** No behavior change, so no doc update needed beyond this changelog entry.

---

### 10.5 Rich Data Storage — NoSQL → MySQL `table_data_json` Column

**Date:** Prior to June 19, 2026 (teammate change)  
**What changed:** Previously, tabular query results attached to an assistant message were stored in a separate Catalyst NoSQL document keyed by `msg_rich_{message_id}`. Now they're serialized directly into a `table_data_json MEDIUMTEXT` column on the `chat_messages` table.

**Rationale:** Eliminates a round-trip, simplifies recovery logic (no need to hydrate from a separate store), and keeps all message data in one indexed query. The `_serialize()` helper in `chat_store.py` handles `date`/`datetime`/`timedelta` objects.

**Functions affected:**
- `chat_store.save_message_pair()`: now serializes `table_data` to `table_data_json` instead of calling a separate `save_rich_data()` helper.
- `chat_store.get_messages_for_session()`: deserializes from `table_data_json` instead of calling `load_rich_data()`.
- `save_rich_data()` and `load_rich_data()` removed from `chat_store.py`.

**Schema change:** `backend/db/schema.sql` — `chat_messages` table gained `table_data_json MEDIUMTEXT DEFAULT NULL`.

**Documentation:** Updated [§3.4 `backend/db/schema.sql`](#34-backenddbschemasql) with a "Rich data storage migration" note and [§3.16b `backend/db/chat_store.py`](#316b-backenddbchat_storepy) function descriptions.

---

### 10.6 NoSQL Client Centralization

**Date:** Prior to June 19, 2026 (teammate change)  
**What changed:** `conversation/history.py` and `conversation/session_store.py` previously had their own inline `httpx` calls to Catalyst NoSQL, each with duplicate `_nosql_headers()`, `_nosql_url()`, and `_nosql_collection_url()` helpers. These were replaced with calls to `db.nosql_client.get_document()`, `insert_document()`, `update_document()`, `delete_document()`, `list_documents()`.

**Auth header change:** `Authorization` header changed from `"Bearer {TOKEN}"` to `"Zoho-oauthtoken {TOKEN}"` (the correct Catalyst API convention, per the BLUEPRINT).

**Documentation:** Added [§3.16c `backend/db/nosql_client.py`](#316c-backenddbnosql_clientpy) section documenting the centralized NoSQL wrapper.

---

### 10.7 Backfill Migration Script

**Date:** June 20, 2026  
**What changed:** Added `backfill.py` to populate the new `table_data_json` field for existing chat messages that were previously `has_table=1` but still had `table_data_json=NULL`.

**How it works:**
- Reads `.env` for DB credentials
- Queries `chat_messages` for rows with `has_table=1` and `table_data_json IS NULL`
- Re-executes each row's original `sql_generated` query against the same database
- Serializes results with `json.dumps(..., default=serialize)` where dates/datetimes use ISO format and timedeltas become `HH:MM:SS`
- Updates `chat_messages.table_data_json` for each backfilled message

**Usage note:** This is a migration helper only; it should be run after the new schema is deployed and only when existing data needs to be backfilled. See `README.md` for the install/setup note.


---

### 10.7 Network Graph Visualization (Step 5 — Part 1)

**Date:** June 19, 2026  
**What:** Renders the criminal network dynamically on demand based on co-accused and crime patterns.

**Backend:**
- `backend/graph/network_builder.py` — `build_graph_for_fir(fir_id)` and `build_graph_for_accused(accused_id)` return vis.js-compatible `{"nodes": [...], "edges": [...]}`. Node IDs are namespaced by entity type (`case_2`, `accused_5`) to avoid cross-table ID collisions. Live network graph derives edges on demand from Accused and CaseMaster linkages (Option A / MIGRATE_STEP4).
- `backend/routers/chat.py` — `GET /api/graph/fir/{fir_id}` and `GET /api/graph/accused/{accused_id}`. Auth-gated via `get_current_officer`. **No ownership check** by design: case/accused data is station-scoped, not officer-owned (unlike chat sessions). Always HTTP 200 (empty graph on error, never 500).

**Frontend:**
- `NetworkGraph.jsx` — vis-network modal, color-coded by entity group, loading/empty/error states, instance destroyed on unmount. **Lazy-loaded** via `React.lazy` so vis-network (≈653 KB) is code-split into its own chunk fetched only when an officer first opens a graph — main bundle unchanged.
- `MessageBubble.jsx` — "View network" button shown when `graphAvailable` and a `CaseMasterID` is extractable from the table rows.
- `ChatWindow.jsx` — graph modal state, `onGraphAvailable` stream callback, `graphAvailable` persisted on history reload.
- `Icons.jsx` — `IconNetwork`. `main.css` — graph overlay + button styles.

**Dependency:** `vis-network` + `vis-data` (MIT, actively maintained). `npm audit` confirmed zero vulnerabilities in these packages (pre-existing dev-only esbuild/vite advisories are unrelated).

**Tests:** `backend/tests/test_network_graph.py` — basic async tests verification for CaseMaster and Accused graph builders.

---

### 10.8 Voice Pipeline (Step 5 — Part 2)

**Date:** June 19, 2026  
**What:** Mic input (Zia STT), Kannada→English translation, and on-demand read-aloud (Zia TTS).

**Backend:**
- `backend/voice/zia_voice.py` (new) — `transcribe_audio()`, `translate_to_english()`, `synthesize_speech()`. House conventions: `Zoho-oauthtoken` auth + `CATALYST-ORG` header, `{"data": ...}` envelope unwrap. STT/TTS raise `VoiceError`; translation degrades gracefully (returns original text on any failure so the pipeline still runs untranslated).
- `translate_to_english()` now uses `src_lang`/`tgt_lang` instead of `source_language`/`target_language`, and correctly extracts `translated_text` from the top-level payload rather than a nested `data` object.
- `synthesize_speech()` pre-processes text before sending it to TTS by stripping markdown tables/symbols, expanding digits into spoken words, and normalizing common police abbreviations like `FIR`, `KOR`, `HSR`, `JPN`, and `BTM` so the voice output is intelligible. The TTS payload is clipped to 400 characters and includes the required speaker/pitch/speed/emotion fields.
- `backend/routers/voice.py` (new) — `POST /api/voice/transcribe` (multipart audio, 10 MB cap; auto-translates when `language="kn"`) and `POST /api/voice/speak` (text → `audio/mpeg` stream). Auth-gated. Failures return HTTP 502 so the UI degrades (STT → "please type"; TTS → simply no audio).
- `backend/main.py` — registered `voice_router`.

**Frontend:**
- `api/voice.js` (new) — `recordAndTranscribe()` and `speakText()` (best-effort, revokes blob URLs after playback).
- `VoiceInput.jsx` (new) — mic button with idle/recording/processing states, 30 s auto-stop, mic-stream cleanup on unmount. Replaces the old placeholder mic in `Composer.jsx`; transcript is appended to the composer for review (not auto-sent). Language comes from `useLang()`.
- `MessageBubble.jsx` — on-demand "Read aloud" button on assistant messages (demo choice: on-demand, not auto-play).
- `Icons.jsx` — `IconSpeaker`. `main.css` — mic recording pulse, spinner, message action row, read-aloud button styles.

**Contract caveat:** The exact Zia REST request/response field names are not in the publicly fetchable docs (behind the console), so request bodies and response extraction are best-guesses based on Catalyst conventions. `_extract_transcript` / `_extract_translation` try several likely field names and log the raw response shape on a miss. When tested against live Catalyst, only those field mappings may need adjustment — not the routes or frontend.

**Tests:** `backend/tests/test_voice.py` (19 tests) — envelope/extraction helpers, the three network functions with a fake httpx client, and both routes with `zia_voice` monkeypatched (Kannada translation path, English no-translation path, 502 on failure, empty-audio 400, audio streaming).

**Tests:** `backend/tests/test_media_resolver.py` — `collect_case_master_ids()` extraction and `resolve_media()` behavior for empty results, no CaseMaster IDs, unavailable preview URL generation, and multiple media files across cases.

---

### 10.9 Schema v2 Migration (Step 3 & 4 Update)

**Date:** June 26, 2026  
**What:** Migrated the database schema to Schema v2, bringing it into full alignment with the official Karnataka State Police database structure, and updated the backend/frontend components accordingly.

**Key Changes:**
- **Database Schema (`backend/db/schema.sql`):** Rewrote table definitions to match official police database layout.
  - Replaced the old child-tables pattern (`cases_theft`, `cases_assault`, etc.) with a single unified `CaseMaster` table representing all cases.
  - Replaced the `officers` table with `Employee` and associated lookup tables (e.g. `Rank`).
  - Added new structural entities: `State`, `District`, `UnitType`, `Unit`, `Court`, `Rank`, `Designation`, `CrimeHead`, `CrimeSubHead` (crime types), `CaseCategory`, `GravityOffence`, `CaseStatusMaster`, `Act`, `Section`, `CasteMaster`, `ReligionMaster`, `OccupationMaster`, `ComplainantDetails`, `Victim`, `Accused`, `ActSectionAssociation`, `ArrestSurrender`.
- **Seeder (`backend/db/seed.py`):** Completely rewritten to seed lookups, employees, complainants, victims, accused, act-sections, and arrest/surrender records. Added logic so 60% of accused are marked as arrested (with records in `ArrestSurrender`) and 40% are still at large.
- **Network Graph (`backend/graph/network_builder.py`):** Eliminated the `case_relationships` table. Edges are now derived live on the fly from co-accused (same `CaseMasterID`) and similar crime patterns (same `CrimeMinorHeadID` and `PoliceStationID` Unit). Node IDs are prefixed by type (e.g. `case_123`, `accused_456`) to prevent collisions.
- **Authentication (`backend/auth/simple_auth.py`):** Swapped lookup target from `officers` to `Employee` and joined `Rank` to fetch the rank name. Authed employees log in using their `KGID` badge number and password equal to `KGID + "123"`.
- **Query Pipeline & LLM Prompts (`backend/pipeline/` & `backend/llm/`):**
  - Updated LLM prompts to use PascalCase table/column names, require joining case-related tables on `CaseMasterID`, escape the MySQL reserved word `Rank`, filter by `CrimeSubHead.CrimeHeadName` for crime type, and represent accused still at large using a `LEFT JOIN ArrestSurrender` check.
  - Updated `media_resolver` and `query_pipeline` to use `CaseMasterID` / `case_master_id` and `collect_case_master_ids()` instead of `fir_id`.
  - Added `_normalize_bit_fields` to `db/connection.py` to transparently convert MySQL `BIT` fields (used for booleans/active flags) into Python booleans.
- **Frontend (`frontend/src/`):** Adapted `ChatWindow.jsx` and `MessageBubble.jsx` to pass and extract `CaseMasterID` (PascalCase!) and `caseMasterId` (camelCase) instead of `fir_id` to/from the table results for opening network graphs.
- **Test Suite:** Fixed and verified all 128 tests passing successfully.
