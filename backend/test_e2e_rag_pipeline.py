"""
End-to-end RAG pipeline test:
1. Count existing cases in MySQL
2. Insert 3 NEW test cases directly into MySQL
3. Run export_cases_for_rag.py (SQL -> TXT -> Consolidation)
4. Verify the new cases appear in the exported raw TXT files
5. Verify the consolidated grouped files contain the new cases
6. Clean up test data from MySQL
"""
import asyncio
import os
import glob
import subprocess
from db.connection import execute_query, create_pool, close_pool, get_pool

# Distinctive test data — easy to grep for in output files
TEST_CASES = [
    {
        "CrimeNo": "TEST_E2E_001",
        "BriefFacts": "TEST CASE ALPHA: Rajendra Prasad was apprehended near Jayanagar for possession of 500 grams of methamphetamine. The accused was operating a clandestine drug lab in a rented apartment.",
    },
    {
        "CrimeNo": "TEST_E2E_002",
        "BriefFacts": "TEST CASE BETA: Ananya Sharma reported that her gold chain worth Rs 2,50,000 was snatched by two unidentified men on a motorcycle near MG Road metro station at approximately 8:30 PM.",
    },
    {
        "CrimeNo": "TEST_E2E_003",
        "BriefFacts": "TEST CASE GAMMA: Deepak Hegde filed a complaint alleging that an unknown person gained access to his online banking credentials through a phishing email and transferred Rs 4,75,000 to an untraceable UPI account.",
    },
]


async def _write(sql: str, params=None):
    """Execute a write query (INSERT/DELETE) using the raw pool."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, params or ())
            await conn.commit()
            return cur.lastrowid


async def main():
    await create_pool()
    try:
        # ── Pre-cleanup: remove leftovers from any previous failed run ──
        test_crimeNos = [tc["CrimeNo"] for tc in TEST_CASES]
        leftover = await execute_query(
            "SELECT CaseMasterID FROM CaseMaster WHERE CrimeNo IN (%s, %s, %s)",
            tuple(test_crimeNos),
        )
        if leftover:
            print(f"[PRE-CLEANUP] Removing {len(leftover)} leftover test cases...")
            for row in leftover:
                cid = row["CaseMasterID"]
                await _write("DELETE FROM ActSectionAssociation WHERE CaseMasterID = %s", (cid,))
                await _write("DELETE FROM Accused WHERE CaseMasterID = %s", (cid,))
                await _write("DELETE FROM Victim WHERE CaseMasterID = %s", (cid,))
                await _write("DELETE FROM CaseMaster WHERE CaseMasterID = %s", (cid,))

        # ── Step 1: Baseline ────────────────────────────────────────
        rows = await execute_query("SELECT COUNT(*) AS cnt FROM CaseMaster")
        baseline = rows[0]["cnt"]
        print(f"[STEP 1] Baseline case count in MySQL: {baseline}")

        # Grab valid FK IDs for the insert
        stations = await execute_query(
            "SELECT UnitID FROM Unit WHERE UnitName LIKE '%PS%' LIMIT 1"
        )
        station_id = stations[0]["UnitID"]

        statuses = await execute_query("SELECT CaseStatusID FROM CaseStatusMaster LIMIT 1")
        status_id = statuses[0]["CaseStatusID"]

        categories = await execute_query("SELECT CaseCategoryID FROM CaseCategory LIMIT 1")
        cat_id = categories[0]["CaseCategoryID"]

        gravities = await execute_query("SELECT GravityOffenceID FROM GravityOffence LIMIT 1")
        grav_id = gravities[0]["GravityOffenceID"]

        crime_heads = await execute_query("SELECT CrimeSubHeadID FROM CrimeSubHead LIMIT 1")
        crime_head_id = crime_heads[0]["CrimeSubHeadID"]

        sections = await execute_query(
            "SELECT ActCode, SectionCode, SectionDescription FROM Section LIMIT 3"
        )

        employees = await execute_query("SELECT EmployeeID FROM Employee LIMIT 1")
        employee_id = employees[0]["EmployeeID"]

        # ── Step 2: Insert 3 new test cases ─────────────────────────
        print("\n[STEP 2] Inserting 3 NEW test cases into MySQL...")
        inserted_ids = []

        for i, tc in enumerate(TEST_CASES):
            case_id = await _write(
                """
                INSERT INTO CaseMaster
                    (CrimeNo, PolicePersonID, PoliceStationID, CaseStatusID,
                     CaseCategoryID, GravityOffenceID, CrimeMinorHeadID,
                     BriefFacts, IncidentFromDate, CrimeRegisteredDate)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), CURDATE())
                """,
                (tc["CrimeNo"], employee_id, station_id, status_id,
                 cat_id, grav_id, crime_head_id, tc["BriefFacts"]),
            )
            inserted_ids.append(case_id)

            # Insert an accused
            await _write(
                "INSERT INTO Accused (CaseMasterID, AccusedName, AgeYear) VALUES (%s, %s, %s)",
                (case_id, f"TestAccused_{tc['CrimeNo']}", 30 + i),
            )

            # Insert a victim
            await _write(
                "INSERT INTO Victim (CaseMasterID, VictimName, AgeYear) VALUES (%s, %s, %s)",
                (case_id, f"TestVictim_{tc['CrimeNo']}", 25 + i),
            )

            # Insert an ActSectionAssociation so the SECTIONS field is populated
            if i < len(sections):
                sec = sections[i]
                await _write(
                    "INSERT INTO ActSectionAssociation (CaseMasterID, ActID, SectionID) VALUES (%s, %s, %s)",
                    (case_id, sec["ActCode"], sec["SectionCode"]),
                )

            print(f"  Inserted: {tc['CrimeNo']} (CaseMasterID={case_id})")

        # Verify insertion
        rows2 = await execute_query("SELECT COUNT(*) AS cnt FROM CaseMaster")
        new_count = rows2[0]["cnt"]
        print(f"\n  Case count after insert: {new_count} (added {new_count - baseline})")
        assert new_count == baseline + 3, f"Expected {baseline + 3}, got {new_count}"
        print("  PASS: 3 new cases successfully inserted!")

        # ── Step 3: Run export + consolidation ──────────────────────
        print("\n[STEP 3] Running export_cases_for_rag.py (SQL -> TXT -> Consolidation)...")
        result = subprocess.run(
            ["python", "backend/export_cases_for_rag.py"],
            cwd=r"c:\Users\navaneeth\AgenticAI-KSP-v2",
            capture_output=True, text=True, timeout=30,
        )
        print(result.stdout)
        if result.returncode != 0:
            print(f"  STDERR: {result.stderr}")
            raise RuntimeError("Export script failed!")

        # ── Step 4: Verify new cases in raw TXT files ───────────────
        print("[STEP 4] Checking raw TXT files in backend/rag_export/...")
        export_dir = r"c:\Users\navaneeth\AgenticAI-KSP-v2\backend\rag_export"
        found_raw = []
        for tc in TEST_CASES:
            pattern = os.path.join(export_dir, f"case_{tc['CrimeNo']}*")
            matches = glob.glob(pattern)
            if matches:
                found_raw.append(tc["CrimeNo"])
                # Read the file and show a snippet
                with open(matches[0], "r", encoding="utf-8") as f:
                    content = f.read()
                print(f"  FOUND: {os.path.basename(matches[0])} ({len(content)} bytes)")
                # Show first 3 lines
                for line in content.strip().split("\n")[:4]:
                    print(f"    | {line}")
            else:
                print(f"  MISSING: case_{tc['CrimeNo']}*")

        assert len(found_raw) == 3, f"Expected 3 raw files, found {len(found_raw)}"
        print(f"  PASS: All 3 test cases found in raw export!")

        # ── Step 5: Verify new cases in consolidated files ──────────
        print("\n[STEP 5] Checking consolidated files in backend/rag_consolidated/...")
        consol_dir = r"c:\Users\navaneeth\AgenticAI-KSP-v2\backend\rag_consolidated"
        consol_files = glob.glob(os.path.join(consol_dir, "*.txt"))
        print(f"  Consolidated files: {len(consol_files)}")
        for f_path in sorted(consol_files):
            print(f"    {os.path.basename(f_path):30s} ({os.path.getsize(f_path) / 1024:.1f} KB)")

        found_in = {}
        for fpath in consol_files:
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
            for tc in TEST_CASES:
                if tc["CrimeNo"] in content:
                    found_in[tc["CrimeNo"]] = os.path.basename(fpath)

        for tc in TEST_CASES:
            if tc["CrimeNo"] in found_in:
                print(f"  FOUND '{tc['CrimeNo']}' in -> {found_in[tc['CrimeNo']]}")
            else:
                print(f"  MISSING '{tc['CrimeNo']}' from ALL consolidated files!")

        assert len(found_in) == 3, f"Expected 3 cases in consolidated files, found {len(found_in)}"
        print(f"  PASS: All 3 test cases correctly consolidated and grouped!")

        # ── Step 6: Cleanup ─────────────────────────────────────────
        print("\n[STEP 6] Cleaning up test data from MySQL...")
        for case_id in inserted_ids:
            await _write("DELETE FROM ActSectionAssociation WHERE CaseMasterID = %s", (case_id,))
            await _write("DELETE FROM Accused WHERE CaseMasterID = %s", (case_id,))
            await _write("DELETE FROM Victim WHERE CaseMasterID = %s", (case_id,))
            await _write("DELETE FROM CaseMaster WHERE CaseMasterID = %s", (case_id,))
        rows3 = await execute_query("SELECT COUNT(*) AS cnt FROM CaseMaster")
        final = rows3[0]["cnt"]
        print(f"  Final case count: {final} (back to baseline: {final == baseline})")
        assert final == baseline, f"Cleanup failed: expected {baseline}, got {final}"
        print("  PASS: Cleanup successful!")

        # ── Summary ─────────────────────────────────────────────────
        print("\n" + "=" * 60)
        print("  END-TO-END RAG PIPELINE TEST: ALL STEPS PASSED")
        print("=" * 60)
        print(f"  Step 1: Baseline count .............. {baseline}")
        print(f"  Step 2: Insert 3 test cases ......... {baseline} -> {baseline + 3}")
        print(f"  Step 3: Export + Consolidation ....... OK")
        print(f"  Step 4: Raw TXT files created ....... 3/3 found")
        print(f"  Step 5: Consolidated grouping ....... 3/3 found")
        for crimeNo, fname in found_in.items():
            print(f"           {crimeNo} -> {fname}")
        print(f"  Step 6: Cleanup ..................... {baseline + 3} -> {baseline}")
        print("=" * 60)

    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
