"""
Decision-support endpoints — per-case investigative aids that connect a case
to patterns/other cases the officer may not have manually cross-referenced.
"""
from fastapi import APIRouter, Depends, HTTPException

from auth.simple_auth import get_current_officer
from auth.role_guard import officer_can_access_case
from pipeline.similar_cases import find_similar_cases
from pipeline.case_timeline import build_case_timeline
from pipeline.case_summary import generate_case_summary

router = APIRouter()


@router.get("/api/decision-support/similar-cases/{case_id}")
async def similar_cases(case_id: int, limit: int = 5, officer: dict = Depends(get_current_officer)):
    """
    Returns cases similar to `case_id`, each with match_reasons so the
    officer sees exactly why it surfaced — never an unexplained black box.
    """
    if not await officer_can_access_case(officer, case_id):
        raise HTTPException(status_code=404, detail="Case not found")
    results = await find_similar_cases(case_id, limit)
    return {"case_id": case_id, "similar_cases": results}


@router.get("/api/decision-support/timeline/{case_id}")
async def case_timeline(case_id: int, officer: dict = Depends(get_current_officer)):
    """Chronological event list for a case."""
    if not await officer_can_access_case(officer, case_id):
        raise HTTPException(status_code=404, detail="Case not found")
    events = await build_case_timeline(case_id)
    return {"case_id": case_id, "timeline": events}


@router.get("/api/decision-support/summary/{case_id}")
async def case_summary(case_id: int, officer: dict = Depends(get_current_officer)):
    """LLM-generated investigative brief for a case."""
    if not await officer_can_access_case(officer, case_id):
        raise HTTPException(status_code=404, detail="Case not found")
    result = await generate_case_summary(case_id)
    return {"case_id": case_id, **result}
