import sys
import re
from db.connection_real import execute_query

_units = {}
_crime_sub_heads = {}
_case_status_master = {}

_units_list = []
_crime_sub_heads_list = []
_case_status_master_list = []

# CONTRACT
# takes:  nothing
# returns: nothing
# raises:  nothing
async def init_lookup_cache() -> None:
    """
    Populate the in-memory cache for static lookup tables (Unit, CrimeSubHead, CaseStatusMaster)
    during startup. This avoids unnecessary RDS calls for static/lookup queries.
    """
    global _units, _crime_sub_heads, _case_status_master
    global _units_list, _crime_sub_heads_list, _case_status_master_list

    try:
        # 1. Cache Unit table
        unit_rows = await execute_query("SELECT UnitID, UnitName, ParentUnit FROM Unit")
        _units = {r["UnitID"]: r for r in unit_rows if r.get("UnitID") is not None}
        _units_list = unit_rows
    except Exception as e:
        print(f"WARNING: Failed to cache Unit table in-memory: {e}", file=sys.stderr)

    try:
        # 2. Cache CrimeSubHead table
        crime_rows = await execute_query("SELECT CrimeSubHeadID, CrimeHeadID, CrimeHeadName, SeqID FROM CrimeSubHead")
        _crime_sub_heads = {r["CrimeSubHeadID"]: r for r in crime_rows if r.get("CrimeSubHeadID") is not None}
        _crime_sub_heads_list = crime_rows
    except Exception as e:
        print(f"WARNING: Failed to cache CrimeSubHead table in-memory: {e}", file=sys.stderr)

    try:
        # 3. Cache CaseStatusMaster table
        status_rows = await execute_query("SELECT CaseStatusID, CaseStatusName FROM CaseStatusMaster")
        _case_status_master = {r["CaseStatusID"]: r for r in status_rows if r.get("CaseStatusID") is not None}
        _case_status_master_list = status_rows
    except Exception as e:
        print(f"WARNING: Failed to cache CaseStatusMaster table in-memory: {e}", file=sys.stderr)


# CONTRACT
# takes:  unit_id (int)
# returns: (list[int]) — list of descendant UnitIDs including the unit itself
# raises:  nothing
def get_descendant_units_mem(unit_id: int) -> list[int]:
    """
    Recursively compute descendant unit IDs from the in-memory cache.
    Replaces recursive CTE queries on the Unit table.
    """
    if not _units or unit_id not in _units:
        return [unit_id]

    descendants = []
    queue = [unit_id]
    visited = set()

    while queue:
        curr = queue.pop(0)
        if curr in visited:
            continue
        visited.add(curr)
        descendants.append(curr)

        for u_id, u_data in _units.items():
            if u_data.get("ParentUnit") == curr:
                queue.append(u_id)

    return descendants


# CONTRACT
# takes:  sql (str), params (tuple)
# returns: (list[dict] | None) — list of row dicts if cache hit, else None
# raises:  nothing
def intercept_lookup_query(sql: str, params: tuple = ()) -> list[dict] | None:
    """
    Intercepts select queries targeting Unit, CrimeSubHead, and CaseStatusMaster,
    serving them directly from the in-memory cache to bypass RDS queries entirely.
    """
    # Clean SQL for normalized lookup matching
    sql_clean = re.sub(r'\s+', ' ', sql.strip().upper().replace('`', ''))

    # 1. Simple Unit Table Queries
    if "FROM UNIT" in sql_clean:
        # Match: SELECT UnitID FROM Unit WHERE UnitID = %s
        if "WHERE UNITID =" in sql_clean and len(params) == 1:
            u_id = params[0]
            if u_id in _units:
                return [{"UnitID": _units[u_id]["UnitID"]}]
            return []

        # Match: SELECT UnitID FROM Unit WHERE UnitName = %s
        if "WHERE UNITNAME =" in sql_clean and len(params) == 1:
            name = params[0]
            for u in _units_list:
                if u.get("UnitName") == name:
                    return [{"UnitID": u["UnitID"]}]
            return []

        # Match: SELECT UnitID FROM Unit or descendants SELECT u.UnitID FROM Unit u
        if sql_clean == "SELECT UNITID FROM UNIT" or sql_clean == "SELECT U.UNITID FROM UNIT U":
            return [{"UnitID": u["UnitID"]} for u in _units_list]

        # Match: SELECT UnitID, UnitName, ParentUnit FROM Unit
        if "SELECT UNITID, UNITNAME, PARENTUNIT" in sql_clean and "WHERE" not in sql_clean:
            return [{"UnitID": u["UnitID"], "UnitName": u["UnitName"], "ParentUnit": u["ParentUnit"]} for u in _units_list]

    # 2. Simple CaseStatusMaster Table Queries
    if "FROM CASESTATUSMASTER" in sql_clean:
        if "SELECT CASESTATUSID, CASESTATUSNAME" in sql_clean and "WHERE" not in sql_clean:
            return [{"CaseStatusID": s["CaseStatusID"], "CaseStatusName": s["CaseStatusName"]} for s in _case_status_master_list]

    # 3. Simple CrimeSubHead Table Queries
    if "FROM CRIMESUBHEAD" in sql_clean:
        # Match: SELECT CrimeSubHeadID FROM CrimeSubHead LIMIT 1 (commonly used in tests)
        if "LIMIT 1" in sql_clean and "WHERE" not in sql_clean:
            if _crime_sub_heads_list:
                return [{"CrimeSubHeadID": _crime_sub_heads_list[0]["CrimeSubHeadID"]}]
            return []

        if "SELECT CRIMESUBHEADID, CRIMEHEADID, CRIMEHEADNAME, SEQID" in sql_clean and "WHERE" not in sql_clean:
            return [
                {
                    "CrimeSubHeadID": c["CrimeSubHeadID"],
                    "CrimeHeadID": c["CrimeHeadID"],
                    "CrimeHeadName": c["CrimeHeadName"],
                    "SeqID": c["SeqID"]
                }
                for c in _crime_sub_heads_list
            ]

    return None
