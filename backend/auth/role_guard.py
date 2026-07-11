"""
Role-based access control and audit logging.
Builds on the existing JWT auth - does NOT replace it.
get_current_officer still runs first; this adds a role check on top.

No schema-specific table references in this file - it only reads officer.get("role")
from the JWT payload dict populated at login time.
"""
from fastapi import Depends, HTTPException, Request
from auth.simple_auth import get_current_officer
from db.connection import execute_write
import sys


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
