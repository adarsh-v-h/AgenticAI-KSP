# FiveToSix — Step 1 of 4 (BLUEPRINT2 Build)

> **Context:** `MIGRATE.md` is fully done — `CaseMaster`, `Accused`, `Employee`, and all the official KSP lookup tables exist and are seeded. `BLUEPRINT2.md` defines five new feature areas (analytics, profiling, decision support, evidence trail, roles/governance), but it was written before the migration, so `BLUEPRINT2_PATCH.md` corrects every query in it against the new schema.
>
> This is Step 1 of 4 in building BLUEPRINT2. **Read `BLUEPRINT2.md` Part E first, then `BLUEPRINT2_PATCH.md` Patches 1 and 6 — apply the patch versions, not BLUEPRINT2's originals.** This step builds the schema additions for all four feature areas at once (cheaper to do all DDL in one pass) plus the role/auth/audit-log infrastructure that every later step depends on.
>
> Do not start Part A, B, C, or D's actual logic yet — that's Steps 2-4. This step is schema + roles only.

---

## What Step 1 Is

Two things, in order:
1. **All new tables for BLUEPRINT2's four feature areas**, created in one pass against the already-migrated `ksp_crime_db_v2` (or whatever you renamed it to).
2. **Role-based access control** — `require_role()` dependency, `audit_log` table + `log_action()` helper, and the JWT payload update so every later step can gate endpoints by role without re-deriving this infrastructure.

No analytics, profiling, decision-support, or evidence-trail *logic* is built in this step — only the tables they'll need, and the auth scaffolding everything else depends on.

---

## What "Done" Looks Like for Step 1

- [ ] `offender_risk_scores`, `chat_evidence_trail`, `audit_log` tables exist in the migrated DB
- [ ] `Employee.role` column exists (should already be there from MIGRATE.md's `Employee` DDL — verify, don't re-add)
- [ ] Logging in returns a JWT that contains a `role` field
- [ ] `require_role(...)` dependency exists and correctly returns 403 for a mismatched role
- [ ] `log_action(...)` helper exists and writes a row to `audit_log` without raising on failure
- [ ] `GET /api/audit-log` works for a supervisor-role officer and returns 403 for an investigator-role officer
- [ ] Existing chat endpoints (`/api/chat`, `/api/chat/stream`) still work exactly as before — this step must not break anything from BLUEPRINT.md or MIGRATE.md

---

## Critical Context — Read Before Writing Code

- **Use `BLUEPRINT2_PATCH.md`'s versions, not `BLUEPRINT2.md`'s originals.** Every table/column name in `BLUEPRINT2.md` itself is stale (pre-migration). Patch 1 has the corrected DDL; Patch 6 has the corrected auth/role code.
- **`Employee.role` likely already exists.** `MIGRATE.md` Section 3's `Employee` table DDL already includes `role ENUM(...) NOT NULL DEFAULT 'investigator'` inline. Check with `DESCRIBE Employee;` before assuming you need to `ALTER TABLE`. If it's there, skip straight to seeding varied roles (below).
- **`offender_risk_scores` and `chat_evidence_trail` use `BLUEPRINT2_PATCH.md`'s renamed columns** (`AccusedMasterID` as PK, `case_ids_referenced` instead of `fir_ids_referenced`) — don't use BLUEPRINT2's original column names.
- **`audit_log.officer_id` stays as-is** — it's our own table, not part of the official KSP schema, so we keep the column name; only its FK *target* changes to `Employee(EmployeeID)`.

---

## Step-by-Step Instructions

### 1. Verify `Employee.role` exists

```bash
mysql -u adarsh -proot ksp_crime_db_v2 -e "DESCRIBE Employee;" | grep role
```

If it shows a `role` ENUM column, skip to step 2. If it's genuinely missing (only possible if your migration DDL was applied before this column was added to MIGRATE.md), run:

```bash
mysql -u adarsh -proot ksp_crime_db_v2 -e "
ALTER TABLE Employee
  ADD COLUMN role ENUM('investigator', 'analyst', 'supervisor', 'policymaker')
  NOT NULL DEFAULT 'investigator';
"
```

### 2. Seed varied roles for testing

You need at least one officer in each role to actually test `require_role()` later. Run:

```bash
mysql -u adarsh -proot ksp_crime_db_v2 -e "
UPDATE Employee e
JOIN Rank r ON r.RankID = e.RankID
SET e.role = 'supervisor'
WHERE r.RankName IN ('Inspector', 'DySP', 'SP');

UPDATE Employee e
JOIN Designation d ON d.DesignationID = e.DesignationID
SET e.role = 'analyst'
WHERE d.DesignationName LIKE '%Analyst%' OR d.DesignationName = 'Investigating Officer';
"
```

Verify the spread:
```bash
mysql -u adarsh -proot ksp_crime_db_v2 -e "SELECT role, COUNT(*) FROM Employee GROUP BY role;"
```

You want at least one `supervisor`, ideally one `analyst`, and the rest `investigator`. If the above UPDATE doesn't catch any rows (depends on your seed data's Rank/Designation values), just pick 2-3 `EmployeeID`s manually and set their role directly:

```bash
mysql -u adarsh -proot ksp_crime_db_v2 -e "
UPDATE Employee SET role = 'supervisor' WHERE EmployeeID = 1;
UPDATE Employee SET role = 'analyst' WHERE EmployeeID = 2;
"
```

### 3. Create `backend/db/blueprint2_schema.sql`

```sql
-- BLUEPRINT2 schema additions - corrected per BLUEPRINT2_PATCH.md Patch 1.
-- Run against the already-migrated ksp_crime_db_v2.

CREATE TABLE IF NOT EXISTS offender_risk_scores (
    AccusedMasterID      INT PRIMARY KEY,
    risk_score           DECIMAL(5,2) NOT NULL,
    risk_tier            ENUM('low', 'medium', 'high', 'critical') NOT NULL,
    contributing_factors TEXT,
    computed_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (AccusedMasterID) REFERENCES Accused(AccusedMasterID)
);

CREATE TABLE IF NOT EXISTS chat_evidence_trail (
    trail_id            INT AUTO_INCREMENT PRIMARY KEY,
    message_id          INT NOT NULL,
    sql_executed        TEXT NOT NULL,
    tables_queried       VARCHAR(300),
    row_count            INT,
    case_ids_referenced  VARCHAR(500),
    created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (message_id) REFERENCES chat_messages(message_id),
    INDEX idx_trail_message (message_id)
);

CREATE TABLE IF NOT EXISTS audit_log (
    log_id          INT AUTO_INCREMENT PRIMARY KEY,
    officer_id      INT NOT NULL,
    action          VARCHAR(50) NOT NULL,
    resource_type   VARCHAR(50),
    resource_id     VARCHAR(50),
    details         TEXT,
    ip_address      VARCHAR(45),
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (officer_id) REFERENCES Employee(EmployeeID),
    INDEX idx_audit_officer (officer_id, created_at),
    INDEX idx_audit_resource (resource_type, resource_id)
);
```

Run it:
```bash
mysql -u adarsh -proot ksp_crime_db_v2 < backend/db/blueprint2_schema.sql
```

Verify:
```bash
mysql -u adarsh -proot ksp_crime_db_v2 -e "SHOW TABLES;" | grep -E "offender_risk_scores|chat_evidence_trail|audit_log"
```

### 4. Create `backend/auth/role_guard.py`

```python
"""
Role-based access control and audit logging.
Builds on the existing JWT auth - does NOT replace it.
get_current_officer still runs first; this adds a role check on top.

No schema-specific table references in this file - it only reads
officer.get("role") from the JWT payload dict populated at login time.
"""
from fastapi import Depends, HTTPException, Request
from auth.simple_auth import get_current_officer
from db.connection import execute_write
import sys


def require_role(*allowed_roles: str):
    """
    FastAPI dependency factory. Use like:
        officer: dict = Depends(require_role("supervisor", "analyst"))

    Checks the officer's role against allowed_roles. Raises 403 if not permitted.
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
    sensitive data in Steps 2-4 - risk scores, evidence trails, exports,
    role-gated actions.

    Non-fatal - audit logging must never break the actual request.
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

### 5. Update `backend/auth/simple_auth.py`

Apply per `BLUEPRINT2_PATCH.md` Patch 6 — this should already match if you applied `MIGRATE.md` Section 6.5 fully. Confirm `create_access_token` and `login` look exactly like this:

```python
def create_access_token(officer_id: int, badge_number: str, role: str) -> str:
    """
    badge_number param name kept for compatibility with existing call sites -
    it now holds the value from Employee.KGID, not officers.badge_number.
    """
    expire = datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS)
    payload = {
        "officer_id": officer_id,
        "badge_number": badge_number,
        "role": role,
        "exp": expire,
    }
    return jwt.encode(payload, get("APP_SECRET_KEY"), algorithm=ALGORITHM)


async def login(badge_number: str, password: str, pool) -> str:
    from db.connection import execute_query

    results = await execute_query(
        "SELECT EmployeeID, KGID, FirstName, role FROM Employee WHERE KGID = %s AND is_active = TRUE",
        (badge_number,)
    )
    if not results:
        raise HTTPException(status_code=401, detail="Invalid badge number or password.")

    employee = results[0]
    expected_password = badge_number + "123"
    if password != expected_password:
        raise HTTPException(status_code=401, detail="Invalid badge number or password.")

    return create_access_token(employee["EmployeeID"], employee["KGID"], employee["role"])
```

If your `login()` currently has a different shape (e.g. it was already migrated but doesn't pass `role` through to `create_access_token`), fix just that gap — don't rewrite working code unnecessarily.

### 6. Add the audit log endpoint to `backend/routers/governance.py` (new file)

```python
from fastapi import APIRouter, Depends
from auth.role_guard import require_role
from db.connection import execute_query

router = APIRouter()


@router.get("/api/audit-log")
async def get_audit_log(limit: int = 50, officer: dict = Depends(require_role("supervisor"))):
    """
    Supervisor-only. Returns the most recent audit log entries.
    """
    rows = await execute_query(
        """SELECT al.created_at, e.FirstName, al.action, al.resource_type, al.resource_id, al.ip_address
           FROM audit_log al
           JOIN Employee e ON e.EmployeeID = al.officer_id
           ORDER BY al.created_at DESC
           LIMIT %s""",
        (limit,)
    )
    return {"entries": rows}
```

Register in `main.py`:
```python
from routers.governance import router as governance_router
app.include_router(governance_router)
```

---

## Verify Step 1 — Run These Tests in Order

Restart the backend first:
```bash
pkill -f uvicorn
cd /home/venzz/Work/Dataathon
.venv/bin/uvicorn backend.main:app --reload --port 8000
```

**Test 1 — Login still works, JWT now has role:**
```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"badge_number": "KSP-2016-0505", "password": "KSP-2016-0505123"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

echo $TOKEN | cut -d. -f2 | base64 -d 2>/dev/null | python3 -m json.tool
```
Expected: the decoded payload includes `"role": "investigator"` (or whatever role that officer has).

**Test 2 — Existing chat still works (regression check):**
```bash
curl -s -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"question": "How many cases are open?", "session_id": "step1test"}' | python3 -m json.tool
```
Expected: same working response as before this step — Step 1 must not break anything.

**Test 3 — `require_role` blocks the wrong role:**
Log in as an `investigator`-role officer (most of your seeded officers), then:
```bash
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/audit-log
```
Expected: HTTP 403 with the role-mismatch message.

**Test 4 — `require_role` allows the right role:**
```bash
SUPERVISOR_TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"badge_number": "<a KGID you set to supervisor>", "password": "<that KGID>123"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl -s -H "Authorization: Bearer $SUPERVISOR_TOKEN" http://localhost:8000/api/audit-log | python3 -m json.tool
```
Expected: HTTP 200, `{"entries": [...]}` (likely empty array right now — that's fine, nothing has logged an action yet).

**Test 5 — `log_action` writes a row without breaking anything:**
```bash
cd backend && python3 -c "
import asyncio, sys
sys.path.insert(0, '.')
from db.connection import create_pool
from auth.role_guard import log_action

async def test():
    await create_pool()
    await log_action(1, 'test_action', 'test_resource', '123', details='Step 1 verification')
    print('log_action completed without raising')

asyncio.run(test())
"
```
Then re-run Test 4's curl — the new row should now appear in the `entries` array.

All 5 passing = Step 1 done.

---

## What Is Explicitly NOT in Step 1

- No analytics logic (`trend_analytics.py`) — Step 2
- No risk scoring logic (`risk_scoring.py`) — Step 3
- No decision support logic (`case_timeline.py`, `similar_cases.py`, `case_summary.py`) — Step 4
- No evidence trail logic (`save_evidence_trail`) — Step 3
- No frontend components — they come in their respective steps alongside the backend they render

---

## What Step 2 Will Build

Step 2 builds Part A (Crime Pattern & Trend Analytics) end to end: `trend_analytics.py` with all 7 corrected queries from `BLUEPRINT2_PATCH.md` Patch 2, the `analytics.py` router with role gates using the `require_role()` built in this step, and the `AnalyticsDashboard.jsx` + `TrendChart.jsx` frontend.
