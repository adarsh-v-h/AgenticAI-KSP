"""
Offender profiling endpoints -- explainable risk scores for accused persons.
"""
from fastapi import APIRouter, Depends, HTTPException, Request

from auth.simple_auth import get_current_officer
from auth.role_guard import log_action
from pipeline.risk_scoring import (
    compute_risk_for_accused,
    save_risk_score,
    get_cached_risk_score,
    recompute_all_risk_scores,
)
from db.connection import execute_query

router = APIRouter()

# Generic/placeholder names that don't represent a single real identity --
# grouping risk by name would otherwise conflate many unrelated unidentified
# people into one falsely "high risk" entity.
_PLACEHOLDER_NAMES = ("Suspect", "Unknown", "Unidentified", "Not Known", "NA", "N/A")


@router.get("/api/profiling/risk/{accused_id}")
async def get_risk_score(accused_id: int, request: Request, force_recompute: bool = False, officer: dict = Depends(get_current_officer)):
    # Audit trail: viewing an individual's risk profile is sensitive.
    await log_action(
        officer["officer_id"], "view_risk_profile",
        resource_type="accused", resource_id=str(accused_id), request=request,
    )
    if not force_recompute:
        cached = await get_cached_risk_score(accused_id)
        if cached:
            return cached

    result = await compute_risk_for_accused(accused_id)
    if result["risk_score"] == 0.0 and not result["contributing_factors"]:
        exists = await execute_query(
            "SELECT AccusedMasterID FROM Accused WHERE AccusedMasterID = %s", (accused_id,)
        )
        if not exists:
            raise HTTPException(status_code=404, detail="Accused person not found.")
    await save_risk_score(result)
    return result


@router.get("/api/profiling/top-risk")
async def top_risk_offenders(limit: int = 10, officer: dict = Depends(get_current_officer)):
    """
    Highest-scored DISTINCT identities (grouped by name, since the same
    person can have multiple AccusedMasterID rows across case appearances).
    Placeholder/generic names (e.g. "Suspect") are excluded -- they represent
    many unrelated unidentified people, not one real repeat offender, and
    would otherwise show up as falsely high-risk.
    """
    placeholders = ",".join(["%s"] * len(_PLACEHOLDER_NAMES))
    rows = await execute_query(
        f"""SELECT MIN(s.AccusedMasterID) AS AccusedMasterID, a.AccusedName,
                   s.risk_score, s.risk_tier, COUNT(*) AS appearance_count
            FROM offender_risk_scores s
            JOIN Accused a ON a.AccusedMasterID = s.AccusedMasterID
            WHERE a.AccusedName NOT IN ({placeholders})
            GROUP BY a.AccusedName, s.risk_score, s.risk_tier
            ORDER BY s.risk_score DESC
            LIMIT %s""",
        (*_PLACEHOLDER_NAMES, limit)
    )
    return {"top_risk": rows}


@router.post("/api/profiling/recompute-all")
async def recompute_all(officer: dict = Depends(get_current_officer)):
    count = await recompute_all_risk_scores()
    return {"recomputed": count}
