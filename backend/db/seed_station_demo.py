"""
Backfills a clean 2-tier station hierarchy for demo purposes: one parent
"Circle" unit supervising 5-8 child police stations. Reassigns a subset of
existing officers and cases onto these stations so the supervisor/
investigator scoping tiers are actually demoable. Additive and idempotent
-- safe to re-run.
"""
import asyncio
import sys
import os

# Ensure backend is on the path
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from db.connection import execute_query, execute_write

DEMO_STATIONS = [
    "Koramangala PS", "Indiranagar PS", "HSR Layout PS",
    "Whitefield PS", "Jayanagar PS", "Yeshwanthpur PS",
]
DEMO_CIRCLE_NAME = "Bengaluru South Circle"


# CONTRACT
# takes:  nothing
# returns: (tuple[int, list[int]]) — (circle_id, list of station_ids)
# raises:  nothing (failures logged, exits on error)
async def ensure_hierarchy():
    """Create or retrieve the circle unit and its child stations."""
    circle_rows = await execute_query(
        "SELECT UnitID FROM Unit WHERE UnitName = %s", (DEMO_CIRCLE_NAME,)
    )
    if circle_rows:
        circle_id = circle_rows[0]["UnitID"]
        print(f"Circle '{DEMO_CIRCLE_NAME}' already exists as UnitID={circle_id}")
    else:
        circle_id = await execute_write(
            "INSERT INTO Unit (UnitName, ParentUnit, Active) VALUES (%s, NULL, 1)",
            (DEMO_CIRCLE_NAME,)
        )
        print(f"Created circle '{DEMO_CIRCLE_NAME}' as UnitID={circle_id}")

    station_ids = []
    for name in DEMO_STATIONS:
        rows = await execute_query("SELECT UnitID FROM Unit WHERE UnitName = %s", (name,))
        if rows:
            station_id = rows[0]["UnitID"]
            await execute_write(
                "UPDATE Unit SET ParentUnit = %s WHERE UnitID = %s",
                (circle_id, station_id)
            )
            print(f"Updated existing station '{name}' (UnitID={station_id}) -> ParentUnit={circle_id}")
        else:
            station_id = await execute_write(
                "INSERT INTO Unit (UnitName, ParentUnit, Active) VALUES (%s, %s, 1)",
                (name, circle_id)
            )
            print(f"Created station '{name}' as UnitID={station_id}")
        station_ids.append(station_id)

    return circle_id, station_ids


# CONTRACT
# takes:  circle_id (int) — circle unit ID to assign supervisor to,
#          station_ids (list[int]) — station IDs to distribute investigators across
# returns: nothing
# raises:  nothing
async def assign_officers(circle_id, station_ids):
    """Reassign existing officers to demo stations for realistic scoping."""
    officers = await execute_query(
        "SELECT EmployeeID, FirstName, role FROM Employee ORDER BY EmployeeID LIMIT 10"
    )
    if not officers:
        print("No officers found -- run the main seed.py first.")
        return

    # Assign ALL supervisor-role officers to the parent circle unit
    supervisors = [o for o in officers if o["role"] == "supervisor"]
    supervisor_ids = {s["EmployeeID"] for s in supervisors}
    for sup in supervisors:
        await execute_write(
            "UPDATE Employee SET UnitID = %s WHERE EmployeeID = %s",
            (circle_id, sup["EmployeeID"])
        )
        print(f"Assigned supervisor '{sup['FirstName']}' (ID={sup['EmployeeID']}) to circle UnitID={circle_id}")

    # Distribute remaining non-supervisor officers across stations
    investigators = [o for o in officers if o["EmployeeID"] not in supervisor_ids]
    for i, officer in enumerate(investigators):
        station_id = station_ids[i % len(station_ids)]
        await execute_write(
            "UPDATE Employee SET UnitID = %s WHERE EmployeeID = %s",
            (station_id, officer["EmployeeID"])
        )
        print(f"Assigned officer '{officer['FirstName']}' (ID={officer['EmployeeID']}, role={officer['role']}) to station UnitID={station_id}")


# CONTRACT
# takes:  station_ids (list[int]) — station IDs to distribute cases across
# returns: nothing
# raises:  nothing
async def assign_cases(station_ids):
    """Reassign a subset of cases to demo stations for realistic data."""
    cases = await execute_query("SELECT CaseMasterID FROM CaseMaster ORDER BY CaseMasterID LIMIT 30")
    if not cases:
        print("No cases found -- run the main seed.py first.")
        return

    for i, case in enumerate(cases):
        station_id = station_ids[i % len(station_ids)]
        await execute_write(
            "UPDATE CaseMaster SET PoliceStationID = %s WHERE CaseMasterID = %s",
            (station_id, case["CaseMasterID"])
        )
    print(f"Reassigned {len(cases)} cases across {len(station_ids)} demo stations (round-robin)")


# CONTRACT
# takes:  nothing
# returns: nothing
# raises:  nothing (exceptions caught and printed)
async def main():
    from db.connection import create_pool, close_pool
    try:
        await create_pool()
        print("DB pool created.")
        circle_id, station_ids = await ensure_hierarchy()
        await assign_officers(circle_id, station_ids)
        await assign_cases(station_ids)
        print(f"\n=== Demo hierarchy ready ===")
        print(f"Circle unit ID: {circle_id}")
        print(f"Station IDs: {station_ids}")
        print(f"Stations: {len(station_ids)} child units under '{DEMO_CIRCLE_NAME}'")
        print("Run this after the main seed.py. Safe to re-run (idempotent).")
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
