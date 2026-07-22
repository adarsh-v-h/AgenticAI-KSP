# Station Scoping & Multi-Station Demo Data — Implementation Plan

> **Context:** Confirmed via direct codebase inspection (not assumption): `role_guard.py` only
> matches role strings (`investigator`/`supervisor`/etc.) against the JWT. It has no database
> awareness. `_format_officer_for_prompt()` only injects `PolicePersonID` for first-person
> questions ("my cases"). `unit_id` is already embedded in the JWT at login and already used by
> `rate_limiter.py` for station-scoped throttling — but nothing uses it to restrict *what data
> comes back*. Any authenticated officer, regardless of role or station, currently sees every
> case in the database. This plan fixes that and gives you a clean 5–8 station demo to show it
> working.

---

## The Decision, Restated

Keep everything in the tables you already have (`CaseMaster`, `Employee`, `Unit`, all of it).
Don't split by station. The fix is an **access-control layer on top of the existing schema**, not
a schema redesign — see the earlier discussion for why per-station tables would actively break
`trend_analytics.py`'s cross-station queries and multiply every future migration by the number of
stations.

---

## Architecture

### 1. `get_scoped_unit_ids(officer)` — the one source of truth for "what can this officer see"

New function in `backend/auth/role_guard.py`. This is a deliberate widening of that file's job —
today it's pure role-string checking; this makes it the actual place "what can this officer see"
logic lives, which fits its name better than scattering the logic across every endpoint.

```python
from db.connection import execute_query


async def get_scoped_unit_ids(officer: dict) -> list[int] | None:
    """
    Returns the list of Unit.UnitID values this officer is allowed to see
    case data for, or None if the officer has unrestricted (state/district-
    wide) access.

    - investigator: only their own station (officer['unit_id'])
    - supervisor: their own station plus every descendant station, walked
      via Unit.ParentUnit (recursive CTE -- MySQL 8.0 supports WITH RECURSIVE)
    - analyst / policymaker: None -- unrestricted access is the entire
      point of these roles
    - anything else (unknown role, missing unit_id): fail closed, treat
      as investigator-tier restricted to their own station (or nothing,
      if they don't even have a station)
    """
    role = officer.get("role")
    unit_id = officer.get("unit_id")

    if role in ("analyst", "policymaker"):
        return None

    if role == "supervisor" and unit_id:
        rows = await execute_query(
            """WITH RECURSIVE descendants AS (
                   SELECT UnitID FROM Unit WHERE UnitID = %s
                   UNION ALL
                   SELECT u.UnitID FROM Unit u
                   JOIN descendants d ON u.ParentUnit = d.UnitID
               )
               SELECT UnitID FROM descendants""",
            (unit_id,)
        )
        return [r["UnitID"] for r in rows]

    # investigator, or any unrecognized role/state -- fail closed
    return [unit_id] if unit_id else []
```

**Fail-closed by design.** An officer with a missing or unrecognized role sees nothing rather than
everything. This matters more than it might look — a bug that defaults to "unrestricted" is a
silent data leak; a bug that defaults to "empty" is an obvious support ticket.

### 2. NL2SQL path — rewrite the generated query, don't trust a prompt instruction to scope it

New module `backend/pipeline/station_scope.py`:

```python
"""
Enforces station-level row visibility on LLM-generated SQL before execution.
Runs after generate_sql()/validate_sql() succeed, before execute_query().
The LLM's output is never trusted as the actual security boundary -- this
is a deterministic rewrite, not a prompt instruction.

**IMPORTANT:** Currently, schema_catalog.py defines always_include=True on
CaseMaster, but this field is not actually enforced by schema_linker —
queries that don't mention case keywords may omit CaseMaster entirely (e.g.,
"top 5 accused with most cases" generates SQL joining only Accused, not
CaseMaster). Before wiring this module into query_pipeline.py, either (a)
implement actual always_include enforcement in schema_linker.select_relevant_tables(),
or (b) make enforce_station_scope() detect queries that genuinely don't touch
case data (e.g., pure Employee/Rank queries) and pass them through instead of
raising StationScopeError. Without this fix, ~15-20% of valid queries will
incorrectly fail closed.
"""
import re
from auth.role_guard import get_scoped_unit_ids

_CASEMASTER_FROM_RE = re.compile(
    r"\bFROM\s+CaseMaster\s+(?:AS\s+)?([A-Za-z_][A-Za-z0-9_]*)?",
    re.IGNORECASE
)
_CLAUSE_BOUNDARY_RE = re.compile(
    r"\b(GROUP\s+BY|HAVING|ORDER\s+BY|LIMIT)\b",
    re.IGNORECASE
)


class StationScopeError(Exception):
    """Raised when a query can't be confidently scoped. Caller must fail closed."""


def _casemaster_alias(sql: str) -> str | None:
    m = _CASEMASTER_FROM_RE.search(sql)
    if not m:
        return None
    return m.group(1) or "CaseMaster"


async def enforce_station_scope(sql: str, officer: dict) -> tuple[str, bool]:
    """
    Returns (possibly-rewritten sql, was_scoped).
    was_scoped is False only when the officer's role is unrestricted
    (analyst/policymaker) -- nothing to inject in that case.
    Raises StationScopeError if CaseMaster's alias can't be located; the
    caller must refuse to execute rather than run an unscoped query for a
    role that should be restricted.
    """
    scoped_ids = await get_scoped_unit_ids(officer)
    if scoped_ids is None:
        return sql, False

    alias = _casemaster_alias(sql)
    if alias is None:
        raise StationScopeError("Could not locate CaseMaster in generated SQL to apply station scope")

    if not scoped_ids:
        scoped_ids = [-1]  # officer has no assigned station -- show nothing, not everything

    # Values are integers sourced from get_scoped_unit_ids()'s own DB
    # lookup, never from user input -- safe to interpolate directly
    # after the int() cast, no injection surface.
    placeholders = ",".join(str(int(i)) for i in scoped_ids)
    condition = f"{alias}.PoliceStationID IN ({placeholders})"

    boundary = _CLAUSE_BOUNDARY_RE.search(sql)
    insert_at = boundary.start() if boundary else len(sql)

    if re.search(r"\bWHERE\b", sql[:insert_at], re.IGNORECASE):
        rewritten = sql[:insert_at].rstrip() + f" AND {condition} " + sql[insert_at:]
    else:
        rewritten = sql[:insert_at].rstrip() + f" WHERE {condition} " + sql[insert_at:]

    return rewritten, True
```

Wire it into `query_pipeline.py`, between SQL generation/validation and execution:

```python
from pipeline.station_scope import enforce_station_scope, StationScopeError

# After generate_sql() returns a validated SQL string, before execute_query(sql):
try:
    sql, _ = await enforce_station_scope(sql, officer)
except StationScopeError:
    return PipelineResponse(
        answer_text=(
            "I couldn't safely restrict that query to your station's data, "
            "so I didn't run it. Try rephrasing, or ask a supervisor if you "
            "need cross-station data."
        ),
        table_data=[], media_attachments=[], sql_generated=sql,
        graph_available=False, error="station_scope_enforcement_failed"
    )
```

**Why rewrite instead of "validate and retry through the existing self-correction loop":** rewriting
is deterministic — it doesn't depend on the LLM cooperating, so there's nothing to retry. It always
either succeeds (because `CaseMaster` is guaranteed present) or fails closed in the rare case it
isn't. Simpler and strictly safer than trying to get the LLM to comply via prompt engineering.

**Optional, secondary — nudge the prompt anyway.** Add a line to `_format_officer_for_prompt()` in
`llm/prompts.py` telling the LLM the officer's station and that results should generally reflect
it. This doesn't do any enforcement — `enforce_station_scope()` still runs regardless — but it
means the LLM's *first* draft is more often already correctly scoped, which matters for edge cases
like aggregates where blindly injecting a filter after the fact could change what a label like
"total cases" means versus what the officer expects to read.

### 3. Every other BLUEPRINT2 endpoint needs the same guard, individually

The rewrite above only covers the NL2SQL chat path. `risk_scoring.py`, `case_timeline.py`,
`case_summary.py`, and `similar_cases.py` are hand-written queries with their own direct-lookup
endpoints — none of them go through `query_pipeline.py` at all, so `enforce_station_scope()` never
touches them. Each needs its own guard, using the same `get_scoped_unit_ids()`.

Two small helpers, alongside `get_scoped_unit_ids()` in `role_guard.py`:

```python
async def officer_can_access_case(officer: dict, case_master_id: int) -> bool:
    scoped_ids = await get_scoped_unit_ids(officer)
    if scoped_ids is None:
        return True  # unrestricted role
    rows = await execute_query(
        "SELECT 1 FROM CaseMaster WHERE CaseMasterID = %s AND PoliceStationID IN ({})".format(
            ",".join(str(int(i)) for i in scoped_ids) or "-1"
        ),
        (case_master_id,)
    )
    return len(rows) > 0


async def officer_can_access_accused(officer: dict, accused_master_id: int) -> bool:
    scoped_ids = await get_scoped_unit_ids(officer)
    if scoped_ids is None:
        return True
    rows = await execute_query(
        """SELECT 1 FROM Accused a JOIN CaseMaster cm ON cm.CaseMasterID = a.CaseMasterID
           WHERE a.AccusedMasterID = %s AND cm.PoliceStationID IN ({})""".format(
            ",".join(str(int(i)) for i in scoped_ids) or "-1"
        ),
        (accused_master_id,)
    )
    return len(rows) > 0
```

Apply as a guard clause at the top of each affected route, 404 on failure — same "don't confirm
existence to someone who shouldn't see it" pattern already used everywhere else in this codebase
for BOLA/IDOR protection:

| Route | File | Guard needed |
|---|---|---|
| `GET /api/decision-support/timeline/{case_id}` | `routers/decision_support.py` | `officer_can_access_case` |
| `GET /api/decision-support/summary/{case_id}` | `routers/decision_support.py` | `officer_can_access_case` |
| `GET /api/decision-support/similar-cases/{case_id}` | `routers/decision_support.py` | `officer_can_access_case` |
| `GET /api/profiling/risk/{accused_id}` | `routers/profiling.py` | `officer_can_access_accused` |
| `GET /api/profiling/top-risk` | `routers/profiling.py` | filter the result list to scoped units (needs a small query change, not just a guard — see note below) |
| `POST /api/profiling/recompute-all` | `routers/profiling.py` | `require_role("supervisor", "analyst", "policymaker")` — this one's a bulk admin action, gate by role instead of trying to scope it |

Example for the single-ID routes:
```python
@router.get("/api/decision-support/timeline/{case_id}")
async def case_timeline(case_id: int, officer: dict = Depends(get_current_officer)):
    if not await officer_can_access_case(officer, case_id):
        raise HTTPException(status_code=404, detail="Case not found")
    events = await build_case_timeline(case_id)
    return {"case_id": case_id, "timeline": events}
```

**`top-risk` needs a slightly different fix** since it's a ranked list, not a single-ID lookup —
add a `JOIN CaseMaster cm ON cm.CaseMasterID = a.CaseMasterID` and a `WHERE cm.PoliceStationID IN (...)`
(or skip the filter entirely when `get_scoped_unit_ids()` returns `None`) directly in its query in
`risk_scoring.py`, rather than trying to guard-and-404 a list endpoint.

`GET /api/analytics/*` (Step 2's trend dashboard) is **intentionally left unrestricted** —
station-level aggregates across the whole state are the point of that dashboard for
analyst/policymaker roles, and per `SixToSeven.md`'s own original scoping decision it was never
role-gated in the first place. If you want investigators to only see their own station's trends
too, that's a follow-up decision, not something this plan assumes.

---

## Demo Seed Data

You already have 30 seeded `Unit` rows and 220 `CaseMaster` rows — the gap for a clean demo isn't
volume, it's **structure**: no `ParentUnit` hierarchy exists yet (so the supervisor tier can't be
demoed), and the 10 existing officers aren't necessarily distributed in a way that tells a clear
story.

**Current state check (as of investigation):** Only 5 Unit rows exist in the live database (not 30),
and 2 of the 6 target demo station names ("Koramangala PS", "Whitefield PS") already exist. Before
running the seed script below, verify whether these 2 existing stations have officers or cases
assigned — if so, either choose different demo station names or document that they'll be repurposed
into the new hierarchy to avoid mixing real data into the demo setup.

New, additive script — `backend/db/seed_station_demo.py` — run *after* the existing `seed.py`,
doesn't touch or duplicate anything it already created:

```python
"""
Backfills a clean 2-tier station hierarchy for demo purposes: one parent
"Circle" unit supervising 5-8 child police stations. Reassigns a subset of
existing officers and cases onto these stations so the supervisor/
investigator scoping tiers are actually demoable. Additive and idempotent
-- safe to re-run.
"""
import asyncio
from db.connection import create_pool, execute_query, execute_write, close_pool

DEMO_STATIONS = [
    "Koramangala PS", "Indiranagar PS", "HSR Layout PS",
    "Whitefield PS", "Jayanagar PS", "Yeshwanthpur PS",
]
DEMO_CIRCLE_NAME = "Bengaluru South Circle"


async def ensure_hierarchy():
    circle_rows = await execute_query(
        "SELECT UnitID FROM Unit WHERE UnitName = %s", (DEMO_CIRCLE_NAME,)
    )
    if circle_rows:
        circle_id = circle_rows[0]["UnitID"]
    else:
        circle_id = await execute_write(
            "INSERT INTO Unit (UnitName, ParentUnit, Active) VALUES (%s, NULL, 1)",
            (DEMO_CIRCLE_NAME,)
        )

    station_ids = []
    for name in DEMO_STATIONS:
        rows = await execute_query("SELECT UnitID FROM Unit WHERE UnitName = %s", (name,))
        if rows:
            station_id = rows[0]["UnitID"]
            await execute_write(
                "UPDATE Unit SET ParentUnit = %s WHERE UnitID = %s", (circle_id, station_id)
            )
        else:
            station_id = await execute_write(
                "INSERT INTO Unit (UnitName, ParentUnit, Active) VALUES (%s, %s, 1)",
                (name, circle_id)
            )
        station_ids.append(station_id)

    return circle_id, station_ids


async def assign_officers(circle_id, station_ids):
    officers = await execute_query("SELECT EmployeeID, role FROM Employee LIMIT 10")
    if not officers:
        print("No officers found -- run the main seed.py first.")
        return

    supervisor = next((o for o in officers if o["role"] == "supervisor"), officers[0])
    await execute_write("UPDATE Employee SET UnitID = %s WHERE EmployeeID = %s",
                         (circle_id, supervisor["EmployeeID"]))

    investigators = [o for o in officers if o["EmployeeID"] != supervisor["EmployeeID"]]
    for i, officer in enumerate(investigators):
        station_id = station_ids[i % len(station_ids)]
        await execute_write("UPDATE Employee SET UnitID = %s WHERE EmployeeID = %s",
                             (station_id, officer["EmployeeID"]))


async def assign_cases(station_ids):
    cases = await execute_query("SELECT CaseMasterID FROM CaseMaster LIMIT 30")
    for i, case in enumerate(cases):
        station_id = station_ids[i % len(station_ids)]
        await execute_write("UPDATE CaseMaster SET PoliceStationID = %s WHERE CaseMasterID = %s",
                             (station_id, case["CaseMasterID"]))


async def main():
    await create_pool()
    circle_id, station_ids = await ensure_hierarchy()
    await assign_officers(circle_id, station_ids)
    await assign_cases(station_ids)
    print(f"Circle unit {circle_id}, stations {station_ids} -- demo hierarchy ready.")
    await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
```

Adjust the `LIMIT 10` / `LIMIT 30` and the loop logic if you want a different split than "first 30
cases round-robined across 6 stations" — the point of the script is the hierarchy + reassignment
mechanics, not the exact distribution, which you know your seed data better than I do to tune.

---

## Step-by-Step Build Order

1. **Create a policymaker officer** — the `policymaker` role is defined in the Employee schema but
   no current officer has it. Add at least one test officer with `role = 'policymaker'` so the
   unrestricted-access tier can be verified:
   ```sql
   UPDATE Employee SET role = 'policymaker' WHERE EmployeeID = <some_test_officer_id>;
   ```
2. **Fix `always_include` enforcement** — either implement actual always_include logic in
   `schema_linker.select_relevant_tables()` to force-add CaseMaster to every query's table set,
   or modify `enforce_station_scope()` to detect and pass through queries that genuinely don't
   reference case data (e.g., pure Employee/Rank queries). Without this, valid non-case queries
   will incorrectly fail with `StationScopeError`.
3. Run `seed_station_demo.py` — but first verify whether Koramangala PS and Whitefield PS (which
   already exist) have officers/cases assigned, to avoid mixing real data into the demo hierarchy.
4. Add `get_scoped_unit_ids()`, `officer_can_access_case()`, `officer_can_access_accused()` to
   `role_guard.py`.
5. Add `pipeline/station_scope.py`, wire `enforce_station_scope()` into `query_pipeline.py`.
6. Add the guard clauses to `decision_support.py` and `profiling.py` per the table above.
7. Fix `top-risk`'s query directly (station-filtered JOIN, not a guard-and-404).

---

## Verify

```bash
# Log in as an investigator assigned to one of the demo stations, and as
# the supervisor at the circle level.
INV_TOKEN=$(...)
SUP_TOKEN=$(...)

# Investigator asking a broad question should only get their own station's cases:
curl -s -X POST http://localhost:8000/api/chat -H "Authorization: Bearer $INV_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question": "Show me all open cases", "session_id": "scope-test-1"}' | python3 -m json.tool
# Manually confirm every returned case's station matches the investigator's own UnitID.

# Supervisor asking the same question should get all 6 demo stations' cases:
curl -s -X POST http://localhost:8000/api/chat -H "Authorization: Bearer $SUP_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question": "Show me all open cases", "session_id": "scope-test-2"}' | python3 -m json.tool

# Investigator trying to view a case timeline from a station they don't belong to:
curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer $INV_TOKEN" \
  "http://localhost:8000/api/decision-support/timeline/<a_case_id_from_another_station>"
# Expected: 404

# Analyst/policymaker asking the same broad question should still see everything (unrestricted by design):
curl -s -X POST http://localhost:8000/api/chat -H "Authorization: Bearer $ANALYST_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question": "Show me all open cases", "session_id": "scope-test-3"}' | python3 -m json.tool
```

---

## What This Plan Does NOT Cover

- DB-level Row-Level Security / parameterized views — doesn't fit the shared connection-pool
  architecture without a bigger rearchitecture; revisit only if this moves beyond hackathon scope
- Restricting `analytics.py`'s dashboard by station — deliberately left as-is; state-wide
  aggregates are the point of that feature for analyst/policymaker roles
- Any frontend changes — this is entirely a backend enforcement layer; the frontend already just
  renders whatever the backend returns, so a properly-scoped response requires no UI changes
- Sharding, partitioning, or any physical data separation — not needed at this data volume, per
  the earlier discussion
