"""
Rule-based case similarity finder.

Purpose: surface cases an officer investigating one case might NOT have
manually thought to cross-reference — same crime type + station clustering,
recency, and (most importantly) shared accused persons across cases that
otherwise look unrelated on the surface.

Similarity signals:
  - Same CrimeMinorHeadID (crime type): +40
  - Same PoliceStationID: +25
  - Filed within 90 days: +15
  - Shares an accused (name match across cases): +20
"""
from db.connection import execute_query


# CONTRACT
# takes:  case_master_id (int) — CaseMasterID of the source case, limit (int) — max results to return
# returns: (list[dict]) — similar cases ranked by match_score with match_reasons
# raises:  nothing (returns empty list on missing source case)
async def find_similar_cases(case_master_id: int, limit: int = 5) -> list[dict]:
    """
    Returns cases similar to `case_master_id`, ranked by match_score desc.
    Each result carries `match_reasons` so the officer sees WHY it surfaced —
    critical for trust: this must never look like an unexplained black box.
    """
    source_rows = await execute_query(
        "SELECT CrimeMinorHeadID, PoliceStationID, CrimeRegisteredDate "
        "FROM CaseMaster WHERE CaseMasterID = %s",
        (case_master_id,)
    )
    if not source_rows:
        return []
    source = source_rows[0]

    candidates = await execute_query(
        """SELECT cm.CaseMasterID, cm.CrimeNo, cm.PoliceStationID, cm.CrimeRegisteredDate
           FROM CaseMaster cm
           WHERE cm.CrimeMinorHeadID = %s AND cm.CaseMasterID != %s
           LIMIT 200""",
        (source["CrimeMinorHeadID"], case_master_id)
    )

    source_accused_rows = await execute_query(
        "SELECT AccusedName FROM Accused WHERE CaseMasterID = %s",
        (case_master_id,)
    )
    source_names = {r["AccusedName"] for r in source_accused_rows if r.get("AccusedName")}

    # Batch fetch accused names for all candidate cases in 1 query (eliminates N+1 query problem)
    candidate_ids = [c["CaseMasterID"] for c in candidates if c.get("CaseMasterID")]
    names_by_case: dict[int, set[str]] = {}
    if candidate_ids:
        placeholders = ",".join(["%s"] * len(candidate_ids))
        all_accused_rows = await execute_query(
            f"SELECT CaseMasterID, AccusedName FROM Accused WHERE CaseMasterID IN ({placeholders})",
            tuple(candidate_ids)
        )
        for r in all_accused_rows:
            cid = r.get("CaseMasterID")
            name = r.get("AccusedName")
            if cid and name:
                names_by_case.setdefault(cid, set()).add(name)

    results = []
    for c in candidates:
        score = 40  # same crime type, guaranteed by the WHERE clause above
        reasons = ["Same crime type"]

        if c["PoliceStationID"] == source["PoliceStationID"]:
            score += 25
            reasons.append("Same police station")

        if source.get("CrimeRegisteredDate") and c.get("CrimeRegisteredDate"):
            delta = abs((c["CrimeRegisteredDate"] - source["CrimeRegisteredDate"]).days)
            if delta <= 90:
                score += 15
                reasons.append("Filed within 90 days")

        cand_names = names_by_case.get(c["CaseMasterID"], set())
        shared = source_names & cand_names
        if shared:
            score += 20
            reasons.append(f"Shares accused: {', '.join(sorted(shared))}")

        results.append({
            "case_id": c["CaseMasterID"],
            "crime_no": c["CrimeNo"],
            "match_score": score,
            "match_reasons": reasons,
        })

    results.sort(key=lambda r: r["match_score"], reverse=True)
    return results[:limit]
