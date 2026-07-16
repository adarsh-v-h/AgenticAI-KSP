# Crime Forecasting & Early Warning

## What it does

A rule-based heuristic system that identifies emerging crime patterns and potential hotspots from existing trend data. Generates alerts for stations showing anomalous activity — NOT machine learning, just smart SQL aggregation with threshold logic.

## Why it matters (hackathon requirement)

Feature List item #8 requires:
- AI-driven identification of emerging crime patterns
- Generate early warning alerts for repeat crimes, gang activity, organized crime
- Predict potential crime hotspots

## Current state

We have `trend_analytics.py` (historical patterns) and `risk_scoring.py` (individual offender risk), but nothing that looks FORWARD to flag emerging issues. The data to support this is already in `CaseMaster` — dates, stations, crime types, and accused links.

## Implementation

### File: `backend/pipeline/crime_forecasting.py`

```python
"""
Rule-based crime forecasting and early warning system.
Identifies emerging patterns from trend analysis — no ML models,
just heuristic thresholds applied to existing crime data.
"""
from db.connection import execute_query


async def get_hotspot_alerts(threshold_pct: float = 50.0) -> list[dict]:
    """
    Identify stations where crime increased significantly in the most recent
    quarter compared to the previous quarter.
    
    Logic: Compare case count in the last 3 months vs the 3 months before that.
    Flag any station where the increase exceeds threshold_pct%.
    
    Returns: [{"station": str, "unit_id": int, "recent_count": int, 
               "previous_count": int, "change_pct": float, "alert_level": str}]
    """
    rows = await execute_query(
        """SELECT 
             u.UnitID AS unit_id,
             u.UnitName AS station,
             SUM(CASE WHEN cm.CrimeRegisteredDate >= DATE_SUB(
               (SELECT MAX(CrimeRegisteredDate) FROM CaseMaster), INTERVAL 3 MONTH)
               THEN 1 ELSE 0 END) AS recent_count,
             SUM(CASE WHEN cm.CrimeRegisteredDate >= DATE_SUB(
               (SELECT MAX(CrimeRegisteredDate) FROM CaseMaster), INTERVAL 6 MONTH)
               AND cm.CrimeRegisteredDate < DATE_SUB(
               (SELECT MAX(CrimeRegisteredDate) FROM CaseMaster), INTERVAL 3 MONTH)
               THEN 1 ELSE 0 END) AS previous_count
           FROM CaseMaster cm
           JOIN Unit u ON u.UnitID = cm.PoliceStationID
           GROUP BY u.UnitID, u.UnitName
           HAVING recent_count > 0 AND previous_count > 0"""
    )

    alerts = []
    for row in rows:
        recent = row["recent_count"]
        previous = row["previous_count"]
        if previous == 0:
            continue
        change_pct = round(((recent - previous) / previous) * 100, 1)
        if change_pct >= threshold_pct:
            alert_level = "critical" if change_pct >= 100 else "high" if change_pct >= 75 else "medium"
            alerts.append({
                "station": row["station"],
                "unit_id": row["unit_id"],
                "recent_count": recent,
                "previous_count": previous,
                "change_pct": change_pct,
                "alert_level": alert_level,
            })
    
    alerts.sort(key=lambda a: a["change_pct"], reverse=True)
    return alerts


async def get_repeat_crime_alerts(min_occurrences: int = 3, days: int = 90) -> list[dict]:
    """
    Identify crime type + station combinations that have spiked in the
    most recent N days (relative to latest case in DB).
    
    Returns: [{"crime_type": str, "station": str, "count": int, "period_days": int}]
    """
    return await execute_query(
        """SELECT csh.CrimeHeadName AS crime_type, u.UnitName AS station, COUNT(*) AS count
           FROM CaseMaster cm
           JOIN CrimeSubHead csh ON csh.CrimeSubHeadID = cm.CrimeMinorHeadID
           JOIN Unit u ON u.UnitID = cm.PoliceStationID
           WHERE cm.CrimeRegisteredDate >= DATE_SUB(
             (SELECT MAX(CrimeRegisteredDate) FROM CaseMaster), INTERVAL %s DAY)
           GROUP BY csh.CrimeHeadName, u.UnitName
           HAVING count >= %s
           ORDER BY count DESC""",
        (days, min_occurrences)
    )


async def get_gang_activity_alerts() -> list[dict]:
    """
    Identify accused persons who appeared in 2+ cases in the last 90 days
    (relative to latest case) — potential organized/gang activity.
    
    Returns: [{"accused_name": str, "case_count": int, "crime_types": str, "stations": str}]
    """
    return await execute_query(
        """SELECT a.AccusedName AS accused_name, 
                  COUNT(DISTINCT a.CaseMasterID) AS case_count,
                  GROUP_CONCAT(DISTINCT csh.CrimeHeadName SEPARATOR ', ') AS crime_types,
                  GROUP_CONCAT(DISTINCT u.UnitName SEPARATOR ', ') AS stations
           FROM Accused a
           JOIN CaseMaster cm ON cm.CaseMasterID = a.CaseMasterID
           JOIN CrimeSubHead csh ON csh.CrimeSubHeadID = cm.CrimeMinorHeadID
           JOIN Unit u ON u.UnitID = cm.PoliceStationID
           WHERE cm.CrimeRegisteredDate >= DATE_SUB(
             (SELECT MAX(CrimeRegisteredDate) FROM CaseMaster), INTERVAL 90 DAY)
             AND a.AccusedName IS NOT NULL
             AND a.AccusedName NOT IN ('Unknown Suspect', 'Suspect', 'Unknown', 'NA')
           GROUP BY a.AccusedName
           HAVING case_count >= 2
           ORDER BY case_count DESC
           LIMIT 20"""
    )


async def get_forecasting_summary() -> dict:
    """
    Combined forecasting dashboard data — all alerts in one call.
    """
    hotspots = await get_hotspot_alerts(threshold_pct=50.0)
    repeat_crimes = await get_repeat_crime_alerts(min_occurrences=3, days=90)
    gang_activity = await get_gang_activity_alerts()

    return {
        "hotspot_alerts": hotspots,
        "repeat_crime_alerts": repeat_crimes,
        "gang_activity_alerts": gang_activity,
        "total_alerts": len(hotspots) + len(repeat_crimes) + len(gang_activity),
    }
```

### Router: add to `backend/routers/analytics.py`

```python
from pipeline.crime_forecasting import (
    get_hotspot_alerts,
    get_repeat_crime_alerts,
    get_gang_activity_alerts,
    get_forecasting_summary,
)

@router.get("/api/analytics/forecasting/summary")
async def forecasting_summary(officer: dict = Depends(get_current_officer)):
    """Combined early warning dashboard."""
    return await get_forecasting_summary()

@router.get("/api/analytics/forecasting/hotspots")
async def forecasting_hotspots(
    threshold: float = Query(50.0, ge=10, le=500),
    officer: dict = Depends(get_current_officer),
):
    return {"alerts": await get_hotspot_alerts(threshold)}

@router.get("/api/analytics/forecasting/repeat-crimes")
async def forecasting_repeat_crimes(
    days: int = Query(90, ge=7, le=365),
    min_count: int = Query(3, ge=2, le=50),
    officer: dict = Depends(get_current_officer),
):
    return {"alerts": await get_repeat_crime_alerts(min_count, days)}

@router.get("/api/analytics/forecasting/gang-activity")
async def forecasting_gang_activity(officer: dict = Depends(get_current_officer)):
    return {"alerts": await get_gang_activity_alerts()}
```

### Frontend: Add a "Forecasting" section to AnalyticsDashboard.jsx

Add a new panel section after the demographics panels:
- **Hotspot Alerts** — table with station, change%, alert level (color-coded)
- **Repeat Crime Clusters** — table with crime type, station, count
- **Gang Activity** — table with accused name, case count, crime types, stations

### Frontend API: `frontend/src/api/analytics.js`

```javascript
export const fetchForecastingSummary = () => get('/forecasting/summary')
```

### Changes summary

| File | Change |
|------|--------|
| `backend/pipeline/crime_forecasting.py` | New file (~100 lines) |
| `backend/routers/analytics.py` | Add 4 endpoints (~20 lines) |
| `frontend/src/api/analytics.js` | Add 1 fetch function |
| `frontend/src/components/AnalyticsDashboard.jsx` | Add 3 alert panels |

### No new dependencies, no new tables, no new DDL.

### Testing

- Hotspot alerts: stations with >50% crime increase in recent quarter
- Repeat crimes: crime type + station combos with 3+ cases in 90 days
- Gang activity: accused appearing in 2+ cases in 90 days

### Effort: ~2 hours
