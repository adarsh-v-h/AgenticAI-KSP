"""
Decision-support endpoints — per-case investigative aids that connect a case
to patterns/other cases the officer may not have manually cross-referenced.
"""
from fastapi import APIRouter, Depends

from auth.simple_auth import get_current_officer
from pipeline.similar_cases import find_similar_cases

router = APIRouter()


@router.get("/api/decision-support/similar-cases/{case_id}")
async def similar_cases(case_id: int, limit: int = 5, officer: dict = Depends(get_current_officer)):
    """
    Returns cases similar to `case_id`, each with match_reasons so the
    officer sees exactly why it surfaced — never an unexplained black box.
    """
    results = await find_similar_cases(case_id, limit)
    return {"case_id": case_id, "similar_cases": results}
