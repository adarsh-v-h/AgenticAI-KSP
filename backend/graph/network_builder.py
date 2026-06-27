"""
Builds vis.js-compatible network graphs.
Graph edges are DERIVED from official KSP schema (CaseMaster, Accused) —
no case_relationships table. This stays faithful to what KSP actually specified.
"""

from db.connection import execute_query


async def _fetch_co_accused_links(case_master_id: int) -> list[dict]:
    """Other accused in the SAME case — trivially co-accused."""
    return await execute_query(
        """SELECT a2.AccusedMasterID, a2.AccusedName
           FROM Accused a1
           JOIN Accused a2 ON a1.CaseMasterID = a2.CaseMasterID
             AND a1.AccusedMasterID != a2.AccusedMasterID
           WHERE a1.CaseMasterID = %s""",
        (case_master_id,)
    )


async def _fetch_repeat_appearances(accused_name: str) -> list[dict]:
    """Other cases featuring an accused with the same name."""
    return await execute_query(
        """SELECT cm.CaseMasterID, cm.CrimeNo, a.AccusedMasterID
           FROM Accused a
           JOIN CaseMaster cm ON cm.CaseMasterID = a.CaseMasterID
           WHERE a.AccusedName = %s""",
        (accused_name,)
    )


async def _fetch_similar_pattern_cases(crime_minor_head_id: int, police_station_id: int, case_master_id: int) -> list[dict]:
    """Cases with same crime type at same station — possible pattern link."""
    return await execute_query(
        """SELECT cm.CaseMasterID, cm.CrimeNo
           FROM CaseMaster cm
           WHERE cm.CrimeMinorHeadID = %s
             AND cm.PoliceStationID = %s
             AND cm.CaseMasterID != %s
           LIMIT 10""",
        (crime_minor_head_id, police_station_id, case_master_id)
    )


async def build_graph_for_fir(fir_id: int) -> dict:
    """
    Build a network graph centered on a case (CaseMasterID).
    Derives edges from:
      - co-accused (same CaseMasterID, different accused)
      - similar pattern (same CrimeMinorHeadID + PoliceStationID)
    """
    nodes = []
    edges = []

    # Central case node
    cases = await execute_query(
        """SELECT cm.CaseMasterID, cm.CrimeNo, csh.CrimeHeadName, cm.CrimeMinorHeadID, cm.PoliceStationID
           FROM CaseMaster cm
           LEFT JOIN CrimeSubHead csh ON csh.CrimeSubHeadID = cm.CrimeMinorHeadID
           WHERE cm.CaseMasterID = %s""",
        (fir_id,)
    )
    if not cases:
        return {"nodes": [], "edges": []}

    case = cases[0]
    nodes.append({
        "id": f"case_{fir_id}",
        "label": case["CrimeNo"] or f"Case {fir_id}",
        "type": "case",
        "title": case.get("CrimeHeadName") or "Unknown crime type"
    })

    # Accused nodes + edges
    accused_rows = await execute_query(
        "SELECT AccusedMasterID, AccusedName FROM Accused WHERE CaseMasterID = %s",
        (fir_id,)
    )
    for acc in accused_rows:
        node_id = f"accused_{acc['AccusedMasterID']}"
        nodes.append({
            "id": node_id,
            "label": acc["AccusedName"] or f"Accused {acc['AccusedMasterID']}",
            "type": "accused"
        })
        edges.append({
            "from": f"case_{fir_id}",
            "to": node_id,
            "label": "accused_in"
        })

    # Similar pattern cases
    if case.get("CrimeMinorHeadID") and case.get("PoliceStationID"):
        pattern_cases = await _fetch_similar_pattern_cases(
            case["CrimeMinorHeadID"], case["PoliceStationID"], fir_id
        )
        for pc in pattern_cases:
            p_node_id = f"case_{pc['CaseMasterID']}"
            if not any(n["id"] == p_node_id for n in nodes):
                nodes.append({
                    "id": p_node_id,
                    "label": pc["CrimeNo"] or f"Case {pc['CaseMasterID']}",
                    "type": "case",
                    "title": "Similar pattern"
                })
            edges.append({
                "from": f"case_{fir_id}",
                "to": p_node_id,
                "label": "similar_pattern"
            })

    return {"nodes": nodes, "edges": edges}


async def build_graph_for_accused(accused_id: int) -> dict:
    """
    Build a network graph centered on an accused person (AccusedMasterID).
    Derives edges from:
      - all cases the accused appears in
      - co-accused in those cases (repeat offender linkage)
    """
    nodes = []
    edges = []

    accused_rows = await execute_query(
        "SELECT AccusedMasterID, AccusedName, CaseMasterID FROM Accused WHERE AccusedMasterID = %s",
        (accused_id,)
    )
    if not accused_rows:
        return {"nodes": [], "edges": []}

    acc = accused_rows[0]
    center_id = f"accused_{accused_id}"
    nodes.append({
        "id": center_id,
        "label": acc["AccusedName"] or f"Accused {accused_id}",
        "type": "accused"
    })

    # All cases this accused appears in (by name, to catch repeat offenders)
    appearances = await _fetch_repeat_appearances(acc["AccusedName"])
    for ap in appearances:
        case_node_id = f"case_{ap['CaseMasterID']}"
        if not any(n["id"] == case_node_id for n in nodes):
            nodes.append({
                "id": case_node_id,
                "label": ap["CrimeNo"] or f"Case {ap['CaseMasterID']}",
                "type": "case"
            })
        edges.append({
            "from": center_id,
            "to": case_node_id,
            "label": "repeat_offender" if ap["CaseMasterID"] != acc["CaseMasterID"] else "accused_in"
        })

        # Co-accused in each case
        co_accused = await _fetch_co_accused_links(ap["CaseMasterID"])
        for co in co_accused:
            if co["AccusedMasterID"] == accused_id:
                continue
            co_node_id = f"accused_{co['AccusedMasterID']}"
            if not any(n["id"] == co_node_id for n in nodes):
                nodes.append({
                    "id": co_node_id,
                    "label": co["AccusedName"] or f"Accused {co['AccusedMasterID']}",
                    "type": "accused"
                })
            edges.append({
                "from": case_node_id,
                "to": co_node_id,
                "label": "co_accused"
            })

    return {"nodes": nodes, "edges": edges}
