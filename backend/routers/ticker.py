"""
Ticker router — serves the per-officer pre-computed intelligence ticker text.

GET /api/ticker returns {"text": str | null}. The text is pulled from the
in-memory cache built by pipeline.intelligence_ticker at startup and refreshed
every 2 hours. Returns null gracefully if the cache isn't ready yet.
"""

import sys
from fastapi import APIRouter, Depends
from auth.simple_auth import get_current_officer
from pipeline.intelligence_ticker import get_ticker

router = APIRouter()


def _log(msg: str) -> None:
    print(f"[ticker_router] {msg}", file=sys.stderr, flush=True)


# CONTRACT
# takes:  officer (dict) — authenticated officer from JWT
# returns: (dict) — {"text": str | null}
# raises:  nothing (returns null gracefully on cache miss)
@router.get("/api/ticker")
async def get_station_ticker(officer: dict = Depends(get_current_officer)) -> dict:
    """
    Return the pre-computed intelligence ticker sentence for this officer.
    The text is role-scoped:
      - investigator/analyst → most recent case at their station
      - supervisor           → cross-sub-station open case summary
      - policymaker          → statewide 30-day snapshot
    Returns {"text": null} if the cache is not yet built (server just started).
    """
    role = officer.get("role", "")
    unit_id = officer.get("unit_id")
    text = get_ticker(unit_id, role)
    return {"text": text}
