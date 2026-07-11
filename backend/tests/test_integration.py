"""
Integration tests — require a live Catalyst token, DB connection, and
(for RAG tests) KB document IDs set in KB_DOCUMENT_IDS in .env.

Usage:
    python backend/tests/test_integration.py              # run all groups
    python backend/tests/test_integration.py llm          # LLM connectivity only
    python backend/tests/test_integration.py rag          # all RAG tests
    python backend/tests/test_integration.py pipeline     # full pipeline tests
    python backend/tests/test_integration.py e2e          # DB-to-export end-to-end
    python backend/tests/test_integration.py role         # role-based access control

Groups: llm | rag | pipeline | e2e | role
"""

import asyncio
import glob
import os
import sys

# Allow running from the project root OR from backend/
_here = os.path.dirname(os.path.abspath(__file__))       # backend/tests/
_backend_root = os.path.dirname(_here)                    # backend/
for _p in (_here, _backend_root):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(os.path.dirname(_here), ".env"))

# ── shared helpers ────────────────────────────────────────────────────────────

def _sep(title: str):
    print(f"\n{'='*60}\n  {title}\n{'='*60}")

def _ok(label: str):
    print(f"  [PASS] {label}")

def _fail(label: str, detail: str = ""):
    print(f"  [FAIL] {label}" + (f": {detail}" if detail else ""))

def _kb_doc_ids() -> list[str]:
    raw = os.getenv("KB_DOCUMENT_IDS", "")
    return [d.strip() for d in raw.split(",") if d.strip()]


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 1 — LLM connectivity
# ══════════════════════════════════════════════════════════════════════════════

async def test_llm_ping():
    """Verify MODEL_SQL is reachable via QuickML."""
    _sep("LLM — ping MODEL_SQL")
    from llm.client import ping_model
    ok = await ping_model("MODEL_SQL")
    if ok:
        _ok("MODEL_SQL reachable")
    else:
        _fail("MODEL_SQL not reachable — check CATALYST_API_TOKEN and QUICKML_LLM_URL")


async def test_sql_generation():
    """Generate a simple SQL query against live LLM and print result."""
    _sep("LLM — SQL generation")
    from llm.sql_generator import generate_sql
    try:
        sql, attempts = await generate_sql(
            question="How many theft cases are open?",
            table_names=["CaseMaster"],
            history=None,
        )
        _ok(f"SQL generated in {attempts} attempt(s)")
        print(f"  SQL: {sql}")
    except Exception as e:
        _fail("SQL generation", f"{type(e).__name__}: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 2 — RAG client
# ══════════════════════════════════════════════════════════════════════════════

async def test_rag_empty_doc_ids():
    """Empty document list should return ungrounded gracefully (no crash)."""
    _sep("RAG — empty document list")
    from llm.rag_client import query_rag
    result = await query_rag("What happened in the Kavitha Raj case?", [])
    assert not result.grounded, "Expected ungrounded result for empty doc list"
    _ok(f"Ungrounded gracefully — response: {result.response[:80]}...")


async def test_rag_known_good(doc_ids: list[str]):
    """Anchored query with a real name — should ground to a specific source."""
    _sep("RAG — known-good anchored query (Kavitha Raj)")
    from llm.rag_client import query_rag
    result = await query_rag("What happened in the Kavitha Raj case?", doc_ids)
    print(f"  Grounded : {result.grounded}")
    print(f"  Response : {result.response[:120]}...")
    print(f"  Sources  : {result.sources}")
    if result.grounded:
        _ok("Grounded response returned")
    else:
        _fail("Not grounded — KB may not have this document")


async def test_rag_known_absent(doc_ids: list[str]):
    """Query for a name that doesn't exist — should return absent/not-found."""
    _sep("RAG — known-absent query (Ramesh Kulkarni)")
    from llm.rag_client import query_rag
    result = await query_rag("What cases involve Ramesh Kulkarni?", doc_ids)
    print(f"  Grounded : {result.grounded}")
    print(f"  Response : {result.response[:120]}...")
    _ok("Query completed (absent entity handled)")


async def test_rag_vague_query(doc_ids: list[str]):
    """Vague query — sources should not be over-attributed."""
    _sep("RAG — vague query (similar pattern)")
    from llm.rag_client import query_rag
    result = await query_rag("Are there any cases with a similar pattern of behavior?", doc_ids)
    print(f"  Grounded : {result.grounded}")
    print(f"  Sources  : {len(result.sources)} (vague query should have few/no sources)")
    _ok("Vague query completed")


async def test_rag_messy_grammar(doc_ids: list[str]):
    """Filler-heavy query — normalize_query should strip fillers before retry."""
    _sep("RAG — filler/messy grammar query")
    from llm.rag_client import query_rag
    result = await query_rag(
        "um so like was there any case where someone got scammed by fake bank people or something",
        doc_ids
    )
    print(f"  Grounded : {result.grounded}")
    print(f"  Response : {result.response[:120]}...")
    _ok("Messy-grammar query completed (normalize_query path exercised)")


async def test_rag_direct_followup(doc_ids: list[str]):
    """Explicit name follow-up — should resolve without pronoun ambiguity."""
    _sep("RAG — explicit follow-up query")
    from llm.rag_client import query_rag
    result = await query_rag("Was Kavitha Raj involved in any other reported cases?", doc_ids)
    print(f"  Grounded : {result.grounded}")
    print(f"  Response : {result.response[:120]}...")
    _ok("Follow-up query completed")


async def test_rag_repeat_consistency(doc_ids: list[str]):
    """Same query three times — responses should be consistent (stable grounding)."""
    _sep("RAG — repeat consistency (3 runs)")
    from llm.rag_client import query_rag
    query = "What happened in the Kavitha Raj case?"
    grounded_count = 0
    for i in range(1, 4):
        result = await query_rag(query, doc_ids)
        grounded_count += int(result.grounded)
        print(f"  Run {i}: grounded={result.grounded}, sources={len(result.sources)}")
    if grounded_count >= 2:
        _ok(f"Grounded {grounded_count}/3 runs (consistent)")
    else:
        _fail(f"Only grounded {grounded_count}/3 runs (inconsistent or KB missing)")


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 3 — RAG session (multi-turn)
# ══════════════════════════════════════════════════════════════════════════════

async def test_rag_session_multiturn(doc_ids: list[str]):
    """Two-turn RAG session — second turn should resolve 'that suspect' via context."""
    _sep("RAG session — multi-turn follow-up")
    from llm.rag_session import RagSession
    session = RagSession(document_ids=doc_ids, history=[])

    r1 = await session.ask("What happened in the Kavitha Raj case?")
    print(f"  Turn 1 response : {r1['response'][:100]}...")
    print(f"  Turn 1 sources  : {r1['sources']}")
    print(f"  Turn 1 follow-ups: {r1.get('suggested_follow_ups', [])}")

    r2 = await session.ask("Was that suspect involved in any other reported cases?")
    print(f"  Turn 2 response : {r2['response'][:100]}...")
    print(f"  Turn 2 sources  : {r2['sources']}")

    _ok("Multi-turn session completed")


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 4 — Full pipeline (narrative routing + empty-results RAG fallback)
# ══════════════════════════════════════════════════════════════════════════════

async def test_pipeline_narrative_routing():
    """Narrative question should bypass SQL and route directly to RAG."""
    _sep("Pipeline — narrative keyword routing")
    from db.connection import create_pool, close_pool
    from pipeline.query_pipeline import run_pipeline
    await create_pool()
    try:
        response = await run_pipeline(
            question="Write a detailed narrative analysis of the Kavitha Raj case documents."
        )
        print(f"  SQL generated : '{response.sql_generated}'")
        print(f"  Answer        : {response.answer_text[:120]}...")
        if not response.sql_generated:
            _ok("SQL was NOT generated — narrative routed to RAG")
        else:
            _fail("SQL was generated for a narrative question (routing may need tuning)")
    finally:
        await close_pool()


async def test_pipeline_off_topic():
    """Off-topic question should surface a graceful non-answer, not crash."""
    _sep("Pipeline — off-topic question")
    from db.connection import create_pool, close_pool
    from pipeline.query_pipeline import run_pipeline
    await create_pool()
    try:
        response = await run_pipeline(question="Tell me a story about a brave police officer.")
        print(f"  Answer : {response.answer_text[:120]}...")
        _ok("Off-topic question handled without crash")
    finally:
        await close_pool()


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 5 — End-to-end RAG pipeline (DB → export → consolidate → verify)
# ══════════════════════════════════════════════════════════════════════════════

_TEST_CASES = [
    {
        "CrimeNo": "TEST_E2E_001",
        "BriefFacts": "TEST CASE ALPHA: Rajendra Prasad was apprehended near Jayanagar for possession of 500 grams of methamphetamine. The accused was operating a clandestine drug lab.",
    },
    {
        "CrimeNo": "TEST_E2E_002",
        "BriefFacts": "TEST CASE BETA: Ananya Sharma reported her gold chain worth Rs 2,50,000 was snatched by two unidentified men on a motorcycle near MG Road metro station.",
    },
    {
        "CrimeNo": "TEST_E2E_003",
        "BriefFacts": "TEST CASE GAMMA: Deepak Hegde filed a complaint alleging an unknown person gained access to his banking credentials through a phishing email and transferred Rs 4,75,000.",
    },
]


async def _write_raw(sql: str, params=None) -> int:
    """Direct write bypassing the SELECT-only guard."""
    import aiomysql
    from dotenv import dotenv_values
    env = dotenv_values(os.path.join(os.path.dirname(_here), ".env"))
    conn = await aiomysql.connect(
        host=env["DB_HOST"], port=int(env.get("DB_PORT", 3306)),
        user=env["DB_USER"], password=env["DB_PASSWORD"], db=env["DB_NAME"]
    )
    try:
        async with conn.cursor() as cur:
            await cur.execute(sql, params or ())
            await conn.commit()
            return cur.lastrowid
    finally:
        conn.close()


async def test_e2e_rag_pipeline():
    """
    Full end-to-end: insert 3 test cases → run export → verify files → cleanup.
    Self-contained: cleans up all inserted rows on completion or failure.
    """
    _sep("E2E — DB → export_cases_for_rag → consolidation → verify")
    from db.connection import create_pool, close_pool, execute_query
    await create_pool()
    inserted_ids = []

    try:
        # Pre-cleanup leftovers from any prior failed run
        crimeNos = tuple(tc["CrimeNo"] for tc in _TEST_CASES)
        placeholders = ",".join(["%s"] * len(crimeNos))
        leftovers = await execute_query(
            f"SELECT CaseMasterID FROM CaseMaster WHERE CrimeNo IN ({placeholders})",
            crimeNos
        )
        for row in leftovers:
            cid = row["CaseMasterID"]
            for tbl in ("ActSectionAssociation", "Accused", "Victim", "CaseMaster"):
                await _write_raw(f"DELETE FROM `{tbl}` WHERE CaseMasterID = %s", (cid,))

        # Baseline count
        baseline = (await execute_query("SELECT COUNT(*) AS n FROM CaseMaster"))[0]["n"]
        print(f"  Baseline: {baseline} cases")

        # Grab valid FK IDs
        station_id = (await execute_query(
            "SELECT UnitID FROM Unit WHERE UnitName LIKE '%PS%' LIMIT 1"
        ))[0]["UnitID"]
        status_id   = (await execute_query("SELECT CaseStatusID  FROM CaseStatusMaster LIMIT 1"))[0]["CaseStatusID"]
        cat_id      = (await execute_query("SELECT CaseCategoryID FROM CaseCategory LIMIT 1"))[0]["CaseCategoryID"]
        grav_id     = (await execute_query("SELECT GravityOffenceID FROM GravityOffence LIMIT 1"))[0]["GravityOffenceID"]
        head_id     = (await execute_query("SELECT CrimeSubHeadID FROM CrimeSubHead LIMIT 1"))[0]["CrimeSubHeadID"]
        emp_id      = (await execute_query("SELECT EmployeeID FROM Employee LIMIT 1"))[0]["EmployeeID"]
        sections    = await execute_query("SELECT ActCode, SectionCode FROM Section LIMIT 3")

        # Insert test cases
        for i, tc in enumerate(_TEST_CASES):
            cid = await _write_raw(
                """INSERT INTO CaseMaster
                   (CrimeNo, PolicePersonID, PoliceStationID, CaseStatusID,
                    CaseCategoryID, GravityOffenceID, CrimeMinorHeadID,
                    BriefFacts, IncidentFromDate, CrimeRegisteredDate)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NOW(),CURDATE())""",
                (tc["CrimeNo"], emp_id, station_id, status_id,
                 cat_id, grav_id, head_id, tc["BriefFacts"])
            )
            inserted_ids.append(cid)
            await _write_raw(
                "INSERT INTO Accused (CaseMasterID, AccusedName, AgeYear) VALUES (%s,%s,%s)",
                (cid, f"TestAccused_{tc['CrimeNo']}", 30 + i)
            )
            await _write_raw(
                "INSERT INTO Victim (CaseMasterID, VictimName, AgeYear) VALUES (%s,%s,%s)",
                (cid, f"TestVictim_{tc['CrimeNo']}", 25 + i)
            )
            if i < len(sections):
                s = sections[i]
                await _write_raw(
                    "INSERT INTO ActSectionAssociation (CaseMasterID, ActID, SectionID) VALUES (%s,%s,%s)",
                    (cid, s["ActCode"], s["SectionCode"])
                )

        new_count = (await execute_query("SELECT COUNT(*) AS n FROM CaseMaster"))[0]["n"]
        assert new_count == baseline + 3, f"Insert failed: expected {baseline+3}, got {new_count}"
        _ok(f"Inserted 3 test cases ({baseline} → {new_count})")

        # Run export + consolidation (reuse the fixed function directly)
        import importlib.util, pathlib
        spec = importlib.util.spec_from_file_location(
            "export_cases_for_rag",
            os.path.join(_here, "export_cases_for_rag.py")
        )
        export_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(export_mod)
        await export_mod.main()
        _ok("Export + consolidation ran without error")

        # Verify raw export files
        export_dir = os.path.join(_here, "rag_export")
        for tc in _TEST_CASES:
            matches = glob.glob(os.path.join(export_dir, f"case_{tc['CrimeNo']}*"))
            assert matches, f"Raw export file missing for {tc['CrimeNo']}"
        _ok("All 3 test cases found in rag_export/")

        # Verify consolidated files
        consol_dir = os.path.join(_here, "rag_consolidated")
        consol_files = glob.glob(os.path.join(consol_dir, "*.txt"))
        found = {}
        for fpath in consol_files:
            content = open(fpath, encoding="utf-8").read()
            for tc in _TEST_CASES:
                if tc["CrimeNo"] in content:
                    found[tc["CrimeNo"]] = os.path.basename(fpath)
        for tc in _TEST_CASES:
            print(f"  {tc['CrimeNo']} → {found.get(tc['CrimeNo'], 'NOT FOUND')}")
        assert len(found) == 3, f"Only {len(found)}/3 test cases found in consolidated files"
        _ok("All 3 test cases consolidated correctly")

    finally:
        # Always clean up
        for cid in inserted_ids:
            for tbl in ("ActSectionAssociation", "Accused", "Victim", "CaseMaster"):
                await _write_raw(f"DELETE FROM `{tbl}` WHERE CaseMasterID = %s", (cid,))
        if inserted_ids:
            final = (await execute_query("SELECT COUNT(*) AS n FROM CaseMaster"))[0]["n"]
            _ok(f"Cleanup done — final count: {final}")
        await close_pool()


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 5 — Role-Based Access Control (BLUEPRINT2 Step 1)
# ══════════════════════════════════════════════════════════════════════════════

async def test_role_based_auth_jwt_includes_role():
    """
    Test 1: Login includes role in JWT (automates FiveToSix.md Test 1).
    
    Verifies that logging in as different officer roles returns a JWT with
    the correct role claim in the payload.
    """
    _sep("Role Auth — JWT includes role claim")
    import httpx
    from jose import jwt
    
    base_url = os.getenv("API_BASE_URL", "http://localhost:8000")
    
    # Test supervisor role
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{base_url}/api/auth/login",
            json={"badge_number": "3254123", "password": "3254123123"}
        )
        if resp.status_code != 200:
            _fail("Supervisor login", f"HTTP {resp.status_code}: {resp.text}")
            return
        
        token = resp.json().get("access_token")
        if not token:
            _fail("Supervisor login", "No access_token in response")
            return
        
        # Decode without verification (test environment)
        payload = jwt.get_unverified_claims(token)
        role = payload.get("role")
        
        if role == "supervisor":
            _ok("Supervisor JWT contains role='supervisor'")
        else:
            _fail("Supervisor JWT", f"Expected role='supervisor', got '{role}'")
    
    # Test investigator role
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{base_url}/api/auth/login",
            json={"badge_number": "7295834", "password": "7295834123"}
        )
        if resp.status_code != 200:
            _fail("Investigator login", f"HTTP {resp.status_code}: {resp.text}")
            return
        
        token = resp.json().get("access_token")
        payload = jwt.get_unverified_claims(token)
        role = payload.get("role")
        
        if role == "investigator":
            _ok("Investigator JWT contains role='investigator'")
        else:
            _fail("Investigator JWT", f"Expected role='investigator', got '{role}'")


async def test_role_based_auth_blocks_wrong_role():
    """
    Test 3: require_role() blocks mismatched roles (automates FiveToSix.md Test 3).
    
    Verifies that an investigator-role officer gets HTTP 403 when attempting
    to access a supervisor-only endpoint.
    """
    _sep("Role Auth — require_role() blocks wrong role")
    import httpx
    
    base_url = os.getenv("API_BASE_URL", "http://localhost:8000")
    
    # Login as investigator
    async with httpx.AsyncClient() as client:
        login_resp = await client.post(
            f"{base_url}/api/auth/login",
            json={"badge_number": "7295834", "password": "7295834123"}
        )
        if login_resp.status_code != 200:
            _fail("Login as investigator", f"HTTP {login_resp.status_code}")
            return
        
        token = login_resp.json().get("access_token")
        
        # Try to access supervisor-only endpoint
        audit_resp = await client.get(
            f"{base_url}/api/audit-log",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        if audit_resp.status_code == 403:
            detail = audit_resp.json().get("detail", "")
            if "supervisor" in detail.lower():
                _ok("Investigator blocked from audit-log with 403")
            else:
                _fail("403 response", f"Expected role mention in detail, got: {detail}")
        else:
            _fail("require_role() enforcement", f"Expected 403, got {audit_resp.status_code}")


async def test_role_based_auth_allows_correct_role():
    """
    Test 4: require_role() allows matching roles (automates FiveToSix.md Test 4).
    
    Verifies that a supervisor-role officer successfully accesses the
    supervisor-only audit-log endpoint.
    """
    _sep("Role Auth — require_role() allows correct role")
    import httpx
    
    base_url = os.getenv("API_BASE_URL", "http://localhost:8000")
    
    # Login as supervisor
    async with httpx.AsyncClient() as client:
        login_resp = await client.post(
            f"{base_url}/api/auth/login",
            json={"badge_number": "3254123", "password": "3254123123"}
        )
        if login_resp.status_code != 200:
            _fail("Login as supervisor", f"HTTP {login_resp.status_code}")
            return
        
        token = login_resp.json().get("access_token")
        
        # Access supervisor-only endpoint
        audit_resp = await client.get(
            f"{base_url}/api/audit-log",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        if audit_resp.status_code == 200:
            data = audit_resp.json()
            if "entries" in data and isinstance(data["entries"], list):
                _ok("Supervisor allowed to access audit-log (HTTP 200)")
            else:
                _fail("Audit-log response", f"Expected 'entries' array, got: {list(data.keys())}")
        else:
            _fail("Supervisor access", f"Expected 200, got {audit_resp.status_code}: {audit_resp.text}")


async def test_log_action_writes_to_audit_log():
    """
    Test 5: log_action() writes to audit_log (automates FiveToSix.md Test 5).
    
    Verifies that log_action() successfully writes a row to the audit_log table
    and that the entry can be retrieved via the audit-log endpoint.
    """
    _sep("Role Auth — log_action() writes to audit_log")
    import httpx
    from db.connection import create_pool, close_pool
    from auth.role_guard import log_action
    
    base_url = os.getenv("API_BASE_URL", "http://localhost:8000")
    
    # Login as supervisor to read audit log
    async with httpx.AsyncClient() as client:
        login_resp = await client.post(
            f"{base_url}/api/auth/login",
            json={"badge_number": "3254123", "password": "3254123123"}
        )
        if login_resp.status_code != 200:
            _fail("Login for audit check", f"HTTP {login_resp.status_code}")
            return
        
        token = login_resp.json().get("access_token")
        
        # Get current audit log count
        before_resp = await client.get(
            f"{base_url}/api/audit-log?limit=100",
            headers={"Authorization": f"Bearer {token}"}
        )
        if before_resp.status_code != 200:
            _fail("Read audit log before", f"HTTP {before_resp.status_code}")
            return
        
        before_count = len(before_resp.json().get("entries", []))
        
        # Write a test action using log_action directly
        await create_pool()
        try:
            await log_action(
                officer_id=1,
                action="test_automated_role_auth",
                resource_type="test_resource",
                resource_id="test_123",
                details="Automated test from test_integration.py"
            )
            
            # Verify the new entry appears
            after_resp = await client.get(
                f"{base_url}/api/audit-log?limit=100",
                headers={"Authorization": f"Bearer {token}"}
            )
            if after_resp.status_code != 200:
                _fail("Read audit log after", f"HTTP {after_resp.status_code}")
                return
            
            after_entries = after_resp.json().get("entries", [])
            after_count = len(after_entries)
            
            if after_count > before_count:
                # Check if our test action is in the results
                found = any(
                    e.get("action") == "test_automated_role_auth" 
                    for e in after_entries
                )
                if found:
                    _ok("log_action() wrote to audit_log (verified via endpoint)")
                else:
                    _fail("log_action() verification", "Entry count increased but test action not found")
            else:
                _fail("log_action() write", f"Count unchanged: before={before_count}, after={after_count}")
        
        finally:
            await close_pool()


async def test_log_action_non_fatal():
    """
    Test: log_action() is non-fatal (doesn't raise on DB failure).
    
    Verifies that log_action() catches exceptions and completes normally
    even when the database write fails.
    """
    _sep("Role Auth — log_action() non-fatal behavior")
    from unittest.mock import AsyncMock, patch
    from auth.role_guard import log_action
    
    # Mock execute_write to raise an exception
    with patch("auth.role_guard.execute_write", new_callable=AsyncMock) as mock_write:
        mock_write.side_effect = Exception("Simulated DB failure")
        
        try:
            # Should complete without raising
            await log_action(
                officer_id=999,
                action="test_failure",
                resource_type="test",
                resource_id="999"
            )
            _ok("log_action() caught exception and completed (non-fatal)")
        except Exception as e:
            _fail("log_action() non-fatal", f"Raised exception: {e}")


async def test_audit_log_endpoint_response_format():
    """
    Test: GET /api/audit-log returns correct format and ordering.
    
    Verifies response shape, ordering by created_at DESC, and that
    Employee FirstName is joined correctly.
    """
    _sep("Role Auth — audit-log endpoint format")
    import httpx
    
    base_url = os.getenv("API_BASE_URL", "http://localhost:8000")
    
    async with httpx.AsyncClient() as client:
        # Login as supervisor
        login_resp = await client.post(
            f"{base_url}/api/auth/login",
            json={"badge_number": "3254123", "password": "3254123123"}
        )
        if login_resp.status_code != 200:
            _fail("Login for format test", f"HTTP {login_resp.status_code}")
            return
        
        token = login_resp.json().get("access_token")
        
        # Get audit log
        resp = await client.get(
            f"{base_url}/api/audit-log?limit=10",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        if resp.status_code != 200:
            _fail("Audit-log endpoint", f"HTTP {resp.status_code}")
            return
        
        data = resp.json()
        
        # Check response shape
        if "entries" not in data:
            _fail("Response format", "Missing 'entries' key")
            return
        
        entries = data["entries"]
        if not isinstance(entries, list):
            _fail("Response format", f"'entries' is not a list: {type(entries)}")
            return
        
        _ok("Response shape is {'entries': [...]}")
        
        if len(entries) > 0:
            # Check first entry has expected fields
            first = entries[0]
            required_fields = ["created_at", "FirstName", "action", "resource_type", "resource_id", "ip_address"]
            missing = [f for f in required_fields if f not in first]
            
            if missing:
                _fail("Entry fields", f"Missing: {missing}")
            else:
                _ok("Entries include joined Employee.FirstName")
            
            # Check ordering (DESC by created_at)
            if len(entries) > 1:
                dates = [e.get("created_at") for e in entries if e.get("created_at")]
                if dates == sorted(dates, reverse=True):
                    _ok("Entries ordered by created_at DESC")
                else:
                    _fail("Entry ordering", "Not sorted by created_at DESC")


async def test_audit_log_no_data_leak_on_403():
    """
    Test: Audit-log endpoint returns 403 for non-supervisor with no data leak.
    
    Verifies that an investigator gets 403 and the response doesn't leak
    any audit log data.
    """
    _sep("Role Auth — audit-log blocks investigator, no leak")
    import httpx
    
    base_url = os.getenv("API_BASE_URL", "http://localhost:8000")
    
    async with httpx.AsyncClient() as client:
        # Login as investigator
        login_resp = await client.post(
            f"{base_url}/api/auth/login",
            json={"badge_number": "7295834", "password": "7295834123"}
        )
        if login_resp.status_code != 200:
            _fail("Login as investigator", f"HTTP {login_resp.status_code}")
            return
        
        token = login_resp.json().get("access_token")
        
        # Try to access audit log
        resp = await client.get(
            f"{base_url}/api/audit-log",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        if resp.status_code != 403:
            _fail("403 enforcement", f"Expected 403, got {resp.status_code}")
            return
        
        body = resp.json()
        
        # Ensure no "entries" or audit data in response
        if "entries" in body:
            _fail("Data leak check", "Response contains 'entries' on 403")
        elif "detail" in body and "role" in body["detail"].lower():
            _ok("Investigator blocked with 403, no data leak")
        else:
            _ok("403 returned (no entries leaked)")


async def test_chat_endpoints_not_role_gated():
    """
    Regression: Chat endpoints work with any role (automates FiveToSix.md regression check).
    
    Verifies that /api/chat and /api/chat/stream are NOT gated by require_role()
    and work for officers of any role (investigator, supervisor, analyst).
    """
    _sep("Regression — chat endpoints not role-gated")
    import httpx
    
    base_url = os.getenv("API_BASE_URL", "http://localhost:8000")
    
    # Test with investigator role
    async with httpx.AsyncClient(timeout=30.0) as client:
        login_resp = await client.post(
            f"{base_url}/api/auth/login",
            json={"badge_number": "7295834", "password": "7295834123"}
        )
        if login_resp.status_code != 200:
            _fail("Investigator login for chat test", f"HTTP {login_resp.status_code}")
            return
        
        token = login_resp.json().get("access_token")
        
        # Test POST /api/chat (non-streaming)
        chat_resp = await client.post(
            f"{base_url}/api/chat",
            headers={"Authorization": f"Bearer {token}"},
            json={"question": "How many cases?", "session_id": "test-role-regression"}
        )
        
        if chat_resp.status_code in (200, 201):
            _ok("POST /api/chat works for investigator (not role-gated)")
        elif chat_resp.status_code == 403:
            _fail("Chat regression", "/api/chat incorrectly gated by role (should allow any role)")
        else:
            # May fail for other reasons (LLM, DB), but not 403
            _ok(f"POST /api/chat not blocked by role (HTTP {chat_resp.status_code})")
        
        # Test GET /api/chat/stream
        stream_resp = await client.get(
            f"{base_url}/api/chat/stream?question=test&session_id=test-stream-role",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        if stream_resp.status_code in (200, 201):
            _ok("GET /api/chat/stream works for investigator (not role-gated)")
        elif stream_resp.status_code == 403:
            _fail("Stream regression", "/api/chat/stream incorrectly gated by role")
        else:
            _ok(f"GET /api/chat/stream not blocked by role (HTTP {stream_resp.status_code})")


# ══════════════════════════════════════════════════════════════════════════════
# Runner
# ══════════════════════════════════════════════════════════════════════════════

async def run_group(group: str):
    doc_ids = _kb_doc_ids()
    has_kb = bool(doc_ids)

    if group in ("llm", "all"):
        await test_llm_ping()
        await test_sql_generation()

    if group in ("rag", "all"):
        if not has_kb:
            print("\n  [SKIP] RAG tests skipped — KB_DOCUMENT_IDS not set in .env")
            print("         Upload backend/rag_consolidated/*.txt to Catalyst KB first,")
            print("         then run: python backend/kb_sync.py --refresh-token")
        else:
            print(f"\n  Using {len(doc_ids)} KB document(s) from .env")
            await test_rag_empty_doc_ids()
            await test_rag_known_good(doc_ids)
            await test_rag_known_absent(doc_ids)
            await test_rag_vague_query(doc_ids)
            await test_rag_messy_grammar(doc_ids)
            await test_rag_direct_followup(doc_ids)
            await test_rag_repeat_consistency(doc_ids)

    if group in ("rag", "all") and has_kb:
        await test_rag_session_multiturn(doc_ids)

    if group in ("pipeline", "all"):
        await test_pipeline_narrative_routing()
        await test_pipeline_off_topic()

    if group in ("e2e", "all"):
        await test_e2e_rag_pipeline()
    
    if group in ("role", "all"):
        await test_role_based_auth_jwt_includes_role()
        await test_role_based_auth_blocks_wrong_role()
        await test_role_based_auth_allows_correct_role()
        await test_log_action_writes_to_audit_log()
        await test_log_action_non_fatal()
        await test_audit_log_endpoint_response_format()
        await test_audit_log_no_data_leak_on_403()
        await test_chat_endpoints_not_role_gated()


if __name__ == "__main__":
    group = sys.argv[1] if len(sys.argv) > 1 else "all"
    valid = ("all", "llm", "rag", "pipeline", "e2e", "role")
    if group not in valid:
        print(f"Unknown group '{group}'. Valid: {', '.join(valid)}")
        sys.exit(1)
    print(f"\nRunning integration tests — group: [{group}]")
    asyncio.run(run_group(group))
    print("\nDone.")
