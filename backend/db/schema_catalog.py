"""
Schema catalog — table descriptions, columns, and keywords for the schema linker.
Used by:
  - pipeline.schema_linker.select_relevant_tables()
  - get_schema_for_tables() to build a compact LLM prompt string
  - get_few_shot_examples() to inject example NL->SQL pairs
"""

# Maximum compact-schema size (chars) injected into the LLM SQL prompt.
# Keep modest — Qwen Coder 7B context is finite and prompt cost == latency.
_MAX_SCHEMA_CHARS = 3000

SCHEMA_CATALOG = {
    "fir_master": {
        "description": "Central FIR registry. Parent record for all cases. Every case starts here.",
        "columns": {
            "fir_id": "INT PRIMARY KEY",
            "fir_number": "VARCHAR(30) UNIQUE - format: FIR/YEAR/PREFIX/SEQ e.g. FIR/2024/KOR/0042",
            "station_code": "VARCHAR(20)",
            "date_filed": "DATE",
            "time_filed": "TIME",
            "case_type": "ENUM: theft, robbery, assault, murder, fraud, cybercrime, missing_person, vehicle_theft, drug_offense, domestic_violence, other",
            "incident_date": "DATE",
            "incident_time": "TIME",
            "incident_location": "VARCHAR(200) - Bengaluru area name e.g. Koramangala",
            "incident_lat": "DECIMAL(10,8)",
            "incident_lng": "DECIMAL(11,8)",
            "description": "TEXT",
            "status": "ENUM: open, under_investigation, closed, chargesheeted",
            "investigating_officer_id": "INT FOREIGN KEY -> officers.officer_id",
        },
        "keywords": [
            "fir", "case", "filed", "station", "status", "date", "location",
            "all cases", "incident", "report", "complaint", "open", "closed",
            "chargesheeted", "under investigation",
        ],
        "always_include": True,
    },
    "accused": {
        "description": "All accused persons linked to FIRs. One FIR can have multiple accused.",
        "columns": {
            "accused_id": "INT PRIMARY KEY",
            "fir_id": "INT FOREIGN KEY -> fir_master.fir_id",
            "full_name": "VARCHAR(100)",
            "alias": "VARCHAR(100)",
            "age": "INT",
            "gender": "ENUM: male, female, other, unknown",
            "address": "TEXT",
            "phone": "VARCHAR(15)",
            "prior_fir_count": "INT - number of previous FIRs this person has been accused in",
            "arrest_status": "ENUM: arrested, at_large, unknown",
            "arrest_date": "DATE",
        },
        "keywords": [
            "accused", "suspect", "arrested", "offender", "criminal", "person",
            "name", "at large", "at_large", "repeat", "prior", "habitual",
            "gang", "mahesh", "ravi", "suresh", "pavan", "anand", "bullet",
        ],
    },
    "victims": {
        "description": "All victims linked to FIRs. One FIR can have multiple victims.",
        "columns": {
            "victim_id": "INT PRIMARY KEY",
            "fir_id": "INT FOREIGN KEY -> fir_master.fir_id",
            "full_name": "VARCHAR(100)",
            "age": "INT",
            "gender": "ENUM: male, female, other, unknown",
            "address": "TEXT",
            "phone": "VARCHAR(15)",
            "injury_description": "TEXT",
        },
        "keywords": [
            "victim", "complainant", "injured", "affected", "hurt", "attacked",
        ],
    },
    "cases_theft": {
        "description": "Theft case details. Join with fir_master on fir_id.",
        "columns": {
            "theft_id": "INT PRIMARY KEY",
            "fir_id": "INT FOREIGN KEY -> fir_master.fir_id",
            "stolen_items": "TEXT (JSON array as string)",
            "estimated_value": "DECIMAL(12,2)",
            "recovered": "BOOLEAN",
            "recovery_date": "DATE",
        },
        "keywords": [
            "theft", "stolen", "burglary", "items", "valuables", "recover",
            "missing items", "break-in", "break in",
        ],
    },
    "cases_assault": {
        "description": "Assault case details. Join with fir_master on fir_id.",
        "columns": {
            "assault_id": "INT PRIMARY KEY",
            "fir_id": "INT FOREIGN KEY -> fir_master.fir_id",
            "weapon_used": "VARCHAR(100)",
            "injury_severity": "ENUM: minor, moderate, severe, fatal",
            "motive": "VARCHAR(200)",
            "witnesses_count": "INT",
        },
        "keywords": [
            "assault", "attack", "fight", "weapon", "injury", "violence",
            "beat", "hit", "stab", "severity",
        ],
    },
    "cases_vehicle_theft": {
        "description": "Vehicle theft details. Join with fir_master on fir_id.",
        "columns": {
            "vt_id": "INT PRIMARY KEY",
            "fir_id": "INT FOREIGN KEY -> fir_master.fir_id",
            "vehicle_type": "ENUM: two_wheeler, car, truck, auto, other",
            "vehicle_make": "VARCHAR(50)",
            "vehicle_model": "VARCHAR(50)",
            "registration_no": "VARCHAR(20) - Karnataka format: KA-XX-XX-XXXX",
            "color": "VARCHAR(30)",
            "recovered": "BOOLEAN",
        },
        "keywords": [
            "vehicle", "bike", "car", "motorcycle", "auto", "registration",
            "two wheeler", "two_wheeler", "scooter", "truck", "ka-",
        ],
    },
    "cases_fraud": {
        "description": "Fraud case details. Join with fir_master on fir_id.",
        "columns": {
            "fraud_id": "INT PRIMARY KEY",
            "fir_id": "INT FOREIGN KEY -> fir_master.fir_id",
            "fraud_type": "ENUM: online, offline, banking, property, other",
            "amount_defrauded": "DECIMAL(14,2)",
            "amount_recovered": "DECIMAL(14,2)",
            "method_used": "TEXT",
        },
        "keywords": [
            "fraud", "cheat", "scam", "money", "financial", "banking",
            "deceive", "amount", "rupees", "lakhs", "defrauded",
        ],
    },
    "cases_cybercrime": {
        "description": "Cybercrime case details. Join with fir_master on fir_id.",
        "columns": {
            "cyber_id": "INT PRIMARY KEY",
            "fir_id": "INT FOREIGN KEY -> fir_master.fir_id",
            "cyber_type": "ENUM: phishing, hacking, online_harassment, identity_theft, other",
            "platform": "VARCHAR(100) - WhatsApp, Instagram, email, Facebook etc.",
            "financial_loss": "DECIMAL(14,2)",
            "digital_evidence": "TEXT (JSON)",
        },
        "keywords": [
            "cyber", "online", "hacking", "phishing", "internet", "whatsapp",
            "social media", "instagram", "email", "digital", "otp",
            "identity theft", "harassment",
        ],
    },
    "cases_missing_person": {
        "description": "Missing person case details. Join with fir_master on fir_id.",
        "columns": {
            "mp_id": "INT PRIMARY KEY",
            "fir_id": "INT FOREIGN KEY -> fir_master.fir_id",
            "missing_since": "DATE",
            "last_seen_location": "VARCHAR(200)",
            "physical_description": "TEXT",
            "found": "BOOLEAN",
            "found_date": "DATE",
            "found_condition": "ENUM: safe, injured, deceased, unknown",
        },
        "keywords": [
            "missing", "lost", "disappeared", "found", "search", "last seen",
            "whereabouts", "missing person",
        ],
    },
    "cases_drug_offense": {
        "description": "Drug offense case details. Join with fir_master on fir_id.",
        "columns": {
            "drug_id": "INT PRIMARY KEY",
            "fir_id": "INT FOREIGN KEY -> fir_master.fir_id",
            "drug_type": "VARCHAR(100) - ganja, cocaine, heroin, MDMA etc.",
            "quantity_seized": "VARCHAR(100)",
            "estimated_street_value": "DECIMAL(12,2)",
        },
        "keywords": [
            "drug", "narcotics", "ganja", "cocaine", "heroin", "seized",
            "contraband", "substance", "possession", "mdma",
        ],
    },
    "case_relationships": {
        "description": "Links between accused, FIRs, victims for network analysis.",
        "columns": {
            "rel_id": "INT PRIMARY KEY",
            "entity_a_type": "ENUM: accused, fir, victim, officer",
            "entity_a_id": "INT",
            "entity_b_type": "ENUM: accused, fir, victim, officer",
            "entity_b_id": "INT",
            "relationship_type": "ENUM: co_accused, repeat_location, same_modus_operandi, linked_gang, victim_of_same_accused, related_case",
        },
        "keywords": [
            "linked", "connected", "gang", "network", "related", "associate",
            "co-accused", "co_accused", "same gang", "accomplice",
            "relationship", "modus operandi",
        ],
    },
    "evidence_media": {
        "description": "Media evidence files (images, audio, video) attached to FIRs.",
        "columns": {
            "media_id": "INT PRIMARY KEY",
            "fir_id": "INT FOREIGN KEY -> fir_master.fir_id",
            "media_type": "ENUM: image, audio, video, document",
            "file_name": "VARCHAR(200)",
            "stratus_folder_id": "VARCHAR(100)",
            "stratus_file_id": "VARCHAR(100)",
            "description": "VARCHAR(500)",
        },
        "keywords": [
            "photo", "image", "video", "audio", "evidence", "file",
            "attachment", "picture", "footage", "recording", "cctv",
            "document",
        ],
    },
    "officers": {
        "description": "Officers at the station.",
        "columns": {
            "officer_id": "INT PRIMARY KEY",
            "badge_number": "VARCHAR(20) UNIQUE",
            "full_name": "VARCHAR(100)",
            "rank": "ENUM: Constable, Head Constable, ASI, SI, PI, Inspector, DySP, SP (NOTE: rank is a reserved word in MySQL — escape with backticks: `rank`)",
            "department": "VARCHAR(50)",
            "phone": "VARCHAR(15)",
            "email": "VARCHAR(100)",
            "is_active": "BOOLEAN",
        },
        "keywords": [
            "officer", "inspector", "constable", "si", "pi", "asi", "dysp",
            "assigned", "investigating", "badge", "rank", "staff",
            "head constable",
        ],
    },
}


def _format_table(name: str, meta: dict, max_col_chars: int | None = None) -> str:
    """Build the per-table block for a schema string."""
    lines = [f"TABLE: {name}", f"Description: {meta['description']}", "Columns:"]
    for col_name, col_desc in meta["columns"].items():
        if max_col_chars is not None and len(col_desc) > max_col_chars:
            col_desc = col_desc[: max_col_chars - 1].rstrip() + "…"
        lines.append(f"  - {col_name}: {col_desc}")
    return "\n".join(lines)


def get_schema_for_tables(table_names: list[str]) -> str:
    """
    Build a compact schema string for LLM prompt injection.

    Always includes fir_master (even if not in table_names) and lists it first.
    Output is capped at _MAX_SCHEMA_CHARS — column descriptions are progressively
    truncated to fit; table names and column names are never dropped.
    """
    seen = set()
    ordered = []

    # Always include fir_master first.
    if "fir_master" in SCHEMA_CATALOG:
        ordered.append("fir_master")
        seen.add("fir_master")

    for t in table_names:
        if t in SCHEMA_CATALOG and t not in seen:
            ordered.append(t)
            seen.add(t)

    # First pass: full descriptions.
    blocks = [_format_table(t, SCHEMA_CATALOG[t]) for t in ordered]
    out = "\n\n".join(blocks)
    if len(out) <= _MAX_SCHEMA_CHARS:
        return out

    # Progressively truncate column descriptions until under the cap.
    for cap in (80, 60, 40, 30):
        blocks = [
            _format_table(t, SCHEMA_CATALOG[t], max_col_chars=cap) for t in ordered
        ]
        out = "\n\n".join(blocks)
        if len(out) <= _MAX_SCHEMA_CHARS:
            return out

    # Last resort: hard-truncate.
    return out[:_MAX_SCHEMA_CHARS]


# Few-shot bank — (relevant_tables_set, question, sql) tuples.
# `relevant_tables` lists which tables in the question's selected set make this
# example useful. We always score against the user's table set.
_FEW_SHOT_BANK: list[dict] = [
    {
        "tables": {"fir_master"},
        "q": "How many cases are open?",
        "sql": (
            "SELECT COUNT(*) AS open_cases\n"
            "FROM fir_master\n"
            "WHERE status = 'open'"
        ),
    },
    {
        "tables": {"fir_master"},
        "q": "Show me the last 5 FIRs filed.",
        "sql": (
            "SELECT fir_id, fir_number, case_type, incident_location, date_filed, status\n"
            "FROM fir_master\n"
            "ORDER BY date_filed DESC, time_filed DESC\n"
            "LIMIT 5"
        ),
    },
    {
        "tables": {"fir_master"},
        "q": "How many cases were filed in 2024?",
        "sql": (
            "SELECT COUNT(*) AS cases_in_2024\n"
            "FROM fir_master\n"
            "WHERE YEAR(date_filed) = 2024"
        ),
    },
    {
        "tables": {"fir_master", "cases_theft"},
        "q": "How many theft cases are still open?",
        "sql": (
            "SELECT COUNT(*) AS open_theft_cases\n"
            "FROM fir_master AS f\n"
            "JOIN cases_theft AS t ON t.fir_id = f.fir_id\n"
            "WHERE f.status = 'open'"
        ),
    },
    {
        "tables": {"fir_master", "cases_theft"},
        "q": "List recovered theft cases with their estimated value.",
        "sql": (
            "SELECT f.fir_number, f.incident_location, t.estimated_value, t.recovery_date\n"
            "FROM fir_master AS f\n"
            "JOIN cases_theft AS t ON t.fir_id = f.fir_id\n"
            "WHERE t.recovered = TRUE\n"
            "ORDER BY t.recovery_date DESC\n"
            "LIMIT 50"
        ),
    },
    {
        "tables": {"fir_master", "accused"},
        "q": "Show me all cases involving Mahesh Gowda.",
        "sql": (
            "SELECT f.fir_id, f.fir_number, f.case_type, f.incident_location,\n"
            "       f.date_filed, f.status, a.full_name, a.alias, a.arrest_status\n"
            "FROM accused AS a\n"
            "JOIN fir_master AS f ON f.fir_id = a.fir_id\n"
            "WHERE a.full_name LIKE '%Mahesh Gowda%'\n"
            "ORDER BY f.date_filed DESC"
        ),
    },
    {
        "tables": {"accused"},
        "q": "Who are the top 5 repeat offenders?",
        "sql": (
            "SELECT full_name, COUNT(DISTINCT fir_id) AS fir_count, MAX(prior_fir_count) AS prior_fir_count, MAX(arrest_status) AS arrest_status\n"
            "FROM accused\n"
            "WHERE full_name IS NOT NULL\n"
            "GROUP BY full_name\n"
            "ORDER BY fir_count DESC\n"
            "LIMIT 5"
        ),
    },
    {
        "tables": {"fir_master", "cases_vehicle_theft"},
        "q": "List all vehicle theft cases with the registration number.",
        "sql": (
            "SELECT f.fir_number, f.incident_location, f.date_filed,\n"
            "       v.vehicle_type, v.vehicle_make, v.registration_no, v.recovered\n"
            "FROM fir_master AS f\n"
            "JOIN cases_vehicle_theft AS v ON v.fir_id = f.fir_id\n"
            "ORDER BY f.date_filed DESC\n"
            "LIMIT 50"
        ),
    },
    {
        "tables": {"fir_master", "cases_cybercrime"},
        "q": "Show all phishing cases on WhatsApp.",
        "sql": (
            "SELECT f.fir_number, f.incident_location, f.date_filed,\n"
            "       c.cyber_type, c.platform, c.financial_loss\n"
            "FROM fir_master AS f\n"
            "JOIN cases_cybercrime AS c ON c.fir_id = f.fir_id\n"
            "WHERE c.cyber_type = 'phishing' AND c.platform = 'WhatsApp'\n"
            "ORDER BY f.date_filed DESC\n"
            "LIMIT 50"
        ),
    },
    {
        "tables": {"fir_master", "cases_fraud"},
        "q": "What is the total amount defrauded in online fraud cases?",
        "sql": (
            "SELECT SUM(fr.amount_defrauded) AS total_defrauded\n"
            "FROM cases_fraud AS fr\n"
            "JOIN fir_master AS f ON f.fir_id = fr.fir_id\n"
            "WHERE fr.fraud_type = 'online'"
        ),
    },
    {
        "tables": {"fir_master", "cases_missing_person"},
        "q": "Show me missing person cases that are still not found.",
        "sql": (
            "SELECT f.fir_number, f.incident_location, m.missing_since,\n"
            "       m.last_seen_location\n"
            "FROM fir_master AS f\n"
            "JOIN cases_missing_person AS m ON m.fir_id = f.fir_id\n"
            "WHERE m.found = FALSE\n"
            "ORDER BY m.missing_since DESC\n"
            "LIMIT 50"
        ),
    },
    {
        "tables": {"fir_master", "evidence_media"},
        "q": "Show me FIRs that have photo evidence.",
        "sql": (
            "SELECT f.fir_id, f.fir_number, f.case_type, f.incident_location,\n"
            "       e.media_type, e.description\n"
            "FROM fir_master AS f\n"
            "JOIN evidence_media AS e ON e.fir_id = f.fir_id\n"
            "WHERE e.media_type = 'image'\n"
            "ORDER BY f.date_filed DESC\n"
            "LIMIT 50"
        ),
    },
    {
        "tables": {"fir_master", "officers"},
        "q": "Which officer is investigating the most cases?",
        "sql": (
            "SELECT o.full_name, o.`rank`, o.badge_number, COUNT(f.fir_id) AS case_count\n"
            "FROM officers AS o\n"
            "JOIN fir_master AS f ON f.investigating_officer_id = o.officer_id\n"
            "GROUP BY o.officer_id, o.full_name, o.`rank`, o.badge_number\n"
            "ORDER BY case_count DESC\n"
            "LIMIT 5"
        ),
    },
    {
        "tables": {"fir_master"},
        "q": "Break down all cases by type with counts.",
        "sql": (
            "SELECT case_type, COUNT(*) AS case_count\n"
            "FROM fir_master\n"
            "GROUP BY case_type\n"
            "ORDER BY case_count DESC"
        ),
    },
    {
        "tables": {"fir_master"},
        "q": "Show me all assault cases reported in Koramangala.",
        "sql": (
            "SELECT fir_number, date_filed, incident_location, status\n"
            "FROM fir_master\n"
            "WHERE case_type = 'assault'\n"
            "  AND incident_location LIKE '%Koramangala%'\n"
            "ORDER BY date_filed DESC\n"
            "LIMIT 50"
        ),
    },
]


def get_few_shot_examples(table_names: list[str]) -> str:
    """
    Return exactly 3 example NL->SQL pairs relevant to the selected tables.

    Scoring: each example earns +1 for every table it shares with the caller's
    selected set. Ties broken by example order in the bank (stable).
    """
    selected = set(table_names) | {"fir_master"}

    scored = []
    for idx, ex in enumerate(_FEW_SHOT_BANK):
        score = len(ex["tables"] & selected)
        # Penalize examples that reference tables NOT selected — those would
        # confuse the LLM into using tables we didn't include in the schema.
        unknown = ex["tables"] - selected
        if unknown:
            score -= len(unknown)
        scored.append((score, idx, ex))

    scored.sort(key=lambda x: (-x[0], x[1]))
    chosen = [ex for _score, _idx, ex in scored[:3]]

    blocks = []
    for ex in chosen:
        blocks.append(f"-- Q: {ex['q']}\n-- SQL:\n{ex['sql']}")
    return "\n\n".join(blocks)


# A handy export for the validator to use without re-importing this dict.
ALLOWED_TABLES: list[str] = list(SCHEMA_CATALOG.keys())
