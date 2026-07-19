"""
Simple JWT auth for local development.
REPLACE with Catalyst Authentication before production deployment.

The `get_current_officer` dependency is the only thing routes touch â€” swapping
the implementation here requires zero route changes.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import bcrypt
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


# CONTRACT
# takes:  officer_id (int) — EmployeeID, badge_number (str) — KGID identifier, role (str) — employee role,
#          unit_id (int | None) — the officer's station Unit.UnitID, unit_name (str | None) — station display name
# returns: (str) — signed JWT token with 24-hour expiry
# raises:  nothing
def create_access_token(
    officer_id: int,
    badge_number: str,
    role: str,
    unit_id: int | None = None,
    unit_name: str | None = None,
) -> str:
    """
    Sign a JWT carrying EmployeeID (as officer_id), KGID (as badge_number), role,
    the officer's station (unit_id / unit_name), and a 24-hour expiry.

    unit_id / unit_name are embedded here — and ONLY here — so the station-wide
    rate limiter can derive the officer's station from the signed token rather
    than trusting anything the client sends. Never read the station from the
    request body/params.

    badge_number param name kept for compatibility with existing call sites -
    it now holds the value from Employee.KGID, not officers.badge_number.
    """
    expire = datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS)
    payload = {
        "officer_id": officer_id,
        "badge_number": badge_number,
        "role": role,
        "unit_id": unit_id,
        "unit_name": unit_name,
        "exp": expire,
    }
    return jwt.encode(payload, get("APP_SECRET_KEY"), algorithm=ALGORITHM)


# CONTRACT
# takes:  detail (str) — error message for the 401 response
# returns: (HTTPException) — configured 401 HTTP exception with WWW-Authenticate header
# raises:  nothing
def _unauthorized(detail: str = "Invalid or expired token. Please log in again.") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


# CONTRACT
# takes:  token (str) — JWT string to verify
# returns: (dict) — decoded JWT payload
# raises:  HTTPException — when token is missing, invalid, or expired (401)
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


# CONTRACT
# takes:  credentials (HTTPAuthorizationCredentials | None) — Bearer token from Authorization header
# returns: (dict) — decoded JWT payload for the authenticated officer
# raises:  HTTPException — when no credentials or token invalid (401)
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


# CONTRACT
# takes:  request (Request) — the incoming HTTP request, credentials (HTTPAuthorizationCredentials | None) — Bearer token from header, token (str | None) — fallback JWT from query param
# returns: (dict) — decoded JWT payload for the authenticated officer
# raises:  HTTPException — when no token found in header or query param (401)
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


# CONTRACT
# takes:  badge_number (str) — employee KGID, password (str) — plaintext password to verify
# returns: (dict) — {"access_token": str, "officer": {...}} with JWT and officer info
# raises:  HTTPException — when credentials are invalid or employee not found (401)
async def login(badge_number: str, password: str) -> dict:
    """
    Authenticate an employee.
    Lookup is by `KGID` against the `Employee` table. Password is verified
    against the bcrypt hash in `Employee.password_hash` (see
    backend/migrate_password_hash.py — every officer's password is currently
    KGID+"123", now stored hashed instead of re-derived from the formula on
    every login; officer-chosen passwords are a future step).
    Returns: {"access_token": str, "officer": {...}} on success.
    Raises HTTP 401 on bad credentials.
    """
    from db.connection import execute_query  # avoid circular import at module load

    if not badge_number or not password:
        raise _unauthorized("Invalid badge number or password.")

    rows = await execute_query(
        "SELECT e.EmployeeID, e.KGID, e.FirstName, e.role, e.UnitID, e.password_hash, "
        "       r.RankName AS `rank`, u.UnitName "
        "FROM Employee AS e "
        "LEFT JOIN `Rank` AS r ON e.RankID = r.RankID "
        "LEFT JOIN Unit AS u ON u.UnitID = e.UnitID "
        "WHERE e.KGID = %s AND e.is_active = TRUE",
        (badge_number,),
    )
    if not rows:
        raise _unauthorized("Invalid badge number or password.")

    employee = rows[0]
    stored_hash = employee.get("password_hash")
    # bcrypt.checkpw is deliberately slow (CPU-bound, ~100-300ms) and has no
    # async variant. Running it directly here would block the whole event
    # loop for that duration — offload it to a worker thread instead.
    if not stored_hash or not await asyncio.to_thread(
        bcrypt.checkpw, password.encode("utf-8"), stored_hash.encode("utf-8")
    ):
        raise _unauthorized("Invalid badge number or password.")

    token = create_access_token(
        employee["EmployeeID"],
        employee["KGID"],
        employee["role"],
        unit_id=employee.get("UnitID"),
        unit_name=employee.get("UnitName"),
    )
    return {
        "access_token": token,
        "officer": {
            "officer_id": employee["EmployeeID"],
            "badge_number": employee["KGID"],
            "full_name": employee["FirstName"],
            "rank": employee["rank"] or "",
            "unit_id": employee.get("UnitID"),
            "unit_name": employee.get("UnitName") or "",
        },
    }

