"""
Builds a chronological timeline for a single case.
Events come from: CaseMaster registration/incident dates, and ArrestSurrender
events (one per arrested/surrendered accused). No ChargesheetDetails reference
-- that table is on MIGRATE.md's deferred list.
"""
from db.connection import execute_query


# CONTRACT
# takes:  case_master_id (int) — CaseMasterID of the case to build a timeline for
# returns: (list[dict]) — chronologically ordered events [{date, event, detail}], empty if case doesn't exist
# raises:  nothing
async def build_case_timeline(case_master_id: int) -> list[dict]:
    """
    Returns chronologically ordered events:
    [{"date": "2024-05-15", "event": "Case registered", "detail": "..."}, ...]
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
