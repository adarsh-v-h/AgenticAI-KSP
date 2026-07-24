"""
Authentication routes. /api/auth/login issues JWTs that protect every other
route via auth.simple_auth.get_current_officer.
"""

import sys
import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from auth.login_rate_limiter import check_login_attempt, reset_login_attempts
from auth.simple_auth import login
from llm.client import ping_model
from voice.zia_voice import ping_voice

router = APIRouter()


class LoginRequest(BaseModel):
    badge_number: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


class OfficerInfo(BaseModel):
    officer_id: int
    badge_number: str
    full_name: str
    rank: str
    role: str = ""
    unit_id: int | None = None
    unit_name: str = ""


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    officer: OfficerInfo


# CONTRACT
# takes:  msg (str) — message to log
# returns: nothing
# raises:  nothing
def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


@router.post("/api/auth/login", response_model=LoginResponse)
async def login_route(request: LoginRequest) -> LoginResponse:
    """
    Validate credentials and issue a JWT.

    Rate limited per badge number (10 attempts / 15 min — see
    auth/login_rate_limiter.py) BEFORE the credential check runs, so brute
    forcing a specific officer's password is capped regardless of source IP.
    This endpoint is exempt from the station-wide limiter (main.py) since
    there's no JWT yet to read a station id from.

    HTTP 401 on bad credentials, HTTP 429 when the badge number has exceeded
    its attempt budget. Other exceptions surface as HTTP 500 from FastAPI's
    default handler — those would be infrastructure errors (DB down).
    """
    limit_result = check_login_attempt(request.badge_number)
    if not limit_result.allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts. Please try again later.",
            headers={"Retry-After": str(limit_result.retry_after_seconds)},
        )

    try:
        result = await login(request.badge_number, request.password)
    except HTTPException:
        # Already a clean 401 from the auth layer.
        raise
    except Exception as e:
        _log(f"login_route unexpected error: {e}")
        raise HTTPException(status_code=503, detail="Login service unavailable.")

    reset_login_attempts(request.badge_number)

    # Pre-warm LLM models and Zia voice services non-blockingly (fire-and-forget)
    asyncio.create_task(ping_model("MODEL_SQL"))
    asyncio.create_task(ping_model("MODEL_ANSWER"))
    asyncio.create_task(ping_voice())

    return LoginResponse(
        access_token=result["access_token"],
        officer=OfficerInfo(**result["officer"]),
    )


@router.post("/api/auth/logout")
async def logout_route() -> dict:
    """
    Stateless logout — the frontend simply drops the token. We respond 200
    so the client has a single happy path.
    """
    return {"message": "Logged out successfully."}
