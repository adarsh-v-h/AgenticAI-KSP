"""
Analytics endpoints — crime trend/pattern data for the officer dashboard.
Pure SQL aggregation under the hood (see pipeline/trend_analytics.py); no LLM
call is on the critical path for correctness.
"""
from fastapi import APIRouter, Depends, Query

from auth.simple_auth import get_current_officer
from pipeline.trend_analytics import (
    get_trend_by_month,
    get_trend_by_crime_type,
    get_trend_by_location,
    get_crime_type_by_location,
    get_status_breakdown,
    get_modus_operandi_clusters,
    get_seasonal_pattern,
)

router = APIRouter()


# CONTRACT
# takes:  months_back (int) — number of months to look back (1-60), officer (dict) — authenticated officer from token
# returns: (dict) — {"trend": list[dict]} with monthly crime counts
# raises:  HTTPException — when authentication fails (401)
@router.get("/api/analytics/trends/monthly")
async def trends_monthly(months_back: int = Query(12, ge=1, le=60), officer: dict = Depends(get_current_officer)):
    return {"trend": await get_trend_by_month(months_back)}


# CONTRACT
# takes:  officer (dict) — authenticated officer from token
# returns: (dict) — {"trend": list[dict]} with crime type counts
# raises:  HTTPException — when authentication fails (401)
@router.get("/api/analytics/trends/crime-type")
async def trends_crime_type(officer: dict = Depends(get_current_officer)):
    return {"trend": await get_trend_by_crime_type()}


# CONTRACT
# takes:  limit (int) — maximum number of stations to return (1-50), officer (dict) — authenticated officer from token
# returns: (dict) — {"trend": list[dict]} with station case counts
# raises:  HTTPException — when authentication fails (401)
@router.get("/api/analytics/trends/stations")
async def trends_stations(limit: int = Query(10, ge=1, le=50), officer: dict = Depends(get_current_officer)):
    return {"trend": await get_trend_by_location(limit)}


# CONTRACT
# takes:  unit_id (int) — police station UnitID to drill into, officer (dict) — authenticated officer from token
# returns: (dict) — {"unit_id": int, "breakdown": list[dict]} with crime types for that station
# raises:  HTTPException — when authentication fails (401)
@router.get("/api/analytics/trends/station/{unit_id}/breakdown")
async def station_breakdown(unit_id: int, officer: dict = Depends(get_current_officer)):
    data = await get_crime_type_by_location(unit_id)
    return {"unit_id": unit_id, "breakdown": data}


# CONTRACT
# takes:  officer (dict) — authenticated officer from token
# returns: (dict) — {"breakdown": list[dict]} with case status counts
# raises:  HTTPException — when authentication fails (401)
@router.get("/api/analytics/status-breakdown")
async def status_breakdown(officer: dict = Depends(get_current_officer)):
    return {"breakdown": await get_status_breakdown()}


# CONTRACT
# takes:  min_occurrences (int) — minimum cluster size threshold (1-100), officer (dict) — authenticated officer from token
# returns: (dict) — {"clusters": list[dict]} with repeated crime-type/station patterns
# raises:  HTTPException — when authentication fails (401)
@router.get("/api/analytics/mo-clusters")
async def mo_clusters(min_occurrences: int = Query(2, ge=1, le=100), officer: dict = Depends(get_current_officer)):
    return {"clusters": await get_modus_operandi_clusters(min_occurrences)}


# CONTRACT
# takes:  officer (dict) — authenticated officer from token
# returns: (dict) — {"pattern": list[dict]} with monthly seasonal crime counts
# raises:  HTTPException — when authentication fails (401)
@router.get("/api/analytics/seasonal")
async def seasonal_pattern(officer: dict = Depends(get_current_officer)):
    return {"pattern": await get_seasonal_pattern()}
