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


@router.get("/api/analytics/trends/monthly")
async def trends_monthly(months_back: int = Query(12, ge=1, le=60), officer: dict = Depends(get_current_officer)):
    return {"trend": await get_trend_by_month(months_back)}


@router.get("/api/analytics/trends/crime-type")
async def trends_crime_type(officer: dict = Depends(get_current_officer)):
    return {"trend": await get_trend_by_crime_type()}


@router.get("/api/analytics/trends/stations")
async def trends_stations(limit: int = Query(10, ge=1, le=50), officer: dict = Depends(get_current_officer)):
    return {"trend": await get_trend_by_location(limit)}


@router.get("/api/analytics/trends/station/{unit_id}/breakdown")
async def station_breakdown(unit_id: int, officer: dict = Depends(get_current_officer)):
    data = await get_crime_type_by_location(unit_id)
    return {"unit_id": unit_id, "breakdown": data}


@router.get("/api/analytics/status-breakdown")
async def status_breakdown(officer: dict = Depends(get_current_officer)):
    return {"breakdown": await get_status_breakdown()}


@router.get("/api/analytics/mo-clusters")
async def mo_clusters(min_occurrences: int = Query(2, ge=1, le=100), officer: dict = Depends(get_current_officer)):
    """
    The 'wider thinking' endpoint — repeated crime-type/station clusters an
    officer working a single case wouldn't otherwise see.
    """
    return {"clusters": await get_modus_operandi_clusters(min_occurrences)}


@router.get("/api/analytics/seasonal")
async def seasonal_pattern(officer: dict = Depends(get_current_officer)):
    return {"pattern": await get_seasonal_pattern()}
