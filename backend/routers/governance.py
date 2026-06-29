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
