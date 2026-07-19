"""
Rule-based, explainable offender risk scoring.

Purpose: this is the "point at what may have gone wrong with this suspect"
feature -- instead of an officer manually recalling a person's history, the
score is computed from actual case data and comes with a factor breakdown,
so it's never an unexplained number. An officer can see exactly why someone
scored "critical" vs "low".

Note: prior_case_count and arrest_status are NOT stored columns in the
official KSP schema -- both are derived live:
  - prior case count = COUNT of Accused rows sharing the same AccusedName
    (identity-by-name is a known limitation of this schema -- no person-level
    ID beyond name matching; same caveat applies to similar_cases.py)
  - at-large status  = TRUE if NO row exists for this accused in
    ArrestSurrender
"""
import orjson
from datetime import date
from db.connection import execute_query, execute_write

WEIGHTS = {
    "prior_case_count": 30,
    "violent_crime_ratio": 25,
    "at_large_status": 15,
    "geographic_spread": 15,
    "recency": 15,
}

VIOLENT_CRIME_NAMES = ("Assault", "Murder", "Domestic Violence", "Robbery")


# CONTRACT
# takes:  accused_id (int) — AccusedMasterID to compute risk score for
# returns: (dict) — risk assessment with accused_id, risk_score, risk_tier, contributing_factors
# raises:  nothing (catches all exceptions internally, returns empty score)
async def compute_risk_for_accused(accused_id: int) -> dict:
    try:
        accused_rows = await execute_query(
            "SELECT AccusedName FROM Accused WHERE AccusedMasterID = %s",
            (accused_id,)
        )
        if not accused_rows:
            return _empty_score(accused_id)
        accused_name = accused_rows[0]["AccusedName"]

        case_rows = await execute_query(
            """SELECT cm.CaseMasterID, csh.CrimeHeadName, u.UnitName, cm.CrimeRegisteredDate
               FROM Accused a
               JOIN CaseMaster cm ON cm.CaseMasterID = a.CaseMasterID
               JOIN CrimeSubHead csh ON csh.CrimeSubHeadID = cm.CrimeMinorHeadID
               JOIN Unit u ON u.UnitID = cm.PoliceStationID
               WHERE a.AccusedName = %s""",
            (accused_name,)
        )

        total_cases = len(case_rows) or 1
        violent_count = sum(1 for r in case_rows if r["CrimeHeadName"] in VIOLENT_CRIME_NAMES)
        violent_ratio = violent_count / total_cases

        stations = {r["UnitName"] for r in case_rows if r["UnitName"]}
        geo_spread = len(stations)

        dates = [r["CrimeRegisteredDate"] for r in case_rows if r["CrimeRegisteredDate"]]
        most_recent = max(dates) if dates else None
        days_since = (date.today() - most_recent).days if most_recent else 9999

        case_ids = [r["CaseMasterID"] for r in case_rows]
        is_at_large = True
        if case_ids:
            placeholders = ",".join(["%s"] * len(case_ids))
            arrest_rows = await execute_query(
                f"""SELECT ar.ArrestSurrenderID
                    FROM ArrestSurrender ar
                    JOIN Accused a ON a.AccusedMasterID = ar.AccusedMasterID
                    WHERE a.AccusedName = %s AND ar.CaseMasterID IN ({placeholders})""",
                (accused_name, *case_ids)
            )
            is_at_large = len(arrest_rows) == 0

        prior_score = min(total_cases * 6, WEIGHTS["prior_case_count"])
        violent_score = round(violent_ratio * WEIGHTS["violent_crime_ratio"], 1)
        at_large_score = WEIGHTS["at_large_status"] if is_at_large else 0
        geo_score = min(geo_spread * 5, WEIGHTS["geographic_spread"])
        if days_since < 90:
            recency_score = WEIGHTS["recency"]
        elif days_since < 365:
            recency_score = round(WEIGHTS["recency"] * 0.55, 1)
        else:
            recency_score = round(WEIGHTS["recency"] * 0.15, 1)

        total_score = min(round(prior_score + violent_score + at_large_score + geo_score + recency_score, 1), 100.0)

        if total_score < 25:
            tier = "low"
        elif total_score < 50:
            tier = "medium"
        elif total_score < 75:
            tier = "high"
        else:
            tier = "critical"

        factors = sorted([
            {"factor": f"{total_cases} case(s) on record under this name", "points": prior_score},
            {"factor": f"{round(violent_ratio*100)}% of cases are violent offenses", "points": violent_score},
            {"factor": "No arrest/surrender record found (at large)" if is_at_large else "Has an arrest/surrender record on file", "points": at_large_score},
            {"factor": f"Cases span {geo_spread} distinct police station(s)", "points": geo_score},
            {"factor": f"Most recent case registered {days_since} days ago", "points": recency_score},
        ], key=lambda x: x["points"], reverse=True)

        return {
            "accused_id": accused_id,
            "risk_score": total_score,
            "risk_tier": tier,
            "contributing_factors": factors,
        }
    except Exception:
        return _empty_score(accused_id)


# CONTRACT
# takes:  accused_id (int) — AccusedMasterID for which no data was found
# returns: (dict) — zeroed-out risk score dict with empty factors
# raises:  nothing
def _empty_score(accused_id: int) -> dict:
    return {"accused_id": accused_id, "risk_score": 0.0, "risk_tier": "low", "contributing_factors": []}


# CONTRACT
# takes:  result (dict) — computed risk score dict with accused_id, risk_score, risk_tier, contributing_factors
# returns: nothing
# raises:  Exception — when DB write fails
async def save_risk_score(result: dict):
    await execute_write(
        """INSERT INTO offender_risk_scores (AccusedMasterID, risk_score, risk_tier, contributing_factors)
           VALUES (%s, %s, %s, %s)
           ON DUPLICATE KEY UPDATE
             risk_score = %s, risk_tier = %s, contributing_factors = %s, computed_at = NOW()""",
        (
            result["accused_id"], result["risk_score"], result["risk_tier"],
            orjson.dumps(result["contributing_factors"]).decode(),
            result["risk_score"], result["risk_tier"], orjson.dumps(result["contributing_factors"]).decode(),
        )
    )


# CONTRACT
# takes:  accused_id (int) — AccusedMasterID to look up cached score for
# returns: (dict | None) — cached risk score dict or None if not found
# raises:  Exception — when DB read fails
async def get_cached_risk_score(accused_id: int) -> dict | None:
    rows = await execute_query(
        "SELECT AccusedMasterID, risk_score, risk_tier, contributing_factors FROM offender_risk_scores WHERE AccusedMasterID = %s",
        (accused_id,)
    )
    if not rows:
        return None
    row = rows[0]
    return {
        "accused_id": row["AccusedMasterID"],
        "risk_score": float(row["risk_score"]),
        "risk_tier": row["risk_tier"],
        "contributing_factors": orjson.loads(row["contributing_factors"]) if row["contributing_factors"] else [],
    }


# CONTRACT
# takes:  nothing
# returns: (int) — count of accused persons whose risk scores were recomputed
# raises:  Exception — when DB operations fail
async def recompute_all_risk_scores() -> int:
    rows = await execute_query("SELECT DISTINCT AccusedMasterID FROM Accused")
    count = 0
    for row in rows:
        result = await compute_risk_for_accused(row["AccusedMasterID"])
        await save_risk_score(result)
        count += 1
    return count
