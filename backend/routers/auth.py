"""
Authentication routes. /api/auth/login issues JWTs that protect every other
route via auth.simple_auth.get_current_officer.
"""

import sys

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from auth.simple_auth import login

router = APIRouter()


class LoginRequest(BaseModel):
    badge_number: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


class OfficerInfo(BaseModel):
    officer_id: int
    badge_number: str
    full_name: str
    rank: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    officer: OfficerInfo


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


@router.post("/api/auth/login", response_model=LoginResponse)
async def login_route(request: LoginRequest) -> LoginResponse:
    """
    Validate credentials and issue a JWT.
    HTTP 401 on bad credentials. Other exceptions surface as HTTP 500 from
    FastAPI's default handler — those would be infrastructure errors (DB down).
    """
    try:
        result = await login(request.badge_number, request.password)
    except HTTPException:
        # Already a clean 401 from the auth layer.
        raise
    except Exception as e:
        _log(f"login_route unexpected error: {e}")
        raise HTTPException(status_code=503, detail="Login service unavailable.")

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
