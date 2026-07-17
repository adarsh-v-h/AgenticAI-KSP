# KSP Crime Intelligence Chatbot

A natural language crime intelligence platform for Karnataka State Police. Officers type a question in plain English, the system converts it to a MySQL query using an LLM, runs it against the crime database, and streams back a formatted answer with tabular results.

> See [Support Documents/Docs.md](Support%20Documents/Docs.md) for full technical documentation — every file, function, and data flow.

---

## What It Does

1. Officer types a question like *"How many theft cases are open in Koramangala?"*
2. A **schema linker** selects the relevant database tables
3. **GLM-4.7-Flash** (LLM) converts the question into a MySQL SELECT query
4. A **SQL validator** checks the query is safe (SELECT-only, valid tables, no injection)
5. The query runs against the crime database (AWS RDS MySQL)
6. **GLM-4.7-Flash** (same LLM) formats the raw results into a natural-language answer
7. The answer streams back token-by-token via Server-Sent Events (SSE)
8. If the query returns tabular data, it renders as an interactive table in the UI
9. 3 follow-up question suggestions are generated for the officer

Multi-turn conversation is supported — follow-up questions use previous context without repeating information.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.10 (Catalyst runtime), FastAPI, uvicorn |
| Frontend | React 18, Vite 5 |
| Relational DB | AWS RDS MySQL 8.0 (ap-south-1 Mumbai) |
| LLM | Zoho Catalyst QuickML — GLM-4.7-Flash (`crm-di-glm47b_30b_it`) |
| Conversation History | Zoho Catalyst NoSQL |
| RAG Knowledge Base | Zoho Catalyst QuickML KB |
| Auth | JWT (dev) / Catalyst Authentication (production) |
| Deployment | Zoho Catalyst AppSail (backend) + Web Client Hosting (frontend) |

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Zoho Catalyst (India)                                  │
│  ┌─────────────┐  ┌──────────┐  ┌───────────────────┐  │
│  │  AppSail    │  │  NoSQL   │  │  QuickML (LLM +   │  │
│  │  (FastAPI)  │  │ (history)│  │  RAG Knowledge Base)│  │
│  └──────┬──────┘  └──────────┘  └───────────────────┘  │
└─────────┼───────────────────────────────────────────────┘
          │ TCP/MySQL (aiomysql)
┌─────────▼───────────────────────────────────────────────┐
│  AWS RDS (ap-south-1 Mumbai)                            │
│  MySQL 8.0 — 25+ tables, 220 seeded cases              │
└─────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
├── .env.example                 # Environment variable template
├── .env                         # Runtime config + secrets (not committed)
├── start.sh                     # One-command local start (Linux/macOS)
├── start.bat                    # One-command local start (Windows)
├── deploy.sh                    # One-command Catalyst deploy (backend/frontend/both)
├── catalyst.json                # Catalyst project resource map (AppSail + client)
├── requirements.txt             # Backend deps (also used for local tests)
├── pytest.ini                   # Test configuration
├── LICENSE                      # AGPL v3
│
├── scripts/
│   └── gen_app_config.py        # Generates backend/app-config.json from .env (secrets stay out of git)
│
├── client-package/              # Frontend build output for Web Client Hosting (generated)
│   └── client-package.json      # Web Client Hosting config
│
├── Support Documents/
│   ├── Docs.md                  # Full technical documentation
│   ├── DESIGN.md                # Frontend design spec
│   ├── DEPLOYMENT.md            # Deployment reference (setup, redeploy, issues)
│   └── FULL_DEPLOYMENT_WALKTHROUGH.md  # First-time-from-scratch deploy walkthrough
│
├── backend/
│   ├── main.py                  # FastAPI app, startup lifecycle, health check
│   ├── app-config.template.json # AppSail config template (no secrets, committed)
│   ├── app-config.json          # Generated AppSail config (has secrets, gitignored)
│   ├── requirements.txt         # Deps bundled into the AppSail runtime
│   ├── .catalystignore          # Files excluded from the deploy bundle
│   ├── Dockerfile               # Container for Catalyst AppSail (custom-runtime option)
│   ├── debug_tools.py           # CLI debug utility (env/db/schema/tables/rag)
│   ├── setup_db.py              # Create tables + seed (any MySQL target)
│   ├── config/
│   │   └── settings.py          # Env var loading and validation
│   ├── db/
│   │   ├── connection.py        # MySQL connection pool (aiomysql)
│   │   ├── schema.sql           # DDL for all tables
│   │   ├── schema_catalog.py    # Table metadata, schema builder, few-shot examples
│   │   ├── seed.py              # Synthetic data generator (220 cases)
│   │   ├── chat_store.py        # Chat session/message persistence (MySQL)
│   │   └── nosql_client.py      # Centralized Catalyst NoSQL client
│   ├── llm/
│   │   ├── client.py            # HTTP client for QuickML GLM-4.7-Flash
│   │   ├── sql_generator.py     # SQL generation with self-correction loop
│   │   ├── answer_formatter.py  # Result formatting + intent router
│   │   ├── rag_client.py        # RAG retrieval via Catalyst QuickML KB
│   │   ├── rag_session.py       # Multi-turn RAG with follow-up generation
│   │   └── prompts.py           # System prompts and prompt builders
│   ├── pipeline/
│   │   ├── query_pipeline.py    # Main orchestrator (route → SQL → answer)
│   │   ├── sql_validator.py     # SQL safety validation
│   │   ├── schema_linker.py     # Keyword-based table selector
│   │   ├── media_resolver.py    # Evidence media lookup
│   │   ├── risk_scoring.py      # Offender risk scoring (explainable)
│   │   ├── trend_analytics.py   # Crime pattern analytics (SQL aggregation)
│   │   ├── similar_cases.py     # Similar case finder
│   │   ├── sociological_analytics.py  # Demographic crime insights
│   │   ├── crime_forecasting.py # Early warning / hotspot detection
│   │   ├── rule_engine.py       # Instant responses for trivial messages
│   │   ├── case_timeline.py     # Case timeline builder
│   │   ├── case_summary.py      # LLM-generated case brief
│   │   └── evidence_trail.py    # Chat SQL provenance logger
│   ├── auth/
│   │   ├── simple_auth.py       # JWT auth for local dev
│   │   └── role_guard.py        # RBAC + audit logging
│   ├── conversation/
│   │   ├── history.py           # Conversation history (NoSQL + fallback)
│   │   ├── session_store.py     # Session metadata + title generation
│   │   └── dialogue_state.py    # Structured conversation state extraction
│   ├── graph/
│   │   └── network_builder.py   # Criminal network graph (vis.js format)
│   ├── voice/
│   │   └── zia_voice.py         # Zia STT/TTS/translate wrapper
│   ├── routers/
│   │   ├── chat.py              # /api/chat, /api/chat/stream, sessions
│   │   ├── auth.py              # Login/logout
│   │   ├── export.py            # Session export (HTML)
│   │   ├── reports.py           # Report analysis
│   │   ├── voice.py             # Voice routes
│   │   ├── governance.py        # Audit log (supervisor-only)
│   │   ├── analytics.py         # Crime trend endpoints
│   │   ├── decision_support.py  # Decision support (similar cases, timeline, summary)
│   │   └── profiling.py         # Offender risk scores
│   └── tests/
│       ├── test_unit.py         # 68 pure unit tests
│       ├── test_pipeline_and_sessions.py  # 15 pipeline/session tests
│       ├── properties/          # 15 property-based tests (hypothesis)
│       └── test_integration.py  # Live integration script (run directly, not via pytest)
│
└── frontend/
    ├── package.json
    ├── vite.config.js
    └── src/
        ├── App.jsx, main.jsx
        ├── api/ (auth.js, chat.js, voice.js)
        ├── components/ (ChatWindow, Composer, LoginPage, etc.)
        ├── context/ (LangContext.jsx)
        ├── hooks/ (useAuth.js)
        └── styles/ (main.css)
```

---

## Prerequisites

1. **Python 3.10+**
2. **Node.js 18+** (for the React frontend)
3. **A Zoho Catalyst project** with these services enabled:
   - **QuickML** — LLM serving (GLM-4.7-Flash) + RAG Knowledge Base
   - **NoSQL** — document store for conversation history and session metadata
4. **An AWS account** (for the MySQL database) — or any MySQL 8.0 server

---

## Step-by-Step Setup

### 1. Clone and enter the project

```bash
git clone https://github.com/adarsh-v-h/AgenticAI-KSP.git
cd AgenticAI-KSP
```

### 2. Create a Python virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install backend dependencies

```bash
pip install -r requirements.txt
```

### 4. Provision MySQL on AWS RDS

Follow these steps to set up an AWS RDS instance configured to allow external connections from Zoho Catalyst:

1. **Set the Region:** In the AWS Console navbar (top-right), switch to **Asia Pacific (Mumbai) ap-south-1**. This ensures lowest latency to Zoho Catalyst India.

2. **Launch the RDS Wizard:** Search for "RDS" in the top search bar. On the RDS Dashboard, click **Create database**. Select **Standard create**.

3. **Engine Selection:** Select **MySQL** under engine options. Leave the version set to the latest MySQL 8.0.x release.

4. **Template Selection:** Select the **Sandbox** template. This uses lightweight `db.t4g.micro` instances — highly cost-effective.

5. **Settings & Credentials:**
   - DB instance identifier: `ksp-crime-db-instance`
   - Credentials management: **Self-managed**
   - Master username: `admin`
   - Master password: choose a strong password (save it — you'll need it for `.env`)

6. **Storage Configuration:** Select **General Purpose SSD (gp3)**, set allocated storage to **20 GiB**. Uncheck "Enable storage autoscaling" to maintain billing control.

7. **Connectivity & Public Access:**
   - VPC: **Default VPC**
   - Public access: **Yes** (CRITICAL — AWS defaults to No. Catalyst AppSail connects over the internet, so this must be Yes)

8. **Initial Database Name:** Scroll to the bottom, expand **Additional configuration**. Under "Database options", enter the initial database name: `ksp_crime_db`. Do NOT leave this blank — AWS will deploy an empty engine with no database otherwise.

9. **Deploy:** Click **Create database**. Wait 5-10 minutes for the instance status to show green **Available**.

10. **Open Inbound Port 3306 (Firewall):**
    - Click your database identifier link to view its details
    - Under **Connectivity & security**, find "Security group rules"
    - Click the security group hyperlink (e.g., `default (sg-047e...)`)
    - This jumps to the EC2 Security Groups console. Select the security group, go to the **Inbound rules** tab, click **Edit inbound rules**
    - Click **Add rule** → Type: **MySQL/Aurora** (forces port 3306) → Source: **Anywhere-IPv4** (auto-fills `0.0.0.0/0`)
    - Click **Save rules**

After setup, your RDS endpoint will look like:
```
ksp-crime-db-instance.xxxxxxx.ap-south-1.rds.amazonaws.com
```

### 5. Get your Catalyst credentials

You need these values from the Catalyst console:

| Variable | Where to find it |
|----------|-----------------|
| `CATALYST_PROJECT_ID` | Project Settings → Project ID |
| `CATALYST_ORG_ID` | Project Settings → Organization ID |
| `CATALYST_API_TOKEN` | OAuth token (see below) |
| `NOSQL_BASE_URL` | NoSQL → API endpoint (pattern in `.env.example`) |

**Generating a Catalyst API token:**

1. Go to [API Console](https://api-console.zoho.in/)
2. Create a Client ID and Client Secret
3. Generate a refresh token via OAuth 2.0
4. Exchange for an access token:

```bash
curl -X POST "https://accounts.zoho.in/oauth/v2/token" \
  -d "grant_type=refresh_token" \
  -d "client_id=YOUR_CLIENT_ID" \
  -d "client_secret=YOUR_CLIENT_SECRET" \
  -d "refresh_token=YOUR_REFRESH_TOKEN"
```

The `access_token` becomes your `CATALYST_API_TOKEN`. Tokens expire after ~1 hour — refresh periodically during development.

### 6. Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and fill in every value. The server crashes on startup if any required variable is missing.

**Critical variables:**

| Variable | Value |
|----------|-------|
| `CATALYST_API_TOKEN` | Your Zoho OAuth access token |
| `CATALYST_ORG_ID` | Your Catalyst organization ID |
| `QUICKML_LLM_URL` | `https://api.catalyst.zoho.in/quickml/v1/project/{PROJECT_ID}/glm/chat` |
| `MODEL_SQL` | `crm-di-glm47b_30b_it` |
| `MODEL_ANSWER` | `crm-di-glm47b_30b_it` |
| `DB_HOST` | Your RDS endpoint (e.g., `ksp-crime-db-instance.xxx.ap-south-1.rds.amazonaws.com`) |
| `DB_PORT` | `3306` |
| `DB_NAME` | `ksp_crime_db` |
| `DB_USER` | `admin` |
| `DB_PASSWORD` | Your RDS master password |
| `NOSQL_BASE_URL` | `https://api.catalyst.zoho.in/baas/v1/project/{PROJECT_ID}/nosqltable` |
| `APP_SECRET_KEY` | Generate: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `ALLOWED_ORIGINS` | `http://localhost:5173` (dev) |

### 7. Create tables and seed the database

```bash
python backend/setup_db.py --seed
```

This:
- Connects to your RDS instance using credentials from `.env`
- Creates all 25+ tables from `backend/db/schema.sql`
- Seeds 220 FIR cases, 260 accused, 10 officers, and all lookup data

To verify connectivity and latency:
```bash
python backend/debug_tools.py db
```

### 8. Set up the RAG Knowledge Base (Optional)

If you want the chatbot to answer narrative/analytical questions from case reports:

```bash
# Export + consolidate cases into 8 category files
python backend/export_cases_for_rag.py

# Upload the 8 files from backend/rag_consolidated/ to Catalyst QuickML → Knowledge Base

# Sync document IDs into .env
python backend/kb_sync.py --refresh-token
```

### 9. Start the backend

```bash
uvicorn backend.main:app --reload --port 8000
```

**Verify:**

```bash
curl http://localhost:8000/health
```

Expected:
```json
{
  "status": "ok",
  "db": "connected",
  "llm_coder": "ok",
  "llm_answer": "ok",
  "env": "development"
}
```

### 10. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend at `http://localhost:5173`. Vite proxies `/api/*` to the backend.

### Quick Start (One Command)

Instead of steps 9-10 separately, use the provided start scripts that run tests, verify DB, and launch both servers:

**Linux / macOS:**
```bash
./start.sh
```

**Windows:**
```
start.bat
```

Both scripts:
1. Run the backend test suite (abort if anything fails)
2. Ping the database to confirm connectivity
3. Start the backend on port 8000
4. Start the frontend on port 5173
5. Print URLs when ready

Press `Ctrl+C` (Linux) or close the server windows (Windows) to stop.

### 11. Log in and test

1. Open `http://localhost:5173`
2. Enter KGID: `3254123`, Password: `3254123123`
3. Try: *"How many theft cases are open?"*

---

## Deployment

The app is deployed to Zoho Catalyst — backend on **AppSail**, frontend on
**Web Client Hosting**. Once your `.env` is populated and the Catalyst CLI is
logged in (`catalyst login`), deploy with a single command:

```bash
./deploy.sh            # deploy backend + frontend
./deploy.sh backend    # backend only
./deploy.sh frontend   # frontend only
```

`deploy.sh` generates `backend/app-config.json` from `.env` (so secrets never
touch git), bundles backend dependencies, builds the frontend with the backend
URL baked in, and runs `catalyst deploy`.

- **Full reference** (setup, making changes, redeploying, and every issue that
  can arise): [Support Documents/DEPLOYMENT.md](Support%20Documents/DEPLOYMENT.md)
- **First-time-from-scratch walkthrough** (installing tools, logging in):
  [Support Documents/FULL_DEPLOYMENT_WALKTHROUGH.md](Support%20Documents/FULL_DEPLOYMENT_WALKTHROUGH.md)

> **Secrets:** never commit `.env` or `backend/app-config.json` (both
> gitignored). Only `backend/app-config.template.json` (placeholders) is
> version-controlled.

---

## Login Credentials

Password formula: `<KGID>123`

| KGID | Name | Rank | Role |
|------|------|------|------|
| `3254123` | Manjunath Patil | Inspector | supervisor |
| `4167892` | Venkatesh Gowda | PI | supervisor |
| `5823641` | Ramesh Naik | SI | investigator |
| `6741028` | Sandeep Hegde | SI | investigator |
| `7295834` | Harish Kumar | ASI | investigator |
| `8412567` | Vijay Raghavendra | ASI | investigator |
| `9128473` | Lokesh Murthy | Head Constable | investigator |
| `1036852` | Shivakumar Swamy | Head Constable | investigator |
| `2847156` | Srinivas Raju | Constable | analyst |
| `3962485` | Naveen Raj | Constable | investigator |

---

## API Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `POST` | `/api/auth/login` | No | Authenticate officer, returns JWT |
| `POST` | `/api/auth/logout` | Yes | Stateless logout |
| `POST` | `/api/chat` | Yes | Non-streaming chat |
| `GET` | `/api/chat/stream` | Yes | SSE streaming chat |
| `GET` | `/api/chat/sessions` | Yes | List officer's sessions |
| `POST` | `/api/chat/sessions` | Yes | Create a new session |
| `GET` | `/api/chat/sessions/{id}/messages` | Yes | Message history |
| `POST` | `/api/chat/sessions/{id}/export` | Yes | Export session as HTML |
| `POST` | `/api/reports/analyze` | Yes | Upload + analyze a report |
| `POST` | `/api/voice/transcribe` | Yes | STT (Zia) |
| `POST` | `/api/voice/speak` | Yes | TTS (Zia) |
| `GET` | `/api/analytics/trends/*` | Yes | Crime trend data |
| `GET` | `/api/analytics/demographics/accused-age` | Yes | Accused age distribution |
| `GET` | `/api/analytics/demographics/crime-by-gender` | Yes | Crime × gender breakdown |
| `GET` | `/api/analytics/demographics/victim-profile` | Yes | Victim demographics |
| `GET` | `/api/analytics/demographics/crime-by-occupation` | Yes | Crime × occupation breakdown |
| `GET` | `/api/analytics/demographics/risk-profile` | Yes | Accused demographic risk factors |
| `GET` | `/api/analytics/forecasting/summary` | Yes | Combined early warning dashboard |
| `GET` | `/api/analytics/forecasting/hotspots` | Yes | Stations with crime spikes |
| `GET` | `/api/analytics/forecasting/repeat-crimes` | Yes | Repeat crime clusters |
| `GET` | `/api/analytics/forecasting/gang-activity` | Yes | Potential organized crime |
| `GET` | `/api/profiling/risk/{accused_id}` | Yes | Offender risk score |
| `GET` | `/api/profiling/top-risk` | Yes | Top risk offenders |
| `GET` | `/api/decision-support/similar-cases/{case_id}` | Yes | Similar case finder |
| `GET` | `/api/decision-support/timeline/{case_id}` | Yes | Case timeline events |
| `GET` | `/api/decision-support/summary/{case_id}` | Yes | LLM-generated case brief |
| `GET` | `/api/chat/messages/{message_id}/evidence-trail` | Yes | SQL provenance for a chat message |
| `GET` | `/api/audit-log` | Supervisor | Audit log entries |
| `GET` | `/api/graph/fir/{id}` | Yes | Network graph for a case |
| `GET` | `/api/graph/accused/{id}` | Yes | Network graph for an accused |
| `GET` | `/health` | No | Service health check |

---

## Debug Tools

```bash
python backend/debug_tools.py env      # Check .env loading
python backend/debug_tools.py db       # Ping DB + measure latency
python backend/debug_tools.py schema   # Dump all DB columns
python backend/debug_tools.py tables   # Verify tables exist + row counts
python backend/debug_tools.py rag      # Test RAG query
python backend/debug_tools.py all      # Run all checks
```

---

## Running Tests

Backend — 98 tests total (68 unit + 15 pipeline/session + 15 property-based),
no network or DB required:

```bash
# All backend tests (unit + pipeline + property)
python -m pytest backend/tests/ -q

# A single suite
python -m pytest backend/tests/test_unit.py -v
python -m pytest backend/tests/test_pipeline_and_sessions.py -v
python -m pytest backend/tests/properties/ -v

# Live integration script (needs real tokens + DB; runs standalone, not via pytest)
python backend/tests/test_integration.py all      # or: llm | rag | pipeline | e2e | role
```

Frontend — property-based component tests (fast-check + vitest):

```bash
cd frontend && npm test
```

---

## Troubleshooting

**Server crashes with missing env vars:** Check `.env` has all REQUIRED variables from `.env.example`.

**Health check shows `"degraded"`:**
- `"db": "error"` — verify RDS endpoint, credentials, and that port 3306 inbound rule is set
- `"llm_coder": "error"` — token likely expired, refresh it

**Token expired (`INVALID_OAUTHTOKEN`):** Refresh using your stored refresh token:
```bash
curl -X POST "https://accounts.zoho.in/oauth/v2/token" \
  -d "grant_type=refresh_token" \
  -d "client_id=YOUR_CLIENT_ID" \
  -d "client_secret=YOUR_CLIENT_SECRET" \
  -d "refresh_token=YOUR_REFRESH_TOKEN"
```

**Frontend can't reach backend:** Ensure backend runs on port 8000. Vite proxies `/api/*` there.

---

## License

Copyright (C) 2024 adarsh.v.h <adarshvh2005@gmail.com>

Licensed under the **GNU Affero General Public License v3.0** — see [LICENSE](LICENSE).
