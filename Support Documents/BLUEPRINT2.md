# KSP Crime Intelligence — BLUEPRINT 2
## Sections 3, 5, 6, 9, 10 — Analytics, Profiling, Decision Support, Explainability, Governance

> **Context:** BLUEPRINT.md covers the core chatbot (sections 1 and 2 of the PS1 brief), which is built and working. This file covers the next five sections: Crime Pattern & Trend Analytics, Criminology-Based Offender Profiling, Investigator Decision Support, Explainable AI & Transparent Analytics, and Secure Role-Based Access & Governance.
>
> **Deliberate constraint, learned the hard way tonight:** every new Catalyst service integration this session (NoSQL, Zia TTS/STT/Translate, SmartBrowz) needed real-world trial-and-error to get auth headers, URL paths, and payload shapes right — and SmartBrowz never worked at all. **This blueprint adds zero new Catalyst service dependencies.** Everything here runs on the same MySQL Data Store, the same two LLM models, and the same FastAPI/React stack already working. No Zia AutoML, no new Zia services, no new auth provider. Pure SQL, Python, and the existing LLM pipeline.
>
> Read `BLUEPRINT.md` and the latest `Docs.md` before starting — this file assumes that schema and pipeline already exist and extends them.

---

## What This Blueprint Adds

| PS1 Section | Feature | New tables? | New endpoints? |
|---|---|---|---|
| 3. Pattern & Trend Analytics | Crime trend dashboard — by time, geography, crime type | No | Yes |
| 5. Offender Profiling | Computed risk score for every accused person | 1 new column-set | Yes |
| 6. Decision Support | Case timeline, similar case finder, case summary | No | Yes |
| 9. Explainable AI | Formal evidence trail attached to every chat answer | 1 new table | No new routes — extends existing chat response |
| 10. Role-Based Access | Officer roles + audit log | 2 new tables/columns | Yes (role check middleware) |

Nothing here touches the existing chat pipeline's core logic. These are additive endpoints and one schema extension.

---

## Database Changes

### 1. Add `role` to `officers` (Section 10)

```sql
ALTER TABLE officers
  ADD COLUMN role ENUM('investigator', 'analyst', 'supervisor', 'policymaker')
  NOT NULL DEFAULT 'investigator';
```

Run:
```bash
mysql -u adarsh -proot ksp_crime_db -e "
ALTER TABLE officers
  ADD COLUMN role ENUM('investigator', 'analyst', 'supervisor', 'policymaker')
  NOT NULL DEFAULT 'investigator';
"
```

Update a few seeded officers to other roles so the role gate is actually testable:
```bash
mysql -u adarsh -proot ksp_crime_db -e "
UPDATE officers SET role = 'supervisor' WHERE rank IN ('Inspector', 'DySP', 'SP');
UPDATE officers SET role = 'analyst' WHERE rank = 'PI';
"
```

### 2. New table: `audit_log` (Section 10)

```sql
CREATE TABLE IF NOT EXISTS audit_log (
    log_id          INT AUTO_INCREMENT PRIMARY KEY,
    officer_id      INT NOT NULL,
    action          VARCHAR(50) NOT NULL,        -- e.g. 'view_risk_score', 'export_chat', 'view_case_timeline'
    resource_type   VARCHAR(50),                  -- e.g. 'accused', 'fir', 'session'
    resource_id     VARCHAR(50),
    details         TEXT,
    ip_address      VARCHAR(45),
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (officer_id) REFERENCES officers(officer_id),
    INDEX idx_audit_officer (officer_id, created_at),
    INDEX idx_audit_resource (resource_type, resource_id)
);
```

### 3. New table: `offender_risk_scores` (Section 5)

Computed and cached, not computed live on every request — risk scores don't need to be real-time.

```sql
CREATE TABLE IF NOT EXISTS offender_risk_scores (
    accused_id          INT PRIMARY KEY,
    risk_score          DECIMAL(5,2) NOT NULL,     -- 0.00 to 100.00
    risk_tier           ENUM('low', 'medium', 'high', 'critical') NOT NULL,
    contributing_factors TEXT,                      -- JSON array of factor strings, for explainability
    computed_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (accused_id) REFERENCES accused(accused_id)
);
```

### 4. New table: `chat_evidence_trail` (Section 9)

Links each assistant chat message to the exact data rows that grounded its answer — the formal version of what `sql_generated` was informally doing.

```sql
CREATE TABLE IF NOT EXISTS chat_evidence_trail (
    trail_id        INT AUTO_INCREMENT PRIMARY KEY,
    message_id      INT NOT NULL,
    sql_executed    TEXT NOT NULL,
    tables_queried  VARCHAR(300),       -- comma-separated table names
    row_count       INT,
    fir_ids_referenced VARCHAR(500),     -- comma-separated fir_ids, for traceability
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (message_id) REFERENCES chat_messages(message_id),
    INDEX idx_trail_message (message_id)
);
```

Run all four DDL changes:
```bash
mysql -u adarsh -proot ksp_crime_db < db/blueprint2_schema.sql
```
(Save the four SQL blocks above into `backend/db/blueprint2_schema.sql` first.)

---

## Part A — Section 3: Crime Pattern & Trend Analytics

### What it does

A dedicated analytics endpoint (separate from the chat pipeline) that returns structured trend data: crime counts by time period, by location, by crime type, and by modus operandi. The frontend renders this as a small set of charts, not as chat answers — this is the "analyst dashboard" half of the PS1 brief, distinct from the conversational half.

### Files to create

```
backend/
└── analytics/
    └── trend_analytics.py       ← NEW: aggregation queries

backend/routers/
└── analytics.py                 ← NEW: GET endpoints for trend data

frontend/src/components/
├── AnalyticsDashboard.jsx       ← NEW: dashboard panel
└── TrendChart.jsx               ← NEW: simple bar/line chart (no chart library — inline SVG)
```

### `backend/analytics/trend_analytics.py`

```python
"""
Crime pattern and trend analytics — pure SQL aggregation, no ML.
All queries read from fir_master and the cases_* tables.
"""
from db.connection import execute_query


async def get_trend_by_month(months_back: int = 12) -> list[dict]:
    """
    Crime count per month for the last `months_back` months.
    Returns: [{"month": "2025-06", "count": 34}, ...]
    Ordered chronologically ascending.
    """
    return await execute_query(
        """SELECT DATE_FORMAT(date_filed, '%Y-%m') AS month, COUNT(*) AS count
           FROM fir_master
           WHERE date_filed >= DATE_SUB(CURDATE(), INTERVAL %s MONTH)
           GROUP BY month
           ORDER BY month ASC""",
        (months_back,)
    )


async def get_trend_by_crime_type() -> list[dict]:
    """
    Total count per case_type, all time.
    Returns: [{"case_type": "theft", "count": 45}, ...]
    Ordered by count descending.
    """
    return await execute_query(
        """SELECT case_type, COUNT(*) AS count
           FROM fir_master
           GROUP BY case_type
           ORDER BY count DESC"""
    )


async def get_trend_by_location(limit: int = 10) -> list[dict]:
    """
    Crime count per incident_location, top `limit` locations.
    Returns: [{"incident_location": "Koramangala, Bengaluru", "count": 28}, ...]
    """
    return await execute_query(
        """SELECT incident_location, COUNT(*) AS count
           FROM fir_master
           WHERE incident_location IS NOT NULL
           GROUP BY incident_location
           ORDER BY count DESC
           LIMIT %s""",
        (limit,)
    )


async def get_crime_type_by_location(location: str) -> list[dict]:
    """
    Breakdown of crime types within a single location — for drill-down.
    Returns: [{"case_type": "theft", "count": 12}, ...]
    """
    return await execute_query(
        """SELECT case_type, COUNT(*) AS count
           FROM fir_master
           WHERE incident_location = %s
           GROUP BY case_type
           ORDER BY count DESC""",
        (location,)
    )


async def get_status_breakdown() -> list[dict]:
    """
    Count of cases by investigation status.
    Returns: [{"status": "open", "count": 132}, ...]
    """
    return await execute_query(
        """SELECT status, COUNT(*) AS count
           FROM fir_master
           GROUP BY status
           ORDER BY count DESC"""
    )


async def get_modus_operandi_clusters(min_occurrences: int = 2) -> list[dict]:
    """
    Group FIRs by relationship_type = 'same_modus_operandi' in case_relationships,
    surfacing repeated MO patterns across cases.
    Returns: [{"relationship_type": "same_modus_operandi", "linked_fir_count": 6}, ...]
    Simple proxy for "MO clustering" without real clustering ML —
    counts how many relationship rows of this type exist.
    """
    return await execute_query(
        """SELECT relationship_type, COUNT(*) AS linked_pair_count
           FROM case_relationships
           WHERE relationship_type IN ('same_modus_operandi', 'repeat_location', 'linked_gang')
           GROUP BY relationship_type
           HAVING linked_pair_count >= %s
           ORDER BY linked_pair_count DESC""",
        (min_occurrences,)
    )


async def get_seasonal_pattern() -> list[dict]:
    """
    Crime count grouped by month-of-year (irrespective of which year),
    to surface seasonal patterns — e.g. "more thefts in December".
    Returns: [{"month_num": 1, "month_name": "January", "count": 18}, ...]
    """
    return await execute_query(
        """SELECT MONTH(date_filed) AS month_num,
                  MONTHNAME(date_filed) AS month_name,
                  COUNT(*) AS count
           FROM fir_master
           GROUP BY month_num, month_name
           ORDER BY month_num ASC"""
    )
```

### `backend/routers/analytics.py`

```python
from fastapi import APIRouter, Depends, Query
from auth.simple_auth import get_current_officer
from analytics.trend_analytics import (
    get_trend_by_month, get_trend_by_crime_type, get_trend_by_location,
    get_crime_type_by_location, get_status_breakdown,
    get_modus_operandi_clusters, get_seasonal_pattern
)

router = APIRouter()


@router.get("/api/analytics/trends/monthly")
async def trends_monthly(
    months_back: int = Query(12, ge=1, le=60),
    officer: dict = Depends(get_current_officer)
):
    """Returns monthly crime count trend."""
    data = await get_trend_by_month(months_back)
    return {"trend": data}


@router.get("/api/analytics/trends/by-crime-type")
async def trends_by_crime_type(officer: dict = Depends(get_current_officer)):
    """Returns total counts grouped by crime type."""
    data = await get_trend_by_crime_type()
    return {"breakdown": data}


@router.get("/api/analytics/trends/by-location")
async def trends_by_location(
    limit: int = Query(10, ge=1, le=50),
    officer: dict = Depends(get_current_officer)
):
    """Returns top locations by crime count."""
    data = await get_trend_by_location(limit)
    return {"locations": data}


@router.get("/api/analytics/trends/location/{location}/breakdown")
async def location_breakdown(location: str, officer: dict = Depends(get_current_officer)):
    """Drill-down: crime type breakdown for a single location."""
    data = await get_crime_type_by_location(location)
    return {"location": location, "breakdown": data}


@router.get("/api/analytics/status-breakdown")
async def status_breakdown(officer: dict = Depends(get_current_officer)):
    """Returns case counts grouped by investigation status."""
    data = await get_status_breakdown()
    return {"breakdown": data}


@router.get("/api/analytics/mo-clusters")
async def mo_clusters(officer: dict = Depends(get_current_officer)):
    """Returns modus-operandi / repeat-pattern relationship counts."""
    data = await get_modus_operandi_clusters()
    return {"clusters": data}


@router.get("/api/analytics/seasonal")
async def seasonal(officer: dict = Depends(get_current_officer)):
    """Returns crime counts grouped by calendar month (seasonal pattern)."""
    data = await get_seasonal_pattern()
    return {"seasonal": data}
```

Register in `main.py`:
```python
from routers.analytics import router as analytics_router
app.include_router(analytics_router)
```

### Frontend — `AnalyticsDashboard.jsx`

```jsx
/*
AnalyticsDashboard — a new view, separate from the chat interface.
Accessible via a new sidebar icon (e.g. a bar-chart icon, next to "New chat").

Layout: a grid of panels, each showing one trend:
  1. Monthly trend (line/bar chart) — last 12 months
  2. Crime type breakdown (horizontal bar chart) — top 8 types
  3. Top 10 locations (horizontal bar chart)
  4. Status breakdown (simple stat cards: open/under_investigation/closed/chargesheeted with counts)
  5. Seasonal pattern (12-bar chart, Jan-Dec)
  6. MO clusters (simple list: relationship_type + count)

On mount: fire all 6 GET requests in parallel (Promise.all), populate each panel
as its data arrives — don't block all panels on the slowest query.

Clicking a location bar in panel 3 calls the drill-down endpoint and shows
a small popover with that location's crime type breakdown.
*/
```

### Frontend — `TrendChart.jsx`

```jsx
/*
TrendChart — a minimal, dependency-free bar chart component.
No chart library — inline SVG, matching the "minimal government portal"
design constraint from Design.md.

Props:
  data: [{label: string, value: number}]
  orientation: 'vertical' | 'horizontal'
  color: string (default var(--primary))
  maxBars: number (default 12, truncates if data is longer)

Renders:
  - SVG with bars scaled to the max value in the dataset
  - Label text below/beside each bar
  - Value text on top of each bar
  - Horizontal orientation: bars grow left-to-right, used for location/crime-type rankings
  - Vertical orientation: bars grow bottom-to-top, used for monthly/seasonal trends

Keep this genuinely simple — calculate bar width/height as a percentage
of the max value, render <rect> elements in a loop. No animation library,
a simple CSS transition on width/height is enough.
*/
```

---

## Part B — Section 5: Criminology-Based Offender Profiling

### What it does

Instead of Zia AutoML (which we're deliberately avoiding given tonight's integration fragility), compute a **transparent, rule-based risk score** in plain Python from data already in the DB. This is actually a *better* fit for the PS1 brief's "Explainable AI" requirement than a black-box ML model would be — every point of the score traces back to a named factor.

### Risk scoring logic (deterministic, explainable)

```python
"""
Rule-based offender risk scoring.
Deliberately NOT a black-box ML model — every point is traceable to a
named factor, satisfying the Explainable AI requirement (Section 9) while
addressing Offender Profiling (Section 5).

Score range: 0-100. Computed in Python from SQL aggregates, cached in
offender_risk_scores table. Recompute on a schedule (manual trigger endpoint
for the hackathon — see recompute_all_risk_scores).
"""

# Scoring weights — each factor's max contribution to the 100-point score
WEIGHTS = {
    "prior_fir_count": 30,        # more priors = higher risk, capped
    "violent_crime_ratio": 25,    # % of their FIRs that are assault/murder/robbery
    "at_large_status": 15,        # currently at large = +15 flat
    "geographic_spread": 15,      # number of distinct locations they've offended in
    "recency": 15,                # how recently their last offense was
}

VIOLENT_TYPES = {"assault", "murder", "robbery", "domestic_violence"}
```

### Files to create

```
backend/
└── profiling/
    └── risk_scoring.py          ← NEW: scoring logic

backend/routers/
└── profiling.py                 ← NEW: endpoints
```

### `backend/profiling/risk_scoring.py`

```python
"""
Rule-based, explainable offender risk scoring.
See module docstring in BLUEPRINT2 for the weighting rationale.
"""
import json
from datetime import date
from db.connection import execute_query, execute_write

WEIGHTS = {
    "prior_fir_count": 30,
    "violent_crime_ratio": 25,
    "at_large_status": 15,
    "geographic_spread": 15,
    "recency": 15,
}
VIOLENT_TYPES = ("assault", "murder", "robbery", "domestic_violence")


async def compute_risk_for_accused(accused_id: int) -> dict:
    """
    Compute a risk score for one accused person.

    Returns:
    {
        "accused_id": int,
        "risk_score": float,        # 0-100
        "risk_tier": str,           # low/medium/high/critical
        "contributing_factors": [   # human-readable, ordered by contribution
            {"factor": "5 prior FIRs", "points": 18.0},
            {"factor": "Currently at large", "points": 15.0},
            ...
        ]
    }

    Steps:
    1. Fetch this accused's full_name, arrest_status, prior_fir_count.
    2. Fetch all FIRs they're linked to (case_type, incident_location, date_filed)
       via the accused table's fir_id join.
    3. Compute violent_crime_ratio = violent FIRs / total FIRs.
    4. Compute geographic_spread = count of DISTINCT incident_location.
    5. Compute recency = days since most recent date_filed; map to a 0-15 score
       (more recent = higher score; e.g. <90 days = 15, <365 days = 8, else 2).
    6. prior_fir_count score = min(prior_fir_count * 6, 30) (caps at 5 priors = 30).
    7. violent_crime_ratio score = violent_crime_ratio * 25.
    8. at_large_status score = 15 if arrest_status == 'at_large' else 0.
    9. geographic_spread score = min(geographic_spread * 5, 15) (caps at 3 locations).
    10. Sum all five → risk_score (0-100).
    11. Map to tier: <25 low, <50 medium, <75 high, >=75 critical.
    12. Build contributing_factors list with the actual points each factor contributed,
        sorted descending — this list IS the explainability output for Section 9.

    Never raises — returns a zero-score default dict on any DB error.
    """
    try:
        accused_rows = await execute_query(
            "SELECT full_name, arrest_status, prior_fir_count FROM accused WHERE accused_id = %s",
            (accused_id,)
        )
        if not accused_rows:
            return _empty_score(accused_id)
        person = accused_rows[0]

        fir_rows = await execute_query(
            """SELECT f.case_type, f.incident_location, f.date_filed
               FROM accused a JOIN fir_master f ON f.fir_id = a.fir_id
               WHERE a.accused_id = %s OR a.full_name = %s""",
            (accused_id, person["full_name"])
        )

        total_firs = len(fir_rows) or 1
        violent_count = sum(1 for r in fir_rows if r["case_type"] in VIOLENT_TYPES)
        violent_ratio = violent_count / total_firs

        locations = {r["incident_location"] for r in fir_rows if r["incident_location"]}
        geo_spread = len(locations)

        dates = [r["date_filed"] for r in fir_rows if r["date_filed"]]
        most_recent = max(dates) if dates else None
        days_since = (date.today() - most_recent).days if most_recent else 9999

        prior_score = min((person["prior_fir_count"] or 0) * 6, WEIGHTS["prior_fir_count"])
        violent_score = round(violent_ratio * WEIGHTS["violent_crime_ratio"], 1)
        at_large_score = WEIGHTS["at_large_status"] if person["arrest_status"] == "at_large" else 0
        geo_score = min(geo_spread * 5, WEIGHTS["geographic_spread"])
        if days_since < 90:
            recency_score = WEIGHTS["recency"]
        elif days_since < 365:
            recency_score = round(WEIGHTS["recency"] * 0.55, 1)
        else:
            recency_score = round(WEIGHTS["recency"] * 0.15, 1)

        total_score = round(prior_score + violent_score + at_large_score + geo_score + recency_score, 1)
        total_score = min(total_score, 100.0)

        if total_score < 25:
            tier = "low"
        elif total_score < 50:
            tier = "medium"
        elif total_score < 75:
            tier = "high"
        else:
            tier = "critical"

        factors = sorted([
            {"factor": f"{person['prior_fir_count'] or 0} prior FIR(s) on record", "points": prior_score},
            {"factor": f"{round(violent_ratio*100)}% of cases are violent offenses", "points": violent_score},
            {"factor": "Currently at large" if at_large_score else "Currently arrested/known status", "points": at_large_score},
            {"factor": f"Offenses span {geo_spread} distinct location(s)", "points": geo_score},
            {"factor": f"Most recent offense {days_since} days ago", "points": recency_score},
        ], key=lambda x: x["points"], reverse=True)

        return {
            "accused_id": accused_id,
            "risk_score": total_score,
            "risk_tier": tier,
            "contributing_factors": factors,
        }
    except Exception:
        return _empty_score(accused_id)


def _empty_score(accused_id: int) -> dict:
    return {"accused_id": accused_id, "risk_score": 0.0, "risk_tier": "low", "contributing_factors": []}


async def save_risk_score(result: dict):
    """
    Upsert the computed score into offender_risk_scores.
    Uses INSERT ... ON DUPLICATE KEY UPDATE since accused_id is the primary key.
    """
    await execute_write(
        """INSERT INTO offender_risk_scores (accused_id, risk_score, risk_tier, contributing_factors)
           VALUES (%s, %s, %s, %s)
           ON DUPLICATE KEY UPDATE
             risk_score = %s, risk_tier = %s, contributing_factors = %s, computed_at = NOW()""",
        (
            result["accused_id"], result["risk_score"], result["risk_tier"],
            json.dumps(result["contributing_factors"]),
            result["risk_score"], result["risk_tier"], json.dumps(result["contributing_factors"]),
        )
    )


async def get_cached_risk_score(accused_id: int) -> dict | None:
    """
    Read a previously computed score from offender_risk_scores.
    Returns None if never computed — caller should then call compute_risk_for_accused.
    """
    rows = await execute_query(
        "SELECT accused_id, risk_score, risk_tier, contributing_factors FROM offender_risk_scores WHERE accused_id = %s",
        (accused_id,)
    )
    if not rows:
        return None
    row = rows[0]
    return {
        "accused_id": row["accused_id"],
        "risk_score": float(row["risk_score"]),
        "risk_tier": row["risk_tier"],
        "contributing_factors": json.loads(row["contributing_factors"]) if row["contributing_factors"] else [],
    }


async def recompute_all_risk_scores() -> int:
    """
    Recompute risk scores for every accused person in the DB.
    Used by a manual "recompute" endpoint (no Catalyst Cron dependency —
    keeps this independent of any new Catalyst service).
    Returns count of accused processed.
    """
    rows = await execute_query("SELECT DISTINCT accused_id FROM accused")
    count = 0
    for row in rows:
        result = await compute_risk_for_accused(row["accused_id"])
        await save_risk_score(result)
        count += 1
    return count
```

### `backend/routers/profiling.py`

```python
from fastapi import APIRouter, Depends, HTTPException
from auth.simple_auth import get_current_officer
from profiling.risk_scoring import (
    compute_risk_for_accused, save_risk_score,
    get_cached_risk_score, recompute_all_risk_scores
)
from db.connection import execute_query

router = APIRouter()


@router.get("/api/profiling/risk/{accused_id}")
async def get_risk_score(accused_id: int, officer: dict = Depends(get_current_officer)):
    """
    Returns the risk score for an accused person.
    Uses cached score if available; computes fresh if not cached yet.
    """
    cached = await get_cached_risk_score(accused_id)
    if cached:
        return cached
    result = await compute_risk_for_accused(accused_id)
    await save_risk_score(result)
    return result


@router.post("/api/profiling/recompute-all")
async def recompute_all(officer: dict = Depends(get_current_officer)):
    """
    Recompute risk scores for all accused. Restricted to supervisor/analyst
    roles — see Part E for the role-check dependency this uses.
    """
    # Role check happens via require_role dependency — see Part E
    count = await recompute_all_risk_scores()
    return {"recomputed": count}


@router.get("/api/profiling/top-risk")
async def top_risk_offenders(limit: int = 10, officer: dict = Depends(get_current_officer)):
    """
    Returns the highest-risk accused persons, for a "watch list" view.
    """
    rows = await execute_query(
        """SELECT s.accused_id, a.full_name, a.alias, a.arrest_status,
                  s.risk_score, s.risk_tier
           FROM offender_risk_scores s
           JOIN accused a ON a.accused_id = s.accused_id
           ORDER BY s.risk_score DESC
           LIMIT %s""",
        (limit,)
    )
    return {"top_risk": rows}
```

Register in `main.py`:
```python
from routers.profiling import router as profiling_router
app.include_router(profiling_router)
```

### Frontend addition

When an officer's chat query surfaces an accused person (e.g. asking about Mahesh Gowda), add a small risk badge next to their name in the table/profile view — color-coded by tier (green/yellow/orange/red), clickable to expand the `contributing_factors` list. This is a small `RiskBadge.jsx` component, not a full new page.

```jsx
/*
RiskBadge.jsx
Props: { accusedId: number }
On mount: GET /api/profiling/risk/{accusedId}
Renders a small pill: risk_tier color + risk_score number.
Click expands an inline list of contributing_factors — this IS your
explainability UI for offender profiling specifically.
*/
```

---

## Part C — Section 6: Investigator Decision Support

### What it does

Three sub-features: automated case summary (LLM-powered, reuses the existing answer formatter pattern), investigation timeline (pure SQL), and similar case finder (rule-based similarity, not real ML — same philosophy as the risk scoring).

### Files to create

```
backend/
└── decision_support/
    ├── case_summary.py          ← NEW: LLM-powered case summary
    ├── case_timeline.py         ← NEW: SQL-based timeline builder
    └── similar_cases.py         ← NEW: rule-based similarity finder

backend/routers/
└── decision_support.py          ← NEW: endpoints
```

### `backend/decision_support/case_timeline.py`

```python
"""
Builds a chronological timeline for a single FIR — every dated event
the schema already tracks, ordered.
"""
from db.connection import execute_query


async def build_case_timeline(fir_id: int) -> list[dict]:
    """
    Returns a list of timeline events, chronologically ordered:
    [{"date": "2024-05-15", "event": "FIR filed", "detail": "..."}, ...]

    Events pulled from:
    - fir_master.date_filed → "FIR filed"
    - fir_master.incident_date → "Incident occurred" (often before filing)
    - accused.arrest_date (for each accused) → "Accused arrested: {name}"
    - cases_missing_person.found_date (if applicable) → "Missing person found"
    - cases_vehicle_theft.recovery_date / cases_theft.recovery_date → "Property recovered"
    - fir_master.updated_at → "Last status update" (only if different from date_filed)

    Pull from the relevant cases_* table based on fir_master.case_type —
    only join the one matching table, not all of them.

    Never raises — returns [] on error.
    """
```

### `backend/decision_support/similar_cases.py`

```python
"""
Finds cases similar to a given FIR using rule-based matching — same
philosophy as risk_scoring.py: transparent and explainable rather than
a black-box embedding similarity search (which would need a vector DB
we deliberately don't have).
"""
from db.connection import execute_query


async def find_similar_cases(fir_id: int, limit: int = 5) -> list[dict]:
    """
    Returns FIRs similar to the given one, ranked by a simple match score.

    Similarity signals (each adds points):
    - Same case_type: +40
    - Same incident_location: +25
    - Filed within 90 days of each other: +15
    - Shares an accused (via case_relationships or matching accused full_name): +20

    Steps:
    1. Fetch the source FIR's case_type, incident_location, date_filed.
    2. Query all OTHER FIRs of the same case_type (this is your candidate pool —
       don't compare against the entire table).
    3. For each candidate, compute the match score using the rules above.
    4. Check case_relationships for any direct link between source and candidate
       FIRs — if linked, add +20 and note the relationship_type.
    5. Sort by score descending, return top `limit`.

    Returns: [{"fir_id": int, "fir_number": str, "match_score": int,
               "match_reasons": ["Same crime type", "Same location"], ...}]

    Never raises — returns [] on error.
    """
```

### `backend/decision_support/case_summary.py`

```python
"""
LLM-powered case summary — reuses the existing answer-formatter LLM call
pattern from llm/client.py. No new LLM integration, just a new prompt.
"""
from llm.client import call_llm
from db.connection import execute_query


async def generate_case_summary(fir_id: int) -> str:
    """
    Builds a structured prompt from all known facts about this FIR
    (case details, accused, victims, timeline, any media count) and
    asks Qwen 2.5-14B Instruct to write a concise investigator summary.

    Steps:
    1. Fetch fir_master row.
    2. Fetch accused (names, ages, arrest_status).
    3. Fetch victims (names, ages).
    4. Fetch case-type-specific details (whichever cases_* table applies).
    5. Build a fact sheet as plain text.
    6. System prompt: "You are writing a case summary for an investigator.
       Be factual, concise, 4-6 sentences. Only state what's in the data.
       Do not speculate about guilt or outcomes."
    7. Call call_llm("MODEL_ANSWER", prompt=fact_sheet, system_prompt=..., max_tokens=4000)
    8. Return the generated text.

    Reuses the existing, working LLM client — same auth, same model,
    same error handling pattern as the chat pipeline.
    """
```

### `backend/routers/decision_support.py`

```python
from fastapi import APIRouter, Depends
from auth.simple_auth import get_current_officer
from decision_support.case_timeline import build_case_timeline
from decision_support.similar_cases import find_similar_cases
from decision_support.case_summary import generate_case_summary

router = APIRouter()


@router.get("/api/decision-support/timeline/{fir_id}")
async def get_timeline(fir_id: int, officer: dict = Depends(get_current_officer)):
    """Returns the chronological event timeline for a FIR."""
    timeline = await build_case_timeline(fir_id)
    return {"fir_id": fir_id, "timeline": timeline}


@router.get("/api/decision-support/similar/{fir_id}")
async def get_similar(fir_id: int, limit: int = 5, officer: dict = Depends(get_current_officer)):
    """Returns similar past cases, ranked by rule-based match score."""
    similar = await find_similar_cases(fir_id, limit)
    return {"fir_id": fir_id, "similar_cases": similar}


@router.get("/api/decision-support/summary/{fir_id}")
async def get_summary(fir_id: int, officer: dict = Depends(get_current_officer)):
    """Returns an LLM-generated case summary."""
    summary = await generate_case_summary(fir_id)
    return {"fir_id": fir_id, "summary": summary}
```

Register in `main.py`:
```python
from routers.decision_support import router as decision_support_router
app.include_router(decision_support_router)
```

### Frontend addition

A "Case Detail" view — accessible when an officer clicks a specific FIR row in any table result. Three tabs: Timeline, Similar Cases, Summary. Each tab lazy-loads its own endpoint on click, not all three upfront.

```jsx
/*
CaseDetailPanel.jsx
Props: { firId: number, onClose: () => void }
Tabs: "Timeline" | "Similar Cases" | "Summary"
Each tab fetches its own data on first activation, caches in component state
so switching tabs doesn't refetch. Same overlay/panel pattern as NetworkGraph.jsx
from Step 5 — reuse that CSS (.graph-overlay, .graph-panel classes).
*/
```

---

## Part D — Section 9: Explainable AI & Transparent Analytics

### What it does

Formalizes what `sql_generated` was already informally doing. Every chat answer gets a structured **evidence trail** record: the exact SQL run, which tables were touched, how many rows came back, and which specific FIR IDs grounded the answer. This is then shown in the UI as an expandable "Show evidence" section under each assistant message.

### Files to update

```
backend/
├── pipeline/
│   └── query_pipeline.py        ← UPDATE: save evidence trail after each run
└── routers/
    └── chat.py                   ← UPDATE: include evidence_trail in stream/response
```

### Update to `query_pipeline.py`

```python
"""
Add a call to save_evidence_trail() right after a message is persisted
(in routers/chat.py's save_message_pair flow — see below), not inside the
pipeline itself. The pipeline's PipelineResponse already carries
sql_generated and table_data; we just need to persist a structured
trail record alongside the message.
"""

async def save_evidence_trail(message_id: int, sql_generated: str, table_data: list[dict], tables_queried: list[str]):
    """
    Insert a row into chat_evidence_trail.

    fir_ids_referenced: extract any "fir_id" values present in table_data
    rows (if the column exists), join as comma-separated string. If no
    fir_id column in results, leave empty.

    Non-fatal — log and continue on failure, same pattern as save_message_pair.
    """
    from db.connection import execute_write
    import sys

    fir_ids = []
    if table_data and "fir_id" in table_data[0]:
        fir_ids = [str(row["fir_id"]) for row in table_data if row.get("fir_id") is not None]

    try:
        await execute_write(
            """INSERT INTO chat_evidence_trail
               (message_id, sql_executed, tables_queried, row_count, fir_ids_referenced)
               VALUES (%s, %s, %s, %s, %s)""",
            (
                message_id, sql_generated, ",".join(tables_queried),
                len(table_data), ",".join(fir_ids[:100])  # cap to avoid runaway VARCHAR
            )
        )
    except Exception as e:
        print(f"WARNING: Failed to save evidence trail for message {message_id}: {e}", file=__import__('sys').stderr)
```

### Wire into `routers/chat.py`

Right after `save_message_pair()` returns the `assistant_id` (this already exists per BLUEPRINT/Docs — Step 4 work), add:

```python
from decision_support.evidence_trail import save_evidence_trail  # or wherever you place it

if assistant_id and result.sql_generated:
    # tables_queried: extract from the schema linker's selection for this turn
    # (the same list select_relevant_tables() returned — pass it through
    # from the pipeline response if not already there, or re-derive from SQL
    # via a simple regex on FROM/JOIN keywords)
    await save_evidence_trail(assistant_id, result.sql_generated, result.table_data, tables_queried)
```

> **Note:** `PipelineResponse` may need one new field — `tables_queried: list[str]` — populated by the schema linker step inside `run_pipeline()`. This is a one-line addition to the existing dataclass/object, not a structural change.

### Add a `GET` endpoint to retrieve the trail

```python
@router.get("/api/chat/messages/{message_id}/evidence")
async def get_evidence_trail(message_id: int, officer: dict = Depends(get_current_officer)):
    """
    Returns the evidence trail for a specific assistant message.
    Officer ownership is implicitly checked via the session this message
    belongs to — join through chat_messages → chat_sessions → officer_id.
    """
    from db.connection import execute_query
    rows = await execute_query(
        """SELECT t.sql_executed, t.tables_queried, t.row_count, t.fir_ids_referenced, t.created_at
           FROM chat_evidence_trail t
           JOIN chat_messages m ON m.message_id = t.message_id
           JOIN chat_sessions s ON s.session_id = m.session_id
           WHERE t.message_id = %s AND s.officer_id = %s""",
        (message_id, officer["officer_id"])
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Evidence trail not found.")
    return rows[0]
```

### Frontend addition

```jsx
/*
EvidenceTrail.jsx — small expandable section under each assistant MessageBubble.

Collapsed by default: a small text link "Show evidence" with a small icon.
Expanded: shows
  - "Queried tables: fir_master, accused"
  - "Records returned: 8"
  - "Referenced FIRs: 1, 2, 3, 4..." (clickable to open CaseDetailPanel)
  - A collapsible <pre> block with the raw SQL, monospace font, for
    officers/analysts who want to verify the exact query (Section 9
    explicitly asks for "clear data references and evidence trails" —
    this is literally that, in officer-readable form)

Fetches GET /api/chat/messages/{message_id}/evidence only when expanded
(lazy load — don't fetch for every message on render).
*/
```

This single component is your direct, literal answer to PS1 Section 9's three bullet points: data references ✓, evidence trails ✓, and a presentable accountability artifact ✓ (the raw SQL is the "reasoning path").

---

## Part E — Section 10: Secure Role-Based Access & Governance

### What it does

Role column already added to `officers` (top of this file). Now: a `require_role()` dependency that gates specific endpoints, and an audit log that records sensitive actions automatically.

### Files to create

```
backend/
└── auth/
    └── role_guard.py             ← NEW: role-check dependency + audit logging helper
```

### `backend/auth/role_guard.py`

```python
"""
Role-based access control and audit logging.
Builds on the existing JWT auth (auth/simple_auth.py) — does NOT replace it.
get_current_officer still runs first; this adds a role check on top.
"""
from fastapi import Depends, HTTPException, Request
from auth.simple_auth import get_current_officer
from db.connection import execute_write
import sys


def require_role(*allowed_roles: str):
    """
    FastAPI dependency factory. Use like:
        officer: dict = Depends(require_role("supervisor", "analyst"))

    Checks the officer's role (must be added to the JWT payload — see note
    below) against allowed_roles. Raises 403 if not permitted.

    IMPORTANT: the current JWT payload (from create_access_token in
    simple_auth.py) only has officer_id and badge_number. This needs ONE
    new field: role. Update create_access_token to also look up and embed
    the officer's role at login time, so it's available here without an
    extra DB query on every request.
    """
    async def checker(officer: dict = Depends(get_current_officer)) -> dict:
        officer_role = officer.get("role")
        if officer_role not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"This action requires one of these roles: {', '.join(allowed_roles)}."
            )
        return officer
    return checker


async def log_action(
    officer_id: int,
    action: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
    details: str | None = None,
    request: Request | None = None,
):
    """
    Insert a row into audit_log. Call this from any endpoint that touches
    sensitive data — risk scores, evidence trails, exports, role-gated actions.

    Non-fatal — audit logging must never break the actual request.
    Extracts IP from request.client.host if a Request object is passed.
    """
    try:
        ip = request.client.host if request and request.client else None
        await execute_write(
            """INSERT INTO audit_log (officer_id, action, resource_type, resource_id, details, ip_address)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (officer_id, action, resource_type, resource_id, details, ip)
        )
    except Exception as e:
        print(f"WARNING: Audit log failed for action {action}: {e}", file=sys.stderr)
```

### Update `auth/simple_auth.py`

Two small changes to the existing file:

```python
# In create_access_token — add role to the payload:
def create_access_token(officer_id: int, badge_number: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS)
    payload = {
        "officer_id": officer_id,
        "badge_number": badge_number,
        "role": role,            # NEW
        "exp": expire,
    }
    return jwt.encode(payload, get("APP_SECRET_KEY"), algorithm=ALGORITHM)


# In login() — fetch role and pass it through:
async def login(badge_number: str, password: str, pool) -> str:
    from db.connection import execute_query
    results = await execute_query(
        "SELECT officer_id, badge_number, role FROM officers WHERE badge_number = %s AND is_active = TRUE",
        (badge_number,)
    )
    if not results:
        raise HTTPException(status_code=401, detail="Invalid badge number or password.")
    officer = results[0]
    expected_password = badge_number + "123"
    if password != expected_password:
        raise HTTPException(status_code=401, detail="Invalid badge number or password.")
    return create_access_token(officer["officer_id"], officer["badge_number"], officer["role"])
```

### Apply role gates to the new endpoints from Parts A-D

Going back through what was just built, apply sensible role restrictions:

```python
# routers/profiling.py — recompute is a heavier, supervisor-level action
@router.post("/api/profiling/recompute-all")
async def recompute_all(officer: dict = Depends(require_role("supervisor", "analyst"))):
    ...

# routers/analytics.py — analytics dashboard is for analyst/supervisor/policymaker,
# not every investigator (per the PS1 brief's role list)
@router.get("/api/analytics/trends/monthly")
async def trends_monthly(
    months_back: int = Query(12, ge=1, le=60),
    officer: dict = Depends(require_role("analyst", "supervisor", "policymaker"))
):
    ...
# Apply the same require_role(...) swap to the other 6 analytics endpoints.
```

Leave the core chat (`/api/chat`, `/api/chat/stream`) and decision support endpoints open to **all** roles including `investigator` — those are the front-line tools every officer needs. The PS1 brief's role list (investigators, analysts, supervisors, policymakers) implies investigators get the conversational tool, while analytics/profiling skew toward the other three roles.

### Wire `log_action` into sensitive endpoints

```python
# Example: in routers/profiling.py
@router.get("/api/profiling/risk/{accused_id}")
async def get_risk_score(accused_id: int, officer: dict = Depends(get_current_officer), request: Request = None):
    cached = await get_cached_risk_score(accused_id)
    result = cached or await compute_risk_for_accused(accused_id)
    if not cached:
        await save_risk_score(result)
    await log_action(officer["officer_id"], "view_risk_score", "accused", str(accused_id), request=request)
    return result
```

Apply the same `log_action(...)` call pattern to: risk score views, evidence trail views, case summary generation, and chat export — these are the "sensitive data" actions Section 10 specifically calls out.

### Frontend addition

A small **"Audit Log"** view, visible only to `supervisor` role (check `officer.role` client-side after login, hide the sidebar entry otherwise — but the backend `require_role` is the real enforcement, never trust client-side hiding alone).

```jsx
/*
AuditLogView.jsx — supervisor-only.
GET /api/audit-log (new simple endpoint, paginated, supervisor-only via require_role)
Renders a plain table: timestamp, officer name, action, resource, IP.
No filtering/search needed for the hackathon — just the raw log, newest first.
*/
```

Add the matching backend endpoint:
```python
@router.get("/api/audit-log")
async def get_audit_log(limit: int = 50, officer: dict = Depends(require_role("supervisor"))):
    rows = await execute_query(
        """SELECT al.created_at, o.full_name, al.action, al.resource_type, al.resource_id, al.ip_address
           FROM audit_log al JOIN officers o ON o.officer_id = al.officer_id
           ORDER BY al.created_at DESC LIMIT %s""",
        (limit,)
    )
    return {"entries": rows}
```

---

## Build Order

Same discipline as the original 5-step plan — don't jump ahead.

1. **Schema first** — run all 4 DDL blocks, verify with `DESCRIBE`/`SHOW TABLES`
2. **Part E (role infra)** — do this first even though it's listed last, because Parts A and B's endpoints need `require_role` to exist before they can use it. Update `simple_auth.py`, create `role_guard.py`, test login still works and JWT now contains `role`
3. **Part A (analytics)** — pure SQL, no dependencies on other parts, build and test the 7 endpoints with curl before touching frontend
4. **Part B (risk scoring)** — build `risk_scoring.py`, test `compute_risk_for_accused` directly in a Python shell against Mahesh Gowda's `accused_id` before wiring the endpoint
5. **Part C (decision support)** — timeline first (pure SQL, easy), then similar cases (rule-based, moderate), then case summary (LLM call, reuses existing pattern)
6. **Part D (evidence trail)** — smallest part, wire in last since it depends on `chat_messages` already having `assistant_id` from Step 4 work
7. **Frontend** — build all backend first, verify every endpoint with curl, then wire up `AnalyticsDashboard`, `RiskBadge`, `CaseDetailPanel`, `EvidenceTrail`, `AuditLogView` in that order

---

## What This Deliberately Does NOT Include

- No Zia AutoML — risk scoring is rule-based Python, not a trained model. This is a feature, not a shortcut: it's MORE explainable than AutoML would be, directly serving Section 9.
- No vector embeddings / semantic search for "similar cases" — rule-based scoring instead, same reasoning.
- No new Catalyst service integrations of any kind — zero new auth headers, URL paths, or payload shapes to debug.
- No real-world demographic/socio-economic datasets (Section 4 from the original gap analysis) — still correctly out of scope, not touched by this blueprint.
- No financial crime or forecasting (Sections 7, 8) — still correctly out of scope, not touched by this blueprint.

This blueprint closes real gaps in sections 3, 5, 6, 9, and 10 using only infrastructure that's already proven to work tonight.
