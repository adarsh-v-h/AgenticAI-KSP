# BLUEPRINT2_PATCH.md — Aligning BLUEPRINT2 with the Migrated Schema

> **Context:** `BLUEPRINT2.md` was written before the official KSP ER diagram existed — it targets the old hackathon schema (`fir_master`, `accused`, `officers`, `cases_*`). `MIGRATE.md` has since replaced that schema entirely (`CaseMaster`, `Accused`, `Employee`, lookup tables for crime type/status/etc.).
>
> **Yes, BLUEPRINT2 needs changes — every SQL query and FK reference in it is now stale.** This file is a targeted patch: it doesn't repeat BLUEPRINT2's full content, it tells you exactly which sections to replace and what to replace them with. Apply this **after** MIGRATE.md is fully done and verified (Section 9, steps 1–15 of MIGRATE.md should all be green before you touch this).
>
> Read this alongside an open copy of `BLUEPRINT2.md` — section numbers below refer to BLUEPRINT2's own headers.

---

## Quick Reference — The Renames That Ripple Through Everything

Keep this open while editing. Every query in BLUEPRINT2 uses some combination of these old names.

| Old (BLUEPRINT2) | New (MIGRATE.md) |
|---|---|
| `fir_master` | `CaseMaster` |
| `fir_id` | `CaseMasterID` |
| `accused` | `Accused` |
| `accused_id` | `AccusedMasterID` |
| `accused.full_name` | `Accused.AccusedName` |
| `accused.alias` | *(gone — folded into AccusedName, see MIGRATE.md §5)* |
| `accused.prior_fir_count` | *(gone — compute live: `COUNT(*) FROM Accused WHERE AccusedName = ...`)* |
| `accused.arrest_status == 'at_large'` | *(gone — derive via `LEFT JOIN ArrestSurrender ... WHERE ArrestSurrenderID IS NULL`)* |
| `officers` | `Employee` |
| `officer_id` | `EmployeeID` |
| `officers.full_name` | `Employee.FirstName` |
| `officers.badge_number` | `Employee.KGID` |
| `fir_master.case_type` (ENUM) | `CaseMaster.CrimeMinorHeadID` → join `CrimeSubHead.CrimeHeadName` |
| `fir_master.date_filed` | `CaseMaster.CrimeRegisteredDate` |
| `fir_master.status` (ENUM) | `CaseMaster.CaseStatusID` → join `CaseStatusMaster.CaseStatusName` |
| `fir_master.incident_location` | *(gone — no free-text location column; use `Unit.UnitName` via `PoliceStationID`, or `latitude`/`longitude`)* |
| `fir_master.description` | `CaseMaster.BriefFacts` |
| `case_relationships` | *(gone — derive relationships computationally, see MIGRATE.md §7)* |
| `chat_messages.fir_id` references | now `CaseMasterID` (the chat/session tables themselves are untouched by MIGRATE.md — only the columns that *referenced* the old crime schema change) |

---

## Patch 1 — Database Changes section (BLUEPRINT2 lines ~26–108)

### `offender_risk_scores` table — FK target changes

Original:
```sql
CREATE TABLE IF NOT EXISTS offender_risk_scores (
    accused_id          INT PRIMARY KEY,
    ...
    FOREIGN KEY (accused_id) REFERENCES accused(accused_id)
);
```

Replace with:
```sql
CREATE TABLE IF NOT EXISTS offender_risk_scores (
    AccusedMasterID      INT PRIMARY KEY,
    risk_score           DECIMAL(5,2) NOT NULL,
    risk_tier            ENUM('low', 'medium', 'high', 'critical') NOT NULL,
    contributing_factors TEXT,
    computed_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (AccusedMasterID) REFERENCES Accused(AccusedMasterID)
);
```

### `chat_evidence_trail` table — `fir_ids_referenced` column

The column itself can stay named `fir_ids_referenced` for simplicity (it's just a comma-separated string, not an FK), but its *meaning* changes — it now stores `CaseMasterID` values, not `fir_id` values. Either rename it for clarity or add a comment:

```sql
CREATE TABLE IF NOT EXISTS chat_evidence_trail (
    trail_id           INT AUTO_INCREMENT PRIMARY KEY,
    message_id         INT NOT NULL,
    sql_executed       TEXT NOT NULL,
    tables_queried     VARCHAR(300),
    row_count          INT,
    case_ids_referenced VARCHAR(500),   -- RENAMED from fir_ids_referenced — comma-separated CaseMasterID values
    created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (message_id) REFERENCES chat_messages(message_id),
    INDEX idx_trail_message (message_id)
);
```

### `role` column on the officer table — table name change only

Original (BLUEPRINT2):
```sql
ALTER TABLE officers
  ADD COLUMN role ENUM('investigator', 'analyst', 'supervisor', 'policymaker')
  NOT NULL DEFAULT 'investigator';
```

**This is actually already handled — skip it entirely.** MIGRATE.md's `Employee` table DDL (§3) already includes the `role` column inline:
```sql
role ENUM('investigator','analyst','supervisor','policymaker') NOT NULL DEFAULT 'investigator',
```
Don't run BLUEPRINT2's `ALTER TABLE officers` — that table doesn't exist anymore. If you already ran it before migrating, no action needed; it's just dead SQL now.

### `audit_log` table — FK target changes

Original:
```sql
FOREIGN KEY (officer_id) REFERENCES officers(officer_id)
```
Replace with:
```sql
FOREIGN KEY (officer_id) REFERENCES Employee(EmployeeID)
```
(Keep the column itself named `officer_id` in `audit_log` — that's our own table, not part of the official schema, so the column name is ours to keep. Only the FK *target* table/column changes.)

---

## Patch 2 — Part A: Analytics (`trend_analytics.py`)

Every function in this module needs its SQL rewritten. Here is the complete corrected module — replace the whole file content with this:

```python
"""
Crime pattern and trend analytics — pure SQL aggregation, no ML.
All queries read from CaseMaster and its classification lookup tables
(CrimeHead/CrimeSubHead/CaseStatusMaster) per the official KSP schema.
"""
from db.connection import execute_query


async def get_trend_by_month(months_back: int = 12) -> list[dict]:
    """
    Crime count per month for the last `months_back` months.
    Returns: [{"month": "2025-06", "count": 34}, ...]
    """
    return await execute_query(
        """SELECT DATE_FORMAT(CrimeRegisteredDate, '%Y-%m') AS month, COUNT(*) AS count
           FROM CaseMaster
           WHERE CrimeRegisteredDate >= DATE_SUB(CURDATE(), INTERVAL %s MONTH)
           GROUP BY month
           ORDER BY month ASC""",
        (months_back,)
    )


async def get_trend_by_crime_type() -> list[dict]:
    """
    Total count per crime sub-head (the actual crime type), all time.
    Returns: [{"crime_type": "Theft", "count": 45}, ...]
    """
    return await execute_query(
        """SELECT csh.CrimeHeadName AS crime_type, COUNT(*) AS count
           FROM CaseMaster cm
           JOIN CrimeSubHead csh ON csh.CrimeSubHeadID = cm.CrimeMinorHeadID
           GROUP BY csh.CrimeHeadName
           ORDER BY count DESC"""
    )


async def get_trend_by_location(limit: int = 10) -> list[dict]:
    """
    Crime count per police station (closest available "location" concept —
    CaseMaster has no free-text location column in the official schema).
    Returns: [{"station": "Koramangala Police Station", "count": 28}, ...]
    """
    return await execute_query(
        """SELECT u.UnitName AS station, COUNT(*) AS count
           FROM CaseMaster cm
           JOIN Unit u ON u.UnitID = cm.PoliceStationID
           GROUP BY u.UnitName
           ORDER BY count DESC
           LIMIT %s""",
        (limit,)
    )


async def get_crime_type_by_location(station_unit_id: int) -> list[dict]:
    """
    Breakdown of crime types within a single police station — for drill-down.
    NOTE: signature changed from `location: str` to `station_unit_id: int`
    since location is now represented by Unit.UnitID, not a free-text string.
    Returns: [{"crime_type": "Theft", "count": 12}, ...]
    """
    return await execute_query(
        """SELECT csh.CrimeHeadName AS crime_type, COUNT(*) AS count
           FROM CaseMaster cm
           JOIN CrimeSubHead csh ON csh.CrimeSubHeadID = cm.CrimeMinorHeadID
           WHERE cm.PoliceStationID = %s
           GROUP BY csh.CrimeHeadName
           ORDER BY count DESC""",
        (station_unit_id,)
    )


async def get_status_breakdown() -> list[dict]:
    """
    Count of cases by investigation status.
    Returns: [{"status": "Open", "count": 132}, ...]
    """
    return await execute_query(
        """SELECT csm.CaseStatusName AS status, COUNT(*) AS count
           FROM CaseMaster cm
           JOIN CaseStatusMaster csm ON csm.CaseStatusID = cm.CaseStatusID
           GROUP BY csm.CaseStatusName
           ORDER BY count DESC"""
    )


async def get_modus_operandi_clusters(min_occurrences: int = 2) -> list[dict]:
    """
    REWORKED — case_relationships no longer exists (MIGRATE.md §7, Option A).
    Proxy for "MO clustering": groups cases by the SAME crime sub-head AND
    SAME police station, surfacing repeated patterns at a given station.
    Returns: [{"crime_type": "Theft", "station": "Koramangala...", "count": 6}, ...]
    Only returns groups with count >= min_occurrences.
    """
    return await execute_query(
        """SELECT csh.CrimeHeadName AS crime_type, u.UnitName AS station, COUNT(*) AS count
           FROM CaseMaster cm
           JOIN CrimeSubHead csh ON csh.CrimeSubHeadID = cm.CrimeMinorHeadID
           JOIN Unit u ON u.UnitID = cm.PoliceStationID
           GROUP BY csh.CrimeHeadName, u.UnitName
           HAVING count >= %s
           ORDER BY count DESC""",
        (min_occurrences,)
    )


async def get_seasonal_pattern() -> list[dict]:
    """
    Crime count grouped by month-of-year, irrespective of which year.
    Returns: [{"month_num": 1, "month_name": "January", "count": 18}, ...]
    """
    return await execute_query(
        """SELECT MONTH(CrimeRegisteredDate) AS month_num,
                  MONTHNAME(CrimeRegisteredDate) AS month_name,
                  COUNT(*) AS count
           FROM CaseMaster
           GROUP BY month_num, month_name
           ORDER BY month_num ASC"""
    )
```

### `routers/analytics.py` changes

The drill-down endpoint's route param changes from a string location to an integer unit ID:

```python
# OLD:
@router.get("/api/analytics/trends/location/{location}/breakdown")
async def location_breakdown(location: str, officer: dict = Depends(...)):
    data = await get_crime_type_by_location(location)
    return {"location": location, "breakdown": data}

# NEW:
@router.get("/api/analytics/trends/station/{unit_id}/breakdown")
async def station_breakdown(unit_id: int, officer: dict = Depends(...)):
    data = await get_crime_type_by_location(unit_id)
    return {"unit_id": unit_id, "breakdown": data}
```

All other analytics routes keep their signatures — only the underlying query changed, not the route or response shape, since they just call the now-corrected functions above.

### Frontend — `AnalyticsDashboard.jsx` panel 3 changes

Panel 3 ("Top 10 locations") now shows police station names instead of free-text locations. Update the panel label from "Top Locations" to "Top Police Stations by Case Count," and update the drill-down click handler to pass `unit_id` (an integer it already has from the API response) instead of a location string — this is actually simpler than before since you're passing a real ID, not URL-encoding a string with spaces/commas.

---

## Patch 3 — Part B: Offender Profiling (`risk_scoring.py`)

This module needs the heaviest rework — three of its five risk factors depended on fields that no longer exist as stored columns. Replace the entire file with this:

```python
"""
Rule-based, explainable offender risk scoring.
Rewritten against the official KSP schema — prior_fir_count and arrest_status
no longer exist as stored fields, so they're computed live.
"""
import json
from datetime import date
from db.connection import execute_query, execute_write

WEIGHTS = {
    "prior_case_count": 30,
    "violent_crime_ratio": 25,
    "at_large_status": 15,
    "geographic_spread": 15,
    "recency": 15,
}

# CrimeHeadName values considered violent — matches the seed mapping in
# MIGRATE.md §4 (Assault, Murder, Domestic Violence under "Crimes Against Person")
VIOLENT_CRIME_NAMES = ("Assault", "Murder", "Domestic Violence", "Robbery")


async def compute_risk_for_accused(accused_id: int) -> dict:
    """
    Compute a risk score for one accused person, identified by AccusedMasterID.

    Key change from the pre-migration version: prior_fir_count and
    arrest_status no longer exist as columns. Both are now derived:
      - prior case count = COUNT of Accused rows sharing the same AccusedName
        (the schema has no person-level identity beyond name matching —
        this is a known limitation, same as MIGRATE.md flagged for the
        network graph's "repeat offender" links)
      - at-large status = TRUE if NO row exists for this accused in
        ArrestSurrender

    Returns the same shape as before:
    {
        "accused_id": int, "risk_score": float, "risk_tier": str,
        "contributing_factors": [{"factor": str, "points": float}, ...]
    }
    Never raises — returns a zero-score default on any DB error.
    """
    try:
        accused_rows = await execute_query(
            "SELECT AccusedName FROM Accused WHERE AccusedMasterID = %s",
            (accused_id,)
        )
        if not accused_rows:
            return _empty_score(accused_id)
        accused_name = accused_rows[0]["AccusedName"]

        # All cases featuring anyone with this exact name (identity-by-name,
        # same limitation noted in MIGRATE.md for repeat-offender detection)
        case_rows = await execute_query(
            """SELECT cm.CaseMasterID, csh.CrimeHeadName, u.UnitName, cm.CrimeRegisteredDate
               FROM Accused a
               JOIN CaseMaster cm ON cm.CaseMasterID = a.CaseMasterID
               JOIN CrimeSubHead csh ON csh.CrimeSubHeadID = cm.CrimeMinorHeadID
               JOIN Unit u ON u.UnitID = cm.PoliceStationID
               WHERE a.AccusedName = %s""",
            (accused_name,)
        )

        total_cases = len(case_rows) or 1
        violent_count = sum(1 for r in case_rows if r["CrimeHeadName"] in VIOLENT_CRIME_NAMES)
        violent_ratio = violent_count / total_cases

        stations = {r["UnitName"] for r in case_rows if r["UnitName"]}
        geo_spread = len(stations)

        dates = [r["CrimeRegisteredDate"] for r in case_rows if r["CrimeRegisteredDate"]]
        most_recent = max(dates) if dates else None
        days_since = (date.today() - most_recent).days if most_recent else 9999

        # At-large check: no ArrestSurrender row exists for ANY of this
        # accused's case appearances
        case_ids = [r["CaseMasterID"] for r in case_rows]
        is_at_large = True
        if case_ids:
            placeholders = ",".join(["%s"] * len(case_ids))
            arrest_rows = await execute_query(
                f"""SELECT ar.ArrestSurrenderID
                    FROM ArrestSurrender ar
                    JOIN Accused a ON a.AccusedMasterID = ar.AccusedMasterID
                    WHERE a.AccusedName = %s AND ar.CaseMasterID IN ({placeholders})""",
                (accused_name, *case_ids)
            )
            is_at_large = len(arrest_rows) == 0

        prior_score = min(total_cases * 6, WEIGHTS["prior_case_count"])
        violent_score = round(violent_ratio * WEIGHTS["violent_crime_ratio"], 1)
        at_large_score = WEIGHTS["at_large_status"] if is_at_large else 0
        geo_score = min(geo_spread * 5, WEIGHTS["geographic_spread"])
        if days_since < 90:
            recency_score = WEIGHTS["recency"]
        elif days_since < 365:
            recency_score = round(WEIGHTS["recency"] * 0.55, 1)
        else:
            recency_score = round(WEIGHTS["recency"] * 0.15, 1)

        total_score = min(round(prior_score + violent_score + at_large_score + geo_score + recency_score, 1), 100.0)

        if total_score < 25:
            tier = "low"
        elif total_score < 50:
            tier = "medium"
        elif total_score < 75:
            tier = "high"
        else:
            tier = "critical"

        factors = sorted([
            {"factor": f"{total_cases} case(s) on record under this name", "points": prior_score},
            {"factor": f"{round(violent_ratio*100)}% of cases are violent offenses", "points": violent_score},
            {"factor": "No arrest/surrender record found (at large)" if is_at_large else "Has an arrest/surrender record on file", "points": at_large_score},
            {"factor": f"Cases span {geo_spread} distinct police station(s)", "points": geo_score},
            {"factor": f"Most recent case registered {days_since} days ago", "points": recency_score},
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
    await execute_write(
        """INSERT INTO offender_risk_scores (AccusedMasterID, risk_score, risk_tier, contributing_factors)
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
    rows = await execute_query(
        "SELECT AccusedMasterID, risk_score, risk_tier, contributing_factors FROM offender_risk_scores WHERE AccusedMasterID = %s",
        (accused_id,)
    )
    if not rows:
        return None
    row = rows[0]
    return {
        "accused_id": row["AccusedMasterID"],
        "risk_score": float(row["risk_score"]),
        "risk_tier": row["risk_tier"],
        "contributing_factors": json.loads(row["contributing_factors"]) if row["contributing_factors"] else [],
    }


async def recompute_all_risk_scores() -> int:
    rows = await execute_query("SELECT DISTINCT AccusedMasterID FROM Accused")
    count = 0
    for row in rows:
        result = await compute_risk_for_accused(row["AccusedMasterID"])
        await save_risk_score(result)
        count += 1
    return count
```

### `routers/profiling.py` — `top-risk` query update

```python
# OLD JOIN used officers.full_name-equivalent (accused.full_name); NEW uses Accused.AccusedName.
# Also note: offender_risk_scores' PK column renamed AccusedMasterID per Patch 1.

@router.get("/api/profiling/top-risk")
async def top_risk_offenders(limit: int = 10, officer: dict = Depends(get_current_officer)):
    rows = await execute_query(
        """SELECT s.AccusedMasterID, a.AccusedName, s.risk_score, s.risk_tier
           FROM offender_risk_scores s
           JOIN Accused a ON a.AccusedMasterID = s.AccusedMasterID
           ORDER BY s.risk_score DESC
           LIMIT %s""",
        (limit,)
    )
    return {"top_risk": rows}
```

(Dropped `alias` and `arrest_status` from the SELECT — neither exists anymore. If you want an at-a-glance arrest status in this list, that requires a correlated subquery against `ArrestSurrender`, which is more than this summary endpoint needs — leave it to the detail view, which already computes `is_at_large` inside `compute_risk_for_accused`.)

---

## Patch 4 — Part C: Decision Support

### `case_timeline.py` — rebuild around new event sources

```python
"""
Builds a chronological timeline for a single case.
REWORKED — the old per-type recovery_date events (cases_theft.recovery_date,
cases_vehicle_theft.recovery_date, etc.) no longer exist. Timeline events now
come from: CaseMaster registration, ArrestSurrender events, and (optionally)
ChargesheetDetails if that table was migrated (it's in MIGRATE.md's "defer"
list — skip referencing it unless you've added it).
"""
from db.connection import execute_query


async def build_case_timeline(case_master_id: int) -> list[dict]:
    """
    Returns chronologically ordered events:
    [{"date": "2024-05-15", "event": "Case registered", "detail": "..."}, ...]

    Events pulled from:
    - CaseMaster.CrimeRegisteredDate -> "Case registered"
    - CaseMaster.IncidentFromDate -> "Incident occurred" (often before registration)
    - ArrestSurrender.ArrestSurrenderDate (one row per arrested accused) ->
      "Accused arrested/surrendered: {AccusedName}"
    """
    events = []

    case_rows = await execute_query(
        "SELECT CrimeRegisteredDate, IncidentFromDate, IncidentToDate FROM CaseMaster WHERE CaseMasterID = %s",
        (case_master_id,)
    )
    if not case_rows:
        return []
    case = case_rows[0]

    if case.get("IncidentFromDate"):
        events.append({"date": str(case["IncidentFromDate"]), "event": "Incident occurred", "detail": ""})
    if case.get("CrimeRegisteredDate"):
        events.append({"date": str(case["CrimeRegisteredDate"]), "event": "Case registered", "detail": ""})

    arrest_rows = await execute_query(
        """SELECT ar.ArrestSurrenderDate, a.AccusedName
           FROM ArrestSurrender ar
           JOIN Accused a ON a.AccusedMasterID = ar.AccusedMasterID
           WHERE ar.CaseMasterID = %s""",
        (case_master_id,)
    )
    for row in arrest_rows:
        if row.get("ArrestSurrenderDate"):
            events.append({
                "date": str(row["ArrestSurrenderDate"]),
                "event": f"Accused arrested/surrendered: {row['AccusedName']}",
                "detail": ""
            })

    events.sort(key=lambda e: e["date"])
    return events
```

### `similar_cases.py` — update similarity signals

```python
"""
Rule-based case similarity finder. Updated similarity signals:
  - Same CrimeMinorHeadID (crime type): +40   [was: same case_type]
  - Same PoliceStationID: +25                 [was: same incident_location]
  - Filed within 90 days: +15                 [unchanged in spirit]
  - case_relationships no longer exists — the "+20 shares an accused"
    signal is now computed directly via an Accused name-match join,
    not via a relationships table lookup.
"""
from db.connection import execute_query


async def find_similar_cases(case_master_id: int, limit: int = 5) -> list[dict]:
    source_rows = await execute_query(
        "SELECT CrimeMinorHeadID, PoliceStationID, CrimeRegisteredDate FROM CaseMaster WHERE CaseMasterID = %s",
        (case_master_id,)
    )
    if not source_rows:
        return []
    source = source_rows[0]

    candidates = await execute_query(
        """SELECT cm.CaseMasterID, cm.CrimeNo, cm.PoliceStationID, cm.CrimeRegisteredDate
           FROM CaseMaster cm
           WHERE cm.CrimeMinorHeadID = %s AND cm.CaseMasterID != %s
           LIMIT 200""",
        (source["CrimeMinorHeadID"], case_master_id)
    )

    # Names of accused in the source case, for the "shares an accused" signal
    source_accused = await execute_query(
        "SELECT AccusedName FROM Accused WHERE CaseMasterID = %s",
        (case_master_id,)
    )
    source_names = {r["AccusedName"] for r in source_accused if r.get("AccusedName")}

    results = []
    for c in candidates:
        score = 40  # same crime type, guaranteed by the WHERE clause above
        reasons = ["Same crime type"]

        if c["PoliceStationID"] == source["PoliceStationID"]:
            score += 25
            reasons.append("Same police station")

        if source.get("CrimeRegisteredDate") and c.get("CrimeRegisteredDate"):
            delta = abs((c["CrimeRegisteredDate"] - source["CrimeRegisteredDate"]).days)
            if delta <= 90:
                score += 15
                reasons.append("Filed within 90 days")

        cand_accused = await execute_query(
            "SELECT AccusedName FROM Accused WHERE CaseMasterID = %s",
            (c["CaseMasterID"],)
        )
        cand_names = {r["AccusedName"] for r in cand_accused if r.get("AccusedName")}
        if source_names & cand_names:
            score += 20
            reasons.append("Shares an accused person")

        results.append({
            "case_id": c["CaseMasterID"],
            "crime_no": c["CrimeNo"],
            "match_score": score,
            "match_reasons": reasons,
        })

    results.sort(key=lambda r: r["match_score"], reverse=True)
    return results[:limit]
```

### `case_summary.py` — update fact-sheet query

The function structure stays identical (it's an LLM call, no integration risk) — only the SQL that builds the "fact sheet" changes:

```python
# Replace the fact-gathering queries inside generate_case_summary() with:
case_rows = await execute_query(
    """SELECT cm.CrimeNo, cm.CrimeRegisteredDate, cm.BriefFacts,
              csh.CrimeHeadName, csm.CaseStatusName, u.UnitName
       FROM CaseMaster cm
       JOIN CrimeSubHead csh ON csh.CrimeSubHeadID = cm.CrimeMinorHeadID
       JOIN CaseStatusMaster csm ON csm.CaseStatusID = cm.CaseStatusID
       JOIN Unit u ON u.UnitID = cm.PoliceStationID
       WHERE cm.CaseMasterID = %s""",
    (case_master_id,)
)
accused_rows = await execute_query(
    "SELECT AccusedName, AgeYear FROM Accused WHERE CaseMasterID = %s",
    (case_master_id,)
)
victim_rows = await execute_query(
    "SELECT VictimName, AgeYear FROM Victim WHERE CaseMasterID = %s",
    (case_master_id,)
)
```

Everything downstream (building the fact-sheet text, the system prompt, the `call_llm` invocation) stays exactly the same — only field names in the fact sheet text change correspondingly (`CrimeHeadName` instead of `case_type`, etc.).

### `routers/decision_support.py` — route param renames

All three routes' path param `fir_id` should be renamed `case_id` for clarity going forward (though FastAPI doesn't care about the param name matching the DB column — this is purely a readability choice). If you want to minimize churn, you can leave the route paths as `/api/decision-support/timeline/{fir_id}` and just treat the value as a `CaseMasterID` internally — your call. Recommend renaming for clarity since this code will likely be read by people unfamiliar with the migration history.

---

## Patch 5 — Part D: Evidence Trail

### `save_evidence_trail()` — field extraction change

```python
# OLD:
fir_ids = []
if table_data and "fir_id" in table_data[0]:
    fir_ids = [str(row["fir_id"]) for row in table_data if row.get("fir_id") is not None]

# NEW:
case_ids = []
if table_data and "CaseMasterID" in table_data[0]:
    case_ids = [str(row["CaseMasterID"]) for row in table_data if row.get("CaseMasterID") is not None]
```

And update the INSERT to use the renamed column from Patch 1:
```python
await execute_write(
    """INSERT INTO chat_evidence_trail
       (message_id, sql_executed, tables_queried, row_count, case_ids_referenced)
       VALUES (%s, %s, %s, %s, %s)""",
    (message_id, sql_generated, ",".join(tables_queried), len(table_data), ",".join(case_ids[:100]))
)
```

> **Important caveat:** the schema linker's table selection (`tables_queried`) will now return PascalCase names like `CaseMaster`, `Accused` — this is fine, it's just a descriptive string in this table, no FK constraint on it. No code change needed beyond what naturally flows from the schema_catalog rewrite already done in MIGRATE.md §6.1.

### `EvidenceTrail.jsx` frontend — field display update

Change the label "Referenced FIRs" to "Referenced Cases" and update the click handler that opens `CaseDetailPanel` to pass the value as `caseId` instead of `firId` (matching whatever prop name you used when updating `CaseDetailPanel.jsx` per MIGRATE.md §10).

---

## Patch 6 — Part E: Roles & Audit Log

### `role_guard.py` — no SQL changes needed

This file has **zero direct table references** — it only reads `officer.get("role")` from the JWT payload dict, which is populated at login time. No patch needed here at all, since the role lookup happens inside `simple_auth.py`'s `login()`, not here.

### `simple_auth.py` — already covered by MIGRATE.md §6.5

MIGRATE.md already specified this exact change (`officers` → `Employee`, `officer_id` → `EmployeeID`, `badge_number` → `KGID`, `full_name` → `FirstName`). Confirm it's done — if you applied MIGRATE.md's Section 6.5 already, **BLUEPRINT2's auth patch is now redundant and superseded.** Just make sure the final `login()` function selects `role` alongside the renamed fields:

```python
results = await execute_query(
    "SELECT EmployeeID, KGID, FirstName, role FROM Employee WHERE KGID = %s AND is_active = TRUE",
    (badge_number,)
)
```

### `routers/profiling.py` and `routers/analytics.py` role gates — no change

The `require_role(...)` dependency calls themselves don't reference any schema-specific names — they're pure role-string checks. No patch needed beyond what Patches 2 and 3 already updated in those files' query bodies.

### `audit_log` query — `officers` → `Employee` join

```python
# OLD:
"""SELECT al.created_at, o.full_name, al.action, al.resource_type, al.resource_id, al.ip_address
   FROM audit_log al JOIN officers o ON o.officer_id = al.officer_id
   ORDER BY al.created_at DESC LIMIT %s"""

# NEW:
"""SELECT al.created_at, o.FirstName, al.action, al.resource_type, al.resource_id, al.ip_address
   FROM audit_log al JOIN Employee o ON o.EmployeeID = al.officer_id
   ORDER BY al.created_at DESC LIMIT %s"""
```

(`audit_log.officer_id` column name itself stays the same per Patch 1's note — only the join target changes.)

---

## Patch 7 — Build Order Addendum

Insert this as a new **Step 0** before BLUEPRINT2's existing 7-step build order:

> **Step 0 — Confirm migration is complete and verified.** Run MIGRATE.md's Section 9 checklist (steps 1–15) end to end, including the Mahesh Gowda survival check, before starting any BLUEPRINT2 work. Every patch in this document assumes `CaseMaster`/`Accused`/`Employee` already exist and are populated. Building BLUEPRINT2 against a half-migrated database will produce confusing FK errors that look like BLUEPRINT2 bugs but are actually migration gaps.

Everything from BLUEPRINT2's original Step 1 onward stays the same sequence — just apply the patches in this document to each file *as you build it*, rather than building the original BLUEPRINT2 code verbatim and patching afterward. It's less rework to write the corrected version directly.

---

## What This Patch Does Not Cover

- `AnalyticsDashboard.jsx`, `RiskBadge.jsx`, `CaseDetailPanel.jsx`, `AuditLogView.jsx` — these frontend components' JSX structure is unaffected by the migration (they just render whatever JSON the backend returns). The only frontend changes needed are the small field-name/label updates called out inline in Patches 2, 3, and 5 above. No frontend component needs a structural rewrite.
- Anything in `BLUEPRINT.md` (the original core chatbot) — that file's own pipeline code is covered by MIGRATE.md directly (Section 6.5 lists every BLUEPRINT2 module it touches, and MIGRATE.md's own scope already includes the core `query_pipeline.py`, `schema_catalog.py`, etc.). This patch is scoped purely to BLUEPRINT2's five additive sections.
