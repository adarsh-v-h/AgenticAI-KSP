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


# CONTRACT
# takes:  months_back (int) — number of months to look back from current date
# returns: (list[dict]) — rows with month (YYYY-MM) and count of crimes
# raises:  Exception — when DB query fails
async def get_trend_by_month(months_back: int = 12) -> list[dict]:
    """Crime count per month for the last `months_back` months."""
    return await execute_query(
        """SELECT DATE_FORMAT(CrimeRegisteredDate, '%%Y-%%m') AS month, COUNT(*) AS count
           FROM CaseMaster
           WHERE CrimeRegisteredDate >= DATE_SUB(CURDATE(), INTERVAL %s MONTH)
           GROUP BY month
           ORDER BY month ASC""",
        (months_back,)
    )


# CONTRACT
# takes:  nothing
# returns: (list[dict]) — rows with crime_type and count, ordered by count descending
# raises:  Exception — when DB query fails
async def get_trend_by_crime_type() -> list[dict]:
    """Total count per crime sub-head (the actual crime type), all time."""
    return await execute_query(
        """SELECT csh.CrimeHeadName AS crime_type, COUNT(*) AS count
           FROM CaseMaster cm
           JOIN CrimeSubHead csh ON csh.CrimeSubHeadID = cm.CrimeMinorHeadID
           GROUP BY csh.CrimeHeadName
           ORDER BY count DESC"""
    )


# CONTRACT
# takes:  limit (int) — maximum number of stations to return
# returns: (list[dict]) — rows with station name and crime count, ordered by count descending
# raises:  Exception — when DB query fails
async def get_trend_by_location(limit: int = 10) -> list[dict]:
    """Crime count per police station."""
    return await execute_query(
        """SELECT u.UnitID AS unit_id, u.UnitName AS station, COUNT(*) AS count
           FROM CaseMaster cm
           JOIN Unit u ON u.UnitID = cm.PoliceStationID
           GROUP BY u.UnitID, u.UnitName
           ORDER BY count DESC
           LIMIT %s""",
        (limit,)
    )


# CONTRACT
# takes:  station_unit_id (int) — UnitID of the police station to drill into
# returns: (list[dict]) — rows with crime_type and count for that station
# raises:  Exception — when DB query fails
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


# CONTRACT
# takes:  nothing
# returns: (list[dict]) — rows with status name and count of cases
# raises:  Exception — when DB query fails
async def get_status_breakdown() -> list[dict]:
    """Count of cases by investigation status."""
    return await execute_query(
        """SELECT csm.CaseStatusName AS status, COUNT(*) AS count
           FROM CaseMaster cm
           JOIN CaseStatusMaster csm ON csm.CaseStatusID = cm.CaseStatusID
           GROUP BY csm.CaseStatusName
           ORDER BY count DESC"""
    )


# CONTRACT
# takes:  min_occurrences (int) — minimum case count threshold for a cluster to be returned
# returns: (list[dict]) — rows with crime_type, station, and count for clusters meeting the threshold
# raises:  Exception — when DB query fails
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


# CONTRACT
# takes:  nothing
# returns: (list[dict]) — rows with month_num, month_name, and count of crimes per calendar month
# raises:  Exception — when DB query fails
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
