"""
Rule-based crime forecasting and early warning system.
Identifies emerging patterns from trend analysis — no ML models,
just heuristic thresholds applied to existing crime data.
"""
from db.connection import execute_query


# CONTRACT
# takes:  threshold_pct (float) — minimum percentage increase to trigger an alert (default 50%)
# returns: (list[dict]) — hotspot alerts with station, unit_id, counts, change_pct, alert_level
# raises:  Exception — when DB query fails
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


# CONTRACT
# takes:  min_occurrences (int) — minimum case count threshold, days (int) — lookback window
# returns: (list[dict]) — repeat crime alerts with crime_type, station, count
# raises:  Exception — when DB query fails
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


# CONTRACT
# takes:  nothing
# returns: (list[dict]) — gang activity alerts with accused_name, case_count, crime_types, stations
# raises:  Exception — when DB query fails
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


# CONTRACT
# takes:  nothing
# returns: (dict) — combined forecasting data with hotspot_alerts, repeat_crime_alerts, gang_activity_alerts, total_alerts
# raises:  Exception — when DB queries fail
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
