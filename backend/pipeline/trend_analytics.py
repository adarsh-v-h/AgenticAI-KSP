"""
Crime pattern and trend analytics — pure SQL aggregation, no LLM involved in
computing the numbers. The LLM (if used at all) only narrates results that
are already correct, which sidesteps the NL2SQL robustness problem entirely
for this feature.

get_modus_operandi_clusters() is the key "wider thinking" primitive: it
surfaces repeated crime-type + station patterns an officer working a single
case wouldn't see just by looking at their own case file.
"""
from db.connection import execute_query


async def get_trend_by_month(months_back: int = 12) -> list[dict]:
    """Crime count per month for the last `months_back` months."""
    return await execute_query(
        """SELECT DATE_FORMAT(CrimeRegisteredDate, '%Y-%m') AS month, COUNT(*) AS count
           FROM CaseMaster
           WHERE CrimeRegisteredDate >= DATE_SUB(CURDATE(), INTERVAL %s MONTH)
           GROUP BY month
           ORDER BY month ASC""",
        (months_back,)
    )


async def get_trend_by_crime_type() -> list[dict]:
    """Total count per crime sub-head (the actual crime type), all time."""
    return await execute_query(
        """SELECT csh.CrimeHeadName AS crime_type, COUNT(*) AS count
           FROM CaseMaster cm
           JOIN CrimeSubHead csh ON csh.CrimeSubHeadID = cm.CrimeMinorHeadID
           GROUP BY csh.CrimeHeadName
           ORDER BY count DESC"""
    )


async def get_trend_by_location(limit: int = 10) -> list[dict]:
    """Crime count per police station."""
    return await execute_query(
        """SELECT u.UnitName AS station, COUNT(*) AS count
           FROM CaseMaster cm
           JOIN Unit u ON u.UnitID = cm.PoliceStationID
           GROUP BY u.UnitName
           ORDER BY count DESC
           LIMIT %s""",
        (limit,)
    )


async def get_crime_type_by_location(station_unit_id: int) -> list[dict]:
    """Breakdown of crime types within a single police station — for drill-down."""
    return await execute_query(
        """SELECT csh.CrimeHeadName AS crime_type, COUNT(*) AS count
           FROM CaseMaster cm
           JOIN CrimeSubHead csh ON csh.CrimeSubHeadID = cm.CrimeMinorHeadID
           WHERE cm.PoliceStationID = %s
           GROUP BY csh.CrimeHeadName
           ORDER BY count DESC""",
        (station_unit_id,)
    )


async def get_status_breakdown() -> list[dict]:
    """Count of cases by investigation status."""
    return await execute_query(
        """SELECT csm.CaseStatusName AS status, COUNT(*) AS count
           FROM CaseMaster cm
           JOIN CaseStatusMaster csm ON csm.CaseStatusID = cm.CaseStatusID
           GROUP BY csm.CaseStatusName
           ORDER BY count DESC"""
    )


async def get_modus_operandi_clusters(min_occurrences: int = 2) -> list[dict]:
    """
    Groups cases by SAME crime sub-head AND SAME police station, surfacing
    repeated patterns at a given station. This is the "the officer may not
    have thought this case connects to a wider pattern" feature — a cluster
    of 6 thefts at one station with the same MO is a lead in itself, even
    with zero shared accused.
    Only returns groups with count >= min_occurrences.
    """
    return await execute_query(
        """SELECT csh.CrimeHeadName AS crime_type, u.UnitName AS station, COUNT(*) AS count
           FROM CaseMaster cm
           JOIN CrimeSubHead csh ON csh.CrimeSubHeadID = cm.CrimeMinorHeadID
           JOIN Unit u ON u.UnitID = cm.PoliceStationID
           GROUP BY csh.CrimeHeadName, u.UnitName
           HAVING count >= %s
           ORDER BY count DESC""",
        (min_occurrences,)
    )


async def get_seasonal_pattern() -> list[dict]:
    """Crime count grouped by month-of-year, irrespective of which year."""
    return await execute_query(
        """SELECT MONTH(CrimeRegisteredDate) AS month_num,
                  MONTHNAME(CrimeRegisteredDate) AS month_name,
                  COUNT(*) AS count
           FROM CaseMaster
           GROUP BY month_num, month_name
           ORDER BY month_num ASC"""
    )
