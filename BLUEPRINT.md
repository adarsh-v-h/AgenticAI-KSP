# KSP Crime Intelligence Chatbot — Full Project Blueprint

> **Read this entire file before writing a single line of code.**
> This is the single source of truth for architecture, tech stack, file structure, DB schema, API design, and every function you need to build.
> Two other files will be in this same folder:
> - `Improved-sys-design.png` — the system flow diagram. Refer to it.
> - `Design.md` — the frontend design spec. Follow it exactly. The UI is for a government police portal — keep it minimal, functional, no unnecessary UI chrome.

---

## 1. What You Are Building

A natural language crime intelligence chatbot for Karnataka State Police (KSP). Police officers at a single station type (or speak) a question in English or Kannada. The system converts it to SQL, queries the crime database, resolves any media attachments, formats a clean natural language answer, and streams it back to the officer. There is also an on-demand criminal network graph view.

This is **not** a general-purpose chatbot. It only queries the crime database. It never modifies data. Every generated SQL must be a SELECT statement. That is a hard constraint, not a preference.

---

## 2. Deployment Target — Zoho Catalyst

**Everything deploys on Zoho Catalyst. No external cloud services. No AWS, GCP, Azure, Firebase, Supabase, Vercel, Render, or any third-party hosting.**

### Catalyst services you have access to (use only these):

| Service | What it does | Use it for |
|---|---|---|
| Catalyst AppSail (custom OCI / Docker) | Always-on containerized backend | FastAPI backend |
| Catalyst Slate / Web Client Hosting | Static SPA hosting | React frontend |
| Catalyst Data Store | Managed MySQL-compatible relational DB | All crime + officer tables |
| Catalyst NoSQL | Document store | Conversation history, session state |
| Catalyst Cache | In-memory key-value cache | Schema cache, query result cache, session context |
| Catalyst Stratus | S3-style object storage | Media files (images, audio, video evidence) |
| Catalyst QuickML — LLM Serving | LLM API endpoints | Qwen 2.5-7B Coder (SQL gen), Qwen 2.5-14B Instruct (answer formatting) |
| Catalyst QuickML — RAG | Knowledge base + retrieval | Optional: FIR document search |
| Catalyst Zia Services — Voice | STT, TTS, Translation APIs | Voice input, Kannada translation, voice output |
| Catalyst Zia AutoML | Tabular ML model training + serving | Repeat offender risk scoring |
| Catalyst Zia Services — Text Analytics | NER, keyword extraction | Extract entities from FIR text |
| Catalyst SmartBrowz | Headless browser, PDF generation | Export conversation to PDF |
| Catalyst Authentication | User auth, sessions | Login/logout |
| Catalyst API Gateway | API routing, throttling | Sits in front of all backend routes |
| Catalyst Signals + Event Functions | DB event triggers | Alert pipeline |
| Catalyst Cron | Scheduled jobs | Cache warm-up, schema refresh |
| Catalyst Circuits | Multi-step workflow orchestration | Voice pipeline chain |
| Catalyst Pipelines | CI/CD | Build and deploy |
| Catalyst NoSQL | Session store | Auth sessions |

### What does NOT exist on Catalyst — do not add these by mistake:
- No pgvector or standalone vector database
- No Redis (use Catalyst Cache instead)
- No separate message queue (use Catalyst Signals)
- No LangChain, LlamaIndex, or any external LLM orchestration framework — all LLM calls go directly to Catalyst QuickML endpoints
- No OpenAI, Anthropic, Gemini, or any external LLM API
- No fine-tuning of any model — you cannot fine-tune models on Catalyst
- No WebSockets — use SSE (Server-Sent Events) for streaming
- No external auth providers (Auth0, Clerk, etc.) — use Catalyst Authentication

---

## 3. The Four Models Available

Call these via the Catalyst QuickML LLM endpoint. Confirm exact model identifier strings from Catalyst docs before hardcoding.

| Model | Use case in this project |
|---|---|
| `qwen2.5-7b-coder` | **SQL generation** — first LLM in the pipeline. Purpose-built for Text-to-SQL. |
| `qwen2.5-14b-instruct` | **Answer formatting** — second LLM. Formats raw DB results into natural language. Also handles conversation. |
| `qwen2.5-7b-vl` | Media understanding — only use if a query involves an uploaded image or evidence photo |
| `glm-4.7-flash` | Fallback / experimentation — test against Qwen Coder for SQL quality, use whichever scores better on your schema |

**Never call an external LLM API. All model calls go to:**
```
POST https://api.catalyst.zoho.in/quickml/v2/project/{PROJECT_ID}/llm/chat
Authorization: Zoho-oauthtoken {TOKEN}
```

---

## 4. Environment Variables

Create a `.env` file at the project root. **Never hardcode any key, token, URL, or ID anywhere in the codebase.** Every config value comes from `.env`.

```env
# Catalyst Project
CATALYST_PROJECT_ID=your_project_id_here
CATALYST_API_TOKEN=your_dev_token_here
CATALYST_BASE_URL=https://api.catalyst.zoho.in

# QuickML LLM
QUICKML_LLM_URL=https://api.catalyst.zoho.in/quickml/v2/project/${CATALYST_PROJECT_ID}/llm/chat
MODEL_SQL=qwen2.5-7b-coder
MODEL_ANSWER=qwen2.5-14b-instruct
MODEL_VISION=qwen2.5-7b-vl

# Catalyst Data Store (MySQL)
DB_HOST=your_catalyst_datastore_host
DB_PORT=3306
DB_NAME=ksp_crime_db
DB_USER=your_db_user
DB_PASSWORD=your_db_password

# Catalyst NoSQL
NOSQL_BASE_URL=https://api.catalyst.zoho.in/baas/v1/project/${CATALYST_PROJECT_ID}/nosql

# Catalyst Cache
CACHE_BASE_URL=https://api.catalyst.zoho.in/baas/v1/project/${CATALYST_PROJECT_ID}/cache

# Catalyst Stratus
STRATUS_BASE_URL=https://api.catalyst.zoho.in/baas/v1/project/${CATALYST_PROJECT_ID}/folder

# Catalyst Zia Voice
ZIA_STT_URL=https://api.catalyst.zoho.in/baas/v1/project/${CATALYST_PROJECT_ID}/ml/zia/speech/transcribe
ZIA_TTS_URL=https://api.catalyst.zoho.in/baas/v1/project/${CATALYST_PROJECT_ID}/ml/zia/speech/synthesize
ZIA_TRANSLATE_URL=https://api.catalyst.zoho.in/baas/v1/project/${CATALYST_PROJECT_ID}/ml/zia/translate

# Catalyst SmartBrowz
SMARTBROWZ_URL=https://api.catalyst.zoho.in/baas/v1/project/${CATALYST_PROJECT_ID}/smartbrowz

# App
APP_ENV=development
APP_SECRET_KEY=generate_a_random_32char_string_here
ALLOWED_ORIGINS=http://localhost:5173
```

Load all values using `python-dotenv` in the backend. Access via `os.getenv("KEY")`. If a variable is missing at startup, raise a clear error and exit — never silently fall back to defaults.

---

## 5. System Flow (follow the diagram in `Improved-sys-design.png`)

```
User Question (text or voice)
        │
        ├─[if voice]──► Zia STT ──► transcript text
        │                    │
        │               [if Kannada]──► Zia Translation ──► English text
        │
        ▼
┌─────────────────────────────────────────────────────────┐
│                      FULL CHAIN                          │
│                                                          │
│   ┌─────────────────────────────────────┐               │
│   │            SQL CHAIN                │               │
│   │                                     │               │
│   │  1. Schema Linker                   │               │
│   │     (picks relevant tables          │               │
│   │      from schema cache)             │               │
│   │             │                       │               │
│   │             ▼                       │               │
│   │  2. LLM — Qwen 2.5-7B Coder        │               │
│   │     Input:                          │               │
│   │     - User question                 │               │
│   │     - Filtered DB schema            │               │
│   │     - Conversation history          │               │
│   │     - Few-shot SQL examples         │               │
│   │     Output: raw SQL string          │               │
│   │             │                       │               │
│   │             ▼                       │               │
│   │  3. SQL Validator                   │               │
│   │     - Must be SELECT only           │               │
│   │     - Table names must exist        │               │
│   │     - Column names must exist       │               │
│   │     - No DROP/DELETE/UPDATE/INSERT  │               │
│   │     - If invalid: retry once        │               │
│   │       (send error back to LLM)      │               │
│   │     - If still invalid: return      │               │
│   │       safe error to user            │               │
│   └─────────────────────────────────────┘               │
│             │                                            │
│             ▼                                            │
│   4. Run Query → Raw Results                             │
│             │                                            │
│             ▼                                            │
│   5. Media Resolver                                      │
│      - Checks if any result row has                      │
│        media_ref (image/audio/video)                     │
│      - If yes: generate signed Stratus URLs              │
│      - Attach URLs + media_type to result payload        │
│             │                                            │
│             ▼                                            │
│   6. LLM — Qwen 2.5-14B Instruct                        │
│      Input:                                              │
│      - User question                                     │
│      - Raw query results (JSON)                          │
│      - Media refs (if any)                               │
│      - Conversation history                              │
│      Output: formatted natural language answer           │
│      (may include a table if result has multiple rows)   │
│             │                                            │
│             ▼                                            │
│   7. Stream Response via SSE                             │
│      - Tokens stream as they generate                    │
│      - Final payload includes:                           │
│        answer_text, table_data (if any),                 │
│        media_attachments (if any),                       │
│        graph_available (bool)                            │
└─────────────────────────────────────────────────────────┘
        │
        ├─[if voice mode]──► Zia TTS ──► audio response
        │
        ▼
Frontend (React SPA on Catalyst Slate)
  - Chat interface
  - Table renderer (if table_data present)
  - Media viewer (image lightbox / audio player / video player)
  - Network graph panel (vis.js, on-demand, separate API call)
```

### The Loop (AI self-correction)

The SQL generation step uses a loop. This is not optional. Implement it exactly as described:

```
attempt = 1
max_attempts = 2

while attempt <= max_attempts:
    sql = call_llm(MODEL_SQL, prompt_with_schema_and_question)
    validation_result = validate_sql(sql)
    
    if validation_result.is_valid:
        break
    else:
        if attempt == max_attempts:
            return error_response("Could not generate a valid query for this question.")
        # Build correction prompt with the error
        prompt = build_correction_prompt(sql, validation_result.error)
        attempt += 1

execute(sql)
```

This loop is the self-correction mechanism. The LLM gets its own error feedback and tries again. Never exceed 2 attempts — latency matters.

---

## 6. Database Schema

**Platform: Catalyst Data Store (MySQL-compatible)**
Single station scope: all records belong to one station.

### Why multiple case tables?

Separating case types means SQL queries are faster (smaller tables, no full-scan with WHERE clause on type) and the schema linker can inject only the relevant table for the query type. Never put all case types in one giant table.

---

### Table: `officers`

Stores all officers at this station.

```sql
CREATE TABLE officers (
    officer_id        INT AUTO_INCREMENT PRIMARY KEY,
    badge_number      VARCHAR(20) NOT NULL UNIQUE,
    full_name         VARCHAR(100) NOT NULL,
    rank              ENUM('Constable','Head Constable','ASI','SI','PI','Inspector','DySP','SP') NOT NULL,
    department        VARCHAR(50),
    phone             VARCHAR(15),
    email             VARCHAR(100),
    date_joined       DATE,
    is_active         BOOLEAN DEFAULT TRUE,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

### Table: `fir_master`

The central FIR registry. Every case starts here regardless of type. Acts as the parent record.

```sql
CREATE TABLE fir_master (
    fir_id            INT AUTO_INCREMENT PRIMARY KEY,
    fir_number        VARCHAR(30) NOT NULL UNIQUE,   -- e.g. "FIR/2024/KOR/0042"
    station_code      VARCHAR(20) NOT NULL,
    date_filed        DATE NOT NULL,
    time_filed        TIME NOT NULL,
    case_type         ENUM(
                        'theft','robbery','assault','murder','fraud',
                        'cybercrime','missing_person','vehicle_theft',
                        'drug_offense','domestic_violence','other'
                      ) NOT NULL,
    incident_date     DATE,
    incident_time     TIME,
    incident_location VARCHAR(200),
    incident_lat      DECIMAL(10, 8),
    incident_lng      DECIMAL(11, 8),
    description       TEXT,
    status            ENUM('open','under_investigation','closed','chargesheeted') DEFAULT 'open',
    investigating_officer_id INT,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    FOREIGN KEY (investigating_officer_id) REFERENCES officers(officer_id)
);

CREATE INDEX idx_fir_case_type ON fir_master(case_type);
CREATE INDEX idx_fir_status ON fir_master(status);
CREATE INDEX idx_fir_date ON fir_master(date_filed);
```

---

### Table: `accused`

All accused persons. One FIR can have multiple accused.

```sql
CREATE TABLE accused (
    accused_id        INT AUTO_INCREMENT PRIMARY KEY,
    fir_id            INT NOT NULL,
    full_name         VARCHAR(100),
    alias             VARCHAR(100),
    age               INT,
    gender            ENUM('male','female','other','unknown') DEFAULT 'unknown',
    address           TEXT,
    phone             VARCHAR(15),
    id_type           VARCHAR(30),         -- Aadhaar, PAN, etc.
    id_number         VARCHAR(50),
    prior_fir_count   INT DEFAULT 0,       -- denormalized for fast risk queries
    arrest_status     ENUM('arrested','at_large','unknown') DEFAULT 'unknown',
    arrest_date       DATE,
    notes             TEXT,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (fir_id) REFERENCES fir_master(fir_id)
);

CREATE INDEX idx_accused_fir ON accused(fir_id);
CREATE INDEX idx_accused_name ON accused(full_name);
```

---

### Table: `victims`

All victims. One FIR can have multiple victims.

```sql
CREATE TABLE victims (
    victim_id         INT AUTO_INCREMENT PRIMARY KEY,
    fir_id            INT NOT NULL,
    full_name         VARCHAR(100),
    age               INT,
    gender            ENUM('male','female','other','unknown') DEFAULT 'unknown',
    address           TEXT,
    phone             VARCHAR(15),
    injury_description TEXT,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (fir_id) REFERENCES fir_master(fir_id)
);

CREATE INDEX idx_victims_fir ON victims(fir_id);
```

---

### Table: `cases_theft`

Theft-specific details. Always join with `fir_master` on `fir_id`.

```sql
CREATE TABLE cases_theft (
    theft_id          INT AUTO_INCREMENT PRIMARY KEY,
    fir_id            INT NOT NULL UNIQUE,
    stolen_items      TEXT,               -- JSON array as text: ["laptop","phone"]
    estimated_value   DECIMAL(12,2),
    recovered         BOOLEAN DEFAULT FALSE,
    recovery_date     DATE,
    recovery_notes    TEXT,

    FOREIGN KEY (fir_id) REFERENCES fir_master(fir_id)
);
```

---

### Table: `cases_assault`

Assault and physical harm cases.

```sql
CREATE TABLE cases_assault (
    assault_id        INT AUTO_INCREMENT PRIMARY KEY,
    fir_id            INT NOT NULL UNIQUE,
    weapon_used       VARCHAR(100),
    injury_severity   ENUM('minor','moderate','severe','fatal') DEFAULT 'minor',
    motive            VARCHAR(200),
    witnesses_count   INT DEFAULT 0,

    FOREIGN KEY (fir_id) REFERENCES fir_master(fir_id)
);
```

---

### Table: `cases_vehicle_theft`

Vehicle theft has distinct attributes worth separating.

```sql
CREATE TABLE cases_vehicle_theft (
    vt_id             INT AUTO_INCREMENT PRIMARY KEY,
    fir_id            INT NOT NULL UNIQUE,
    vehicle_type      ENUM('two_wheeler','car','truck','auto','other'),
    vehicle_make      VARCHAR(50),
    vehicle_model     VARCHAR(50),
    registration_no   VARCHAR(20),
    color             VARCHAR(30),
    recovered         BOOLEAN DEFAULT FALSE,
    recovery_date     DATE,
    recovery_location VARCHAR(200),

    FOREIGN KEY (fir_id) REFERENCES fir_master(fir_id)
);
```

---

### Table: `cases_fraud`

Financial fraud and cheating cases.

```sql
CREATE TABLE cases_fraud (
    fraud_id          INT AUTO_INCREMENT PRIMARY KEY,
    fir_id            INT NOT NULL UNIQUE,
    fraud_type        ENUM('online','offline','banking','property','other'),
    amount_defrauded  DECIMAL(14,2),
    amount_recovered  DECIMAL(14,2) DEFAULT 0,
    method_used       TEXT,
    account_numbers   TEXT,               -- JSON array as text

    FOREIGN KEY (fir_id) REFERENCES fir_master(fir_id)
);
```

---

### Table: `cases_cybercrime`

```sql
CREATE TABLE cases_cybercrime (
    cyber_id          INT AUTO_INCREMENT PRIMARY KEY,
    fir_id            INT NOT NULL UNIQUE,
    cyber_type        ENUM('phishing','hacking','online_harassment','identity_theft','other'),
    platform          VARCHAR(100),       -- WhatsApp, Instagram, email, etc.
    financial_loss    DECIMAL(14,2) DEFAULT 0,
    digital_evidence  TEXT,               -- JSON: IP addresses, device IDs, URLs

    FOREIGN KEY (fir_id) REFERENCES fir_master(fir_id)
);
```

---

### Table: `cases_missing_person`

```sql
CREATE TABLE cases_missing_person (
    mp_id             INT AUTO_INCREMENT PRIMARY KEY,
    fir_id            INT NOT NULL UNIQUE,
    missing_since     DATE,
    last_seen_location VARCHAR(200),
    physical_description TEXT,
    found             BOOLEAN DEFAULT FALSE,
    found_date        DATE,
    found_location    VARCHAR(200),
    found_condition   ENUM('safe','injured','deceased','unknown'),

    FOREIGN KEY (fir_id) REFERENCES fir_master(fir_id)
);
```

---

### Table: `cases_drug_offense`

```sql
CREATE TABLE cases_drug_offense (
    drug_id           INT AUTO_INCREMENT PRIMARY KEY,
    fir_id            INT NOT NULL UNIQUE,
    drug_type         VARCHAR(100),
    quantity_seized   VARCHAR(100),
    estimated_street_value DECIMAL(12,2),
    source_location   VARCHAR(200),

    FOREIGN KEY (fir_id) REFERENCES fir_master(fir_id)
);
```

---

### Table: `case_relationships`

Links accused to other accused, and FIRs to other FIRs. Powers the network graph.

```sql
CREATE TABLE case_relationships (
    rel_id            INT AUTO_INCREMENT PRIMARY KEY,
    entity_a_type     ENUM('accused','fir','victim','officer') NOT NULL,
    entity_a_id       INT NOT NULL,
    entity_b_type     ENUM('accused','fir','victim','officer') NOT NULL,
    entity_b_id       INT NOT NULL,
    relationship_type ENUM(
                        'co_accused','repeat_location','same_modus_operandi',
                        'linked_gang','victim_of_same_accused','related_case'
                      ) NOT NULL,
    notes             TEXT,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_rel_a ON case_relationships(entity_a_type, entity_a_id);
CREATE INDEX idx_rel_b ON case_relationships(entity_b_type, entity_b_id);
```

---

### Table: `evidence_media`

Links evidence files (stored in Catalyst Stratus) to FIRs.

```sql
CREATE TABLE evidence_media (
    media_id          INT AUTO_INCREMENT PRIMARY KEY,
    fir_id            INT NOT NULL,
    media_type        ENUM('image','audio','video','document') NOT NULL,
    file_name         VARCHAR(200) NOT NULL,
    stratus_folder_id VARCHAR(100) NOT NULL,   -- Catalyst Stratus folder ID
    stratus_file_id   VARCHAR(100) NOT NULL,   -- Catalyst Stratus file ID
    description       VARCHAR(500),
    uploaded_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (fir_id) REFERENCES fir_master(fir_id)
);

CREATE INDEX idx_media_fir ON evidence_media(fir_id);
```

---

### Schema Annotations (for the Schema Linker)

Store a static schema description object in your backend code (also cached in Catalyst Cache). Each table entry includes: table name, description, columns, and which keywords in a user query should trigger including this table.

```python
SCHEMA_CATALOG = {
    "fir_master": {
        "description": "Central FIR registry. Parent record for all cases.",
        "keywords": ["fir", "case", "filed", "station", "status", "date", "location", "officer", "all cases"],
        "always_include": True   # always inject this table
    },
    "accused": {
        "description": "All accused persons linked to FIRs.",
        "keywords": ["accused", "suspect", "arrested", "offender", "person", "name", "criminal"]
    },
    "victims": {
        "description": "All victims linked to FIRs.",
        "keywords": ["victim", "complainant", "injured", "affected"]
    },
    "cases_theft": {
        "description": "Theft case details — stolen items, value, recovery.",
        "keywords": ["theft", "stolen", "burglary", "robbery", "items", "valuables"]
    },
    "cases_assault": {
        "description": "Assault case details — weapon, severity, motive.",
        "keywords": ["assault", "attack", "fight", "weapon", "injury", "violence", "beat"]
    },
    "cases_vehicle_theft": {
        "description": "Vehicle theft — make, model, registration, recovery.",
        "keywords": ["vehicle", "bike", "car", "motorcycle", "auto", "registration", "two wheeler"]
    },
    "cases_fraud": {
        "description": "Fraud cases — type, amount, method.",
        "keywords": ["fraud", "cheat", "scam", "money", "financial", "banking", "deceive"]
    },
    "cases_cybercrime": {
        "description": "Cybercrime — platform, type, digital evidence.",
        "keywords": ["cyber", "online", "hacking", "phishing", "internet", "whatsapp", "social media"]
    },
    "cases_missing_person": {
        "description": "Missing person cases — last seen, found status.",
        "keywords": ["missing", "lost", "disappeared", "found", "search"]
    },
    "cases_drug_offense": {
        "description": "Drug offense — drug type, quantity seized.",
        "keywords": ["drug", "narcotics", "ganja", "cocaine", "seized", "contraband"]
    },
    "case_relationships": {
        "description": "Links between accused, FIRs, victims — for network analysis.",
        "keywords": ["linked", "connected", "gang", "network", "related", "associate"]
    },
    "evidence_media": {
        "description": "Media evidence files (images, audio, video) attached to FIRs.",
        "keywords": ["photo", "image", "video", "audio", "evidence", "file", "attachment"]
    },
    "officers": {
        "description": "Officers at the station.",
        "keywords": ["officer", "inspector", "constable", "SI", "PI", "assigned", "investigating"]
    }
}
```

---

## 7. File Structure

```
project-root/
├── .env                          # All environment variables — never commit
├── .gitignore                    # Must include .env
├── Improved-sys-design.png       # System design reference (do not modify)
├── Design.md                     # Frontend design spec (follow exactly)
├── BLUEPRINT.md                  # This file
│
├── backend/
│   ├── Dockerfile                # Python 3.11-slim base, for Catalyst AppSail
│   ├── requirements.txt
│   ├── main.py                   # FastAPI app entry point
│   │
│   ├── config/
│   │   └── settings.py           # Loads and validates all .env variables at startup
│   │
│   ├── db/
│   │   ├── connection.py         # MySQL connection pool (aiomysql)
│   │   ├── schema.sql            # Full CREATE TABLE statements (from section 6)
│   │   ├── seed.py               # Synthetic data seeder — 200+ realistic records
│   │   └── schema_catalog.py     # SCHEMA_CATALOG dict + schema linker logic
│   │
│   ├── llm/
│   │   ├── client.py             # All Catalyst QuickML LLM API calls
│   │   ├── sql_generator.py      # SQL Chain: prompt builder + Qwen Coder call
│   │   ├── answer_formatter.py   # Answer Chain: Qwen 14B formats raw results
│   │   └── prompts.py            # All system prompts and few-shot examples
│   │
│   ├── pipeline/
│   │   ├── query_pipeline.py     # Orchestrates the full chain (the main pipeline)
│   │   ├── sql_validator.py      # SQL validation + sanitization
│   │   ├── media_resolver.py     # Checks results for media refs, generates signed URLs
│   │   └── schema_linker.py      # Picks relevant tables from SCHEMA_CATALOG
│   │
│   ├── voice/
│   │   └── zia_voice.py          # Zia STT, TTS, Translation wrappers
│   │
│   ├── graph/
│   │   └── network_builder.py    # Queries case_relationships, returns graph JSON
│   │
│   ├── conversation/
│   │   └── history.py            # Read/write conversation history in Catalyst NoSQL
│   │
│   ├── cache/
│   │   └── catalyst_cache.py     # Catalyst Cache read/write wrappers
│   │
│   ├── storage/
│   │   └── stratus.py            # Catalyst Stratus: upload, signed URL generation
│   │
│   ├── export/
│   │   └── pdf_export.py         # SmartBrowz: render conversation as PDF
│   │
│   ├── auth/
│   │   └── simple_auth.py        # Simple JWT auth (temporary — replace with Catalyst Auth on deploy)
│   │
│   └── routers/
│       ├── chat.py               # POST /api/chat + GET /api/chat/stream (SSE)
│       ├── voice.py              # POST /api/voice/transcribe, /api/voice/speak
│       ├── graph.py              # GET /api/graph/{fir_id} or /api/graph/accused/{accused_id}
│       ├── export.py             # POST /api/export/pdf
│       └── auth.py               # POST /api/auth/login, /api/auth/logout
│
└── frontend/
    ├── index.html
    ├── package.json
    ├── vite.config.js
    ├── .env                      # VITE_API_BASE_URL only
    │
    └── src/
        ├── main.jsx
        ├── App.jsx
        │
        ├── api/
        │   ├── chat.js           # Chat API calls + SSE stream handler
        │   ├── voice.js          # Voice API calls
        │   ├── graph.js          # Graph API calls
        │   └── auth.js           # Auth API calls
        │
        ├── components/
        │   ├── ChatWindow.jsx    # Main chat interface
        │   ├── MessageBubble.jsx # Single message display
        │   ├── TableRenderer.jsx # Renders tabular query results
        │   ├── MediaViewer.jsx   # Image lightbox / audio / video player
        │   ├── NetworkGraph.jsx  # vis.js network graph panel
        │   ├── VoiceInput.jsx    # Mic button + recording state
        │   └── LoginPage.jsx     # Simple login form
        │
        ├── hooks/
        │   ├── useSSE.js         # SSE stream connection hook
        │   └── useAuth.js        # Auth state hook
        │
        └── styles/
            └── main.css          # Minimal government-appropriate styling per Design.md
```

---

## 8. Backend — Every Function, What It Does

### `config/settings.py`
```python
def load_settings() -> Settings:
    """
    Load all env vars at startup. Raise ValueError with a clear message
    if any required variable is missing. Return a Settings dataclass.
    Never use default values for secrets or URLs.
    """
```

---

### `db/connection.py`
```python
async def get_db_pool() -> aiomysql.Pool:
    """
    Create and return a connection pool to Catalyst Data Store.
    Pool size: min=3, max=10.
    Called once at FastAPI startup, stored in app.state.db_pool.
    """

async def execute_query(pool, sql: str, params: tuple = ()) -> list[dict]:
    """
    Execute a SELECT query. Return results as list of dicts.
    Enforce 5-second query timeout.
    Never accept non-SELECT statements — raise ValueError if attempted.
    """
```

---

### `db/schema_catalog.py`
```python
def get_schema_for_tables(table_names: list[str]) -> str:
    """
    Given a list of table names, return a compact schema string
    (table name, columns, types, PKs, FKs) suitable for LLM prompt injection.
    Always include fir_master. Never exceed 2000 tokens.
    """

def get_few_shot_examples(table_names: list[str]) -> str:
    """
    Return 3-5 example NL→SQL pairs relevant to the selected tables.
    Used in the SQL generation prompt.
    """
```

---

### `db/seed.py`
```python
async def seed_database(pool):
    """
    Insert synthetic data:
    - 10 officers with realistic Karnataka names, ranks, badge numbers
    - 200 FIRs spread across all case types, 2022-2025
    - Accused and victims for each FIR
    - Type-specific records in each cases_* table
    - 30 case_relationships entries forming 2-3 visible gang clusters
    - 20 evidence_media records pointing to placeholder Stratus file IDs
    
    Make the data geographically coherent — use real Bengaluru area names
    (Koramangala, Indiranagar, Jayanagar, Shivajinagar, Yeshwanthpur etc.)
    Make 5 accused appear in 3+ FIRs each — these are your repeat offenders.
    Make one accused appear in 8 FIRs — this is your demo star.
    """
```

---

### `llm/client.py`
```python
async def call_llm(model: str, messages: list[dict], max_tokens: int = 1000) -> str:
    """
    POST to Catalyst QuickML LLM endpoint.
    messages format: [{"role": "system", ...}, {"role": "user", ...}]
    Return the assistant's text content only.
    Raise LLMError with message on non-200 response.
    Timeout: 25 seconds.
    """

async def call_llm_stream(model: str, messages: list[dict]):
    """
    Same as call_llm but returns an async generator yielding token chunks.
    Used for the answer formatter step (streaming to frontend via SSE).
    """
```

---

### `llm/prompts.py`
```python
SQL_SYSTEM_PROMPT = """
You are a SQL expert for a Karnataka State Police crime database.
Your ONLY job is to write a valid MySQL SELECT query.
Rules:
- Only use tables and columns from the schema provided.
- Only write SELECT statements. Never write INSERT, UPDATE, DELETE, DROP, CREATE, or ALTER.
- Always join with fir_master when querying case-type tables.
- Return ONLY the SQL query. No explanation. No markdown. No backticks.
- If the question cannot be answered with the given schema, return: CANNOT_ANSWER
"""

ANSWER_SYSTEM_PROMPT = """
You are a police intelligence assistant helping Karnataka State Police officers.
You receive raw database query results and must format them as a clear, professional answer.
Rules:
- Be concise. Officers are busy.
- If the result has multiple rows, format as a markdown table.
- If media attachments are present, mention them clearly: "This case has 2 attached photos."
- Never add information not present in the data.
- Never speculate. If the data doesn't have an answer, say so clearly.
- Use plain English. No technical jargon.
"""

def build_sql_prompt(question: str, schema: str, history: list, few_shots: str) -> list[dict]:
    """Build the messages array for the SQL generation LLM call."""

def build_answer_prompt(question: str, results: list[dict], history: list, media_refs: list) -> list[dict]:
    """Build the messages array for the answer formatting LLM call."""

def build_correction_prompt(original_sql: str, error: str, schema: str) -> list[dict]:
    """Build the correction prompt when SQL validation fails. Include the error message."""
```

---

### `pipeline/schema_linker.py`
```python
def select_relevant_tables(question: str) -> list[str]:
    """
    Given a user question, return list of relevant table names.
    Algorithm:
    1. Lowercase the question
    2. For each table in SCHEMA_CATALOG, check if any keyword matches
    3. Always include fir_master
    4. Cap at 5 tables maximum to avoid context overflow
    Returns list of table names.
    """
```

---

### `pipeline/sql_validator.py`
```python
FORBIDDEN_KEYWORDS = ["drop", "delete", "update", "insert", "create", "alter", "truncate", "--", ";--", "/*"]

def validate_sql(sql: str, allowed_tables: list[str]) -> ValidationResult:
    """
    Validate generated SQL.
    Checks:
    1. Not empty, not "CANNOT_ANSWER" (handle separately)
    2. Starts with SELECT (case-insensitive)
    3. No forbidden keywords (check FORBIDDEN_KEYWORDS list)
    4. All table names in the query exist in allowed_tables or fir_master
    Returns ValidationResult(is_valid: bool, error: str | None)
    """
```

---

### `pipeline/media_resolver.py`
```python
async def resolve_media(results: list[dict], pool) -> tuple[list[dict], list[dict]]:
    """
    Check results for fir_id values.
    Query evidence_media table for any media attached to those fir_ids.
    For each media record found, generate a signed Stratus URL.
    Return (enriched_results, media_attachments).
    media_attachments format: [{"media_type": "image", "url": "...", "description": "..."}]
    """
```

---

### `pipeline/query_pipeline.py`
```python
async def run_pipeline(
    question: str,
    session_id: str,
    pool,
    voice_mode: bool = False
) -> AsyncGenerator[str, None]:
    """
    The main pipeline. Orchestrates everything. Yields SSE chunks.
    
    Steps:
    1. Load conversation history from NoSQL (last 6 turns)
    2. Schema linker: select relevant tables
    3. Get schema string + few-shot examples for selected tables
    4. SQL generation loop (max 2 attempts):
       a. Call Qwen 2.5-7B Coder
       b. Validate SQL
       c. If invalid: build correction prompt, retry
       d. If still invalid after 2 attempts: yield error event, return
    5. Execute SQL query
    6. Media resolver: check for and resolve media attachments
    7. Answer formatter: stream Qwen 14B response
       - Yield tokens as SSE events
    8. Save full turn (question + answer) to NoSQL history
    9. If graph data available: yield graph_available event
    
    SSE event format:
    - data: {"type": "token", "content": "..."}
    - data: {"type": "table", "data": [...]}
    - data: {"type": "media", "attachments": [...]}
    - data: {"type": "graph_available", "fir_ids": [...]}
    - data: {"type": "error", "message": "..."}
    - data: {"type": "done"}
    """
```

---

### `conversation/history.py`
```python
async def get_history(session_id: str) -> list[dict]:
    """
    Fetch last 6 conversation turns from Catalyst NoSQL for this session_id.
    Return as list: [{"role": "user"|"assistant", "content": "..."}]
    If no history: return empty list.
    """

async def save_turn(session_id: str, user_message: str, assistant_message: str):
    """
    Append a turn to the session's history in Catalyst NoSQL.
    Keep only the last 10 turns (pop oldest if over 10).
    """

async def clear_history(session_id: str):
    """Delete all history for this session."""
```

---

### `cache/catalyst_cache.py`
```python
async def cache_get(key: str) -> str | None:
    """GET from Catalyst Cache. Return None if miss."""

async def cache_set(key: str, value: str, ttl_seconds: int = 900):
    """SET in Catalyst Cache with TTL."""

async def get_cached_schema(table_names: list[str]) -> str | None:
    """
    Try to get pre-formatted schema string from cache.
    Cache key: "schema:" + sorted joined table names
    """

async def set_cached_schema(table_names: list[str], schema_str: str):
    """Cache schema string. TTL: 1 hour."""
```

---

### `voice/zia_voice.py`
```python
async def transcribe_audio(audio_bytes: bytes, language: str = "en") -> str:
    """
    POST audio to Catalyst Zia STT endpoint.
    Return transcript text.
    """

async def translate_to_english(text: str, source_language: str = "kn") -> str:
    """
    POST text to Catalyst Zia Translation endpoint.
    source_language: "kn" for Kannada
    Return English translation.
    """

async def synthesize_speech(text: str, language: str = "en") -> bytes:
    """
    POST text to Catalyst Zia TTS endpoint.
    Return audio bytes (MP3 or WAV depending on Zia response).
    """
```

---

### `graph/network_builder.py`
```python
async def build_graph_for_fir(fir_id: int, pool) -> dict:
    """
    Query case_relationships for all entities connected to this fir_id.
    Also query accused for this FIR.
    Return vis.js-compatible graph:
    {
        "nodes": [{"id": "accused_12", "label": "Ravi Kumar", "group": "accused"}, ...],
        "edges": [{"from": "accused_12", "to": "accused_15", "label": "co_accused"}, ...]
    }
    Max 50 nodes. If more, keep top 50 by connection count.
    """

async def build_graph_for_accused(accused_id: int, pool) -> dict:
    """
    Same as above but starting from an accused person.
    Show all FIRs they appear in and co-accused.
    """
```

---

### `storage/stratus.py`
```python
async def generate_signed_url(folder_id: str, file_id: str, expiry_seconds: int = 3600) -> str:
    """
    Generate a signed URL for a Stratus file.
    URL valid for expiry_seconds (default 1 hour).
    Return the URL string.
    """
```

---

### `export/pdf_export.py`
```python
async def export_conversation_pdf(session_id: str, history: list[dict]) -> bytes:
    """
    Render conversation history as an HTML template.
    Pass to Catalyst SmartBrowz to convert to PDF.
    Return PDF bytes.
    Store PDF in Catalyst Stratus.
    Return download URL.
    """
```

---

### `auth/simple_auth.py`

> **Note:** This is a temporary, minimal auth for local development and early testing.
> When deploying to Catalyst production, replace with Catalyst Authentication (session-based).
> The session-based auth swap should require zero changes to routes — just replace the `get_current_officer` dependency.

```python
def create_access_token(officer_id: int, badge_number: str) -> str:
    """
    Create a signed JWT with officer_id, badge_number, exp (24 hours).
    Sign with APP_SECRET_KEY from env.
    """

def verify_token(token: str) -> dict:
    """
    Verify JWT signature and expiry.
    Return payload dict.
    Raise HTTPException 401 if invalid or expired.
    """

async def get_current_officer(token: str = Depends(oauth2_scheme)) -> dict:
    """
    FastAPI dependency. Extracts and verifies token.
    Inject into any route that requires auth: officer = Depends(get_current_officer)
    """

async def login(badge_number: str, password: str, pool) -> str:
    """
    Look up officer by badge_number in DB.
    For now: password is just badge_number + "123" (placeholder).
    Return JWT token on success.
    Raise HTTPException 401 on failure.
    """
```

---

### `routers/chat.py`
```python
@router.post("/api/chat")
async def chat(request: ChatRequest, officer = Depends(get_current_officer)):
    """
    Non-streaming version. For testing only.
    Runs full pipeline, returns complete response.
    ChatRequest: { question: str, session_id: str, voice_mode: bool }
    """

@router.get("/api/chat/stream")
async def chat_stream(question: str, session_id: str, officer = Depends(get_current_officer)):
    """
    SSE streaming version. This is the production path.
    Returns EventSourceResponse.
    Frontend connects and receives token chunks as they stream.
    """
```

---

### `routers/voice.py`
```python
@router.post("/api/voice/transcribe")
async def transcribe(audio: UploadFile, language: str = "en", officer = Depends(get_current_officer)):
    """Accept audio file. Return transcript text. Detect if Kannada, auto-translate."""

@router.post("/api/voice/speak")
async def speak(text: str, officer = Depends(get_current_officer)):
    """Accept text. Return audio file via Zia TTS."""
```

---

### `routers/graph.py`
```python
@router.get("/api/graph/fir/{fir_id}")
async def graph_by_fir(fir_id: int, officer = Depends(get_current_officer)):
    """Return vis.js graph JSON for a given FIR."""

@router.get("/api/graph/accused/{accused_id}")
async def graph_by_accused(accused_id: int, officer = Depends(get_current_officer)):
    """Return vis.js graph JSON for a given accused person."""
```

---

## 9. Frontend — What Each Component Does

Follow `Design.md` exactly for all visual decisions. The UI is for a government police portal — not a consumer app. Clean, functional, minimal. No animations beyond SSE token streaming. No gradients. No dark mode toggle.

### Component responsibilities:

**`ChatWindow.jsx`** — Main layout. Holds message list, input bar, voice button, export button. Manages SSE connection via `useSSE` hook. Passes streaming tokens to the active `MessageBubble`.

**`MessageBubble.jsx`** — Renders a single message. If `table_data` present, renders `TableRenderer`. If `media_attachments` present, renders `MediaViewer`. If `graph_available` present, shows "View network graph" button that opens `NetworkGraph`.

**`TableRenderer.jsx`** — Takes an array of objects, renders as an HTML table. Sortable by column. Exportable row. No external table library — build it plain.

**`MediaViewer.jsx`** — Receives array of `{media_type, url, description}`. For `image`: lightbox on click. For `audio`: HTML5 `<audio>` player. For `video`: HTML5 `<video>` player. No external media library.

**`NetworkGraph.jsx`** — Calls `/api/graph/fir/{id}` on mount. Renders vis.js Network. Node groups: accused (red), victim (blue), fir (gray), officer (green). On node click: show a details panel. Default: show top 30 nodes.

**`VoiceInput.jsx`** — Mic button. On click: start MediaRecorder. On stop: POST audio to `/api/voice/transcribe`. Inject transcript into chat input. Show recording state clearly.

**`LoginPage.jsx`** — Badge number + password fields. POST to `/api/auth/login`. Store JWT in memory (not localStorage). Redirect to chat on success.

### `hooks/useSSE.js`
```javascript
function useSSE(url, onToken, onTable, onMedia, onGraphAvailable, onDone, onError) {
    /*
    Opens an EventSource connection to the streaming chat endpoint.
    Parses incoming events by type:
    - token: append to current message
    - table: pass table_data to onTable
    - media: pass attachments to onMedia
    - graph_available: pass fir_ids to onGraphAvailable
    - error: call onError
    - done: call onDone, close connection
    Clean up EventSource on component unmount.
    */
}
```

---

## 10. Performance Rules

These are non-negotiable. Never make a decision that reduces performance.

1. **Minimum API calls.** The schema string is built once per unique table combination and cached in Catalyst Cache for 1 hour. Never rebuild it on every request.

2. **Conversation history** is fetched once at the start of the pipeline and passed through all steps. Never fetch it twice.

3. **DB connection pool** is created once at FastAPI startup (`app.state.db_pool`). Never open a new connection per request.

4. **The SQL chain and answer chain share the same conversation history object.** Fetch once, pass through. Never fetch separately.

5. **Media resolution is lazy.** Only query `evidence_media` if the raw SQL results contain at least one `fir_id`. Don't run it on every query.

6. **AppSail, not Serverless Functions, for the backend.** AppSail is always-on and avoids cold starts. This is critical for demo performance.

7. **SSE streaming starts immediately.** The answer formatter begins streaming tokens as soon as the LLM starts responding. The user sees text appearing, not a blank screen with a spinner.

8. **Graph endpoint is separate from the chat pipeline.** Never compute graph data inside the chat pipeline. It's on-demand via a separate API call triggered by a frontend button.

9. **Never log sensitive data.** No logging of officer identifiers, FIR numbers, accused names, or query contents to any output that could be persisted. Logs should contain only: timestamp, route, latency, status code.

---

## 11. Security Rules

1. All SQL is generated by the LLM and validated before execution. The validator is the gatekeeper — never bypass it.
2. The forbidden keyword list in `sql_validator.py` is checked before every query execution. No exceptions.
3. All API routes except `/api/auth/login` require a valid JWT via `Depends(get_current_officer)`.
4. All secrets and config come from `.env`. Never hardcode. Never log.
5. Stratus URLs are signed with expiry. Never expose permanent file URLs.
6. CORS: only allow the specific frontend origin from `.env ALLOWED_ORIGINS`. Never `*`.
7. Audio files from voice input are processed in memory and never written to disk.
8. On invalid token: return HTTP 401 immediately. No fallback, no retry.

---

## 12. Docker Setup for AppSail

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
```

**`requirements.txt`** must include:
```
fastapi
uvicorn[standard]
aiomysql
httpx
python-dotenv
python-jose[cryptography]
python-multipart
sse-starlette
pydantic
pydantic-settings
```

No LangChain. No LlamaIndex. No OpenAI SDK. No external LLM libraries. All LLM calls are direct HTTP via httpx.

---

## 13. What to Build First — Order of Operations

Build in this exact order. Do not skip ahead. Each step must work before moving to the next.

1. `.env` + `config/settings.py` — verify all vars load, crash on missing
2. `db/connection.py` — connect to Catalyst Data Store, run a test query
3. `db/schema.sql` — create all tables
4. `db/seed.py` — insert synthetic data, verify with a direct DB query
5. `llm/client.py` — ping both models with "What is 2+2?", confirm responses
6. `db/schema_catalog.py` + `pipeline/schema_linker.py` — verify table selection logic
7. `pipeline/sql_validator.py` — unit test with valid and invalid SQL strings
8. `llm/sql_generator.py` — test SQL generation on 10 sample questions
9. `pipeline/query_pipeline.py` — wire it all together, test non-streaming
10. `routers/chat.py` non-streaming endpoint — test with curl/Postman
11. SSE streaming — add to pipeline, test in browser
12. `conversation/history.py` — add history, test multi-turn
13. `auth/simple_auth.py` + login route — protect all routes
14. Frontend — build after backend is confirmed working
15. `graph/network_builder.py` + `NetworkGraph.jsx` — add last
16. `voice/zia_voice.py` + voice routes — add last

---

## 14. Things You Must Never Do

- Never call any external LLM API (OpenAI, Anthropic, Gemini, etc.)
- Never use LangChain, LlamaIndex, or any LLM orchestration framework
- Never use Redis, Pinecone, Weaviate, or any external database/cache
- Never use WebSockets (use SSE for streaming)
- Never store JWT tokens in localStorage (keep in memory only)
- Never log sensitive data (names, FIR numbers, query content)
- Never execute a SQL query without running it through `sql_validator.py` first
- Never hardcode any API key, token, URL, or project ID
- Never add UI animations, gradients, or consumer-app styling — this is a government portal
- Never run more than 2 LLM calls per user query (1 for SQL, 1 for answer)
- Never fetch conversation history more than once per pipeline run
- Never open more than one DB connection per request (use the pool)
- Never bypass authentication on any route except `/api/auth/login`
