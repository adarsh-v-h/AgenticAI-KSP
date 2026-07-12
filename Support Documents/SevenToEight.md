# SevenToEight — Step 3 of 4 (BLUEPRINT2 Build)

> **Context:** `FiveToSix.md` (Step 1) and `SixToSeven.md` (Step 2) are done. Between them and
> whatever got built directly off `BLUEPRINT2_PATCH.md` out of sequence, the actual state of the
> codebase as of this step is:
>
> | Feature | Status |
> |---|---|
> | Part A — Trend Analytics (`trend_analytics.py`, `routers/analytics.py`, dashboard) | ✅ Done (Step 2) |
> | Part B — Offender Profiling (`risk_scoring.py`, `routers/profiling.py`) | ✅ Done — built out of sequence, already live |
> | Part C — `similar_cases.py` + `GET /api/decision-support/similar-cases/{case_id}` | ✅ Done — also built out of sequence |
> | Part C — `case_timeline.py`, `case_summary.py` | ❌ Do not exist |
> | Part D — `chat_evidence_trail` table | ✅ Exists on AWS RDS, but **zero code writes to it** |
> | Part E — Roles & Audit (`role_guard.py`, `audit_log`, `governance.py`) | ✅ Done (Step 1) |
>
> **This changes what Step 3 is.** It is *not* "build Part B" (the original plan in
> `SixToSeven.md`'s closing note) — Part B is already live and more refined than
> `BLUEPRINT2_PATCH.md` Patch 3's literal text (it dedupes by `AccusedName` and excludes
> placeholder names on `top-risk`, neither of which the patch specifies). Step 3 is instead:
> **audit the two features that already exist, finish the two Part C files that don't, and wire
> up the evidence-trail table that's been sitting empty since Step 1.**
>
> Frontend (`RiskBadge.jsx`, `EvidenceTrail.jsx`, and `CaseDetailPanel.jsx` wiring for
> timeline/summary/similar-cases) is **deliberately out of scope for this step** — see
> "What Step 4 Will Build" at the end. This step touches three feature areas' backends already;
> bundling three new frontend components on top of that in the same doc isn't worth the sprawl.

---

## What Step 3 Is

Four things, in order:
1. **Audit, don't rebuild** — verification passes against `risk_scoring.py`/`routers/profiling.py`
   (Part B) and `similar_cases.py`/`routers/decision_support.py`'s existing `similar-cases` route
   (Part C), confirming both still behave correctly against current seeded data. No code changes
   unless a test actually fails.
2. **`backend/pipeline/case_timeline.py`** — new file. Builds a chronological event list for one
   case from `CaseMaster` + `ArrestSurrender`. This is `BLUEPRINT2_PATCH.md` Patch 4's
   `build_case_timeline()`, already schema-correct — no further migration work needed, just needs
   to actually be created.
3. **`backend/pipeline/case_summary.py`** — new file. LLM-generated case brief from structured
   `CaseMaster`/`Accused`/`Victim` facts, using the same `MODEL_ANSWER` model and `call_llm()`
   interface every other LLM call in the codebase already uses. Two new routes added to the
   *existing* `routers/decision_support.py` (timeline + summary) alongside its current
   `similar-cases` route.
4. **Evidence trail write + read path** — a new `backend/pipeline/evidence_trail.py` module with
   `save_evidence_trail()`, wired into `routers/chat.py`'s existing `_persist_turn()` so every
   chat turn that actually runs SQL gets a `chat_evidence_trail` row. Plus a new read endpoint,
   `GET /api/chat/messages/{message_id}/evidence-trail`, so that data is actually retrievable
   (ownership-scoped, same BOLA/IDOR pattern as `verify_session_owner()`).

---

## What "Done" Looks Like for Step 3

- [ ] Part B verification tests pass against current seeded data (no code changes expected)
- [ ] Part C's existing `similar-cases` route verification test passes (no code changes expected)
- [ ] `backend/pipeline/case_timeline.py` exists; `GET /api/decision-support/timeline/{case_id}` returns ordered events
- [ ] `backend/pipeline/case_summary.py` exists; `GET /api/decision-support/summary/{case_id}` returns an LLM-generated brief
- [ ] `backend/pipeline/evidence_trail.py` exists with `save_evidence_trail()`
- [ ] `routers/chat.py`'s `_persist_turn()` calls `save_evidence_trail()` after every SQL-path turn
- [ ] `chat_evidence_trail` actually has rows in it after a chat turn (verified via direct query)
- [ ] `GET /api/chat/messages/{message_id}/evidence-trail` returns the trail for the requesting officer's own messages, 404s for someone else's
- [ ] DIRECT-path chat turns (no SQL) correctly get **no** evidence trail row — not an error, expected behavior
- [ ] No new DDL, no new `main.py` router registrations — every new route slots into an already-registered router
- [ ] All previously-working endpoints (chat, analytics, audit-log, profiling, existing similar-cases) still return 200

---

## Critical Context — Read Before Writing Code

- **Part B needs an audit, not a rewrite.** `risk_scoring.py` and `routers/profiling.py` are
  already live, already handle the `AccusedName`-dedup and placeholder-exclusion edge cases, and
  the recency factor's use of `date.today()` is *correct* there — it's measuring how stale an
  offender's most recent activity is relative to the real world right now, which is exactly what
  an investigator wants to know today, tomorrow, or a year from now. That's a different problem
  shape than Step 2's `CURDATE()` bug, which was a query *window filter* against a dataset frozen
  at a fixed point — don't "fix" this by anchoring it to `MAX(CrimeRegisteredDate)` like the
  monthly trend was. One thing worth just being aware of for a live demo: since the seeded dataset
  tops out mid-2025 and today is well past that, every offender's recency factor will currently
  land in the same low bucket regardless of how "hot" they are relative to each other — that's a
  demo-data characteristic, not a bug, and not something this step touches.
- **Part C's `similar_cases.py` is also done — same audit-only treatment.** It already implements
  all four signals from `BLUEPRINT2_PATCH.md` Patch 4 (same crime type +40, same station +25,
  within 90 days +15, shares an accused +20) via a direct `AccusedName` join, not the deleted
  `case_relationships` table. Nothing to change.
- **`case_timeline.py` and `case_summary.py` are genuinely new — use Patch 4's schema verbatim.**
  Timeline events come from `CaseMaster.CrimeRegisteredDate`/`IncidentFromDate` and
  `ArrestSurrender` — no `ChargesheetDetails` (that's on MIGRATE.md's deferred list, don't
  reference it). Case summary's fact-gathering queries join `CrimeSubHead`/`CaseStatusMaster`/
  `Unit`/`Accused`/`Victim`, same joins every other Part A/B/C module already uses.
- **`chat_evidence_trail` is already correctly shaped.** Unlike `BLUEPRINT2_PATCH.md` Patch 1's
  rename of `fir_ids_referenced` → `case_ids_referenced`, that rename already happened in Step 1's
  schema batch (`Docs.md` confirms the column is already named `case_ids_referenced`). This step
  is pure wiring — no DDL, no column changes, just the missing `INSERT`.
- **DIRECT-path turns don't get an evidence trail row, and that's correct, not a gap.** A turn
  answered from cached conversation history has no SQL to trail. `save_evidence_trail()` should
  no-op (not error) when `sql_generated` is empty — this mirrors the existing convention where
  `resolve_media()` and `_check_graph_available()` also no-op cleanly when there's nothing to do.
- **Reuse existing extraction logic instead of duplicating it.** `case_ids_referenced` should come
  from `pipeline/media_resolver.py`'s existing `collect_case_master_ids()` — the same function
  `query_pipeline.py` already uses — not a re-implementation of Patch 5's inline
  `"CaseMasterID" in table_data[0]` check. `tables_queried` should come from
  `pipeline/sql_validator.py`'s existing `_extract_tables()` regex parser rather than a second
  parser. That function is currently private (underscore-prefixed, single caller inside
  `validate_sql()`); since it now has a second caller, promote it to a public `extract_tables()`
  as part of this step — a two-line rename, not a rewrite, matching the same "promote to shared"
  pattern already used for `collect_case_master_ids()` itself (see `Docs.md` §3.13).
- **No new DDL, no new `main.py` registrations.** `routers/decision_support.py` and
  `routers/chat.py` are both already registered — the new routes in this step are just additional
  `@router.get(...)` functions inside files that already exist and already run. Nothing to add to
  `main.py`.
- **The evidence-trail read endpoint needs ownership scoping; the case-lookup ones don't.**
  `GET /api/decision-support/timeline/{case_id}` and `.../summary/{case_id}` are case-level
  investigative lookups (same tier as the existing `similar-cases` route) — any authenticated
  officer can look up any case, same as today. But `GET /api/chat/messages/{message_id}/evidence-
  trail` is tied to a specific officer's own chat session, so it needs the same BOLA/IDOR-style
  ownership check `verify_session_owner()` already does elsewhere — 404 (not 403) if the message
  belongs to someone else's session, to avoid confirming it exists.
- **DB verification commands in this doc target the current AWS RDS deployment**, not the local
  `ksp_crime_db_v2` instance `SixToSeven.md`'s Step 1 check still references. Per `Docs.md`
  §10.15, the DB moved to AWS RDS (`ksp_crime_db`, no `_v2` suffix) on July 11 — use your `.env`'s
  `DB_HOST`/`DB_USER` for any direct SQL checks below.

---

## Step-by-Step Instructions

### 1. Audit Part B — confirm `risk_scoring.py` + `routers/profiling.py` against current data

No code changes expected. Just run the verification tests in the section below (Tests 1–3) and
confirm they pass. If any of them fail, that's a real regression worth fixing before continuing —
but go in expecting a pass, not a rewrite.

### 2. Audit Part C (existing) — confirm `similar_cases.py` + the `similar-cases` route

Same treatment — run Test 4 below, expect a pass, don't touch the code unless it fails.

### 3. Promote `_extract_tables()` to a public helper in `backend/pipeline/sql_validator.py`

A small prerequisite before Step 3's new evidence-trail module can import it cleanly.

```python
# OLD (private — single internal caller inside validate_sql()):
def _extract_tables(sql) -> list[str]:
    ...

# NEW (public — now has a second caller in pipeline/evidence_trail.py):
def extract_tables(sql) -> list[str]:
    ...
```

Update the one call site inside `validate_sql()` (in the same file) from `_extract_tables(sql)` to
`extract_tables(sql)`. That's the entire change — same regex logic, just no longer private.

### 4. Create `backend/pipeline/case_timeline.py`

```python
"""
Builds a chronological timeline for a single case.
Events come from: CaseMaster registration/incident dates, and ArrestSurrender
events (one per arrested/surrendered accused). No ChargesheetDetails reference
-- that table is on MIGRATE.md's deferred list.
"""
from db.connection import execute_query


async def build_case_timeline(case_master_id: int) -> list[dict]:
    """
    Returns chronologically ordered events:
    [{"date": "2024-05-15", "event": "Case registered", "detail": "..."}, ...]

    Events pulled from:
    - CaseMaster.IncidentFromDate -> "Incident occurred" (usually before registration)
    - CaseMaster.CrimeRegisteredDate -> "Case registered"
    - ArrestSurrender.ArrestSurrenderDate (one row per arrested accused) ->
      "Accused arrested/surrendered: {AccusedName}"

    Returns [] if the case doesn't exist.
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

### 5. Create `backend/pipeline/case_summary.py`

An LLM-generated case brief from structured facts — not free text, so no RAG/knowledge-base
dependency. Reuses `MODEL_ANSWER` (same model that already handles answer formatting, intent
routing, and direct answers) via the existing `call_llm()` interface.

First, add a system prompt and prompt builder to `backend/llm/prompts.py`:

```python
# Add alongside the other *_SYSTEM_PROMPT constants:

CASE_SUMMARY_SYSTEM_PROMPT = """You are an assistant writing a concise investigative case brief \
for a Karnataka State Police officer. Given structured case facts (crime type, status, station, \
brief facts, accused, victims), write a 3-5 sentence professional summary covering what happened, \
who is involved, and the current status. Do not invent facts not present in the data. No \
markdown, no headers -- plain prose only."""


# Add alongside the other build_*_prompt functions:

def build_case_summary_prompt(case_row: dict, accused_rows: list[dict], victim_rows: list[dict]) -> tuple[str, str]:
    accused_str = ", ".join(
        f"{a['AccusedName']} ({a['AgeYear']})" if a.get("AgeYear") else a["AccusedName"]
        for a in accused_rows
    ) or "none on record"
    victim_str = ", ".join(
        f"{v['VictimName']} ({v['AgeYear']})" if v.get("AgeYear") else v["VictimName"]
        for v in victim_rows
    ) or "none on record"

    user_prompt = f"""Case: {case_row['CrimeNo']}
Registered: {case_row['CrimeRegisteredDate']}
Crime type: {case_row['CrimeHeadName']}
Status: {case_row['CaseStatusName']}
Station: {case_row['UnitName']}
Brief facts: {case_row['BriefFacts'] or 'Not recorded'}
Accused: {accused_str}
Victims: {victim_str}

Write the case brief."""
    return CASE_SUMMARY_SYSTEM_PROMPT, user_prompt
```

Then `backend/pipeline/case_summary.py`:

```python
"""
LLM-generated case brief -- a short investigative summary of a single case,
built from structured CaseMaster/Accused/Victim facts. Uses MODEL_ANSWER via
the same call_llm() interface every other LLM call in the codebase already
uses -- no new model, no new plumbing.
"""
from db.connection import execute_query
from llm.client import call_llm, LLMError
from llm.prompts import build_case_summary_prompt


async def generate_case_summary(case_master_id: int) -> dict:
    """
    Returns {"summary": str, "error": None} on success, or
    {"summary": None, "error": str} on any failure -- mirrors
    query_pipeline.py's "never raise, always return something
    displayable" convention.
    """
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
    if not case_rows:
        return {"summary": None, "error": "Case not found"}
    case_row = case_rows[0]

    accused_rows = await execute_query(
        "SELECT AccusedName, AgeYear FROM Accused WHERE CaseMasterID = %s",
        (case_master_id,)
    )
    victim_rows = await execute_query(
        "SELECT VictimName, AgeYear FROM Victim WHERE CaseMasterID = %s",
        (case_master_id,)
    )

    system_prompt, user_prompt = build_case_summary_prompt(case_row, accused_rows, victim_rows)

    try:
        summary = await call_llm("MODEL_ANSWER", user_prompt, system_prompt, max_tokens=4000)
        return {"summary": summary.strip(), "error": None}
    except LLMError:
        return {"summary": None, "error": "Summary generation is temporarily unavailable"}
```

`max_tokens=4000` matches the documented QuickML minimum — the fact sheet here is short (a few
hundred tokens at most), well under the budget that matters for `answer_formatter.py`'s much
larger result-set payloads.

### 6. Add two routes to `backend/routers/decision_support.py`

Add alongside the existing `similar-cases` route — same file, same auth pattern
(`get_current_officer`, no `require_role()` gate, matching the existing route's tier):

```python
from pipeline.case_timeline import build_case_timeline
from pipeline.case_summary import generate_case_summary


@router.get("/api/decision-support/timeline/{case_id}")
async def case_timeline(case_id: int, officer: dict = Depends(get_current_officer)):
    events = await build_case_timeline(case_id)
    return {"case_id": case_id, "timeline": events}


@router.get("/api/decision-support/summary/{case_id}")
async def case_summary(case_id: int, officer: dict = Depends(get_current_officer)):
    result = await generate_case_summary(case_id)
    return {"case_id": case_id, **result}
```

No changes to the existing `similar-cases` route or its imports.

### 7. Create `backend/pipeline/evidence_trail.py`

```python
"""
Writes SQL provenance for chat answers into chat_evidence_trail -- the
"why did the assistant say this" explainability record BLUEPRINT2 Part D
calls for. The table was created in Step 1 but nothing has ever written to
it until this step. Non-fatal by design: a failure here must never break a
chat turn, same convention as chat_store.py's storage functions.
"""
import sys
from db.connection import execute_write
from pipeline.sql_validator import extract_tables
from pipeline.media_resolver import collect_case_master_ids


def _log(msg):
    print(f"[evidence_trail] {msg}", file=sys.stderr, flush=True)


async def save_evidence_trail(message_id: int, sql_generated: str | None, table_data: list[dict] | None):
    """
    Persists one row per assistant turn that actually ran SQL.
    DIRECT-path answers (no SQL) are skipped entirely -- there's nothing to
    trail, and that's correct, not an error condition.
    """
    if not sql_generated or not message_id:
        return
    try:
        tables_queried = extract_tables(sql_generated)
        case_ids = collect_case_master_ids(table_data) if table_data else []
        await execute_write(
            """INSERT INTO chat_evidence_trail
               (message_id, sql_executed, tables_queried, row_count, case_ids_referenced)
               VALUES (%s, %s, %s, %s, %s)""",
            (
                message_id,
                sql_generated,
                ",".join(tables_queried),
                len(table_data) if table_data else 0,
                ",".join(str(c) for c in case_ids[:100]),
            )
        )
    except Exception as e:
        _log(f"save_evidence_trail failed for message_id={message_id}: {e}")
```

### 8. Wire `save_evidence_trail()` into `routers/chat.py`'s `_persist_turn()`

`_persist_turn()` already calls `chat_store.save_message_pair(...)`, which returns the assistant
`message_id`. Add the evidence-trail call right after that, before the timestamp bump:

```python
from pipeline.evidence_trail import save_evidence_trail

# inside _persist_turn(session_id, officer, question, result, session_exists), after:
message_id = await chat_store.save_message_pair(
    session_id, question, result.answer_text, result.sql_generated,
    has_table, has_media, result.graph_available, result.table_data, result.media_attachments
)

# add this line:
await save_evidence_trail(message_id, result.sql_generated, result.table_data)

# ...then the existing update_session_timestamp(...) call continues as before
```

Adapt the exact variable names to your current `_persist_turn()` implementation — the key point
is the ordering: `save_evidence_trail()` needs the `message_id` that `save_message_pair()`
returns, so it has to run after that call, not before.

### 9. Add the evidence-trail read path

**`backend/db/chat_store.py`** — new function, same ownership-scoping pattern as
`verify_session_owner()`:

```python
async def get_evidence_trail_for_message(message_id: int, officer_id: int) -> dict | None:
    """
    Returns the chat_evidence_trail row for a message, scoped to the
    requesting officer via a join through chat_messages -> chat_sessions.
    Returns None if the message doesn't exist, belongs to another officer,
    or has no evidence trail row (DIRECT-path answers never get one --
    that's expected, not an error).
    """
    rows = await execute_query(
        """SELECT et.trail_id, et.message_id, et.sql_executed, et.tables_queried,
                  et.row_count, et.case_ids_referenced, et.created_at
           FROM chat_evidence_trail et
           JOIN chat_messages cm ON cm.message_id = et.message_id
           JOIN chat_sessions cs ON cs.session_id = cm.session_id
           WHERE et.message_id = %s AND cs.officer_id = %s""",
        (message_id, officer_id)
    )
    if not rows:
        return None
    row = rows[0]
    row["created_at"] = str(row["created_at"]) if row.get("created_at") else None
    return row
```

**`backend/routers/chat.py`** — new route, alongside the existing session/message routes:

```python
@router.get("/api/chat/messages/{message_id}/evidence-trail")
async def message_evidence_trail(message_id: int, officer: dict = Depends(get_current_officer)):
    """
    Read authorization: scoped through chat_messages -> chat_sessions ->
    officer_id, same BOLA/IDOR pattern as verify_session_owner(). Returns
    404 (not 403) whether the message doesn't exist, belongs to another
    officer's session, or simply has no trail row -- these are
    indistinguishable to the caller by design, same reasoning as every
    other 404-not-403 decision in this codebase.
    """
    trail = await chat_store.get_evidence_trail_for_message(message_id, officer["officer_id"])
    if trail is None:
        raise HTTPException(status_code=404, detail="No evidence trail for this message")
    return trail
```

Requires `HTTPException` to already be imported in `routers/chat.py` (it is, for the existing
BOLA/IDOR checks) and `chat_store` to already be imported (it is).

**Optional — audit logging.** If your Step 1 `log_action()` signature takes
`(officer_id, action, resource_type, resource_id)` (matching `audit_log`'s own columns), it's
worth a call here since evidence-trail views are exactly the kind of sensitive read Step 1's
`role_guard.py` docstring calls out — something like
`await log_action(officer["officer_id"], "view_evidence_trail", "message", str(message_id))`
right before the return. Adjust to whatever your actual signature is; this isn't a hard
requirement for Step 3 to be "done," just worth doing if it's a one-liner.

---

## Verify Step 3 — Run These Tests in Order

Get a token:
```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"badge_number": "7295834", "password": "7295834123"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
```

Get known-good IDs from the seeded demo data (Mahesh Gowda, the 8-case repeat offender) via
direct SQL — replace host/user with whatever your `.env` points at (AWS RDS as of `Docs.md`
§10.15, not the old local `ksp_crime_db_v2`):
```bash
ACCUSED_ID=$(mysql -h "$DB_HOST" -u "$DB_USER" -p ksp_crime_db -N -e \
  "SELECT AccusedMasterID FROM Accused WHERE AccusedName = 'Mahesh Gowda' LIMIT 1;")
CASE_ID=$(mysql -h "$DB_HOST" -u "$DB_USER" -p ksp_crime_db -N -e \
  "SELECT CaseMasterID FROM Accused WHERE AccusedName = 'Mahesh Gowda' LIMIT 1;")
echo "accused_id=$ACCUSED_ID case_id=$CASE_ID"
```

**Test 1 — Part B audit: risk detail endpoint:**
```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/profiling/risk/$ACCUSED_ID" | python3 -m json.tool
```
Expected: `risk_score`, `risk_tier`, and `contributing_factors` for Mahesh Gowda — given 8 cases on
record, expect this to land in `high` or `critical`, not `low`.

**Test 2 — Part B audit: force recompute + top-risk:**
```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/profiling/risk/$ACCUSED_ID?force_recompute=true" | python3 -m json.tool

curl -s -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/profiling/top-risk?limit=5" | python3 -m json.tool
```
Expected: recompute returns a fresh score without erroring; top-risk returns 5 distinct
identities, none of which are placeholder names (`Suspect`, `Unknown`, etc.).

**Test 3 — Part B audit: 404 on a nonexistent accused:**
```bash
curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/profiling/risk/999999999"
```
Expected: `404` — confirms the "doesn't exist" case is distinguishable from "exists but scored
zero," per how `Docs.md` describes this endpoint.

**Test 4 — Part C audit: existing similar-cases route:**
```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/decision-support/similar-cases/$CASE_ID" | python3 -m json.tool
```
Expected: ranked matches with `match_score` and `match_reasons`, no errors.

**Test 5 — New: case timeline:**
```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/decision-support/timeline/$CASE_ID" | python3 -m json.tool
```
Expected: `{"case_id": N, "timeline": [{"date": "...", "event": "Case registered", ...}, ...]}`,
chronologically ordered.

**Test 6 — New: case summary (LLM-backed, expect a few seconds):**
```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/decision-support/summary/$CASE_ID" | python3 -m json.tool
```
Expected: `{"case_id": N, "summary": "...", "error": null}` — a 3-5 sentence prose brief, no
markdown, no fabricated details beyond what the case facts contain.

**Test 7 — New: evidence trail gets written after a normal chat turn:**
```bash
SESSION_ID="evidence-trail-test-$(date +%s)"

curl -s -X POST http://localhost:8000/api/chat \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"question\": \"How many theft cases are open?\", \"session_id\": \"$SESSION_ID\"}" \
  | python3 -m json.tool

MESSAGE_ID=$(curl -s -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/chat/sessions/$SESSION_ID/messages" \
  | python3 -c "import sys,json; msgs=json.load(sys.stdin)['messages']; print([m for m in msgs if m['role']=='assistant'][-1]['message_id'])")
echo "message_id=$MESSAGE_ID"

curl -s -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/chat/messages/$MESSAGE_ID/evidence-trail" | python3 -m json.tool
```
Expected: the evidence-trail response includes `sql_executed` (the SQL that ran),
`tables_queried` (should include `CaseMaster`), and `row_count`.

**Test 8 — New: evidence trail is ownership-scoped:**
```bash
curl -s -o /dev/null -w "%{http_code}\n" \
  "http://localhost:8000/api/chat/messages/$MESSAGE_ID/evidence-trail"
```
(no `Authorization` header)
Expected: `401` — confirms the route is actually behind `get_current_officer`.

If you have a second officer's token available, also confirm `GET .../evidence-trail` with
*that* token against `$MESSAGE_ID` returns `404`, not the other officer's data.

**Test 9 — New: DIRECT-path turns get no evidence trail row (expected, not a bug):**
```bash
# Send a follow-up in the same session that should route DIRECT (referential language)
curl -s -X POST http://localhost:8000/api/chat \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"question\": \"Thanks, what else can you help with?\", \"session_id\": \"$SESSION_ID\"}" \
  | python3 -m json.tool

DIRECT_MESSAGE_ID=$(curl -s -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/chat/sessions/$SESSION_ID/messages" \
  | python3 -c "import sys,json; msgs=json.load(sys.stdin)['messages']; print([m for m in msgs if m['role']=='assistant'][-1]['message_id'])")

curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/chat/messages/$DIRECT_MESSAGE_ID/evidence-trail"
```
Expected: `404` on the DIRECT-path message — no SQL ran, so there's nothing to trail. This is the
correct outcome, not a failure.

**Test 10 — Direct DB check: confirm the table actually has rows:**
```bash
mysql -h "$DB_HOST" -u "$DB_USER" -p ksp_crime_db -e \
  "SELECT COUNT(*) AS trail_rows FROM chat_evidence_trail;"
```
Expected: a nonzero count, and higher than it was before Test 7.

**Test 11 — Regression check: everything from Steps 1 and 2 still works:**
```bash
curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/chat/sessions
curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/analytics/status-breakdown
curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/audit-log
```
Expected: `200`, `200`, and `200` or `403` (depending on this officer's role) — no `404`s or
`500`s.

All 11 passing = Step 3 done.

---

## What Is Explicitly NOT in Step 3

- No frontend at all — `RiskBadge.jsx`, `EvidenceTrail.jsx`, and any `CaseDetailPanel.jsx` wiring
  for timeline/summary/similar-cases are Step 4
- No changes to `risk_scoring.py` or `routers/profiling.py` unless the audit tests actually fail
- No changes to `similar_cases.py` or the existing `similar-cases` route unless its audit test fails
- No caching table for case summaries — unlike risk scores, summaries are generated fresh on every
  request; add a cache later only if latency becomes a real problem, not preemptively
- No `require_role()` gating on the new timeline/summary routes — same tier as the existing
  `similar-cases` route, any authenticated officer can look up any case
- No changes to `main.py` — every new route lives inside an already-registered router

---

## What Step 4 Will Build

Step 4 is the frontend consolidation pass across everything BLUEPRINT2's backend now supports:
`RiskBadge.jsx` (surfacing `risk_scoring.py`'s scores, likely inline on accused-related table
rows and/or a dedicated risk view, since Part B currently has zero UI despite being fully live),
`EvidenceTrail.jsx` (surfacing this step's new evidence-trail endpoint — probably an expandable
"why did it say this" affordance per assistant message, similar in spirit to the existing
"View network" button pattern), and wiring `case_timeline`/`case_summary`/`similar-cases` into
`CaseDetailPanel.jsx` (which already exists per `MIGRATE.md` §10, so this is extension, not new
component creation). No new backend work is expected in Step 4 — everything it needs already
exists as of this step.
