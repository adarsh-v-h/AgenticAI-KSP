"""
Sociological crime insights — demographic analysis of accused, victims,
and complainants. Pure SQL aggregation against existing demographic columns
(AgeYear, GenderID, OccupationID, ReligionID, CasteID).
"""
from db.connection import execute_query


# CONTRACT
# takes:  nothing
# returns: (list[dict]) — rows with age_group and count of accused persons
# raises:  Exception — when DB query fails
async def get_accused_age_distribution() -> list[dict]:
    """Accused persons bucketed by age group."""
    return await execute_query(
        """SELECT
             CASE
               WHEN AgeYear < 18 THEN 'Under 18'
               WHEN AgeYear BETWEEN 18 AND 25 THEN '18-25'
               WHEN AgeYear BETWEEN 26 AND 35 THEN '26-35'
               WHEN AgeYear BETWEEN 36 AND 50 THEN '36-50'
               WHEN AgeYear > 50 THEN 'Over 50'
               ELSE 'Unknown'
             END AS age_group,
             COUNT(*) AS count
           FROM Accused
           WHERE AgeYear IS NOT NULL
           GROUP BY age_group
           ORDER BY FIELD(age_group, 'Under 18', '18-25', '26-35', '36-50', 'Over 50', 'Unknown')"""
    )


# CONTRACT
# takes:  nothing
# returns: (list[dict]) — rows with crime_type, gender, and count
# raises:  Exception — when DB query fails
async def get_crime_by_gender() -> list[dict]:
    """Crime type breakdown by accused gender."""
    return await execute_query(
        """SELECT csh.CrimeHeadName AS crime_type,
                  CASE a.GenderID
                    WHEN 1 THEN 'Male'
                    WHEN 2 THEN 'Female'
                    ELSE 'Other'
                  END AS gender,
                  COUNT(*) AS count
           FROM Accused a
           JOIN CaseMaster cm ON cm.CaseMasterID = a.CaseMasterID
           JOIN CrimeSubHead csh ON csh.CrimeSubHeadID = cm.CrimeMinorHeadID
           WHERE a.GenderID IS NOT NULL
           GROUP BY csh.CrimeHeadName, a.GenderID
           ORDER BY count DESC"""
    )


# CONTRACT
# takes:  nothing
# returns: (list[dict]) — rows with crime_type, age_group, gender, and count for victims
# raises:  Exception — when DB query fails
async def get_victim_demographics() -> list[dict]:
    """Victim age/gender breakdown per crime type."""
    return await execute_query(
        """SELECT csh.CrimeHeadName AS crime_type,
                  CASE
                    WHEN v.AgeYear < 18 THEN 'Under 18'
                    WHEN v.AgeYear BETWEEN 18 AND 35 THEN '18-35'
                    WHEN v.AgeYear BETWEEN 36 AND 60 THEN '36-60'
                    WHEN v.AgeYear > 60 THEN 'Over 60'
                    ELSE 'Unknown'
                  END AS age_group,
                  CASE v.GenderID
                    WHEN 1 THEN 'Male'
                    WHEN 2 THEN 'Female'
                    ELSE 'Other'
                  END AS gender,
                  COUNT(*) AS count
           FROM Victim v
           JOIN CaseMaster cm ON cm.CaseMasterID = v.CaseMasterID
           JOIN CrimeSubHead csh ON csh.CrimeSubHeadID = cm.CrimeMinorHeadID
           WHERE v.AgeYear IS NOT NULL
           GROUP BY csh.CrimeHeadName, age_group, gender
           ORDER BY count DESC"""
    )


# CONTRACT
# takes:  limit (int) — max number of occupations to return
# returns: (list[dict]) — rows with occupation and count of complainants
# raises:  Exception — when DB query fails
async def get_crime_by_occupation(limit: int = 10) -> list[dict]:
    """Which occupations appear most frequently in complainant data."""
    return await execute_query(
        """SELECT om.OccupationName AS occupation, COUNT(*) AS count
           FROM ComplainantDetails cd
           JOIN OccupationMaster om ON om.OccupationID = cd.OccupationID
           GROUP BY om.OccupationName
           ORDER BY count DESC
           LIMIT %s""",
        (limit,)
    )


# CONTRACT
# takes:  nothing
# returns: (list[dict]) — rows with crime_type, age_group, gender, and count for accused
# raises:  Exception — when DB query fails
async def get_demographic_risk_profile() -> list[dict]:
    """Cross-tabulation: crime type × age group × gender for accused persons."""
    return await execute_query(
        """SELECT csh.CrimeHeadName AS crime_type,
                  CASE
                    WHEN a.AgeYear < 18 THEN 'Under 18'
                    WHEN a.AgeYear BETWEEN 18 AND 25 THEN '18-25'
                    WHEN a.AgeYear BETWEEN 26 AND 35 THEN '26-35'
                    WHEN a.AgeYear BETWEEN 36 AND 50 THEN '36-50'
                    WHEN a.AgeYear > 50 THEN 'Over 50'
                    ELSE 'Unknown'
                  END AS age_group,
                  CASE a.GenderID
                    WHEN 1 THEN 'Male'
                    WHEN 2 THEN 'Female'
                    ELSE 'Other'
                  END AS gender,
                  COUNT(*) AS count
           FROM Accused a
           JOIN CaseMaster cm ON cm.CaseMasterID = a.CaseMasterID
           JOIN CrimeSubHead csh ON csh.CrimeSubHeadID = cm.CrimeMinorHeadID
           WHERE a.AgeYear IS NOT NULL AND a.GenderID IS NOT NULL
           GROUP BY csh.CrimeHeadName, age_group, gender
           ORDER BY count DESC"""
    )
