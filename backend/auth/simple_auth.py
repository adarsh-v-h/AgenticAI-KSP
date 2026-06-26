"""
Simple JWT auth for local development.
REPLACE with Catalyst Authentication before production deployment.

The `get_current_officer` dependency is the only thing routes touch — swapping
the implementation here requires zero route changes.
"""

from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status, Query, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt

from config.settings import get

TOKEN_EXPIRE_HOURS = 24
ALGORITHM = "HS256"

# auto_error=False so we can produce a friendlier 401 ourselves and so the
# SSE route can fall back to a `?token=` query parameter (EventSource can't
# set custom headers).
_security = HTTPBearer(auto_error=False)


def create_access_token(officer_id: int, badge_number: str) -> str:
    """
    Sign a JWT carrying EmployeeID (as officer_id), KGID (as badge_number), and a 24-hour expiry.
    """
    expire = datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS)
    payload = {
        "officer_id": officer_id,
        "badge_number": badge_number,
        "exp": expire,
    }
    return jwt.encode(payload, get("APP_SECRET_KEY"), algorithm=ALGORITHM)


def _unauthorized(detail: str = "Invalid or expired token. Please log in again.") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def verify_token(token: str) -> dict:
    """
    Verify JWT signature and expiry. Returns the decoded payload.
    Raises HTTP 401 on any failure.
    """
    if not token:
        raise _unauthorized("Missing token.")
    try:
        return jwt.decode(token, get("APP_SECRET_KEY"), algorithms=[ALGORITHM])
    except JWTError:
        raise _unauthorized()


async def get_current_officer(
    credentials: HTTPAuthorizationCredentials | None = Depends(_security),
) -> dict:
    """
    Dependency for protected routes that receive the token in the
    `Authorization: Bearer ...` header. Returns the decoded payload.
    """
    if credentials is None or not credentials.credentials:
        raise _unauthorized("Missing Authorization header.")
    return verify_token(credentials.credentials)


async def get_current_officer_sse(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_security),
    token: str | None = Query(default=None),
) -> dict:
    """
    Same as `get_current_officer` but accepts a `?token=...` query param as a
    fallback so browser EventSource clients (which can't set headers) can
    authenticate the SSE stream endpoint.

    Order of precedence:
      1. Authorization header (Bearer)
      2. ?token=... query parameter
    """
    if credentials and credentials.credentials:
        return verify_token(credentials.credentials)
    if token:
        return verify_token(token)
    raise _unauthorized("Missing token.")


async def login(badge_number: str, password: str) -> dict:
    """
    Authenticate an employee.
    Lookup is by `KGID` against the `Employee` table.
    Password rule (Step 3): password must equal `KGID + "123"`.
    Returns: {"access_token": str, "officer": {...}} on success.
    Raises HTTP 401 on bad credentials.
    """
    from db.connection import execute_query  # avoid circular import at module load

    if not badge_number or not password:
        raise _unauthorized("Invalid badge number or password.")

    rows = await execute_query(
        "SELECT e.EmployeeID, e.KGID, e.FirstName, r.RankName AS rank "
        "FROM Employee AS e "
        "LEFT JOIN `Rank` AS r ON e.RankID = r.RankID "
        "WHERE e.KGID = %s AND e.is_active = TRUE",
        (badge_number,),
    )
    if not rows:
        raise _unauthorized("Invalid badge number or password.")

    employee = rows[0]
    expected = badge_number + "123"
    if password != expected:
        raise _unauthorized("Invalid badge number or password.")

    token = create_access_token(employee["EmployeeID"], employee["KGID"])
    return {
        "access_token": token,
        "officer": {
            "officer_id": employee["EmployeeID"],
            "badge_number": employee["KGID"],
            "full_name": employee["FirstName"],
            "rank": employee["rank"] or "",
        },
    }
