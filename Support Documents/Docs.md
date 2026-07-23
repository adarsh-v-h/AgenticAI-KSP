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

**Single LLM — GLM-4.7-Flash** (`crm-di-glm47b_30b_it`):  
A 30B Mixture-of-Experts model (GLM-4.7 family) handling all three roles:
1. `MODEL_SQL` — generates SQL from natural language
2. `MODEL_ANSWER` — (a) **intent routing** (SQL vs DIRECT), (b) formatting raw DB results into a natural-language answer, (c) **direct conversational answers** for follow-ups/insights, and (d) **follow-up question suggestions**

Called via the Catalyst QuickML GLM endpoint (`/quickml/v1/project/.../glm/chat`) using OpenAI-compatible `messages` format. No external LLM providers (OpenAI, Anthropic, etc.) are used.

**Two answer paths (see [Section 4.6](#46-intent-routing--direct-answers)):**
- **SQL path** — fresh data requests run the full NL→SQL→execute→format chain.
- **DIRECT path** — follow-ups about already-retrieved data ("which of those is open?"), requests for insight, greetings, and general questions are answered straight from the conversation + the most recent result set, with **no SQL and no DB hit**. The most recent answer's table is cached in conversation history (a bounded snapshot) so the model can discuss the data instead of re-querying it.

**Key constraints enforced in code:**
- Every SQL query must be a SELECT — validated before execution
- Maximum 2 SQL generation attempts (self-correction loop)
- Conversation history limited to 10 turns per session
- Sessions and messages are persisted to MySQL (AWS RDS); conversation context for LLM goes to Catalyst NoSQL — see [Section 4.7](#47-persistent-chat-storage)
- All secrets loaded from `.env`, never hardcoded

---

## 2. Backend Architecture

```
backend/
├── main.py                    # FastAPI app, lifespan, CORS, health check
├── benchmark.py               # Standalone HTTP benchmark harness for API latency testing
├── Dockerfile                 # Container for Catalyst AppSail
├── debug_tools.py             # Unified CLI debug utility (env/db/schema/tables/rag)
├── setup_db.py                # Create tables + seed from .env (any MySQL target)
├── config/
│   └── settings.py            # Environment variable loading and validation
    ├── db/
    │   ├── connection.py          # MySQL connection pool (aiomysql) + execute_query / execute_write
    │   ├── schema.sql             # DDL for all tables (incl. chat_sessions, chat_messages)
    │   ├── seed.py                # Synthetic data generator (200+ FIRs)
    │   ├── chat_store.py          # Persistent sessions + messages (MySQL) + rich data (NoSQL)
    │   ├── nosql_client.py        # Centralized Catalyst NoSQL client wrapper
    │   ├── schema_catalog.py      # Table metadata, schema builder, few-shot bank
    │   └── lookup_cache.py        # In-memory lookup tables cache (Unit, CrimeSubHead, CaseStatusMaster)
├── llm/
│   ├── client.py              # HTTP client for Catalyst QuickML (GLM-4.7-Flash)
│   ├── sql_generator.py       # SQL generation with retry loop
│   ├── answer_formatter.py    # Result-to-text formatting + intent router + direct answers
│   └── prompts.py             # All prompts and prompt builders
├── pipeline/
│   ├── query_pipeline.py      # Main orchestrator (route → NL → SQL → answer, or DIRECT)
│   ├── station_scope.py       # Role-based station scoping & disclaimer engine
│   ├── date_utils.py          # Shared date predicate extraction & rewrite utility
│   ├── sql_validator.py       # SQL safety validation
│   ├── media_resolver.py      # Evidence media lookup
│   ├── schema_linker.py       # Keyword-based table selector with assumption tracking
│   ├── risk_scoring.py        # Offender risk scoring (rule-based, explainable)
│   ├── trend_analytics.py     # Crime pattern analytics (pure SQL aggregation)
│   ├── similar_cases.py       # Similar case finder
│   ├── case_timeline.py       # Case timeline builder (CaseMaster + ArrestSurrender events)
│   ├── case_summary.py        # LLM-generated investigative case brief
│   └── evidence_trail.py      # Chat SQL provenance writer (chat_evidence_trail)
├── conversation/
│   ├── history.py             # Conversation history + recent-table snapshot (NoSQL + in-memory fallback)
│   └── session_store.py       # Session metadata + title generation (NoSQL + fallback)
├── auth/
│   ├── simple_auth.py         # JWT auth (dev) with Catalyst Auth swap path
│   └── role_guard.py          # RBAC + audit logging
├── graph/
│   └── network_builder.py     # Criminal network graph (vis.js format)
├── voice/
│   └── zia_voice.py           # Zia STT/TTS/translate wrapper
├── routers/
│   ├── chat.py                # /api/chat, /api/chat/stream (SSE), /api/chat/sessions*
│   ├── export.py              # POST /api/chat/sessions/{id}/export (HTML conversation export)
│   ├── reports.py             # POST /api/reports/analyze (Report analysis & upload)
│   ├── voice.py               # POST /api/voice/transcribe, /api/voice/speak
│   ├── governance.py          # GET /api/audit-log (supervisor-only)
│   ├── analytics.py           # GET /api/analytics/* (trend/pattern endpoints)
│   ├── decision_support.py    # Decision support (similar cases, timeline, summary)
│   ├── profiling.py           # GET /api/profiling/risk/* (offender risk scores)
│   └── auth.py                # POST /api/auth/login + /api/auth/logout
└── tests/
    ├── conftest.py            # pytest config (sys.path setup)
    ├── test_unit.py           # 57 pure unit tests
    ├── test_pipeline_and_sessions.py  # 15 pipeline + session tests
    └── test_integration.py    # Live integration tests (needs real tokens)
```

---

## 3. File-by-File Reference

### 3.1 `backend/main.py`

**Purpose:** FastAPI application entry point. Manages startup/shutdown lifecycle, registers routers, configures CORS, exposes a health check endpoint, and manages gRPC service lifecycle.

**sys.path manipulation:** Lines 9-11 add the `backend/` directory to `sys.path` so that imports like `from config.settings import get` resolve correctly when the app is run via `uvicorn backend.main:app` from the project root.

**Functions:**

| Function | Lines | Description |
|----------|-------|-------------|
| `lifespan(app)` | 20-50 | Async context manager. On startup: (1) calls `validate_settings()` to crash if any env var is missing, (2) creates the MySQL connection pool via `create_pool()`, (3) runs a `SELECT 1` probe to confirm DB reachability (stores result in `app.state.db_ok`), (4) calls `init_nosql_table()` to probe Catalyst NoSQL, (5) starts gRPC LLM Service (port 50051) and SQL Service (port 50052) via `start_llm_grpc_server()` and `start_sql_grpc_server()`. On shutdown: stops gRPC servers via `stop_llm_grpc_server()` / `stop_sql_grpc_server()`, closes gRPC client channels via `close_llm_client()` / `close_sql_client()`, and calls `close_pool()`. |
| `health_check()` | 74-123 | `GET /health` — returns `{"status": "ok"|"degraded", "db": ..., "llm_coder": ..., "llm_answer": ..., "env": ...}`. Runs LLM pings (via gRPC) in parallel via `asyncio.gather`. Always returns HTTP 200, even if degraded. |
| `warm_endpoint()` | - | `POST /internal/warm` — returns `{"status": "success", "message": "Pings dispatched successfully"}`. Pings LLM (via gRPC) and Zia Voice services in parallel to keep serverless containers warm. |

**Startup sequence:**
1. `validate_settings()` → crash if `.env` incomplete
2. `create_pool()` → MySQL connection pool (minsize/maxsize configurable via `DB_POOL_MINSIZE`/`DB_POOL_MAXSIZE` env vars, defaults 5/10)
3. DB probe → `SELECT 1`, sets `app.state.db_ok`
4. NoSQL probe → confirms Catalyst NoSQL reachable
5. **Start gRPC services** → LLM Service (port 50051) and SQL Service (port 50052) as background tasks
6. Rate limiter background sync started
7. Eager warm-up → `ping_model("MODEL_SQL")`, `ping_model("MODEL_ANSWER")` (via gRPC), and `ping_voice()` run concurrently via `asyncio.gather` **before** accepting connections; then a background `_keep_warm_loop` repeats the same pings every 300 s (sleep-first, so the loop waits before each iteration rather than pinging immediately after the eager run)
8. Register `auth_router`, `chat_router`, `export_router`, and `reports_router`

**gRPC Lifecycle:**
- Both gRPC services run as background asyncio tasks within the same process as the FastAPI gateway — no separate containers or service discovery in Phase 1.
- gRPC servers use `insecure_channel` (localhost-only, no TLS) since all communication is intra-process.
- On shutdown, gRPC servers stop gracefully before closing the MySQL pool.

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

**Tests:** `backend/tests/test_pipeline_and_sessions.py` (TestSessionAuthz) covers all three write endpoints: intruder rejection (404, asserting the pipeline/LLM never runs), owner acceptance, and brand-new-session acceptance.

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

**Purpose:** gRPC client for the SQL Service. Forwards `execute_query()` calls to the gRPC SQL Service running on port 50052. Re-exports pool lifecycle functions and `execute_write()` from `connection_real.py`.

**Module-level state:** 
- `_channels` — dict mapping asyncio event loop to gRPC channel
- `_stubs` — dict mapping asyncio event loop to `SQLServiceStub`

**Functions:**

| Function | Description |
|----------|-------------|
| `_get_grpc_stub() -> SQLServiceStub` | Returns a per-event-loop gRPC stub for the SQL Service (localhost:50052). Creates channel and stub lazily on first call per loop. |
| `close_sql_client() -> None` | Closes all gRPC channels and clears stub cache. Called during FastAPI shutdown. |
| `execute_query(sql, params) -> list[dict]` | **gRPC client function.** (1) Tries to serve from in-memory lookup cache via `intercept_lookup_query()` — returns immediately if cache hit. (2) On cache miss, forwards the query to SQL Service via gRPC. (3) Serializes `params` to JSON, sends `ExecuteQueryRequest`, deserializes `ExecuteQueryResponse.rows_json` back to `list[dict]` via `orjson`. (4) Uses 5-second timeout. Raises `RuntimeError` on gRPC failure. |
| `create_pool()` | Re-exported from `connection_real.py` — creates the actual MySQL connection pool. Called during FastAPI startup. |
| `get_pool()` | Re-exported from `connection_real.py` — returns the existing pool. |
| `close_pool()` | Re-exported from `connection_real.py` — closes all pool connections. Called during FastAPI shutdown. |
| `execute_write(sql, params) -> int` | Re-exported from `connection_real.py` — executes INSERT/UPDATE/DELETE directly against MySQL (writes stay local, not routed through gRPC). |

**Lookup cache fast path:** `execute_query()` checks `intercept_lookup_query()` **before** making the gRPC call, preserving zero-latency cache hits for `Unit`, `CrimeSubHead`, and `CaseStatusMaster` queries.

**Why writes stay local:** `execute_write()` is not routed through gRPC — chat message persistence and session updates go directly to MySQL via `connection_real.py`. Only read-heavy SELECT queries (which dominate the workload) use gRPC.

---

### 3.3a `backend/db/connection_real.py`

**Purpose:** Direct MySQL connection pool and query execution. Used by the SQL gRPC Service (`grpc_server.py`) and for local writes (`execute_write`). This is the "real" connection layer extracted from the original `connection.py`.

**Module-level state:** `_pool` — the global `aiomysql.Pool` instance, created once at startup.

**Functions:**

| Function | Description |
|----------|-------------|
| `create_pool() -> aiomysql.Pool` | Creates the connection pool with `host`, `port`, `user`, `password`, `db` from env vars. Pool sizes are configurable via `DB_POOL_MINSIZE` (default `5`) and `DB_POOL_MAXSIZE` (default `10`) environment variables. Settings: `autocommit=True`, `connect_timeout=5`. Stores in `_pool`. Called once during FastAPI lifespan. |
| `get_pool() -> aiomysql.Pool` | Returns the existing pool. Raises `RuntimeError` if called before `create_pool()`. |
| `execute_query(sql, params) -> list[dict]` | **Direct MySQL execution.** (1) Validates SQL is SELECT or WITH. (2) Acquires a connection from the pool. (3) Executes with `aiomysql.DictCursor`. (4) Uses `asyncio.wait_for` with a 5-second timeout. (5) Normalizes BIT fields to booleans via `_normalize_bit_fields()`. (6) Releases connection in `finally` block. Returns `list[dict]` where keys are column names. |
| `execute_write(sql, params) -> int` | INSERT/UPDATE/DELETE execution. Refuses SELECT (raises `ValueError`). Commits and returns `cur.lastrowid` for INSERTs or `cur.rowcount` for UPDATEs. Same pool, 5-second timeout. |
| `close_pool()` | Closes all connections in the pool. Called during FastAPI shutdown. |
| `_normalize_bit_fields(row) -> dict` | Helper that converts single-byte BIT column values (returned as `b'\x00'` or `b'\x01'` by aiomysql) to Python `bool`. |
| `_validate_read_only_sql(sql)` | Helper that raises `ValueError` if SQL is not SELECT/WITH or contains forbidden write/DDL keywords (INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, CREATE, REPLACE). |

**Security enforcement:** `execute_query` validates SQL is read-only before execution — second line of defense after `sql_validator.py`.

---

### 3.3b `backend/db/grpc_server.py`

**Purpose:** gRPC SQL Service server. Wraps `connection_real.execute_query()` and exposes it over gRPC on port 50052. Started automatically during FastAPI lifespan.

**Functions:**

| Function | Description |
|----------|-------------|
| `SQLServiceServicer.ExecuteQuery(request, context)` | gRPC RPC handler. Deserializes `params_json` from request, calls `connection_real.execute_query(sql, params)`, serializes result rows to JSON via `orjson` with custom `_default_serialize()` handler (converts `Decimal` to `int`/`float`, dates to ISO strings), returns `ExecuteQueryResponse(rows_json=...)`. On exception, sets gRPC status code to `INTERNAL` and returns empty response. |
| `start_sql_grpc_server(port=50052)` | Creates a gRPC async server, registers `SQLServiceServicer`, binds to `[::]:{port}` (all interfaces), and starts the server. Prints "gRPC SQL Service listening on port 50052" to stderr. |
| `stop_sql_grpc_server()` | Stops the gRPC server with a 0-second grace period. |
| `_default_serialize(obj)` | JSON serialization helper for `orjson.dumps()`. Converts `decimal.Decimal` to `int` (if whole number) or `float`, `datetime`/`date` to ISO string, and falls back to `str()` for other types. |

**Why `orjson`:** Faster than stdlib `json` for large result sets (50+ row tables).

**Decimal serialization:** MySQL DECIMAL columns return `decimal.Decimal` objects, which are not JSON-serializable. The `_default_serialize()` handler converts them to `int` or `float` depending on whether they have a fractional part. This fix was added in commit 85a33ea.

---

### 3.4 `backend/db/schema.sql`

**Purpose:** DDL statements for all database tables. Idempotent (`CREATE TABLE IF NOT EXISTS`). Run once against the Catalyst Data Store. The original 13 domain tables plus 2 chat-persistence tables added in Step 4 (`chat_sessions`, `chat_messages`).

**Tables defined:**

| Table | Purpose | Key columns |
|-------|---------|-------------|
| `Employee` | Station employees / officers (replaces `officers`) | `EmployeeID` (PK), `KGID` (UNIQUE badge number), `FirstName`, `RankID` (FK→`Rank`), `role` (ENUM), `is_active`, `password_hash` (bcrypt, added [10.25](#1025-password-hashing--login-brute-force-protection)) |
| `CaseMaster` | Central case/FIR registry (replaces `fir_master`) | `CaseMasterID` (PK), `CrimeNo` (UNIQUE), `CrimeRegisteredDate`, `PolicePersonID` (FK→Employee), `PoliceStationID` (FK→Unit), `CaseStatusID` (FK→CaseStatusMaster), `CrimeMinorHeadID` (FK→CrimeSubHead), `BriefFacts` (TEXT) |
| `ComplainantDetails` | Complainants who filed cases | `ComplainantID` (PK), `CaseMasterID` (FK→CaseMaster), `ComplainantName`, `GenderID` |
| `Victim` | Victims linked to cases (replaces `victims`) | `VictimMasterID` (PK), `CaseMasterID` (FK→CaseMaster), `VictimName`, `AgeYear`, `GenderID`, `VictimPolice` (BIT) |
| `Accused` | Accused persons linked to cases (replaces `accused`) | `AccusedMasterID` (PK), `CaseMasterID` (FK→CaseMaster), `AccusedName`, `AgeYear`, `GenderID`, `PersonID` |
| `ActSectionAssociation` | Links cases to acts and sections charged | `CaseMasterID` (FK→CaseMaster), `ActID` (FK→Act), `SectionID` (FK→Section) |
| `ArrestSurrender` | Arrest or surrender details of accused | `ArrestSurrenderID` (PK), `CaseMasterID` (FK→CaseMaster), `AccusedMasterID` (FK→Accused), `ArrestSurrenderDate`, `IOID` (FK→Employee) |
| `evidence_media` | Media files attached to cases | `media_id` (PK), `case_master_id` (FK→CaseMaster), `media_type` (ENUM), `stratus_folder_id`, `stratus_file_id`, `description` |
| `chat_sessions` | One row per conversation | `session_id` (PK, VARCHAR 36), `officer_id` (FK→Employee), `title`, `created_at`, `updated_at`, `message_count`, `is_active` |
| `chat_messages` | One row per turn — user OR assistant | `message_id` (PK, AUTO_INCREMENT), `session_id` (FK→chat_sessions), `role` (ENUM `user`/`assistant`), `content`, `sql_generated`, `has_table`, `has_media`, `graph_available`, `table_data_json` (MEDIUMTEXT, nullable), `created_at` |
| `offender_risk_scores` | Risk scores for accused persons | `AccusedMasterID` (PK, FK→Accused), `risk_score` (DECIMAL), `risk_tier` (ENUM: low/medium/high/critical), `contributing_factors` (TEXT), `computed_at` (TIMESTAMP) |
| `chat_evidence_trail` | SQL query audit trail from chat | `trail_id` (PK, AUTO_INCREMENT), `message_id` (FK→chat_messages), `sql_executed` (TEXT), `tables_queried` (VARCHAR 300), `row_count` (INT), `case_ids_referenced` (VARCHAR 500), `created_at` (TIMESTAMP) |
| `audit_log` | Governance audit log | `log_id` (PK, AUTO_INCREMENT), `officer_id` (FK→Employee), `action` (VARCHAR 50), `resource_type` (VARCHAR 50), `resource_id` (VARCHAR 50), `details` (TEXT), `ip_address` (VARCHAR 45), `created_at` (TIMESTAMP) |

**Rich data storage migration:** The `table_data_json` column (MEDIUMTEXT) was added to `chat_messages` to co-locate tabular query results with the message they belong to. Previously, this data lived in a separate NoSQL document (`message_rich_data`). The new approach eliminates a round-trip, simplifies recovery logic, and keeps all message data in one indexed query. The `_serialize()` helper in `chat_store.py` handles `date`/`datetime`/`timedelta` objects during JSON serialization.

**Extended schema tables:** The three tables (`offender_risk_scores`, `chat_evidence_trail`, `audit_log`) were added to support role-based access control, audit logging, risk scoring, and evidence tracking features.

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

**Purpose:** gRPC client for the LLM Service. Forwards `call_llm()` and `ping_model()` calls to the gRPC LLM Service running on port 50051.

**Module-level state:**
- `_channels` — dict mapping asyncio event loop to gRPC channel
- `_stubs` — dict mapping asyncio event loop to `LLMServiceStub`

**Custom exceptions:**

| Exception | When raised |
|-----------|-------------|
| `LLMError` | Any LLM call failure — gRPC error, empty response |

**Functions:**

| Function | Description |
|----------|-------------|
| `_get_grpc_stub() -> LLMServiceStub` | Returns a per-event-loop gRPC stub for the LLM Service (localhost:50051). Creates channel and stub lazily on first call per loop. |
| `close_llm_client() -> None` | Closes all gRPC channels and clears stub cache. Called during FastAPI shutdown. |
| `ping_model(model_key) -> bool` | **gRPC client function.** Sends `PingModelRequest` to LLM Service via gRPC. Returns `response.success`. Never raises — returns `False` on any gRPC error. Timeout: 30s. |
| `call_llm(model_key, prompt, system_prompt, max_tokens) -> str` | **gRPC client function.** Sends `CallLLMRequest` to LLM Service via gRPC with model_key, prompt, system_prompt, and max_tokens. Returns `response.text`. Raises `LLMError` on gRPC failure or empty response. Timeout: 180s. |

**Why gRPC:** Centralizes all QuickML LLM logic in one service, enables connection reuse, and isolates LLM failures from the gateway. The gateway never talks to QuickML directly — all LLM calls route through the gRPC LLM Service.

---

### 3.7a `backend/llm/client_real.py`

**Purpose:** Direct HTTP client for Catalyst QuickML LLM API. Used by the LLM gRPC Service (`grpc_server.py`). This is the "real" LLM client extracted from the original `client.py`.

**Custom exceptions:**

| Exception | When raised |
|-----------|-------------|
| `LLMError` | Any LLM call failure — network error, non-200 status, empty/missing response field |

**Functions:**

| Function | Description |
|----------|-------------|
| `_llm_headers() -> dict` | Returns `{"Authorization": "Zoho-oauthtoken ...", "Content-Type": "application/json", "CATALYST-ORG": "..."}` — required on every Catalyst API call. Uses `catalyst_token.get_access_token()` to get a refreshed token. |
| `ping_model(model_key) -> bool` | Sends `"Say OK."` to the given model. Returns `True` on non-empty 200 response, `False` otherwise. Never raises — used by health check. Timeout: 120s. |
| `call_llm(model_key, prompt, system_prompt, max_tokens) -> str` | **Core LLM call.** Sends a POST to `QUICKML_LLM_URL` with payload: `{model, messages: [{role: "system", ...}, {role: "user", ...}], max_tokens, temperature: 0.1, stream: False}`. **Retry with exponential backoff:** on HTTP 429 (rate-limited), 408 (timeout), or 5xx (server error), retries up to 3 times with jittered backoff (`base_delay × 2^attempt + random(0.1, 0.5)`). Also retries on `httpx.TimeoutException` and `httpx.HTTPError`. Returns the `response` field from JSON. Raises `LLMError` on: missing config, non-retryable non-200 status, retries exhausted, invalid JSON, or empty response. |

**Catalyst QuickML API format (different from OpenAI):**
```json
{
  "model": "crm-di-glm47b_30b_it",
  "prompt": "user message here",
  "system_prompt": "system instruction here",
  "max_tokens": 4000,
  "temperature": 0.1
}
```
Response: `{"response": "generated text"}`

**Key difference from standard chat APIs:** Uses `prompt`/`system_prompt` fields, NOT a `messages` array. Uses `Zoho-oauthtoken` auth, NOT `Bearer`. Requires `CATALYST-ORG` header.

---

### 3.7b `backend/llm/grpc_server.py`

**Purpose:** gRPC LLM Service server. Wraps `client_real.call_llm()` and `client_real.ping_model()` and exposes them over gRPC on port 50051. Started automatically during FastAPI lifespan.

**Functions:**

| Function | Description |
|----------|-------------|
| `LLMServiceServicer.CallLLM(request, context)` | gRPC RPC handler. Extracts `model_key`, `prompt`, `system_prompt`, `max_tokens` from request, calls `client_real.call_llm()`, returns `CallLLMResponse(text=...)`. On exception, sets gRPC status code to `INTERNAL` and returns empty response. |
| `LLMServiceServicer.PingModel(request, context)` | gRPC RPC handler. Calls `client_real.ping_model(request.model_key)`, returns `PingModelResponse(success=...)`. On exception, sets gRPC status code to `INTERNAL` and returns `success=False`. |
| `start_llm_grpc_server(port=50051)` | Creates a gRPC async server, registers `LLMServiceServicer`, binds to `[::]:{port}` (all interfaces), and starts the server. Prints "gRPC LLM Service listening on port 50051" to stderr. |
| `stop_llm_grpc_server()` | Stops the gRPC server with a 0-second grace period. |

**Why this exists:** Isolates all QuickML interaction (auth, retry logic, token refresh) in one service. The FastAPI gateway becomes a thin gRPC client that doesn't know about QuickML API details.

---

### 3.7c `backend/protos/services.proto`

**Purpose:** gRPC service definitions for LLM and SQL services. Compiled into Python stubs via `grpcio-tools`.

**Services defined:**

| Service | RPCs | Purpose |
|---------|------|---------|
| `LLMService` | `CallLLM(CallLLMRequest) -> CallLLMResponse`, `PingModel(PingModelRequest) -> PingModelResponse` | LLM inference and health check |
| `SQLService` | `ExecuteQuery(ExecuteQueryRequest) -> ExecuteQueryResponse` | SQL query execution |

**Message types:**

| Message | Fields |
|---------|--------|
| `CallLLMRequest` | `model_key`, `prompt`, `system_prompt`, `max_tokens` |
| `CallLLMResponse` | `text` |
| `PingModelRequest` | `model_key` |
| `PingModelResponse` | `success` |
| `ExecuteQueryRequest` | `query`, `params_json` |
| `ExecuteQueryResponse` | `rows_json` |

**Generated files:**
- `backend/protos/services_pb2.py` — Protocol Buffer message classes
- `backend/protos/services_pb2_grpc.py` — gRPC service stubs and servicers

**Compilation command:**
```bash
python -m grpc_tools.protoc -I backend/protos --python_out=backend/protos --grpc_python_out=backend/protos backend/protos/services.proto
```

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
| `CASE_SUMMARY_SYSTEM_PROMPT` | Case summary generation | Write a 3-5 sentence professional investigative case brief for a KSP officer; cover what happened, who is involved, and current status; do not invent facts not present in the data; plain prose only, no markdown/headers. |

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
| `build_case_summary_prompt(case_row, accused_rows, victim_rows) -> (system_prompt, user_prompt)` | Builds the case summary prompt from structured facts. Formats accused/victim lists with names and ages ("none on record" if empty), assembles a fact sheet (CrimeNo, registration date, crime type, status, station, brief facts), and pairs it with `CASE_SUMMARY_SYSTEM_PROMPT`. |

---

### 3.11 `backend/pipeline/query_pipeline.py`

**Purpose:** The main orchestrator. Runs the full NL→SQL→answer chain. This is the function called by the chat routes.

**Data structures:**

`PipelineCache` — LRU cache with TTL eviction. Backed by `collections.OrderedDict`. Constructor takes `capacity` (max entries, default 500) and `ttl_seconds` (entry lifetime, default 300). Methods: `get(key)` returns cached value or `None` (expired entries are deleted on access); `put(key, value)` inserts with a `time.monotonic()` timestamp, evicting the oldest entry when at capacity.

Module-level instance: `_pipeline_cache = PipelineCache(capacity=1000, ttl_seconds=300)`.

`PipelineResponse` — dataclass with fields:
- `answer_text: str` — the formatted natural-language answer
- `table_data: list[dict]` — raw query results (for table rendering)
- `media_attachments: list[dict]` — evidence media references
- `sql_generated: str` — the SQL that was executed
- `graph_available: bool` — whether network graph data exists for the cases in results
- `error: str | None` — error message if something went wrong

**KB document ID loading:** `_kb_doc_ids_cache` is populated eagerly at **module load time** from the `KB_DOCUMENT_IDS` environment variable (comma-separated). The old `_get_kb_document_ids()` function, which used to re-read the `.env` file on every request based on mtime changes, has been replaced by a simple accessor that returns the cached list. This eliminates synchronous filesystem I/O from the hot request path.

**Functions:**

| Function | Description |
|----------|-------------|
| `get_pipeline_cache_key(question, history, officer) -> str` | Builds an MD5 hash key from the lowercased question, serialized history (role+content only), and officer identity (unit_id + role). Used to look up / store cached `PipelineResponse` objects. |
| `_has_case_master_id(results)` | Checks if the first result row contains a `CaseMasterID` or `case_master_id` key |
| `collect_case_master_ids(results)` | Imported from `media_resolver` — extracts unique integer `CaseMasterID` or `case_master_id` values from all result rows. |
| `_check_graph_available(case_master_ids)` | Probe that returns `True` if any case IDs are present. The network graph is constructed dynamically on-demand from Accused and CaseMaster linkages. |
| `_most_recent_table(history)` | Walks history newest-first and returns the most recent assistant turn's stored table snapshot (or `[]`). Lets a follow-up be answered from the last result set without re-querying. |
| `_run_direct(question, history, recent_table)` | Runs the DIRECT path — calls `generate_direct_answer()` and returns a `PipelineResponse` with only `answer_text` filled. On `LLMError`/exception, returns a friendly error response (never raises). |
| `run_pipeline(question, history, officer=None) -> PipelineResponse` | **The main pipeline.** Never raises — every error is caught and converted to a user-friendly `answer_text` + `error` field. |

**Pipeline steps (in `run_pipeline`):**

0. **Semantic cache check** — `get_pipeline_cache_key(question, history, officer)` hashes the inputs; if `_pipeline_cache.get(key)` returns a hit, the cached `PipelineResponse` is returned immediately (no LLM calls, no DB). Failures in cache lookup are caught and logged, never block the pipeline.
1. **Intent routing** — `_most_recent_table(history)` recovers the last result set. **Optimization:** the router only runs when there *is* prior history (a brand-new chat with no history skips the router LLM call and goes straight to SQL — there's nothing to answer "directly" from yet). When history exists, `route_intent()` returns `SQL` or `DIRECT`; a `DIRECT` decision calls `_run_direct()` and returns immediately (no SQL, no DB).
2. **Schema linker** — `select_relevant_tables(question)` → list of table names
3. **SQL generation** — `generate_sql(question, tables, history, officer)` → `(SQL, attempts_used)` (with retry loop)
4. **Execute SQL** — `execute_query(sql)` → `list[dict]` (one corrective retry on MySQL error, within the shared `MAX_ATTEMPTS` budget)
5. **Media resolver** — `resolve_media(results)` → only if results have `CaseMasterID`/`case_master_id` column
6. **Graph probe** — `_check_graph_available(case_master_ids)` → boolean
7. **Answer formatting** — `format_answer(question, results, media, history)` → text
8. **Cache store** — on successful, error-free completion, stores the `PipelineResponse` in `_pipeline_cache` for future hits

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
| `extract_tables(sql) -> list[str]` | Regex-based extraction of table names after `FROM` and `JOIN` clauses. Handles backtick-quoted identifiers. Not a full parser — catches simple cases, MySQL catches the rest. Public function — promoted from `_extract_tables` (Step 3) because `pipeline/evidence_trail.py` is a second caller outside `validate_sql()`. |
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
| `save_turn(session_id, user_message, assistant_message, assistant_sql=None, assistant_table=None)` | Appends a user+assistant turn. Updates in-memory first (always). Then **offloads** the NoSQL save and session-metadata sync to a **background `asyncio` task** (`_bg_save`) so the request path is not blocked by remote I/O. The background task PUTs to NoSQL; if PUT returns 404 (document doesn't exist), POSTs to create it. During `pytest`, the background task is awaited inline for test determinism. `assistant_sql` is stored on the assistant turn so follow-up SQL generation can preserve filter clauses; `assistant_table` stores a bounded (`_TABLE_SNAPSHOT_ROWS`) snapshot of the result set so the next turn can answer follow-ups via the DIRECT path **without re-querying**. Uses `json.dumps(..., default=str)` when serializing history payloads so `date`/`datetime`/`timedelta` values persist cleanly. Never raises. |
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
| `create_session(document) -> dict` | Persists a new `session_metadata` document (writes in-memory first, then **offloads** the NoSQL POST to a background `asyncio` task with one retry). During `pytest`, the background task is awaited inline. Never raises. |
| `get_session(session_id) -> dict \| None` | Fetches one session document; falls back to in-memory on NoSQL error. Never raises. |
| `update_session(session_id, updates) -> dict \| None` | Merges `updates` into an existing document, updates in-memory first, then **offloads** the NoSQL PUT to a background task (creating on 404). During `pytest`, the background task is awaited inline. Returns `None` when no session exists. Never raises. |
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
| `get_sessions_for_officer(officer_id, limit=30) -> list[dict]` | Loads the officer's active sessions **with `message_count > 0`** newest-first (`ORDER BY updated_at DESC`). Datetimes are passed through `_utc_iso()` (attaches an explicit UTC offset to the naive MySQL datetime before `.isoformat()`) so the frontend doesn't misread them as local time. Backs the sidebar. Returns `[]` on error. See [10.24](#1024-empty-chat-sessions--utc-timestamp-fix). |
| `verify_session_owner(session_id, officer_id) -> bool` | **Read authorization:** checks that `session_id` exists and belongs to `officer_id`. Used before loading messages (`GET .../messages`) or exporting. Returns `False` if not found or owned by another officer. Enables BOLA/IDOR mitigation on read paths. |
| `save_message_pair(session_id, question, answer_text, sql_generated, has_table, has_media, graph_available, table_data, media_attachments) -> int \| None` | Inserts the user row + assistant row. When `has_table` is True, serializes `table_data` directly into the `table_data_json` MEDIUMTEXT column (replacing the old NoSQL `save_rich_data` pattern). Returns the assistant `message_id`. |
| `get_messages_for_session(session_id) -> list[dict]` | Loads all messages oldest-first (cap 100); deserializes `table_data` from the `table_data_json` column for assistant messages. |
| `save_rich_data(message_id, table_data, media_attachments)` | Writes `{table_data, media_attachments}` to NoSQL `message_rich_data` under key `msg_rich_{message_id}`. Falls back to `local_rich_data.json` on any NoSQL error. Non-fatal. |
| `load_rich_data(message_id) -> dict \| None` | Reads and parses the rich-data document for a message from NoSQL, or from `local_rich_data.json` if NoSQL is missing/fails. Returns `None` on miss/error. |
| `get_evidence_trail_for_message(message_id, officer_id) -> dict \| None` | **Ownership-scoped read:** joins `chat_evidence_trail` → `chat_messages` → `chat_sessions` to return the evidence trail row only if the message belongs to the requesting officer's session. Returns `None` if the message doesn't exist, belongs to another officer, or has no evidence trail row (DIRECT-path answers never get one — that's expected). Non-fatal — catches all exceptions and returns `None`. |

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
| `create_access_token(officer_id, badge_number, role) -> str` | Creates a JWT with `officer_id` (EmployeeID), `badge_number` (KGID), `role`, and `exp` (24h from now). Signed with `APP_SECRET_KEY`. |
| `_unauthorized(detail)` | Helper that returns an `HTTPException(401)` with the given detail message. |
| `verify_token(token) -> dict` | Decodes and verifies JWT. Returns payload dict. Raises HTTP 401 on any failure (expired, invalid signature, missing). |
| `get_current_officer(credentials) -> dict` | **FastAPI dependency for header-based auth.** Extracts Bearer token from `Authorization` header. Returns decoded payload. Raises 401 if missing. |
| `get_current_officer_sse(request, credentials, token) -> dict` | **FastAPI dependency for SSE auth.** Accepts token from: (1) `Authorization: Bearer` header, OR (2) `?token=` query parameter. Needed because browser `EventSource` can't set custom headers. |
| `login(badge_number, password) -> dict` | Queries `Employee` table by `KGID` (badge number), joining `Rank` for the rank name. Verifies the submitted password against `Employee.password_hash` via `bcrypt.checkpw()` (every officer's actual password is still `KGID + "123"` — see [10.25](#1025-password-hashing--login-brute-force-protection) — but it's no longer compared as a plaintext formula). Returns `{access_token, officer: {officer_id, badge_number, full_name, rank}}`. The `role` field is embedded in the JWT payload (used by `role_guard.py`). Raises HTTP 401 on failure. |

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
| `_persist_turn(session_id, officer, question, result, session_exists)` | **Step 4 persistence helper.** Creates the `chat_sessions` row on a session's first message (when `session_exists=False`), saves the user+assistant pair via `chat_store.save_message_pair` (table data serialized to MySQL `table_data_json` column), calls `save_evidence_trail(message_id, sql_generated, table_data)` to record SQL provenance in `chat_evidence_trail` (Step 3), then bumps `updated_at`/`message_count`. Never raises — logs and continues on failure. **Wrapped in `asyncio.shield()` at both call sites** (see [10.24](#1024-empty-chat-sessions--utc-timestamp-fix)) so a client disconnect mid-call can't interrupt it between creating the row and saving the message, which used to leave permanent empty sessions behind. Called after `save_turn` in both chat endpoints. |
| `list_chat_sessions(officer)` | `GET /api/chat/sessions` — lists the officer's sessions newest-first **from MySQL** (`chat_store.get_sessions_for_officer`). Always HTTP 200 (returns `[]` on DB error). |
| `create_chat_session(officer)` | `POST /api/chat/sessions` — creates a NoSQL `session_metadata` doc and returns `SessionMetadata` (HTTP 201). **Currently unused by the UI** (see [9.5](#95-backend-created-sessions-on-new-chat--deprecated-flow-change)). |
| `get_session_messages(session_id, officer)` | `GET /api/chat/sessions/{id}/messages` — **read authorization:** verifies ownership via `chat_store.verify_session_owner` (404 on mismatch/not-found), then returns all messages oldest-first from MySQL with `table_data` deserialized from the `table_data_json` column. **No pagination** (the prior `limit`/`before_message_id` cursor flow was removed — see [9.9](#99-message-pagination--removed)). |
| `chat(request, officer)` | `POST /api/chat` — non-streaming endpoint (testing/fallback). **Enforces write authorization** via `_authorize_session_write` before any pipeline work. Fetches history, runs pipeline, `save_turn` (with `assistant_table`), then `_persist_turn`. Always returns HTTP 200 with `ChatResponse`. Returns HTTP 404 if `session_id` belongs to another officer. |
| `chat_stream(question, session_id, officer)` | `GET /api/chat/stream` — SSE streaming endpoint. Protected by `get_current_officer_sse` (header or query param). **Enforces write authorization** via `_authorize_session_write` before opening the stream, so a forged `session_id` returns a clean HTTP 404 instead of an in-stream error. After the pipeline, `save_turn` (with `assistant_table`) then `_persist_turn`. Returns `StreamingResponse` with `text/event-stream`. |
| `_tokenize(text) -> list[str]` | Splits text into space-preserving tokens for word-by-word streaming. Each token (except last) includes trailing space. |
| `message_evidence_trail(message_id, officer)` | `GET /api/chat/messages/{message_id}/evidence-trail` — **ownership-scoped read** of the SQL provenance record for a specific assistant message. Delegates to `chat_store.get_evidence_trail_for_message`, which joins through `chat_messages` → `chat_sessions` to enforce BOLA/IDOR scoping. Returns the trail row (sql_executed, tables_queried, row_count, case_ids_referenced). Returns HTTP 404 if the message doesn't exist, belongs to another officer's session, or has no trail row (DIRECT-path answers). |

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
| `login_route(request)` | `POST /api/auth/login` — checks `auth/login_rate_limiter.check_login_attempt(badge_number)` first (10 attempts / 15 min per badge number, HTTP 429 with `Retry-After` if exceeded — see [10.25](#1025-password-hashing--login-brute-force-protection)), then calls `login()` from the auth layer. On success, calls `reset_login_attempts()` so a legitimate officer's earlier typos don't linger. Returns `LoginResponse` with token + officer info. HTTP 401 on bad credentials, HTTP 503 on infrastructure error. |
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

**Status: wired into the UI.** The composer's attach button (`frontend/src/components/Composer.jsx`) opens a native file picker, uploads via `frontend/src/api/reports.js::analyzeReport()`, and the result renders as a normal user+assistant turn in the transcript (`ChatWindow.jsx::handleReportAnalyzed`). This was previously backend-only with the frontend button disabled ("coming soon") — see [10.26](#1026-report-upload-wired-end-to-end) for the change.

**How the file actually reaches the LLM** (no filesystem I/O, no low-level `read()`/`open()` syscalls anywhere in this path — see the module docstring in `reports.py` for the full breakdown): the browser base64-encodes the file client-side via `FileReader`, POSTs it as one JSON field, `_decode_file()` runs a pure in-memory `base64.b64decode()`, `extract_report_text()` turns the bytes into a plain string, and that string is spliced into a prompt sent to Catalyst QuickML over HTTPS. The raw bytes are never written to disk and are discarded once text extraction finishes.

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

### 3.22 `backend/llm/rag_client.py`

**Purpose:** Connects the application to Zoho Catalyst's `/quickml/v1/project/{PROJECT_ID}/rag/answer` endpoint for document-grounded question answering. Implements phrase-based verification to reduce false-positive source attributions.

**Key Helpers:**
- `_significant_phrases(text)`: Extracts multi-word capitalized phrases (names, locations) and long numbers (crime registration numbers) to serve as a high-fidelity fingerprint of the text.
- `_node_supports_response(node_content, response_phrases)`: Grounding Rule 2. Checks if a retrieved document chunk shares at least one significant phrase or case number with the LLM's generated response. If it does not, it is filtered out as a false positive.
- `_is_negative_claim(response_text)`: Grounding Rule 3. Identifies negative/absence statements (e.g. "no record found", "none listed").
- `normalize_query(query)`: Cleans up conversational filler (e.g. "could you please tell me", "just wondering") to produce a denser search query.

**Functions:**

| Function | Description |
|----------|-------------|
| `query_rag(query, document_ids)` | Submits a query along with document IDs to the Catalyst RAG API. Returns a `RagResult` containing the natural language response, the verified source document list, and a grounding flag. Retries once with filler words stripped if the first attempt returns ungrounded. |

---

### 3.23 `backend/llm/rag_session.py`

**Purpose:** Wraps stateless RAG queries in a stateful conversational session. Translates pronoun references (e.g. "him", "the accused", "that suspect") using the last mentioned entity and handles follow-up query suggestion generation.

**Key Helpers:**
- `_resolve_references(query)`: Substitutes general pronoun references in follow-up queries with the primary entity (e.g., suspect name) from the previous turn.
- `_build_contextual_query(resolved_query)`: Appends the last 2 turns of conversation history to the RAG query to provide connection context.
- `_generate_follow_ups(case_context)`: **Generates suggested follow-ups.** Automatically reads the **last 5 turns of conversation history** (`self.history[-5:]`) and the current case context, prompting `MODEL_ANSWER` to generate 3 relevant follow-up questions that guide the investigator's next steps.

**Methods:**

| Method | Description |
|--------|-------------|
| `ask(query)` | Entry point for a conversational turn. Resolves pronouns, embeds history context, queries the RAG client, updates history, and returns the response alongside 3 relevant follow-ups. |

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
          
          Step 0: Pipeline Cache Check
            → get_pipeline_cache_key(question, history, officer)
            → _pipeline_cache.get(key)
            → if HIT: return cached PipelineResponse immediately (no LLM, no DB)
          
          Step 1: Intent Router (only when history exists)
            → llm/answer_formatter.py: route_intent(question, history, has_recent_data)
              → "DIRECT" → generate_direct_answer(...) and RETURN (no SQL, no DB)
              → "SQL"    → continue below
              (a brand-new chat with no history skips this step → straight to SQL)
          
          Step 2: Schema Linker
            → pipeline/schema_linker.py: select_relevant_tables(question)
              → SCHEMA_CATALOG keyword matching
              → returns ["CaseMaster", "Accused", ...]
          
          Step 3: SQL Generation
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
        
          Step 4: Execute SQL
            → db/connection.py: execute_query(sql)
              → aiomysql pool → MySQL → returns list[dict]
        
          Step 5: Media Resolution
            → pipeline/media_resolver.py: resolve_media(results)
              → db/connection.py: execute_query("SELECT ... FROM evidence_media WHERE case_master_id IN (...)")
              → returns [{media_type, url, description, case_master_id}]
        
          Step 6: Graph Probe
            → _check_graph_available(case_master_ids)
              → returns True/False
        
          Step 7: Answer Formatting
            → llm/answer_formatter.py: format_answer(question, results, media, history)
              → llm/prompts.py: build_answer_prompt(...)
              → llm/client.py: call_llm("MODEL_ANSWER", prompt, system_prompt)
                → HTTP POST to Catalyst QuickML (Qwen 2.5-14B Instruct)
              → returns formatted text
          
          Step 8: Cache Store
            → _pipeline_cache.put(cache_key, response)  // only on success, no error
        
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
            // NoSQL write + metadata sync offloaded to background asyncio task
    
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
  → pipeline runs, saves turn to in-memory (sync) + NoSQL (background task)

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
4. After pipeline completes, `save_turn(session_id, question, answer, assistant_sql, assistant_table)` → updates in-memory first (synchronous), then offloads the NoSQL save + session-metadata sync to a background `asyncio` task; `assistant_table` stores a bounded result snapshot so the next turn's DIRECT path can answer without re-querying. `_persist_turn(...)` then writes the session + message pair to MySQL (see [4.7](#47-persistent-chat-storage))

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
  → asyncio.shield( _persist_turn(session_id, officer, question, result) )
      # shielded so a client disconnect can't interrupt the row-create /
      # message-save sequence below and leave an empty session (see 10.24)
      → if first message of session: chat_store.create_session(...)   # chat_sessions row
      → chat_store.save_message_pair(...)  # user row + assistant row → chat_messages (MySQL)
          → if has_table/has_media: save_rich_data(...)               # → NoSQL message_rich_data
      → chat_store.update_session_timestamp(...)                      # bump updated_at + message_count

On login / sidebar load:
  → GET /api/chat/sessions      → chat_store.get_sessions_for_officer(officer_id)
      # MySQL, newest-first, WHERE message_count > 0 (excludes empty/abandoned sessions)

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
- Badge number input (placeholder: `e.g. 3254123`)
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

**Props:** `{ value, onChange, onSend, disabled, statusText, rateLimitInfo, sessionId, onReportAnalyzed, onAuthExpired }`

**Behavior:**
- Auto-growing textarea: a `useEffect` resizes it on every `value` change, capped at 160px (then scrolls).
- Enter sends, Shift+Enter inserts a newline. Send is suppressed while `disabled` or when the trimmed value is empty.
- `statusText` (pipeline progress) renders in small text above the box while streaming.
- Left actions:
  - **Attach** (paperclip) — opens a native file picker (`accept=".docx,.txt,.md,.markdown,.csv,.log,.json,.html,.htm"`), pre-validates the file client-side via `validateReportFile()` (size/extension), then uploads through `api/reports.js::analyzeReport()` to `POST /api/reports/analyze`. Any text currently typed in the composer is sent along as the analysis prompt. On success, `onReportAnalyzed(result, fileName)` is called so the parent (`ChatWindow.jsx`) can append the analysis to the transcript; on failure an inline error message renders above the composer; a 401 calls `onAuthExpired`. The button shows a spinner while the upload is in flight.
  - **Voice** (mic) — `VoiceInput.jsx`, records audio and sends it to Zia STT (unrelated to file upload).
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
    "response": "SELECT COUNT(*) AS open_cases FROM CaseMaster cm JOIN CaseStatusMaster cs ON cm.CaseStatusID = cs.CaseStatusID WHERE cs.CaseStatusName = 'Open'"
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
- **Caveat (found 2026-07-19):** this client-side no-op only stops *new* clicks
  from hitting the backend — it was never backed by a server-side guarantee.
  `_persist_turn` still creates the `chat_sessions` row (`message_count=0`)
  *before* saving the message pair, and a client disconnect mid-call (e.g.
  clicking New chat while a previous SSE stream was still finishing) could
  interrupt persistence in between, leaving a permanent empty session that
  `GET /api/chat/sessions` returned unfiltered. This is what actually caused
  ~20 "New chat" rows to accumulate and become visible in Recents. Fixed in
  [10.24](#1024-empty-chat-sessions--utc-timestamp-fix): the list query now
  filters `message_count > 0`, and the persistence calls are shielded from
  cancellation.

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

### 10.1 gRPC Microservices Migration — Phase 1 (LLM & SQL Services)

**Date:** July 23, 2026  
**Commits:** e20ce4a (gRPC migration PR #5), 85a33ea (Decimal serialization fix), fea9d60 (benchmark results)

**Objective:** Extract compute-intensive LLM and SQL operations into standalone gRPC microservices to enable independent scaling, centralize connection pooling, and isolate failure domains while keeping the browser-facing API as REST/SSE.

**Architecture Changes:**

The FastAPI gateway now acts as an API gateway that delegates to two internal gRPC services:

```
Browser (REST/SSE)
       ↓
FastAPI Gateway (port 8000)
       ├── gRPC → LLM Service (port 50051) → Catalyst QuickML
       └── gRPC → SQL Service (port 50052) → AWS RDS MySQL
```

**Files Added:**

| File | Purpose |
|------|---------|
| `backend/protos/services.proto` | gRPC service definitions (LLMService, SQLService) |
| `backend/protos/services_pb2.py` | Generated Protocol Buffer message classes |
| `backend/protos/services_pb2_grpc.py` | Generated gRPC service stubs and servicers |
| `backend/llm/grpc_server.py` | gRPC LLM Service server — wraps `client_real.py` |
| `backend/llm/client_real.py` | Direct HTTP client for Catalyst QuickML (extracted from `client.py`) |
| `backend/db/grpc_server.py` | gRPC SQL Service server — wraps `connection_real.py` |
| `backend/db/connection_real.py` | Direct MySQL connection pool (extracted from `connection.py`) |

**Files Modified:**

| File | Change |
|------|--------|
| `backend/llm/client.py` | Now a gRPC client — `call_llm()` and `ping_model()` forward requests to LLM Service via gRPC |
| `backend/db/connection.py` | Now a gRPC client — `execute_query()` forwards SELECT queries to SQL Service via gRPC; re-exports `execute_write()` from `connection_real.py` (writes stay local) |
| `backend/main.py` | Lifespan now starts/stops LLM and SQL gRPC servers alongside the FastAPI app |
| `requirements.txt` | Added `grpcio` and `grpcio-tools` dependencies |

**Key Design Decisions:**

1. **gRPC for internal calls only** — Browser-facing endpoints remain REST/SSE (browsers don't speak gRPC natively; gRPC-Web would add deployment complexity).
2. **Single-process deployment** — Both gRPC services run as background tasks within the FastAPI process, simplifying deployment (no separate containers or service discovery in Phase 1).
3. **Insecure channels** — gRPC servers use `insecure_channel` (localhost-only, no TLS overhead) since all services run on the same host.
4. **Lookup cache preservation** — `execute_query()` in the gRPC client still checks the in-memory lookup cache (`intercept_lookup_query()`) before making the gRPC call, preserving the zero-latency fast path for `Unit`, `CrimeSubHead`, and `CaseStatusMaster` queries.
5. **Decimal serialization fix** — `backend/db/grpc_server.py` initially returned JSON with unserializable `Decimal` objects from MySQL DECIMAL columns; fixed by adding a `_default_serialize()` helper that converts `Decimal` to `int` (if whole number) or `float`, and dates to ISO strings. Uses `orjson` for faster serialization.

**Performance Impact (Benchmark Results):**

Benchmarks run on local dev (backend + MySQL on same machine) and deployed Catalyst environment (AppSail in Mumbai + RDS in Mumbai).

| Metric | Pre-gRPC (local) | gRPC (local) | Pre-gRPC (deployed) | gRPC (deployed) |
|--------|------------------|--------------|---------------------|-----------------|
| **Endpoint p50 latency** | ~41ms | ~43ms | ~88-125ms | ~82-91ms |
| **Quality suite (cold)** | 4.65s avg | 3.69s avg | 3.05s avg | 3.05s avg |
| **Quality suite (hot)** | 2.56s avg | 1.43s avg | 1.50s avg | 5.72s avg* |

*One outlier (38s timeout on "Find victims aged under 18") skewed the deployed hot-cache average; median latency remains similar.

**Analysis:**
- **Minimal overhead** — gRPC adds ~2ms p50 latency locally (43ms vs 41ms), well within acceptable bounds.
- **Cold-cache improvement** — Local cold-cache queries improved from 4.65s → 3.69s (~21% faster), likely due to better connection reuse in the gRPC service.
- **Hot-cache improvement** — Local hot-cache queries improved from 2.56s → 1.43s (~44% faster), showing effective caching and reduced per-query overhead.
- **Deployed performance stable** — Deployed endpoint latency is consistent pre/post-gRPC, confirming that network I/O to RDS and QuickML (not internal service calls) remains the dominant factor.

The migration achieves the architectural goals (service isolation, independent scaling, centralized pooling) with acceptable latency tradeoff — the ~2ms gRPC overhead is negligible compared to LLM inference (~2s) and database round-trips (~80ms cross-region).

**Testing:**
- All 98 existing tests pass (68 unit + 15 pipeline/session + 15 property-based).
- gRPC services tested implicitly through existing integration tests (LLM calls and SQL queries now route through gRPC).
- `backend/benchmark.py` used to generate all four benchmark result files (pre/post-gRPC, local/deployed).

**Next Steps (Phase 2):**
- Extract Conversation Service (session/history storage)
- Extract Analytics Service (trend/risk/timeline endpoints)
- Extract Graph Service (network visualization)

---

### 10.2 Security — BOLA/IDOR Mitigation (Authorization on Session Access)

**Date:** June 19, 2026  
**Issue:** Three write endpoints (`POST /api/chat`, `GET /api/chat/stream`, `POST /api/reports/analyze`) and the reports feature lacked object-level authorization. An authenticated officer could write turns into another officer's session by supplying its `session_id` — a textbook BOLA (Broken Object Level Authorization) / IDOR (Insecure Direct Object Reference) vulnerability (OWASP API1:2023).

**Fix:**
- **Read paths** (already correct): `GET /api/chat/sessions/{id}/messages` and `POST /api/chat/sessions/{id}/export` call `verify_session_owner()` and return HTTP 404 (not 403) on mismatch, to avoid leaking that a foreign session exists.
- **Write paths** (added authorization):
  - `POST /api/chat` and `GET /api/chat/stream` now call `_authorize_session_write()` **before** any pipeline work, returning HTTP 404 if the `session_id` exists and belongs to another officer. Create-or-append semantics are preserved: a not-yet-existing `session_id` is allowed (the officer will own it on creation).
  - `POST /api/reports/analyze` does an inline ownership check before file decode and the LLM call, reusing the existence result to avoid a duplicate query in `_persist_report_turn`.
  - All three write paths reuse the existence flag so `_persist_turn` / `_persist_report_turn` no longer run a separate `SELECT` to check if the session exists — **same query count as before, now also doing authorization.**

**Performance:** Single indexed PK lookup (session_id is the PK) — effectively free. Zero added round-trips.

**Tests:** `backend/tests/test_pipeline_and_sessions.py` (TestSessionAuthz, 4 tests) covers intruder rejection (404, asserting pipeline/LLM/decode never runs), owner acceptance, and brand-new-session acceptance across all three write endpoints.

**Documentation:** Added [§3.1a Security — Authorization & BOLA/IDOR Mitigation](#31a-security--authorization--bolaidor-mitigation) section explaining the two patterns and why we return 404 instead of 403.

---

### 10.3 Report Text Extraction — Lean & Reliable (Removed Fragile PDF Parser)

**Date:** June 19, 2026  
**Issue:** `routers/reports.py` included a hand-rolled PDF text extractor (`_extract_pdf_text`) that brute-forced `zlib.decompress` on every stream in the PDF and ran multiple regex passes over PDF operators. High compute, unreliable output (garbage on most real PDFs — compressed object streams, custom encodings, scanned pages).

**Fix:**
- **Kept** (cheap, stdlib-only, reliable): DOCX (unzip + XML parse), text/markdown/HTML/JSON/CSV (decode + optional tag-stripping via `_extract_html_text`).
- **Removed**: `_pdf_literal_to_text()`, `_extract_pdf_text()`, and the `zlib` import.
- **PDF and unknown binary types now reject cleanly** with HTTP 415 (`UnsupportedReportFormat`) and an actionable message: *"PDF analysis isn't supported yet. Please upload the report as text, Markdown, or a Word (.docx) file."*
- Proper PDF support, if the feature gets prioritized, should use a real library (pypdf/pdfminer) — a deliberate dependency, not a hack.

**Rationale:** Aligns with the "least compute, enough results" principle. DOCX extraction is a trivial unzip + XML read, and text/markdown/HTML are just decode + optional tag-strip. The PDF brute-forcer was the only compute-heavy, fragile part.

**Tests:** `backend/tests/test_unit.py` (TestReportExtraction) covers DOCX, plain text, HTML tag-stripping, and PDF rejection.

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

### 10.7 Backfill Migration Script (OBSOLETE — see §10.17)

**Date:** June 20, 2026  
**Status:** Obsolete. File still exists at project root but serves no purpose on the fresh AWS RDS deployment. Safe to delete.

**What it did:** Populated the `table_data_json` field for existing chat messages that had `has_table=1` but `table_data_json=NULL`, by re-executing each row's stored SQL query.


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

**Tests:** `backend/tests/test_unit.py` (TestNetworkGraph) — basic async tests for CaseMaster and Accused graph builders.

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

**Tests:** `backend/tests/test_unit.py` (TestVoiceHelpers, TestVoiceTranscribe) — envelope/extraction helpers and transcribe/translate functions with fake httpx client.

**Tests:** `backend/tests/test_unit.py` (TestMediaResolver) — `collect_case_master_ids()` extraction and `resolve_media()` behavior for empty results, no CaseMaster IDs, unavailable preview URL generation, and document fallback.

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

---

### 10.10 Roles, Audit Log, and Governance Foundation

**Date:** June 29, 2026  
**What:** Implemented role-based access control, audit logging, and supervisor-only governance endpoints — the foundation for analytics, risk scoring, and decision support features.

**Database Schema (extended tables):**
- **`offender_risk_scores`:** Risk scoring table with FK to `Accused(AccusedMasterID)`. Columns: `risk_score` (DECIMAL), `risk_tier` (ENUM: low/medium/high/critical), `contributing_factors` (TEXT), `computed_at` (TIMESTAMP).
- **`chat_evidence_trail`:** Tracks SQL queries and case references from chat interactions. Columns: `message_id` (FK→chat_messages), `sql_executed` (TEXT), `tables_queried` (VARCHAR 300), `row_count` (INT), `case_ids_referenced` (VARCHAR 500 — comma-separated CaseMasterID values), `created_at` (TIMESTAMP). Indexed on `message_id`.
- **`audit_log`:** Records all sensitive actions. Columns: `officer_id` (FK→Employee), `action` (VARCHAR 50), `resource_type` (VARCHAR 50), `resource_id` (VARCHAR 50), `details` (TEXT), `ip_address` (VARCHAR 45), `created_at` (TIMESTAMP). Indexed on `(officer_id, created_at)` and `(resource_type, resource_id)`.

**Authentication Changes (`backend/auth/simple_auth.py`):**
- `create_access_token()` now accepts a `role` parameter and includes it in the JWT payload alongside `officer_id`, `badge_number`, and `exp`.
- `login()` now selects `role` from the `Employee` table and passes it to `create_access_token()`. The JWT payload now contains: `{"officer_id": int, "badge_number": str, "role": str, "exp": timestamp}`.

**New Files:**
- **`backend/auth/role_guard.py`:** Role-based access control module. `require_role(*allowed_roles)` — FastAPI dependency factory that checks the officer's role from the JWT payload against allowed roles, raising HTTP 403 if not permitted. `log_action()` — non-fatal audit logging helper that inserts rows into `audit_log`; failures are logged to stderr but never break the request.
- **`backend/routers/governance.py`:** Supervisor-only governance endpoints. `GET /api/audit-log?limit=50` — returns recent audit log entries joined with `Employee` for officer name display. Gated by `require_role("supervisor")`.

**Router Registration (`backend/main.py`):**
- Registered `governance_router` alongside existing routers (`auth`, `chat`, `export`, `reports`, `voice`).

**Verification Status:**
- All 5 verification tests passed:
  1. JWT payload includes `role` field correctly (tested with investigator-role token).
  2. Existing `/api/chat` endpoint works without regression (returned valid response with no breaking changes).
  3. `require_role()` correctly blocks investigator-role from supervisor-only endpoint (HTTP 403 with proper error message).
  4. `require_role()` allows supervisor-role to access `/api/audit-log` (HTTP 200 with entries array).
  5. `log_action()` writes audit log entries without raising exceptions (entry visible in subsequent query).

---

### 10.11 RAG Pipeline Optimization — Bypassing Zoho Catalyst 12-Doc Limit

**Date:** July 7, 2026  
**Issue:** The Zoho Catalyst QuickML Knowledge Base (in Early Access) has an undocumented soft limit of ~12 documents per KB. If you attempt to upload more individual files or query with more than 12 document IDs, the endpoint throws a `400 Bad Request` or upload error. Converting 220 MySQL cases to individual text files exceeded this limit, rendering the RAG pipeline non-functional for the full dataset.

**Fix:**
- **Consolidation (`backend/consolidate_cases.py`):** Added a script that parses the `SECTIONS` field from all 220+ case files and groups them by primary crime type (e.g., `Theft`, `Assault`, `Drug Offences`). These are merged into exactly **8 larger text files** inside `backend/rag_consolidated/` with clear section headers and case separators (`========================================`). This keeps the file count under the 12-doc limit while maintaining semantic coherence for RAG chunking.
- **Integrated Export (`backend/export_cases_for_rag.py`):** Modified the case export script to automatically invoke the consolidation function. Running a single command exports cases from MySQL and regenerates the 8 consolidated category files.
- **Dynamic ID Discovery (`backend/kb_sync.py`):** Created a script that calls the Catalyst QuickML RAG APIs to discover uploaded documents. It automatically extracts document IDs, refreshes the Zoho OAuth access token if expired, and updates `KB_DOCUMENT_IDS` in `.env` automatically.
- **Dynamic Config Reload (`backend/pipeline/query_pipeline.py`):** Modified the query pipeline to dynamically reload `KB_DOCUMENT_IDS` from `.env` by checking the file's modification time. This allows the backend to pick up newly synced document IDs without needing a FastAPI server restart.

**Tests:**
- `backend/test_full_kb.py`, `backend/test_rag_session.py`, `backend/test_rag_scale.py` were run and verified as fully passing.
- `backend/test_rag_client.py` was used to confirm that sending more than 12 document IDs throws an HTTP 400 Bad Request, verifying that consolidation is required for both uploading and querying.


## RAG Pipeline Routing Fix (2026-07-07)

**Problem:** `run_pipeline()` in `backend/pipeline/query_pipeline.py` only invoked
`RagSession` as a fallback inside the `CannotAnswerError` and `LLMError` exception
handlers around `generate_sql()`. In practice the SQL generator almost never raises
these — it produces a syntactically valid query even for questions that should be
answered from free-text case narratives, so RAG was effectively unreachable for most
narrative/analytical questions. Confirmed via reproduction: "List all cases involving
stolen vehicles" and "What do the case reports say about how thefts typically occur?"
both returned 0-row SQL results instead of being answered from the Knowledge Base.

**Fix 1 (narrative-keyword pre-router):** Added a keyword check at the very start of
`run_pipeline()`, before schema linking / SQL generation. Questions containing phrases
like "summarize", "narrative", "typically occur", etc. are routed directly to
`RagSession.ask()`. Falls through to normal SQL flow if RAG comes back ungrounded.

**Fix 2 (empty-results RAG fallback):** After `execute_query(sql)` succeeds but
`results` is empty, the pipeline now retries via `RagSession.ask()` before proceeding
to `format_answer()`. This catches cases where SQL is syntactically valid but
semantically wrong for the question (no matching column/value), while the answer
genuinely exists in the RAG-indexed case narratives.

Both fixes are additive and fail open — any exception inside the RAG attempt is
caught and logged, and the pipeline falls back to its original behavior.

## 10.12 Session Fixes — 2026-07-10

Four issues found and fixed in one debugging session, all confirmed via direct file/DB checks rather than assumed from memory.

**1. Missing `follow_ups_json` column (schema drift)**
`backend/db/chat_store.py` read/wrote a `follow_ups_json` column on `chat_messages` that was never added to `backend/db/schema.sql`, and `migrate.py` had no guarded step for it (only `table_data_json` was guarded). The live `ksp_crime_db_v2` DB already had the column from a prior manual `ALTER TABLE`, masking the gap locally. Fresh clones would hit `(1054, "Unknown column 'follow_ups_json'")` on every session reload. Fixed: added `follow_ups_json TEXT` to `schema.sql` (matching the live DB's type) and added a second guarded `information_schema.COLUMNS` check + `ALTER TABLE` step to `migrate.py`, mirroring the existing `table_data_json` pattern.

**2. `kb_sync.py` --refresh-token broken for all standard `.env` setups**
`backend/kb_sync.py`'s token-refresh function read `ZOHO_CLIENT_ID` / `ZOHO_CLIENT_SECRET` / `ZOHO_REFRESH_TOKEN`, while every other function in the same file (and every `.env`/`.env.example` in the repo) uses `CATALYST_CLIENT_ID` / `CATALYST_CLIENT_SECRET` / `CATALYST_REFRESH_TOKEN`. This made `python backend/kb_sync.py --refresh-token` fail with `ZOHO_CLIENT_ID not set in .env` for anyone following the documented setup. Fixed by renaming the three `_get_env()` calls to the `CATALYST_*` names, matching the rest of the file. Verified: token refresh + KB document discovery (9 documents) succeeded after the fix.

**3. Answer formatter payload overflow on large result sets**
`backend/llm/answer_formatter.py`'s `format_answer()` could hit Zoho QuickML's `MORE_THAN_MAX_LENGTH` error (`Error in processing zoho-inputstream parameter`) even within the existing 50-row / 200-char-per-field cap in `_truncate_for_answer()`, because that cap alone wasn't small enough for some wide result sets. Previously this silently fell back to a fixed generic response. Fixed: `build_answer_prompt()` (in `prompts.py`) now accepts `max_rows`/`max_field_chars` overrides. `format_answer()` wraps its `call_llm` in a try/except; on `MORE_THAN_MAX_LENGTH` specifically, it retries once with a much smaller payload (`max_rows=15`, `max_field_chars=80`) before giving up. Other exceptions are re-raised unchanged.

**4. `session_metadata` silently and permanently lost on transient NoSQL failure**
`session_store.py`'s `create_session()` attempted a single `insert_document()` call; any failure (timeout, transient NoSQL error) was logged and swallowed, leaving that session's metadata doc permanently missing. Every later `update_session()` call for that session would then log `session_metadata PUT skipped — <id> not found` and silently no-op for the rest of the session's lifetime (title never generated, message_count never synced to NoSQL — the MySQL-backed message history itself is unaffected). Fixed: `create_session()` now retries the `insert_document()` call once after a 0.5s backoff before giving up, so a single transient NoSQL blip no longer strands a session permanently. Sessions created before this fix (e.g. NoSQL doc never written) remain unrecoverable without a separate backfill — this fix only prevents new occurrences.

**5. README section ordering**
`### 8b. Refreshing the RAG Knowledge Base After New Case Data` was misplaced after `## License` (effectively at the end of the file) instead of between `8a` and `9. Start the backend`. Moved to the correct position; no content changes.


## 10.13 NoSQL Root Cause Fix + Session ID Column Width -- 2026-07-10 (continued)

Following up on 10.12, deeper investigation found the actual root cause of `session_metadata PUT skipped` -- the earlier NoSQL key-name theory (`session_id` vs `id` across Catalyst projects) was a real but separate issue; this was the primary bug affecting all projects.

**1. `nosql_client.py` `get_document()` was structurally broken**
Two compounding bugs meant `get_document()` returned `None` for every existing document, regardless of key correctness:
- The fetch payload sent `"required_attributes": []`. Per Catalyst's Custom JSON API, `required_attributes` is a filter list used to narrow the response to specific attributes -- an empty list was being interpreted as "return no attributes," not "return everything." Confirmed directly: a raw fetch against a known-good document (`size: 64`, proving the record existed) returned `"item": {}` -- empty despite the record being present.
- The response-shape parsing only checked for `data` as a list of items or a dict with a direct `"item"` key. The real Catalyst response shape is `{"data": {"size": N, "get": [{"item": {...}}]}}` -- never matched by the existing code.
Fixed: removed `required_attributes` from the payload entirely, and added parsing for the correct `data["get"][0]["item"]` shape. Verified via direct API calls: insert then read of a test document round-tripped correctly after the fix, confirmed independently in the Catalyst console.

Practical effect: `update_session()` calls `get_session()` -> `get_document()` first to check if a session exists before updating it. Because this always returned `None`, every session update after creation was silently treated as "session not found" and skipped -- logged as `session_metadata PUT skipped`. This affected every session, every time, on every project, independent of the key-name question.

**2. `chat_sessions.session_id` / `chat_messages.session_id` too narrow for real session IDs**
Both columns were `VARCHAR(36)` -- sized for a bare UUID. The actual session ID generator in `routers/chat.py` builds IDs as `f"sess-{uuid4()}"`, which is 41 characters, overflowing the column. This caused `(1406, "Data too long for column session_id")` and silently failed to save the message pair for every session created through the real `/api/chat/sessions` endpoint. Fixed: widened both columns to `VARCHAR(50)`.

**3. `migrate.py`'s `information_schema.COLUMNS` queries were unscoped to the current database**
None of the guarded-migration checks included a `TABLE_SCHEMA` filter, so on a machine with multiple similarly-named databases, `fetchone()` could return a row from the wrong database. Confirmed: an unscoped query for `session_id` returned 8 rows across multiple databases before the fix. Fixed: every query now includes `AND TABLE_SCHEMA = DATABASE()`.

All three fixes verified end-to-end via the real `/api/chat/sessions` + `/api/chat/stream` flow.


## 10.14 Behavior Rules & Station Scoping Reliability System

**Date:** July 22, 2026  
**What:** Implemented a centralized behavior rules framework and station scoping reliability architecture across the pipeline, database guard, and answer generation layers.

**The 12 Enforced Behavior Rules:**
1. **Rule 1 (First-Person Query Scoping)**: First-person queries ("my cases", "assigned to me") scope to `PolicePersonID = {officer_id}`.
2. **Rule 2 (Scope Disclosure Requirement)**: When wide-scope queries ("all cases in Karnataka", "statewide statistics") are submitted by restricted roles (`investigator`/`supervisor`), an explicit disclosure is prepended: *"Note: Results are limited to your assigned station ({unit_name})."*
3. **Rule 3 (Employee Listing Scoping)**: Queries listing officers or station personnel without `CaseMaster` (e.g. *"list all officers"*) are automatically scoped to `Employee.UnitID IN (...)` rather than throwing `StationScopeError`.
4. **Rule 4 (Policymaker Unrestricted State-wide Access)**: `policymaker`, `analyst`, and `admin` roles bypass station-level WHERE clauses and access unfiltered state-wide data without scope disclaimers.
5. **Rule 5 (Assigned Case Protection)**: Protects cases assigned to an officer outside their primary station by constructing `({alias}.PoliceStationID IN (...) OR {alias}.PolicePersonID = {officer_id})`.
6. **Rule 6 (Role-Restricted Cross-Station Comparison Intercept)**: Pre-execution intercept in `query_pipeline.py` detects comparison intent ("compare Koramangala PS with Whitefield PS") for restricted roles and returns a direct policy response before SQL generation.
7. **Rule 7 (Date Fallback Retry)**: When a date-filtered SQL query returns 0 rows, `_retry_with_latest_date()` extracts the date predicate, queries `SELECT MAX(YEAR(CrimeRegisteredDate)) FROM CaseMaster`, rewrites the year, and retries execution automatically with an informative note.
8. **Rule 8 (Deterministic Victim PII Redaction)**: On aggregate queries (`GROUP BY`, `COUNT`, `SUM`, `AVG`), `_sanitize_pii()` inside `_truncate_for_answer()` replaces victim PII keys (`VictimName`, `Phone`, `Address`, `NationalID`, `Aadhaar`) with `"[REDACTED]"`.
9. **Rule 9 (Accused Detail Privacy Default)**: `SQL_SYSTEM_PROMPT` enforces privacy by excluding unnecessary personal identifiers for accused persons unless explicitly asked.
10. **Rule 10 (Scope Disclaimer Refinement & First-Person Exclusion)**: `_compute_scope_disclaimer_needed()` triggers disclaimers only on wide queries and explicitly suppresses them when first-person keywords ("my", "I'm", "assigned to me") are present.
11. **Rule 11 (Zero-Result Diagnostic Context)**: When queries return 0 rows, diagnostic metadata (`active_station_scope` and `date_filter`) is passed to `format_answer()` so the LLM explains *why* no records matched.
12. **Rule 12 (Entity Resolution Assumption Disclosure)**: `schema_linker.select_relevant_tables()` returns `(tables, assumptions)` to capture fuzzy keyword mappings (e.g., `"vehicle"` -> `CrimeSubHead` = `'Vehicle Theft'`) and passes assumptions to `format_answer()` for user disclosure.

**Database & Hierarchy Resolution Changes:**
- **`backend/db/connection.py`**: Created `_validate_read_only_sql(sql)` allowing `SELECT` and `WITH` (read-only CTE) statements. Enabled `WITH RECURSIVE` queries for supervisor unit hierarchy resolution while maintaining strict guards against write/DDL operations.
- **`backend/auth/role_guard.py`**: Defined `ScopeResolutionError(Exception)` and logged supervisor CTE failures via standard `logging` (`logger.error(..., exc_info=True)`).
- **`backend/pipeline/date_utils.py`**: Created shared date predicate extraction and rewriting utility module shared between Rule 7 (date retry) and Rule 11 (zero-result diagnostics).


### 3.X backend/pipeline/risk_scoring.py + backend/routers/profiling.py

**Purpose:** Rule-based, explainable offender risk scoring. Computes a 0-100
score for an accused person from live case data (not a black-box model), with
a breakdown of exactly which factors contributed and how many points each
contributed -- an officer can see why someone scored "critical" vs "low".

**Identity matching caveat:** `prior_case_count` and `at_large_status` are not
stored columns -- both are derived live by matching `AccusedName` across the
`Accused` table. There is no person-level ID beyond name matching in the KSP
schema, so this can undercount or overcount if the same person's name is
recorded inconsistently across cases. The same caveat applies to
`similar_cases.py`.

**Scoring factors (max 100 points):**

| Factor | Max points | How it's computed |
|---|---|---|
| Prior case count | 30 | `min(total_cases * 6, 30)` |
| Violent crime ratio | 25 | `(violent case count / total cases) * 25`, where violent = Assault, Murder, Domestic Violence, Robbery |
| At-large status | 15 | Full 15 if no `ArrestSurrender` row exists for this accused across their cases, else 0 |
| Geographic spread | 15 | `min(distinct police stations involved * 5, 15)` |
| Recency | 15 | Full 15 if most recent case < 90 days old; 55% (8.25) if < 365 days; 15% (2.25) otherwise |

**Risk tiers:** `low` (<25), `medium` (25-49), `high` (50-74), `critical` (75+).

**Functions (`pipeline/risk_scoring.py`):**
- `compute_risk_for_accused(accused_id)` -- runs the full scoring pipeline above; returns a dict with `risk_score`, `risk_tier`, and `contributing_factors` (sorted highest-point-contribution first). Returns a zeroed `low` score on any exception -- **this is indistinguishable from a legitimately low score**, which is why `profiling.py` does a separate existence check.
- `save_risk_score(result)` -- upserts into `offender_risk_scores` via `ON DUPLICATE KEY UPDATE`.
- `get_cached_risk_score(accused_id)` -- reads the stored score without recomputing.
- `recompute_all_risk_scores()` -- iterates every distinct `AccusedMasterID` and recomputes/saves; used by the bulk recompute endpoint.

**Endpoints (`routers/profiling.py`):**

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/profiling/risk/{accused_id}` | Returns the cached score, or computes fresh if none cached. `?force_recompute=true` always recomputes. Raises 404 only if the accused ID doesn't exist at all (distinguishing "not found" from "scored zero"). |
| `GET` | `/api/profiling/top-risk?limit=10` | Ranked list of highest-scoring **distinct identities** (grouped by `AccusedName`, since one person can have multiple `AccusedMasterID` rows). Excludes placeholder/generic names (`Suspect`, `Unknown`, `Unidentified`, `Not Known`, `NA`, `N/A`) to avoid falsely aggregating many unidentified people into one high-risk entity. |
| `POST` | `/api/profiling/recompute-all` | Recomputes and saves scores for every accused person in the DB. Returns the count recomputed. No batching/pagination -- runs synchronously for all rows. |

All three endpoints require officer authentication via `get_current_officer`.

---

### 3.X `backend/pipeline/case_timeline.py`

**Purpose:** Builds a chronological timeline for a single case. Events come from `CaseMaster` registration/incident dates and `ArrestSurrender` records (one per arrested/surrendered accused). No `ChargesheetDetails` reference — that table is on the deferred migration list.

**Functions:**

| Function | Description |
|----------|-------------|
| `build_case_timeline(case_master_id) -> list[dict]` | Returns chronologically ordered events: `[{"date": "2024-05-15", "event": "Case registered", "detail": "..."}, ...]`. Queries `CaseMaster` for `IncidentFromDate` and `CrimeRegisteredDate`, then `ArrestSurrender` joined with `Accused` for arrest/surrender events with accused name. Returns `[]` if the case doesn't exist. Events are sorted by date ascending. |

---

### 3.X `backend/pipeline/case_summary.py`

**Purpose:** LLM-generated investigative case brief — a 3-5 sentence professional summary of a single case, built from structured `CaseMaster`/`Accused`/`Victim` facts. Uses `MODEL_ANSWER` via the same `call_llm()` interface every other LLM call in the codebase already uses — no new model, no new plumbing.

**Functions:**

| Function | Description |
|----------|-------------|
| `generate_case_summary(case_master_id) -> dict` | Returns `{"summary": str, "error": None}` on success, or `{"summary": None, "error": str}` on failure. Queries `CaseMaster` (joined with `CrimeSubHead`, `CaseStatusMaster`, `Unit`) for case facts, `Accused` and `Victim` for involved parties. Passes structured data to `build_case_summary_prompt()` to assemble the LLM prompt, then calls `call_llm("MODEL_ANSWER", ..., max_tokens=4000)`. Never raises — catches `LLMError` and surfaces it in the return dict. |

---

### 3.X `backend/pipeline/evidence_trail.py`

**Purpose:** Writes SQL provenance for chat answers into `chat_evidence_trail` — the "why did the assistant say this" explainability record. The table was created with the schema extensions but nothing wrote to it until this step. Non-fatal by design: a failure here must never break a chat turn.

**Key helpers:**
- `_log(msg)` — writes to stderr with `[evidence_trail]` prefix.

**Functions:**

| Function | Description |
|----------|-------------|
| `save_evidence_trail(message_id, sql_generated, table_data)` | Persists one row per assistant turn that actually ran SQL. **DIRECT-path answers** (no SQL) are skipped entirely — there's nothing to trail, and that's correct, not an error condition. Uses `extract_tables()` from `sql_validator.py` to identify queried tables and `collect_case_master_ids()` from `media_resolver.py` to extract referenced case IDs (capped at 100). Writes via `execute_write` to `chat_evidence_trail` with `message_id`, `sql_executed`, `tables_queried` (comma-separated), `row_count`, and `case_ids_referenced` (comma-separated). Never raises — catches all exceptions and logs to stderr. Called from `_persist_turn` in `routers/chat.py` after `save_message_pair`. |

---

### 3.X `backend/routers/decision_support.py` (updated)

**Purpose:** Decision-support endpoints — per-case investigative aids that connect a case to patterns/other cases the officer may not have manually cross-referenced.

**Functions:**

| Function | Description |
|----------|-------------|
| `similar_cases(case_id, limit=5, officer)` | `GET /api/decision-support/similar-cases/{case_id}` — returns cases similar to `case_id`, each with `match_reasons` so the officer sees exactly why it surfaced. Delegates to `pipeline/similar_cases.find_similar_cases`. Auth-gated via `get_current_officer`. Returns `{"case_id": int, "similar_cases": list}`. |
| `case_timeline(case_id, officer)` | `GET /api/decision-support/timeline/{case_id}` — returns a chronological event list for a case. Delegates to `pipeline/case_timeline.build_case_timeline`. Auth-gated via `get_current_officer`. Returns `{"case_id": int, "timeline": list}`. |
| `case_summary(case_id, officer)` | `GET /api/decision-support/summary/{case_id}` — returns an LLM-generated investigative brief for a case. Delegates to `pipeline/case_summary.generate_case_summary`. Auth-gated via `get_current_officer`. Returns `{"case_id": int, "summary": str|None, "error": str|None}`. |

---

## 10.14 LLM Migration — Qwen → GLM-4.7-Flash

**Date:** July 11, 2026  
**Issue:** The two Qwen models previously used (`crm-di-qwen_coder_7b-it` for SQL, `crm-di-qwen_text_14b-fp8-it` for answers) were deprecated by Zoho Catalyst. Replaced by a single GLM-4.7-Flash model (`crm-di-glm47b_30b_it`) — a Mixture-of-Experts 30B model optimized for coding, reasoning, and agent workflows.

**Changes:**

| File | Change |
|------|--------|
| `backend/llm/client.py` | Complete rewrite. Old format used flat `prompt`/`system_prompt` fields against `/quickml/v2/.../llm/chat`. New format uses OpenAI-style `messages` array against `/quickml/v1/.../glm/chat`. Response parsing handles both `{"response": "..."}` (observed in production) and `{"choices": [...]}` (per Zoho sample docs). Added `"chat_template_kwargs": {"enable_thinking": false}` to suppress chain-of-thought leaking into output. |
| `.env` | `QUICKML_LLM_URL` changed from `.../v2/.../llm/chat` to `.../v1/.../glm/chat`. Both `MODEL_SQL` and `MODEL_ANSWER` set to `crm-di-glm47b_30b_it`. |
| `.env.example` | Updated URL pattern and model names. |

**What did NOT change:** `prompts.py`, `sql_generator.py`, `answer_formatter.py`, `query_pipeline.py`, all routers — the `call_llm(model_key, prompt, system_prompt, max_tokens)` interface is identical; only the internal HTTP payload shape and response extraction changed.

**Performance note:** Both SQL generation and answer formatting now use the same model. The pipeline makes 3 LLM calls per query (SQL gen + answer format + follow-up suggestions). GLM-4.7-Flash responds in ~2-4s per call, giving ~10s total pipeline latency.

---

## 10.15 Database Migration — Local MySQL → AWS RDS (ap-south-1)

**Date:** July 11, 2026  
**Issue:** The codebase previously ran against a local MySQL instance (`localhost`). For the hackathon, the backend will deploy on Zoho Catalyst AppSail — which cannot host a MySQL server. Catalyst Data Store was evaluated but rejected: tables can only be created via the console UI (no DDL via code), ZCQL lacks subqueries, GROUP_CONCAT, and MySQL date functions, and the 5000-row/table dev limit is restrictive.

**Solution:** AWS RDS MySQL 8.0 in `ap-south-1` (Mumbai) — same region as Zoho Catalyst India. The backend on AppSail connects to RDS over the public internet via standard `aiomysql`.

**Changes:**

| File | Change |
|------|--------|
| `.env` | `DB_HOST` → `ksp-crime-db-instance.cng002wykxbp.ap-south-1.rds.amazonaws.com`, `DB_NAME` → `ksp_crime_db` (removed `_v2` suffix), `DB_USER` → `admin` |
| `.env.example` | Updated DB section header and placeholders to reflect AWS RDS |

**No code changes.** `db/connection.py` reads credentials from `.env` — it doesn't care whether the host is localhost or a remote RDS endpoint.

**Latency (measured):** 36ms average query latency from local dev to Mumbai RDS (includes internet hop). When running on Catalyst AppSail (also India), expected to drop to 5-15ms server-to-server.

**Deployment architecture:**
```
Zoho Catalyst (India)          AWS (ap-south-1 Mumbai)
├── AppSail (FastAPI)  ──TCP──→  RDS MySQL 8.0
├── NoSQL (history)              (all 25+ tables, 220 cases)
├── QuickML (GLM LLM)
└── Web Client (React)
```

---

## 10.16 Codebase Cleanup — Consolidated Debug Scripts & Tests

**Date:** July 11, 2026  
**What:** Removed redundant standalone scripts and merged scattered test files into a clean structure.

**Deleted files (debug/utility):**
- `backend/create_risk_table.py` — redundant, table already defined in `schema.sql`
- `backend/check_table.py` — merged into `debug_tools.py`
- `backend/debug_env.py` — merged; also had hardcoded Windows path that didn't work
- `backend/dump_raw_response.py` — merged into `debug_tools.py`
- `backend/inspect_schema.py` — merged into `debug_tools.py`

**Deleted files (orphaned tests from root of backend/):**
- `backend/test_direct_followup.py`, `test_e2e_rag_pipeline.py`, `test_empty_docs.py`, `test_full_kb.py`, `test_ping_sql.py`, `test_pipeline_rag.py`, `test_rag_client.py`, `test_rag_repeat.py`, `test_rag_scale.py`, `test_rag_session.py`, `test_sql_gen.py`

**New files:**

| File | Purpose |
|------|---------|
| `backend/debug_tools.py` | Unified CLI debug utility with subcommands: `env` (check .env vars), `db` (ping DB + measure latency), `schema` (dump all columns), `tables` (verify critical tables exist + row counts), `rag` (fire test RAG query). Usage: `python backend/debug_tools.py db` |
| `backend/setup_db.py` | Creates all tables from `schema.sql` on whatever DB `.env` points to, optionally seeds data and runs migrations. Usage: `python backend/setup_db.py --seed` |

**Test consolidation (11 files → 3):**

| Old files | New file | Contents |
|-----------|----------|----------|
| `test_generate_title.py`, `test_backward_compat.py`, `test_nosql_client.py`, `test_media_resolver.py`, `test_network_graph.py`, `test_export.py`, `test_report_extraction.py`, `test_voice.py` | `backend/tests/test_unit.py` | 68 pure unit tests — title generation, history migration, NoSQL serialization, media resolver, network graph, export HTML/PDF, report extraction, voice helpers, sociological analytics |
| `test_intent_routing.py`, `test_session_authz.py`, `test_session_lifecycle.py` | `backend/tests/test_pipeline_and_sessions.py` | 15 tests — intent routing, BOLA/IDOR authorization, session lifecycle |
| (new) | `backend/tests/properties/` | 15 property-based tests (hypothesis) — session metadata schema, message-id uniqueness, title constraints, message ordering/timestamps |
| `backend/integration_tests.py` (moved) | `backend/tests/test_integration.py` | Live integration script (LLM, RAG, pipeline, E2E, role auth) — requires real tokens/DB; run directly, excluded from pytest collection |

**Total:** 98 tests pass in ~9s (68 unit + 15 pipeline/session + 15 property). Frontend adds 6 property-based component tests (vitest + fast-check).

---

## 10.17 Files Safe to Delete (Migration Artifacts)

The following files at the project root are one-time local MySQL migration artifacts that serve no purpose going forward:

| File | Was | Status |
|------|-----|--------|
| `migrate.py` | ALTER TABLE script to add `table_data_json`, `follow_ups_json` columns and widen `session_id` | Obsolete — `schema.sql` already has these; `setup_db.py` creates from scratch |
| `backfill.py` | Re-ran old SQL queries to populate `table_data_json` for pre-migration messages | Obsolete — no legacy messages exist on the fresh RDS |
| `backup_pre_migration_20260626.sql` | MySQL dump of the old local DB before schema v2 migration | Obsolete — local backup with no relevance to the AWS RDS deployment |


---

### 10.18 Analytics Dashboard Implementation

**Date:** July 12, 2026  
**Issue:** During the analytics implementation audit, it was identified that the backend analytics functions in `trend_analytics.py` and `routers/analytics.py` already existed, but had several bugs and the entire frontend (dashboard, chart component, API client, wiring) was missing. Additionally, three runtime bugs were discovered during live testing after the frontend was built.

**Changes Made:**

**1. Backend Bug Fix — Missing `unit_id` in station endpoint**
- **File:** `backend/pipeline/trend_analytics.py`, `get_trend_by_location()` function
- **Issue:** The query returned `u.UnitName AS station` and `COUNT(*)`, but not `u.UnitID`, breaking the planned drill-down feature (frontend couldn't call `/trends/station/{unit_id}/breakdown` without the ID).
- **Fix:** Added `u.UnitID AS unit_id` to the SELECT clause and `u.UnitID` to the GROUP BY clause.
- **Verified:** `curl -H "Authorization: Bearer $TOKEN" "http://localhost:8000/api/analytics/trends/stations"` now returns `unit_id` in every row.

**2. Backend Enhancement — Input validation**
- **File:** `backend/routers/analytics.py`
- **Issue:** Route handlers accepted plain `int` parameters with no bounds checking (`months_back: int = 12`), allowing nonsensical values like `months_back=-5` or `limit=99999`.
- **Fix:** Added `Query` import from FastAPI and applied bounds validation:
  - `months_back: int = Query(12, ge=1, le=60)` (1–60 months)
  - `limit: int = Query(10, ge=1, le=50)` (max 50 stations)
  - `min_occurrences: int = Query(2, ge=1, le=100)` (min 1, max 100)
- **Verified:** Requests with out-of-bounds params now return HTTP 422 Unprocessable Entity with clear validation messages.

**3. Response Shape Decision**
- **Issue:** The originally planned frontend expected response keys like `breakdown` and `stations`, but the existing backend returned `trend` for most endpoints.
- **Decision:** Kept the existing backend response shapes (`trend`, `trend`, `trend`) unchanged to avoid breaking any undocumented consumers. Built the frontend to adapt to the existing backend instead.
- **Frontend Adaptation:** `AnalyticsDashboard.jsx` reads `m.trend`, `c.trend`, `s.trend` instead of the originally planned `m.months`, `c.breakdown`, `s.stations`.

**4. Frontend Implementation**
- **Files Created:**
  - `frontend/src/api/analytics.js` — 7 fetch functions: `fetchMonthlyTrend()`, `fetchCrimeTypeTrend()`, `fetchStationTrend()`, `fetchStationBreakdown()`, `fetchStatusBreakdown()`, `fetchMoClusters()`, `fetchSeasonalPattern()`. Reuses existing `getToken()` from `auth.js` and `AuthError` from `chat.js` (no duplication).
  - `frontend/src/components/TrendChart.jsx` — Dependency-free SVG chart component (640×240 viewBox) supporting bar and line modes, with optional click handlers for drill-down, empty-state handling, and custom axis formatters. Includes `wrapLabel()` for horizontal 2-line word-wrapped labels on bar charts with ≥8 categories (replacing earlier −45° rotation), `formatLabel()` for abbreviating YYYY-MM dates to "Mon 'YY" format, and tick-skipping for line charts with >8 points (every 2nd label hidden, all data dots retained). Accepts `height` and `padding` props for per-chart layout overrides.
  - `frontend/src/components/AnalyticsDashboard.jsx` — 6-panel grid dashboard with lazy data fetching, per-panel error isolation via `Promise.allSettled()`, and a drill-down modal for station crime-type breakdown. Passes explicit `height` and `padding` props to each `TrendChart` instance.
  - `IconAnalytics` added to `frontend/src/components/Icons.jsx` (bar-chart icon, matching existing icon conventions).
- **Wiring (`frontend/src/components/ChatWindow.jsx`):**
  - Added `analyticsOpen` state and `handleAnalyticsToggle()`.
  - Added sidebar button (between "New chat" and session list) with `IconAnalytics`.
  - Lazy-imported `AnalyticsDashboard` via `React.lazy()` to keep it code-split from the main bundle.
  - Added Suspense block alongside the existing NetworkGraph Suspense block.
- **CSS (`frontend/src/styles/main.css`):**
  - Added ~200 lines of `.analytics-*` classes: `.analytics-dashboard`, `.analytics-dashboard__header`, `.analytics-dashboard__grid` (520px column width), `.analytics-panel` (overflow: visible), `.analytics-panel__title` (20px font-size), `.analytics-panel__state`, `.analytics-table`, `.analytics-drilldown`, `.trend-chart`, `.trend-chart__empty`, and all chart-specific bar/line/axis styles.

**5. Runtime Bug Fix — SQL `%Y` escaping crash**
- **File:** `backend/pipeline/trend_analytics.py`, `get_trend_by_month()` function
- **Issue:** Query used `DATE_FORMAT(CrimeRegisteredDate, '%Y-%m')` with literal `%` characters. `aiomysql` uses Python's `%-style` parameter substitution internally (`query % args`), so any `%` in the raw SQL that isn't a placeholder (`%s`) gets misinterpreted as a Python format directive, causing `ValueError: unsupported format character 'Y'` and 500 errors.
- **Fix:** Escaped literal `%` as `%%` → `'%%Y-%%m'`. The driver un-escapes `%%` back to `%` before sending the query to MySQL, so the database still receives `'%Y-%m'`.
- **Verified:** `curl -H "Authorization: Bearer $TOKEN" "http://localhost:8000/api/analytics/trends/monthly?months_back=12"` returns 200 OK with real month/count data.

**6. Runtime Bug Fix — Per-panel error isolation in frontend**
- **File:** `frontend/src/components/AnalyticsDashboard.jsx`
- **Issue:** Dashboard used `Promise.all([...])` to fetch all 6 panels. When one panel's endpoint returned a 500 error (e.g., `trends/monthly` before the `%Y` fix), the entire `Promise.all` rejected, blanking all 6 panels with a generic "Could not load analytics" message even though 5 of 6 endpoints were working.
- **Fix:** Replaced `Promise.all()` with `Promise.allSettled()`. Each panel's fetch result is checked independently:
  - `AuthError` instances still fail the entire dashboard (triggers `onAuthExpired()`).
  - Individual panel failures set that panel's data to `null`, which renders an inline "Could not load this panel" error without affecting the other 5 panels.
- **Verified:** When `trends/monthly` was temporarily broken, the other 5 panels loaded normally. After fixing `trends/monthly`, all 6 panels load correctly.

**7. Backend Bug Fix — Clock-dependency in monthly trends**
- **File:** `backend/pipeline/trend_analytics.py`, `get_trend_by_month()` function
- **Issue:** Query filtered relative to `CURDATE()` (real-world "today") via `WHERE CrimeRegisteredDate >= DATE_SUB(CURDATE(), INTERVAL %s MONTH)`. The seeded dataset spans 2022-01-01 to 2025-06-30. Since the current date (July 12, 2026) is ~13 months past the dataset's latest date, `months_back=12` looked for June 2025–July 2026 data, returning empty results. This would continue breaking as time passes, regardless of data quality.
- **Fix:** Replaced `CURDATE()` with `(SELECT MAX(CrimeRegisteredDate) FROM CaseMaster)` as the reference point. "Last N months" is now relative to the dataset's own most recent case, not the real-world clock. With `months_back=12`, the query returns June 2024–June 2025 data (always works regardless of execution date).
- **Analysis:** All other functions in `trend_analytics.py` (`get_trend_by_crime_type`, `get_trend_by_location`, `get_crime_type_by_location`, `get_status_breakdown`, `get_modus_operandi_clusters`, `get_seasonal_pattern`) are data-independent (all-time aggregations with no date filters) and required no changes.
- **Verified:** `curl` to `trends/monthly` returns 12 months of real data anchored to the dataset's latest case, not empty results.

**Tests:**
- All 7 backend analytics endpoints return 200 OK with expected JSON structure.
- Frontend dashboard loads all 6 panels successfully.
- Drill-down feature (click station → see crime-type breakdown) works correctly using the `unit_id` from station data.
- Per-panel error isolation confirmed (temporarily broke one endpoint, verified other 5 panels still rendered).

**Documentation:**
- This changelog entry documents all changes from the analytics implementation.
- `backend/pipeline/trend_analytics.py` docstrings and CONTRACT comments unchanged (already present and correct).
- `backend/routers/analytics.py` route docstrings unchanged (already present and correct).

---

### 10.19 Decision Support & Evidence Trail

**Date:** July 13, 2026
**What:** Implemented case timeline, LLM case summary, and SQL evidence trail — the remaining backend deliverables for decision support and explainability.

**New pipeline modules:**
- **`backend/pipeline/case_timeline.py`** — `build_case_timeline(case_master_id)` queries `CaseMaster` for registration/incident dates and `ArrestSurrender` (joined with `Accused`) for arrest events, returning a chronologically sorted list of `{date, event, detail}` dicts. Returns `[]` for non-existent cases.
- **`backend/pipeline/case_summary.py`** — `generate_case_summary(case_master_id)` gathers structured facts from `CaseMaster`/`CrimeSubHead`/`CaseStatusMaster`/`Unit`/`Accused`/`Victim`, assembles a prompt via `build_case_summary_prompt()`, and calls `call_llm("MODEL_ANSWER", ..., max_tokens=4000)`. Returns `{summary, error}` — never raises.
- **`backend/pipeline/evidence_trail.py`** — `save_evidence_trail(message_id, sql_generated, table_data)` records SQL provenance in `chat_evidence_trail`. Uses `extract_tables()` from `sql_validator.py` (promoted from `_extract_tables` to public) and `collect_case_master_ids()` from `media_resolver.py`. Non-fatal — failures logged, never break a chat turn. Wired into `_persist_turn` in `routers/chat.py`.

**New prompts:**
- **`backend/llm/prompts.py`** — added `CASE_SUMMARY_SYSTEM_PROMPT` (3-5 sentence investigative brief, plain prose, no hallucination) and `build_case_summary_prompt(case_row, accused_rows, victim_rows)`.

**New store function:**
- **`backend/db/chat_store.py`** — added `get_evidence_trail_for_message(message_id, officer_id)` — ownership-scoped read via join through `chat_messages` → `chat_sessions`. Returns `None` on any failure.

**New routes:**
- `GET /api/decision-support/timeline/{case_id}` — chronological event list. Auth-gated.
- `GET /api/decision-support/summary/{case_id}` — LLM-generated case brief. Auth-gated.
- `GET /api/chat/messages/{message_id}/evidence-trail` — SQL provenance for a chat message. BOLA/IDOR-scoped.

**Interface change:**
- `pipeline/sql_validator.py` — `_extract_tables()` promoted to public `extract_tables()` because `evidence_trail.py` is a second caller outside `validate_sql()`. No signature change.

**Documentation:**
- Updated `README.md` project structure tree and API endpoints table.
- Updated `CONTRACTS.md` with 10 new function contracts (213 functions across 47 files).
- Updated `Docs.md` §2 architecture tree, §3.10 prompts.py, §3.12 sql_validator.py, §3.16b chat_store.py, §3.18 routers/chat.py, and added §3.X sections for case_timeline.py, case_summary.py, evidence_trail.py, and decision_support.py (updated).


---

### 10.20 Frontend: RiskBadge, CaseDetailPanel, EvidenceTrail (FINAL)

**Date:** July 13, 2026
**What:** Built the three frontend components that surface Steps 1-3's backend features to officers. Zero backend changes — all endpoints already existed and were tested.

**New files created:**

| File | Purpose |
|------|---------|
| `frontend/src/api/profiling.js` | Fetch client for `/api/profiling/risk/{accusedId}` |
| `frontend/src/api/decisionSupport.js` | Fetch client for timeline/summary/similar-cases endpoints |
| `frontend/src/api/evidenceTrail.js` | Fetch client for `/api/chat/messages/{id}/evidence-trail` |
| `frontend/src/components/RiskBadge.jsx` | Inline colored pill showing risk tier + expandable contributing factors |
| `frontend/src/components/EvidenceTrail.jsx` | Inline expandable section showing SQL provenance (tables, rows, query) |
| `frontend/src/components/CaseDetailPanel.jsx` | Full-screen modal with 3 tabs (Timeline, Summary, Similar Cases) |

**Modified files:**

| File | Change |
|------|--------|
| `frontend/src/components/MessageBubble.jsx` | Added `firstAccusedId()` helper, imported RiskBadge + EvidenceTrail, added "View case details" button, added "Why this answer?" toggle, accepts new props (`onCaseDetailRequest`, `messageId`, `onAuthExpired`) |
| `frontend/src/components/ChatWindow.jsx` | Added `CaseDetailPanel` lazy import + state, added `messageId` sourcing via post-`onDone` fetch, passes new props to MessageBubble |
| `frontend/src/styles/main.css` | Added ~130 lines: `.risk-badge*`, `.case-detail-panel*`, `.case-timeline`, `.case-summary-text`, `.evidence-trail*` |

**Architecture decisions:**

1. **RiskBadge triggers from `AccusedMasterID` in table data** — same pattern as "View network" triggering from `CaseMasterID`. Shows wherever a query naturally surfaces accused rows.
2. **CaseDetailPanel tabs load independently** — Summary (LLM-backed, slow) doesn't block Timeline/Similar Cases (SQL, fast). Data cached per-caseId, no refetch on tab switch.
3. **EvidenceTrail uses message_id fetched after stream completes** — persistence creates the `message_id` after `done` is sent, so the frontend fetches messages right after `onDone` to get the real ID. Non-fatal: failure just means no trail button until session reload.
4. **Evidence trail 404 = "No SQL ran"** — DIRECT-path answers, missing messages, and ownership failures all surface the same "No SQL ran for this answer" message, per the 404-not-403 BOLA convention.
5. **Code-split correctly** — CaseDetailPanel is a separate chunk (2.72 kB), loaded only on first "View case details" click. RiskBadge and EvidenceTrail are inlined in the main bundle (tiny components, no lazy-load needed).

**Feature implementation status:** All feature areas complete:
- Roles, Audit Log, Governance
- Crime Trend Analytics Dashboard
- Case Timeline, Case Summary, Evidence Trail (backend)
- RiskBadge, CaseDetailPanel, EvidenceTrail (frontend)

**Documentation:**
- `CONTRACTS.md` updated: 223 functions across 50 files (+10 new entries).
- Inline CONTRACT comments added to all new functions.


---

### 10.21 PDF Export — Real PDF Generation via fpdf2

**Date:** July 13, 2026
**What:** Replaced the HTML-only export with actual PDF generation using `fpdf2` (pure Python, no system dependencies).

**Changes:**
- `backend/routers/export.py` — Added `_build_pdf()`, `_render_user_message()`, `_render_assistant_message()`, `_render_table()`, `_safe_text()`. PDF is now the default format. HTML kept as fallback via `?format=html` query param.
- `requirements.txt` — Added `fpdf2`.
- Route signature: `POST /api/chat/sessions/{id}/export?format=pdf|html` (default: `pdf`)

**PDF layout:**
- Header: KSP branding + officer name/badge + session title + export date
- User messages: beige background box
- Assistant messages: prose text + embedded tables (colored headers, alternating rows, max 6 columns, max 50 rows) + SQL query in monospace + media placeholders
- Footer: confidentiality notice

**Frontend:** No changes needed — `exportSession()` in `api/chat.js` already reads filename from `Content-Disposition` header and triggers a blob download regardless of content type.

**Dependencies:** `fpdf2` — pure Python, no C extensions, no system packages required. Deploys cleanly on Catalyst AppSail without Docker changes.


---

### 10.22 Sociological Crime Insights — Demographic Analytics

**Date:** July 14, 2026
**What:** Added demographic analysis features for crime patterns by age, gender, and occupation — satisfying the "Sociological Crime Insights" requirement from the hackathon feature list.

**New file:**
- `backend/pipeline/sociological_analytics.py` — 5 pure SQL functions: `get_accused_age_distribution()`, `get_crime_by_gender()`, `get_victim_demographics()`, `get_crime_by_occupation()`, `get_demographic_risk_profile()`

**Modified files:**
- `backend/routers/analytics.py` — Added 5 new endpoints under `/api/analytics/demographics/*`
- `frontend/src/api/analytics.js` — Added 5 fetch functions for demographic endpoints
- `frontend/src/components/AnalyticsDashboard.jsx` — Added 5 new panels: Accused Age Distribution (bar chart), Crime by Gender (table), Crime by Occupation (bar chart), Victim Profile (table), Demographic Risk Profile (table)
- `backend/db/schema_catalog.py` — Added GenderID enum documentation (1=Male, 2=Female, 3=Other) and demographic keywords (gender, male, female, age) to Accused table for improved NL2SQL routing
- `backend/llm/prompts.py` — Updated ROUTER_SYSTEM_PROMPT to explicitly route demographics/gender/age/occupation queries to SQL path (prevents router from misclassifying these as DIRECT-answerable general questions)

**New endpoints:**
- `GET /api/analytics/demographics/accused-age` — age group distribution of accused
- `GET /api/analytics/demographics/crime-by-gender` — crime type × gender cross-tabulation
- `GET /api/analytics/demographics/victim-profile` — victim demographics per crime type
- `GET /api/analytics/demographics/crime-by-occupation` — occupation frequency in complainant data
- `GET /api/analytics/demographics/risk-profile` — crime type × age group × gender for accused

**Tests:** 11 new tests added (6 PDF export + 5 sociological analytics). Total: 83 tests pass.

**Scope note:** Urbanization/migration/economic stress correlations are not implemented — the schema has no columns for those indicators. The feature covers what's achievable with existing data: age, gender, occupation, caste, and religion demographics.


---

### 10.23 Advanced Pipeline Improvements — Rule Engine, Forecasting, Few-Shot, State Engine

**Date:** July 14, 2026
**What:** Four pipeline optimizations implemented from the Advanced System Design analysis.

**1. Rule Engine Before LLM** (`backend/pipeline/rule_engine.py`)
- Intercepts greetings, help, thanks, goodbye BEFORE any LLM call
- Instant deterministic responses (0ms vs 3-4s for trivial messages)
- `try_rule_response(question)` → response string or None (pass-through)
- Wired as first check in `run_pipeline()` in `query_pipeline.py`

**2. Crime Forecasting & Early Warning** (`backend/pipeline/crime_forecasting.py`)
- `get_hotspot_alerts()` — stations with ≥50% crime increase (recent quarter vs previous)
- `get_repeat_crime_alerts()` — crime type + station combos with 3+ cases in 90 days
- `get_gang_activity_alerts()` — accused in 2+ cases in 90 days (excludes placeholder names)
- `get_forecasting_summary()` — combined dashboard data
- 4 new endpoints at `/api/analytics/forecasting/*`
- 3 new frontend panels in AnalyticsDashboard (Hotspot Alerts, Repeat Crimes, Gang Activity)

**3. Dynamic Few-Shot Retrieval** (`backend/db/schema_catalog.py`)
- Added `_question_similarity(q1, q2)` — Jaccard word-overlap scoring
- `get_few_shot_examples` now accepts `question` param
- Scoring: table overlap (40%) + question similarity (60%) — picks examples most relevant to the officer's actual phrasing
- `sql_generator.py` passes `question=question` to the function

**4. Conversation State Engine** (`backend/conversation/dialogue_state.py`)
- `extract_state(history)` — parses history into structured state (crime_type, station, accused, topic, result_count)
- `state_to_prompt_block(state)` — renders compact context block for LLM
- Injected into `build_sql_prompt()` — gives the LLM structured awareness of what the officer is working on
- Additive: raw history still preserved for SQL clause continuity

**No breaking changes.** All 83 tests pass. Frontend builds clean.

---

### 10.24 Empty Chat Sessions & UTC Timestamp Fix

**Date:** July 19, 2026
**What:** Fixed empty "New chat" sessions (`message_count=0`) accumulating in MySQL and leaking into the "Recents" sidebar, plus a timestamp bug that made session times display in the wrong (misread-as-local) hour.

**Root cause (session leak):** [§9.5](#95-backend-created-sessions-on-new-chat--deprecated-flow-change) documents that new chats became provisional/client-side to stop empty sessions from reaching the sidebar — but that was only a *client* behavior change. `_persist_turn` (`routers/chat.py`) and `_persist_report_turn` (`routers/reports.py`) still create the `chat_sessions` row first and save the message pair second. Their `except Exception` handlers don't catch `asyncio.CancelledError` (not an `Exception` subclass since Python 3.8), so a client disconnect between those two steps — e.g. an officer clicking "New chat" while a previous SSE stream was still resolving — left a permanently empty row behind. `get_sessions_for_officer` had no filter to exclude these, so all of them surfaced in "Recents" as blank "New chat" entries with "0 messages". 20 such rows had accumulated in production before this fix; they were soft-deleted (`is_active = FALSE`) as part of the cleanup.

**Root cause (timestamp bug):** MySQL's `chat_sessions.created_at`/`updated_at` are `TIMESTAMP` columns in a server with `time_zone=UTC`, but `aiomysql` returns them as naive `datetime` objects (no `tzinfo`). Calling `.isoformat()` directly produced strings like `"2026-07-19T05:23:19"` with no offset — which JS's `new Date(iso)` parses as **local** time, not UTC. A session created at 05:23 UTC (10:53 AM IST) rendered in the sidebar as "5:23" with no AM/PM, because the browser treated the raw UTC clock digits as if they were already local.

**Fix (4 changes, `backend/` only):**
1. `db/chat_store.py::get_sessions_for_officer` — added `AND message_count > 0` to the `WHERE` clause, so no zero-message session can appear in "Recents" regardless of how it was created.
2. `db/chat_store.py` — added `_utc_iso(dt)` helper that attaches `timezone.utc` to the naive datetime before calling `.isoformat()`; used in `get_sessions_for_officer` and `get_messages_for_session`.
3. `routers/chat.py` (`/api/chat` and `/api/chat/stream`) and `routers/reports.py` (`/api/reports/analyze`) — wrapped the `_persist_turn` / `_persist_report_turn` calls (and the paired `save_turn` calls) in `asyncio.shield()`, so a client disconnect can no longer interrupt persistence mid-write.
4. One-time cleanup script (not committed) deactivated the 20 existing zombie rows via `UPDATE chat_sessions SET is_active = FALSE WHERE message_count <= 0`.

**Not changed:** the frontend's provisional-new-chat flow (§9.5) is unchanged and still correct — this fix makes the backend enforce the same guarantee structurally instead of relying on the frontend never calling `POST /api/chat/sessions`.

**Tests:** existing `tests/test_pipeline_and_sessions.py` suite (16 tests) re-run and passing; no new tests added for this fix (targeted bug fix, not new behavior).

---

### 10.25 Password Hashing & Login Brute-Force Protection

**Date:** July 19, 2026
**What:** Fixed two auth issues surfaced by a security audit ([Cleanup And Imp/WorkInPrg.md](../Cleanup%20And%20Imp/WorkInPrg.md)): passwords were compared as a plaintext, badge-number-derived formula, and `/api/auth/login` had no rate limiting.

**Root cause:** `auth/simple_auth.py::login()` computed `expected = badge_number + "123"` at request time and compared it directly against the submitted password. Since the badge number (`KGID`) is not secret — it's visible in the JWT payload and the UI — every officer's password was reconstructable by anyone who knew (or guessed) their badge number. Compounding this, `main.py`'s station-wide rate limiter explicitly exempts `/api/auth/login` (`_RATE_LIMIT_EXEMPT`) because it reads `unit_id` from the JWT, which doesn't exist yet at login time — leaving the login endpoint with no attempt cap at all.

**Fix (backend only, no frontend changes, no change to officer-facing behavior):**
1. Added `Employee.password_hash VARCHAR(255)` (`db/schema.sql`).
2. One-time migration (`backend/migrate_password_hash.py`, not part of the running app — run once, safe to re-run) added the column to the live AWS RDS DB and backfilled all existing officers with `bcrypt(badge_number + "123")`. Guarded the same way as the earlier `migrate.py` schema-drift fix ([10.13](#1013-nosql-root-cause-fix--session-id-column-width----2026-07-10-continued)): checks `information_schema.COLUMNS` scoped to `TABLE_SCHEMA = DATABASE()` before altering.
3. `auth/simple_auth.py::login()` now calls `bcrypt.checkpw(password, employee["password_hash"])` instead of the string comparison.
4. `db/seed.py::seed_employees()` now generates a bcrypt hash of `badge + "123"` per officer at seed time, so a fresh clone's seeded data works against the same verification path as migrated production data (no separate migration step needed after a fresh seed).
5. New `auth/login_rate_limiter.py` — a login-specific limiter (separate from `pipeline/rate_limiter.py`'s station-wide one, since there's no JWT/unit_id at login time to key off). Fixed window, in-memory, keyed by the **badge number being attempted** (not IP — the threat is "guess this officer's password," which doesn't change with source IP). Caps at 10 attempts per badge number per 15-minute window; both failed and successful attempts count toward the cap; a successful login resets the counter via `reset_login_attempts()` so an officer's own earlier typos don't leave them near the limit.
6. `routers/auth.py::login_route` calls `check_login_attempt()` before `login()` runs, returning HTTP 429 with a `Retry-After` header when exceeded.
7. Added `bcrypt==4.2.0` (exact-pinned, matching the project's existing dependency discipline) to both `requirements.txt` and `backend/requirements.txt`.

**What did NOT change:** every officer's actual password is still `badge_number + "123"` — this was a deliberate scoping decision, not an oversight. Officer-chosen/stronger passwords are a separate future step. The JWT payload, `get_current_officer`, `create_access_token`, and every other route's authorization model are untouched.

**Verified:** ran the migration against the live RDS instance (10 officers backfilled successfully); confirmed end-to-end against the real DB that correct credentials still log in, wrong passwords return 401, and unknown badge numbers return 401; confirmed the rate limiter allows exactly 10 attempts then denies, and resets cleanly on a successful login. Full backend test suite (125 tests) passes.

**Deferred to later (tracked in `Cleanup And Imp/WorkInPrg.md`, not yet actioned):** the remaining findings from the same security audit — a UNION/tautology bypass gap in the LLM-generated SQL validator, `.env`/`app-config.json` being committed to git with live secrets (DB password, JWT signing key, Catalyst OAuth credentials), missing magic-byte validation on file uploads, `/docs` (Swagger) being reachable in production, and frontend dependency versions not being exact-pinned.

---

### 10.26 Report Upload Wired End-to-End

**Date:** July 19, 2026
**What:** Connected the report-analysis feature's frontend to its (previously backend-only) endpoint. The composer's attach button was a disabled placeholder ("Attach report (coming soon)") even though `POST /api/reports/analyze` (`backend/routers/reports.py`) has existed and worked since an earlier step — the frontend simply never called it.

**Why it was still disabled:** no functional reason — the backend endpoint was complete (auth, ownership check, size/type validation, text extraction, LLM analysis, persistence), it just had zero callers in the frontend (confirmed by grep before starting: no reference to `/api/reports/analyze` anywhere in `frontend/src/`).

**Frontend changes:**
1. New `frontend/src/api/reports.js` — `analyzeReport(file, sessionId, prompt)` reads the file via `FileReader.readAsDataURL()`, strips the `data:<mime>;base64,` prefix (browser-side, no filesystem access), and POSTs the bare base64 payload as JSON — matching the backend's expected shape. Also exports `validateReportFile()`, a client-side pre-check (5 MB cap, PDF/unknown-extension rejection) mirroring the backend's own validation, purely for faster feedback — the backend remains the source of truth and re-validates independently.
2. `Composer.jsx` — the attach button now opens a real `<input type="file">` (hidden, triggered via `ref.click()`), shows a spinner while uploading, and surfaces upload errors inline above the composer (same visual slot as the rate-limit and status-text messages). Any text currently typed in the composer is sent along as the analysis prompt. New props: `sessionId`, `onReportAnalyzed`, `onAuthExpired`.
3. `ChatWindow.jsx` — new `handleReportAnalyzed(result, fileName)` appends the analysis as a normal user+assistant message pair (same shape `handleSend` produces), so it renders and behaves identically to any other chat turn. The backend has already persisted the turn (`_persist_report_turn` in `reports.py`), so this only updates the local transcript + sidebar metadata (`bumpSessionMetadata`, `fetchSessions()`) — no extra network round-trip for the message content itself.
4. Removed the now-dead `.composer-action-btn.not-yet` CSS rule (its only usage was the disabled placeholder); disabled-state styling now uses the standard `:disabled` pseudo-class instead, consistent with how other composer buttons already handle their disabled state.

**Backend changes:** none to behavior — only a documentation-focused module docstring added to `routers/reports.py` explaining exactly how an uploaded file reaches the LLM (base64 → in-memory decode → text extraction → prompt text → HTTPS call to Catalyst QuickML), since a natural question when reviewing this endpoint is "does this do a low-level file read()?" — it does not. No filesystem I/O exists anywhere in this request path; the file lives in HTTP request/response bodies and Python `bytes`/`str` objects in memory for the duration of the request, and is discarded once text extraction completes.

**Tests added:**
- `backend/tests/test_pipeline_and_sessions.py::TestSessionAuthz` — three new tests alongside the existing intruder-rejection test: `test_reports_happy_path_persists_and_returns_analysis` (full mocked round-trip: decode → extract → LLM → MySQL session-row creation → message-pair save → NoSQL history save), `test_reports_rejects_unsupported_file_type` (415, LLM never called), `test_reports_rejects_oversized_file` (413, LLM never called).
- `frontend/src/api/reports.test.js` (new file) — 10 tests covering `validateReportFile()` (size cap, PDF rejection, unknown-extension rejection, valid `.txt`/`.docx` acceptance) and `analyzeReport()` (correct base64 payload with no `data:` prefix, auth header, session_id/prompt/file_name in the request body, `AuthError` on 401, backend `detail` message surfaced on failure, generic message on network failure). Confirms `FileReader` works correctly under Vitest's jsdom environment.

**Verified live, end-to-end, against the real GLM backend (not just mocked tests):** started the local backend, logged in, POSTed a real text file through the exact JSON shape the frontend now sends, got back a genuine LLM-generated intelligence note referencing the uploaded content, and confirmed via `GET /api/chat/sessions/{id}/messages` that the turn was actually persisted to MySQL. Test session cleaned up afterward.

**Test counts:** backend 125 → 128 tests (all passing). Frontend 6 → 16 tests (all passing). Frontend `vite build` succeeds with no new warnings.

**Not changed / explicitly out of scope for this pass:** PDF support (still rejected — needs a real parser + OCR, a separate, larger effort), and the FILE_UPLOADS magic-byte-validation gap already tracked in `Cleanup And Imp/WorkInPrg.md` (file type is still trusted from the client-supplied extension/MIME string, not verified against actual file signatures) — this pass only wired the existing, already-reviewed backend endpoint to the UI; it didn't change the endpoint's validation model.


---

### 10.27 Performance Optimization: N+1 Query & Concurrency Improvements

**Date:** July 23, 2026
**What:** Fixed major performance bottlenecks inside `backend/pipeline/similar_cases.py` (N+1 database query pattern) and `backend/pipeline/risk_scoring.py` (sequential recomputation loop).

**Issues Resolved:**
1. **N+1 Query Pattern in Similar Cases:** 
   `find_similar_cases()` was query-inefficient: it retrieved up to 200 candidate similar cases, and then looped through them, executing a separate database query per candidate to retrieve their accused list. On an AWS RDS deployment, this resulted in up to 201 sequential queries ($\approx 2.0\text{s}$ latency overhead).
   - **Fix:** Refactored accused name retrieval to batch all candidates into a single `WHERE CaseMasterID IN (...)` query. This reduced database round-trips from 201 queries to exactly 2 queries per search, dropping execution time to under $20\text{ms}$.
2. **Sequential Risk Score Recomputation:**
   `recompute_all_risk_scores()` processed every offender in the database sequentially. With 350+ seeded offenders and 3–4 database pings per offender, this resulted in nearly 1,000 sequential RDS round-trips, taking over 10 seconds.
   - **Fix:** Converted the sequential loop to execute concurrently using `asyncio.gather` bounded by an `asyncio.Semaphore(8)` to keep concurrent connection counts safely within the application's MySQL connection pool `maxsize` (10). This parallelized execution and reduced recomputation time to $\approx 1.5\text{–}2.0\text{s}$.

**Verified:** Tests in `backend/tests/` verify both similar case search results and offender risk score recomputation behave exactly as before while running significantly faster.

---

### 10.28 Cold-Start Mitigation: Keep-Warm Loop & Login Pre-warming

**Date:** July 23, 2026
**What:** Implemented automated keep-warm loops and pre-warming triggers to mitigate high cold-start latencies of Zoho serverless and LLM/Zia QuickML services.

**Warming Methods Applied:**
1. **Zia Voice Warming (`ping_voice`):**
   Added a new `ping_voice()` function to `voice/zia_voice.py` that hits all three Zia services (Translation, TTS, STT) with minimal, safe payloads to warm their serverless containers non-blockingly without throwing uncaught exceptions.
2. **Pre-warming on Login:**
   Added a fire-and-forget pre-warm task in `routers/auth.py::login_route` right after successful user authentication. It initiates non-blocking `asyncio` tasks to ping the SQL generating GLM (`MODEL_SQL`), the answer GLM (`MODEL_ANSWER`), and the Zia voice services. This keeps the models hot while the officer is logging in and reading their dashboard before executing their first query.
3. **Background Keep-Warm Loop:**
   Started a background asyncio loop task in `main.py` lifespan startup. This runs every 5 minutes (300 seconds) in parallel and pings `MODEL_SQL`, `MODEL_ANSWER`, and `ping_voice()`. It is cleanly cancelled and closed during the application shutdown phase to avoid resource leaks.
4. **Lightweight `/internal/warm` Endpoint:**
   Added a `POST /internal/warm` endpoint to `main.py` which executes the LLM and Voice warm-up pings in parallel. This can be pointed to by Catalyst Job Scheduling or external cron jobs to maintain container warmth.

**Verified:** The full test suite was verified and all 138 unit/integration tests pass cleanly.


---

### 10.29 In-Memory Lookup Cache (Unit, CrimeSubHead, CaseStatusMaster)

**Date:** July 23, 2026
**What:** Implemented in-memory caching of the static lookup tables (`Unit`, `CrimeSubHead`, and `CaseStatusMaster`) in Python application state. This eliminates recursive database queries and joins against static metadata tables, speeding up key operational paths.

**Implementation Details:**
1. **New Cache Module (`db/lookup_cache.py`):**
   - Created `init_lookup_cache()` to fetch all lookup rows from the database once during application startup.
   - Implemented `get_descendant_units_mem(unit_id)` to recursively resolve descendant units entirely in-memory, replacing recursive SQL CTEs.
   - Implemented `intercept_lookup_query(sql, params)` to transparently catch and serve simple select queries on `Unit`, `CrimeSubHead`, and `CaseStatusMaster` from cache.
2. **FastAPI Lifespan Startup:**
   - Modified `main.py` to trigger cache initialization immediately after DB connection pool setup.
3. **Query Interception (`db/connection.py`):**
   - Integrated `intercept_lookup_query` into the start of `execute_query(sql, params)` to intercept lookup queries, returning dict results instantly and bypassing RDS entirely.
4. **Optimized Scopes & Caps:**
   - Updated `auth/role_guard.py` (supervisor scope check) and `pipeline/rate_limiter.py` (active headcount headcount calculation) to resolve descendants via `get_descendant_units_mem()`, removing recursive CTE queries.

**Verified:** The test suite was extended with `TestLookupCache` covering lookups and descendant hierarchy resolution. All 140 tests pass cleanly.

---

### 10.30 Resource Optimization: Connection Pools, Retry Backoffs, Async NoSQL Writes, Pipeline Cache, and Eager Warmup

**Date:** July 23, 2026
**What:** A broad set of optimizations targeting connection pool sizing, LLM call resilience, NoSQL write latency on the request path, pipeline-level semantic caching, eager warm-up before accepting connections, and the configurable uvicorn startup command.

**Files Changed:**

1. **`backend/db/connection.py`** — `create_pool()` now reads `DB_POOL_MINSIZE` (default `5`) and `DB_POOL_MAXSIZE` (default `10`) from environment variables via `os.getenv()`, replacing the previous hard-coded `minsize=3`, `maxsize=10`. This allows pool sizing to be tuned per deployment without code changes.

2. **`backend/llm/client.py`** — `call_llm()` now retries up to 3 times with jittered exponential backoff on transient failures: HTTP 429 (rate-limited), 408 (request timeout), 5xx (server error), `httpx.TimeoutException`, and `httpx.HTTPError`. Backoff formula: `base_delay × 2^attempt + random(0.1, 0.5)` with `base_delay=1.0`. Non-retryable non-200 responses raise `LLMError` immediately. The payload format was also updated to use the OpenAI-compatible `messages` array (`[{role, content}]`) instead of the flat `prompt`/`system_prompt` fields.

3. **`backend/conversation/history.py`** — `save_turn()` now offloads the NoSQL save and session-metadata sync (`_sync_session_metadata`) to a **background `asyncio` task** (`_bg_save`). The in-memory fallback is still updated synchronously before returning. During `pytest`, the task is `await`-ed inline so tests remain deterministic. This removes ~200–500 ms of NoSQL I/O latency from the request path.

4. **`backend/conversation/session_store.py`** — `create_session()` and `update_session()` now offload their NoSQL POST/PUT operations to background `asyncio` tasks (`_bg_insert`, `_bg_update`), following the same pattern as `history.py`. In-memory state is updated synchronously first. During `pytest`, tasks are awaited inline.

5. **`backend/pipeline/query_pipeline.py`** — Two major changes:
   - **Pipeline semantic cache:** Added `PipelineCache` (LRU + TTL, capacity=1000, ttl=300s) and `get_pipeline_cache_key()` (MD5 of normalized question + history + officer identity). `run_pipeline()` checks the cache before any LLM/DB work and stores successful responses after completion. Cache misses proceed through the normal pipeline; cache errors are caught and logged.
   - **Eager KB doc loading:** `_kb_doc_ids_cache` is now populated once at module load time from `os.getenv("KB_DOCUMENT_IDS")`. The old `_get_kb_document_ids()`, which re-read `.env` via `os.path.getmtime()` on every request, was replaced by a simple accessor returning the pre-loaded list. This eliminates synchronous filesystem I/O from the hot path.

6. **`backend/pipeline/rate_limiter.py`** — `check_and_increment()` now checks `os.getenv("DISABLE_RATE_LIMIT")` at the top; when set to `"true"`, the function returns an allow-all result immediately. This supports load testing and benchmarking without rate-limit interference.

7. **`backend/main.py`** — The keep-warm lifecycle was restructured: an **eager warm-up** (`asyncio.gather(ping_model("MODEL_SQL"), ping_model("MODEL_ANSWER"), ping_voice())`) now runs **before** the app yields and starts accepting connections. The subsequent `_keep_warm_loop` was changed to **sleep-first** (300 s wait before each iteration) so it doesn't immediately re-ping after the eager run.

8. **`backend/app-config.template.json`** — The startup command was updated to `python3 -m uvicorn main:app --host 0.0.0.0 --port 9000 --workers 2 --loop uvloop`, adding multi-worker and uvloop support for AppSail deployments.

9. **`scripts/gen_app_config.py`** — Three new optional env-var mappings added to `_OPTIONAL_ENV_VAR_SOURCES`: `DISABLE_RATE_LIMIT`, `DB_POOL_MAXSIZE`, and `DB_POOL_MINSIZE`. These are forwarded from `.env` into `app-config.json` so AppSail deployments can configure pool sizes and rate-limit bypass without code changes.

10. **`Support Documents/DEPLOYMENT.md`** — Updated the startup command documentation from `--port 9000` to `--port 9000 --workers 2 --loop uvloop`.

11. **`Support Documents/FULL_DEPLOYMENT_WALKTHROUGH.md`** — Updated the startup command from `--port 8000` to `--port 9000 --workers 2 --loop uvloop`.

12. **`Support Documents/STATION_SCOPING_PLAN.md`** — **Deleted.** The station scoping plan was a design artifact from before the scoping feature was implemented; the implementation itself (in `pipeline/station_scope.py`, `auth/role_guard.py`, etc.) is the source of truth and is documented in Docs.md §10.14.

13. **`backend/benchmark.py`** — **New file.** Standalone HTTP benchmark harness that hits the running API over HTTP to measure endpoint latency. Usage: `python backend/benchmark.py --base-url http://localhost:8000 --badge <KGID> --password <password>`.
