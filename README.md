# KSP Crime Intelligence Chatbot

A natural language crime intelligence platform for Karnataka State Police. Officers type a question in plain English, the system converts it to a MySQL query using an LLM, runs it against the crime database, and streams back a formatted answer with tabular results.

> See [Docs.md](https://github.com/adarsh-v-h/AgenticAI-KSP/blob/main/Docs.md) for full technical documentation — every file, function, and data flow.

---

## What It Does

1. Officer types a question like *"How many theft cases are open in Koramangala?"*
2. A **schema linker** selects the relevant database tables
3. **Qwen 2.5-7B Coder** (LLM) converts the question into a MySQL SELECT query
4. A **SQL validator** checks the query is safe (SELECT-only, valid tables, no injection)
5. The query runs against the crime database
6. **Qwen 2.5-14B Instruct** (LLM) formats the raw results into a natural-language answer
7. The answer streams back token-by-token via Server-Sent Events (SSE)
8. If the query returns tabular data, it renders as an interactive table in the UI

Multi-turn conversation is supported — follow-up questions use previous context without repeating information.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11, FastAPI, uvicorn |
| Frontend | React 18, Vite 5 |
| Database | Zoho Catalyst Data Store (MySQL-compatible) |
| LLM | Zoho Catalyst QuickML (Qwen 2.5-7B Coder + Qwen 2.5-14B Instruct) |
| Conversation History | Zoho Catalyst NoSQL |
| Auth | JWT (dev) / Catalyst Authentication (production) |

Everything runs on **Zoho Catalyst** — no AWS, GCP, Azure, or external services.

---

## Project Structure

```
├── BLUEPRINT.md                 # Original project specification
├── DESIGN.md                    # Frontend design spec (colors, typography, layout)
├── Docs.md                      # Full technical documentation
├── TwoToThree.md                # Step 3 implementation guide
├── requirements.txt             # Python dependencies
├── .env.example                 # Environment variable template
│
├── backend/
│   ├── main.py                  # FastAPI app, startup lifecycle, health check
│   ├── Dockerfile               # Container for Catalyst AppSail
│   ├── config/settings.py       # Env var loading and validation
│   ├── db/
│   │   ├── connection.py        # MySQL connection pool (aiomysql)
│   │   ├── schema.sql           # DDL for all 13 tables
│   │   ├── seed.py              # Synthetic data generator (220 FIRs)
│   │   └── schema_catalog.py    # Table metadata, schema builder, few-shot examples
│   ├── llm/
│   │   ├── client.py            # HTTP client for Catalyst QuickML
│   │   ├── sql_generator.py     # SQL generation with self-correction loop
│   │   ├── answer_formatter.py  # Result-to-text formatting
│   │   └── prompts.py           # System prompts and prompt builders
│   ├── pipeline/
│   │   ├── query_pipeline.py    # Main orchestrator (NL → SQL → answer)
│   │   ├── sql_validator.py     # SQL safety validation
│   │   ├── media_resolver.py    # Evidence media lookup
│   │   └── schema_linker.py     # Keyword-based table selector
│   ├── conversation/history.py  # Conversation history (NoSQL + in-memory fallback)
│   ├── cache/catalyst_cache.py  # Cache wrappers (Catalyst + local fallback)
│   ├── auth/simple_auth.py      # JWT auth for local dev
│   └── routers/
│       ├── chat.py              # POST /api/chat + GET /api/chat/stream (SSE)
│       └── auth.py              # POST /api/auth/login + /api/auth/logout
│
└── frontend/
    ├── package.json
    ├── vite.config.js           # Dev proxy: /api → localhost:8000
    ├── index.html
    └── src/
        ├── main.jsx             # React entry point
        ├── App.jsx              # Root: auth gate → LoginPage or ChatWindow
        ├── api/
        │   ├── auth.js          # Token management + login/logout
        │   └── chat.js          # SSE stream consumer via fetch + ReadableStream
        ├── components/
        │   ├── LoginPage.jsx    # Badge number + password form
        │   ├── ChatWindow.jsx   # Main chat interface
        │   ├── MessageBubble.jsx # Single message renderer
        │   └── TableRenderer.jsx # HTML table from JSON query results
        ├── hooks/
        │   └── useAuth.js       # Auth state management
        └── styles/
            └── main.css         # Government portal styling (warm cream + coral)
```

> See [Docs.md §2](https://github.com/adarsh-v-h/AgenticAI-KSP/blob/main/Docs.md#2-backend-architecture) and [Docs.md §5](Docs.md#5-frontend-architecture) for what each file does.

---

## Prerequisites

1. **Python 3.11+**
2. **Node.js 18+** (for the React frontend)
3. **A Zoho Catalyst project** with the following services enabled:
   - **QuickML** — for LLM serving (Qwen models)
   - **Data Store** — MySQL-compatible relational database
   - **NoSQL** — document store for conversation history
   - **Cache** — key-value cache (optional, has local fallback)

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

This installs: FastAPI, uvicorn, aiomysql, httpx, python-dotenv, python-jose (JWT), python-multipart, sse-starlette, pydantic.

### 4. Set up your Zoho Catalyst project

If you don't have a Catalyst project yet:

1. Go to [console.catalyst.zoho.in](https://console.catalyst.zoho.in) (or `.zoho.com` / `.zoho.eu` for other regions)
2. Create a new project
3. Enable **QuickML** from the Services section
4. Enable **Data Store** — create a MySQL database named `ksp_crime_db`
5. Enable **NoSQL** — create a table called `conversation_history` with a string field `history`
6. Enable **Cache** (optional — the app has a local in-memory fallback)

### 5. Get your Catalyst credentials

You need these values from the Catalyst console:

| Variable | Where to find it |
|----------|-----------------|
| `CATALYST_PROJECT_ID` | Project Settings → Project ID (numeric) |
| `CATALYST_ORG_ID` | Project Settings → Organization ID (numeric) |
| `CATALYST_API_TOKEN` | API Console → Generate OAuth Token (see below) |
| `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD` | Data Store → Connection Details |
| `NOSQL_BASE_URL` | NoSQL → API endpoint (follows pattern in .env.example) |
| `CACHE_BASE_URL` | Cache → API endpoint (follows pattern in .env.example) |

**Generating a Catalyst API token:**

1. Go to [API Console](https://api-console.zoho.in/) (or your region's console)
2. Create a Client ID and Client Secret for your project
3. Generate a refresh token using OAuth 2.0
4. Exchange the refresh token for an access token:

```bash
curl -X POST "https://accounts.zoho.in/oauth/v2/token" \
  -d "grant_type=refresh_token" \
  -d "client_id=YOUR_CLIENT_ID" \
  -d "client_secret=YOUR_CLIENT_SECRET" \
  -d "refresh_token=YOUR_REFRESH_TOKEN"
```

The `access_token` from the response becomes your `CATALYST_API_TOKEN`. **Note:** Catalyst tokens expire after ~1 hour. You'll need to refresh them periodically during development.

### 6. Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and fill in every value. The server will crash on startup if any variable is missing.

**Critical variables:**
- `CATALYST_PROJECT_ID`, `CATALYST_ORG_ID`, `CATALYST_API_TOKEN` — your Catalyst identity
- `QUICKML_LLM_URL` — construct from pattern: `{CATALYST_BASE_URL}/quickml/v2/project/{CATALYST_PROJECT_ID}/llm/chat`
- `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` — database connection
- `APP_SECRET_KEY` — generate a random string: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`
- `MODEL_SQL=crm-di-qwen_coder_7b-it` — the SQL generation model
- `MODEL_ANSWER=crm-di-qwen_text_14b-fp8-it` — the answer formatting model

> See [.env.example](.env.example) for the full list with descriptions and URL patterns.

### 7. Create database tables

Run the schema SQL against your Catalyst Data Store:

```bash
# Option A: Use the MySQL client from Catalyst console
# Copy the contents of backend/db/schema.sql and execute it

# Option B: If you have direct MySQL access
mysql -h <DB_HOST> -P <DB_PORT> -u <DB_USER> -p <DB_NAME> < backend/db/schema.sql
```

### 8. Seed the database with synthetic data

```bash
python backend/db/seed.py
```

This inserts:
- 10 officers with Karnataka names and realistic ranks
- 220 FIRs across 11 case types (2022-2025)
- Accused persons including 5 named repeat offenders
- Victims for each case
- Case-type-specific details (stolen items, weapons, vehicle info, etc.)
- 35 case relationship records (for network graph — not yet implemented)
- 25 evidence media records (placeholder Stratus IDs)

The seeder is deterministic (`random.seed(42)`) and skips execution if data already exists.

### 9. Start the backend

```bash
# Make sure you're in the project root with .venv activated
uvicorn backend.main:app --reload --port 8000
```

The server starts at `http://localhost:8000`. On startup it:
1. Validates all environment variables (crashes if any are missing)
2. Creates the MySQL connection pool
3. Probes the database with `SELECT 1`
4. Probes Catalyst NoSQL connectivity

**Verify it's running:**

```bash
curl http://localhost:8000/health
```

Expected response:
```json
{
  "status": "ok",
  "db": "connected",
  "llm_coder": "ok",
  "llm_answer": "ok",
  "env": "development"
}
```

If `status` is `"degraded"`, check which component is `"error"` and verify your Catalyst credentials.

### 10. Start the frontend

In a separate terminal:

```bash
cd frontend
npm install
npm run dev
```

The frontend starts at `http://localhost:5173`. Vite proxies all `/api/*` requests to the backend at port 8000, so no CORS issues in development.

### 11. Log in and test

1. Open `http://localhost:5173` in your browser
2. Enter a badge number from the seeded database (e.g., `KSP-2019-0042`)
3. Enter the password: `<badge_number>123` (e.g., `KSP-2019-0042123`)
4. You'll see the chat interface with sample questions
5. Click a sample question or type your own

**Example questions to try:**
- "How many theft cases are open?"
- "Show me all cases involving Mahesh Gowda"
- "List all vehicle theft cases with the registration number"
- "Who are the top 5 repeat offenders?"
- "Show me phishing cases on WhatsApp"
- "What is the total amount defrauded in online fraud cases?"

---

## How It Works (Brief)

The system uses a **two-LLM pipeline**:

1. **Schema Linker** — keyword matching selects the 1-5 most relevant database tables for the question
2. **SQL Generation** — Qwen 2.5-7B Coder generates a MySQL SELECT query, with a self-correction loop (max 2 attempts if validation fails)
3. **SQL Validation** — checks the query is SELECT-only, uses only known tables, contains no forbidden keywords
4. **Query Execution** — runs against the MySQL database with a 5-second timeout
5. **Answer Formatting** — Qwen 2.5-14B Instruct converts raw results into a professional natural-language answer

> See [Docs.md §4.2](https://github.com/adarsh-v-h/AgenticAI-KSP/blob/main/Docs.md#42-ask-a-question-full-pipeline) for the complete end-to-end flow.

---

## API Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `POST` | `/api/auth/login` | No | Authenticate officer, returns JWT |
| `POST` | `/api/auth/logout` | Yes | Stateless logout |
| `POST` | `/api/chat` | Yes | Non-streaming chat (for testing) |
| `GET` | `/api/chat/stream` | Yes | SSE streaming chat (production path) |
| `GET` | `/health` | No | Service health check |

> See [Docs.md §3.18](https://github.com/adarsh-v-h/AgenticAI-KSP/blob/main/Docs.md#318-backendrouterschatpy) and [Docs.md §3.19](https://github.com/adarsh-v-h/AgenticAI-KSP/blob/main/Docs.md#319-backendroutersauthpy) for request/response details.

---

## Login Credentials

The seeder creates these officers (password is always `<badge_number>123`):

| Badge Number | Name | Rank |
|-------------|------|------|
| `KSP-2010-0101` | Manjunath Patil | Inspector |
| `KSP-2012-0202` | Venkatesh Gowda | PI |
| `KSP-2014-0303` | Ramesh Naik | SI |
| `KSP-2015-0404` | Sandeep Hegde | SI |
| `KSP-2016-0505` | Harish Kumar | ASI |
| `KSP-2017-0606` | Vijay Raghavendra | ASI |
| `KSP-2018-0707` | Lokesh Murthy | Head Constable |
| `KSP-2019-0808` | Shivakumar Swamy | Head Constable |
| `KSP-2020-0909` | Srinivas Raju | Constable |
| `KSP-2021-1010` | Naveen Raj | Constable |

---

## Database

13 tables in a MySQL-compatible Catalyst Data Store:

| Table | Purpose |
|-------|---------|
| `officers` | Station officers with ranks and badge numbers |
| `fir_master` | Central FIR registry — parent record for all cases |
| `accused` | Accused persons linked to FIRs |
| `victims` | Victims linked to FIRs |
| `cases_theft` | Theft-specific details (stolen items, value, recovery) |
| `cases_assault` | Assault details (weapon, severity, motive) |
| `cases_vehicle_theft` | Vehicle theft (make, model, registration) |
| `cases_fraud` | Fraud details (type, amount, method) |
| `cases_cybercrime` | Cybercrime (platform, digital evidence) |
| `cases_missing_person` | Missing person (last seen, found status) |
| `cases_drug_offense` | Drug offenses (type, quantity, value) |
| `case_relationships` | Links between entities (for network graph) |
| `evidence_media` | Media files attached to FIRs |

> Note: 4 case types (`robbery`, `murder`, `domestic_violence`, `other`) exist in `fir_master` but have no dedicated child tables. See [Docs.md §3.4](https://github.com/adarsh-v-h/AgenticAI-KSP/blob/main/Docs.md#34-backendschemasql) for details.

---

## Deployment to Zoho Catalyst

### Backend (AppSail)

The backend deploys as a Docker container on Catalyst AppSail:

```bash
# Build the image
docker build -t ksp-backend ./backend

# Deploy via Catalyst CLI or Pipelines
# The Dockerfile uses python:3.11-slim and runs uvicorn on port 8000
```

The `Dockerfile` at `backend/Dockerfile`:
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
```

### Frontend (Catalyst Slate)

The frontend is a static SPA. Build and deploy to Catalyst Slate:

```bash
cd frontend
npm run build
# Deploy the contents of frontend/dist/ to Catalyst Slate
```

### Environment Variables in Production

Update `ALLOWED_ORIGINS` in your production `.env` to your Catalyst Slate URL instead of `http://localhost:5173`. Generate a new `APP_SECRET_KEY` for production — never reuse the dev key.

---

## Troubleshooting

**Server crashes on startup with missing env vars:**
- Check your `.env` file has all 22 required variables (see `.env.example`)
- The server lists every missing variable in the error message

**Health check shows `"degraded"`:**
- `"db": "error"` — check `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`
- `"llm_coder": "error"` or `"llm_answer": "error"` — check `QUICKML_LLM_URL`, `CATALYST_API_TOKEN`, `CATALYST_ORG_ID`
- Token may have expired — regenerate using the OAuth refresh flow

**Frontend can't reach the backend:**
- Make sure the backend is running on port 8000
- Vite proxies `/api/*` to `localhost:8000` — check `vite.config.js`

**SQL generation fails or returns weird queries:**
- The LLM may not have enough context — check that the schema was seeded correctly
- Try simpler questions first ("How many cases are open?")
- Check the backend logs for SQL validation errors

---

## License

Copyright (C) 2024 adarsh.v.h <adarshvh2005@gmail.com>

This project is licensed under the **GNU Affero General Public License v3.0** — see the [LICENSE](LICENSE) file for details.

### What this means:

- **Free to use, modify, and distribute** — you can run, study, and adapt this software
- **Copyleft** — any modified version must also be released under AGPL v3
- **Network use clause** — if you run this as a service (SaaS), you must share your source code
- **Patent protection** — contributors grant patent rights to users
- **No warranty** — the software is provided "as is"

### For Karnataka State Police:

This license ensures the software remains open and transparent for law enforcement use, while preventing any party from making it proprietary. If the KSP incorporates this into production, all future modifications must remain open source under the same license.
