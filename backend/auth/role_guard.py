"""
Role-based access control, audit logging, and station-scoped data access.

Builds on the existing JWT auth - does NOT replace it.
get_current_officer still runs first; this adds a role check on top.

This file is now also the single source of truth for "what can this officer
see" — see get_scoped_unit_ids(), officer_can_access_case(), and
officer_can_access_accused() below.
"""
import logging
from fastapi import Depends, HTTPException, Request
from auth.simple_auth import get_current_officer
from db.connection import execute_query, execute_write
import sys

logger = logging.getLogger(__name__)


class ScopeResolutionError(Exception):
    """Raised when scoped unit IDs cannot be reliably determined."""


# CONTRACT
# takes:  officer (dict) — authenticated officer's JWT payload
# returns: (list[int] | None) — list of Unit.UnitID values this officer can see,
#          or None if unrestricted (analyst/policymaker)
# raises:  ScopeResolutionError — when unit hierarchy resolution fails
async def get_scoped_unit_ids(officer: dict) -> list[int] | None:
    """
    Returns the list of Unit.UnitID values this officer is allowed to see
    case data for, or None if the officer has unrestricted (state/district-
    wide) access.

    - investigator: only their own station (officer['unit_id'])
    - supervisor: their own station plus every descendant station, walked
      via Unit.ParentUnit (recursive CTE)
    - analyst / policymaker: None — unrestricted access is the entire
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
        try:
            from db.lookup_cache import get_descendant_units_mem
            return get_descendant_units_mem(unit_id)
        except Exception as e:
            logger.error(
                "Failed to resolve scoped unit IDs for supervisor unit_id=%s: %s",
                unit_id, e, exc_info=True
            )
            raise ScopeResolutionError(
                f"Could not resolve station hierarchy scope for supervisor unit_id={unit_id}"
            ) from e

    # investigator, or any unrecognized role/state — fail closed
    return [unit_id] if unit_id else []


# CONTRACT
# takes:  officer (dict) — authenticated officer's JWT payload,
#          case_master_id (int) — CaseMasterID to check
# returns: (bool) — True if officer can access this case
# raises:  nothing (fail-closed: returns False on any error)
async def officer_can_access_case(officer: dict, case_master_id: int) -> bool:
    """
    Check whether the officer is permitted to access a specific case by its
    CaseMasterID.

    An officer may access a case if EITHER:
      1. The case's PoliceStationID is within the officer's scoped stations
         (their home station for investigators; home + descendants for supervisors).
      2. The case is directly assigned to this officer as the investigating officer
         (CaseMaster.PolicePersonID = officer's EmployeeID). An officer assigned
         to a case always has a legitimate need to view that case's details, even
         if it was registered at a different station (cross-station assignments).
    """
    scoped_ids = await get_scoped_unit_ids(officer)
    if scoped_ids is None:
        return True  # unrestricted role
    if not scoped_ids:
        return False  # officer has no assigned station

    officer_id = officer.get("officer_id")

    try:
        placeholders = ",".join(str(int(i)) for i in scoped_ids)
        rows = await execute_query(
            """SELECT 1 FROM CaseMaster
               WHERE CaseMasterID = %s
                 AND (PoliceStationID IN ({}) OR PolicePersonID = %s)""".format(
                placeholders
            ),
            (case_master_id, officer_id)
        )
        return len(rows) > 0
    except Exception:
        return False


# CONTRACT
# takes:  officer (dict) — authenticated officer's JWT payload,
#          accused_master_id (int) — AccusedMasterID to check
# returns: (bool) — True if officer can access this accused record
# raises:  nothing (fail-closed: returns False on any error)
async def officer_can_access_accused(officer: dict, accused_master_id: int) -> bool:
    """
    Check whether the officer is permitted to access a specific accused
    record by its AccusedMasterID. Uses get_scoped_unit_ids() to determine
    allowed stations.
    """
    scoped_ids = await get_scoped_unit_ids(officer)
    if scoped_ids is None:
        return True  # unrestricted role
    if not scoped_ids:
        return False  # officer has no assigned station
    try:
        placeholders = ",".join(str(int(i)) for i in scoped_ids)
        rows = await execute_query(
            """SELECT 1 FROM Accused a
               JOIN CaseMaster cm ON cm.CaseMasterID = a.CaseMasterID
               WHERE a.AccusedMasterID = %s AND cm.PoliceStationID IN ({})""".format(
                placeholders
            ),
            (accused_master_id,)
        )
        return len(rows) > 0
    except Exception:
        return False


# CONTRACT
# takes:  *allowed_roles (str) — one or more role names that are permitted
# returns: (Callable) — FastAPI dependency that checks the officer's role and returns the officer dict
# raises:  nothing (returned dependency raises HTTPException 403 on role mismatch)
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


# CONTRACT
# takes:  officer_id (int) — EmployeeID performing the action, action (str) — action name, resource_type (str | None) — type of resource affected, resource_id (str | None) — ID of resource affected, details (str | None) — extra context, request (Request | None) — HTTP request for IP extraction
# returns: nothing
# raises:  nothing (non-fatal, failures are logged to stderr)
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
