"""
Intelligence Ticker — Station situational awareness text, pre-computed at startup
and refreshed every 2 hours. Each entry is a single AI-narrated sentence tuned
for the login-screen ticker display.

Cache keys:
  int  unit_id           → investigator/analyst text for that station
  str  "sup_{unit_id}"   → supervisor text (cross-sub-station summary)
  str  "policymaker"     → statewide snapshot (all policymakers share this)
"""

import sys
from datetime import datetime

_ticker_cache: dict = {}  # keyed as described above


def _log(msg: str) -> None:
    print(f"[intelligence_ticker] {msg}", file=sys.stderr, flush=True)


# CONTRACT
# takes:  unit_id (int) — station unit ID, role (str) — officer role
# returns: (str | None) — pre-built ticker sentence, or None if cache miss
# raises:  nothing
def get_ticker(unit_id: int | None, role: str) -> str | None:
    """Return the cached ticker sentence for the given officer context."""
    try:
        if role == "policymaker":
            return _ticker_cache.get("policymaker")
        if role == "supervisor" and unit_id is not None:
            return _ticker_cache.get(f"sup_{unit_id}")
        if unit_id is not None:
            return _ticker_cache.get(int(unit_id))
    except Exception:
        pass
    return None


# CONTRACT
# takes:  nothing
# returns: nothing (populates _ticker_cache in-place)
# raises:  nothing (all errors are logged, never propagated)
async def build_intelligence_cache() -> None:
    """
    Query the DB for per-station/supervisor/policymaker intelligence data,
    then call the LLM once per entry to narrate it into a single-sentence
    ticker string. Results are stored in _ticker_cache.

    Designed to run at startup and every 2 hours thereafter (via main.py).
    Never raises — errors are logged and the cache is left unchanged for
    that entry so the frontend falls back gracefully to no ticker.
    """
    _log("Starting intelligence cache build…")
    try:
        from db.connection import execute_query
        from llm.client import call_llm
        from db.lookup_cache import get_descendant_units_mem
    except Exception as e:
        _log(f"Import error during cache build: {e}")
        return

    # ── 1. Investigator/Analyst: most recent case per station ────────────────
    try:
        station_rows = await execute_query(
            """
            SELECT cm.PoliceStationID AS UnitID, cm.CrimeNo, cs.CrimeHeadName, cm.CrimeRegisteredDate AS DateOfRegistration,
                   LEFT(cm.BriefFacts, 160) AS BriefFacts,
                   u.UnitName
            FROM CaseMaster cm
            JOIN CrimeSubHead cs ON cm.CrimeMinorHeadID = cs.CrimeSubHeadID
            JOIN Unit u ON u.UnitID = cm.PoliceStationID
            WHERE cm.CaseMasterID IN (
                SELECT MAX(cm2.CaseMasterID)
                FROM CaseMaster cm2
                GROUP BY cm2.PoliceStationID
            )
            ORDER BY cm.PoliceStationID
            """
        )
    except Exception as e:
        _log(f"Station query failed: {e}")
        station_rows = []

    for row in station_rows:
        unit_id = row.get("UnitID")
        if unit_id is None:
            continue
        date_str = _fmt_date(row.get("DateOfRegistration"))
        prompt = (
            f"Station: {row.get('UnitName', 'Unknown')}.\n"
            f"Most recent FIR: {row.get('CrimeNo', 'N/A')} — {row.get('CrimeHeadName', 'Unknown crime')}, "
            f"registered {date_str}.\n"
            f"Brief facts: {row.get('BriefFacts', 'No details.')}\n"
            "Write ONE ticker sentence (max 18 words). Police audience. Lead with the critical fact. No markdown."
        )
        text = await _call_ticker_llm(call_llm, prompt)
        if text:
            _ticker_cache[int(unit_id)] = text

    _log(f"Investigator cache: {len(station_rows)} stations processed")

    # ── 2. Supervisor: cross-sub-station open count + most recent case ────────
    try:
        all_units = await execute_query("SELECT DISTINCT UnitID FROM Employee WHERE role = 'supervisor' AND UnitID IS NOT NULL")
        supervisor_unit_ids = [r["UnitID"] for r in all_units if r.get("UnitID")]
    except Exception as e:
        _log(f"Supervisor unit query failed: {e}")
        supervisor_unit_ids = []

    for sup_unit in supervisor_unit_ids:
        try:
            descendant_ids = list(get_descendant_units_mem(int(sup_unit)))
            if not descendant_ids:
                descendant_ids = [int(sup_unit)]
            placeholders = ",".join(["%s"] * len(descendant_ids))

            # Open case count across sub-stations
            count_rows = await execute_query(
                f"""
                SELECT COUNT(*) AS open_count, COUNT(DISTINCT cm.PoliceStationID) AS station_count
                FROM CaseMaster cm
                JOIN CaseStatusMaster csm ON cm.CaseStatusID = csm.CaseStatusID
                WHERE cm.PoliceStationID IN ({placeholders})
                  AND csm.CaseStatusName IN ('Open', 'Under Investigation')
                """,
                tuple(descendant_ids),
            )
            open_count = count_rows[0]["open_count"] if count_rows else 0
            station_count = count_rows[0]["station_count"] if count_rows else 0

            # Most recent case across sub-stations
            recent_rows = await execute_query(
                f"""
                SELECT cm.CrimeNo, cs.CrimeHeadName, u.UnitName, cm.CrimeRegisteredDate AS DateOfRegistration
                FROM CaseMaster cm
                JOIN CrimeSubHead cs ON cm.CrimeMinorHeadID = cs.CrimeSubHeadID
                JOIN Unit u ON u.UnitID = cm.PoliceStationID
                WHERE cm.PoliceStationID IN ({placeholders})
                ORDER BY cm.CrimeRegisteredDate DESC, cm.CaseMasterID DESC
                LIMIT 1
                """,
                tuple(descendant_ids),
            )

            sup_unit_name_rows = await execute_query(
                "SELECT UnitName FROM Unit WHERE UnitID = %s", (int(sup_unit),)
            )
            sup_unit_name = sup_unit_name_rows[0]["UnitName"] if sup_unit_name_rows else f"Unit {sup_unit}"

            recent = recent_rows[0] if recent_rows else {}
            date_str = _fmt_date(recent.get("DateOfRegistration"))
            prompt = (
                f"Command: {sup_unit_name}.\n"
                f"{open_count} open/active cases across {station_count} sub-station(s).\n"
                f"Most recent FIR: {recent.get('CrimeNo', 'N/A')} — {recent.get('CrimeHeadName', 'Unknown')}, "
                f"at {recent.get('UnitName', 'unknown station')}, registered {date_str}.\n"
                "Write ONE ticker sentence (max 18 words). Police supervisory audience. No markdown."
            )
            text = await _call_ticker_llm(call_llm, prompt)
            if text:
                _ticker_cache[f"sup_{sup_unit}"] = text
        except Exception as e:
            _log(f"Supervisor ticker build failed for unit {sup_unit}: {e}")

    _log(f"Supervisor cache: {len(supervisor_unit_ids)} supervisor units processed")

    # ── 3. Policymaker: statewide 30-day snapshot ─────────────────────────────
    try:
        policy_rows = await execute_query(
            """
            SELECT COUNT(*) AS total_cases FROM CaseMaster
            WHERE CrimeRegisteredDate >= DATE_SUB(NOW(), INTERVAL 30 DAY)
            """
        )
        total_cases = policy_rows[0]["total_cases"] if policy_rows else 0

        top_crime_rows = await execute_query(
            """
            SELECT cs.CrimeHeadName, COUNT(*) AS cnt
            FROM CaseMaster cm
            JOIN CrimeSubHead cs ON cm.CrimeMinorHeadID = cs.CrimeSubHeadID
            WHERE cm.CrimeRegisteredDate >= DATE_SUB(NOW(), INTERVAL 30 DAY)
            GROUP BY cs.CrimeHeadName
            ORDER BY cnt DESC LIMIT 1
            """
        )
        top_crime = top_crime_rows[0]["CrimeHeadName"] if top_crime_rows else "Unknown"
        top_crime_count = top_crime_rows[0]["cnt"] if top_crime_rows else 0

        top_district_rows = await execute_query(
            """
            SELECT u.UnitName, COUNT(*) AS cnt
            FROM CaseMaster cm
            JOIN Unit u ON cm.PoliceStationID = u.UnitID
            WHERE cm.CrimeRegisteredDate >= DATE_SUB(NOW(), INTERVAL 30 DAY)
            GROUP BY u.UnitID, u.UnitName
            ORDER BY cnt DESC LIMIT 1
            """
        )
        top_district = top_district_rows[0]["UnitName"] if top_district_rows else "Unknown"

        prompt = (
            f"Karnataka State Police — statewide summary (past 30 days).\n"
            f"Total cases registered: {total_cases}.\n"
            f"Top crime type: {top_crime} ({top_crime_count} cases).\n"
            f"Highest-activity station: {top_district}.\n"
            "Write ONE ticker sentence (max 18 words). Senior police leadership audience. No markdown."
        )
        text = await _call_ticker_llm(call_llm, prompt)
        if text:
            _ticker_cache["policymaker"] = text
    except Exception as e:
        _log(f"Policymaker ticker build failed: {e}")

    _log("Intelligence cache build complete.")


def _fmt_date(val) -> str:
    """Format a date value (string, datetime.date, or datetime) into a readable string."""
    if val is None:
        return "unknown date"
    if isinstance(val, str):
        try:
            return datetime.fromisoformat(val).strftime("%d %b %Y")
        except Exception:
            return val
    try:
        return val.strftime("%d %b %Y")
    except Exception:
        return str(val)


async def _call_ticker_llm(call_llm, prompt: str) -> str | None:
    """Call the LLM with the ticker system prompt and user prompt. Returns None on failure."""
    _TICKER_SYSTEM = (
        "You are a police intelligence briefing assistant. "
        "You write a single sentence (max 18 words) for a police dashboard ticker. "
        "No markdown. No speculation. Start with the critical fact. "
        "Do NOT include FIR numbers directly — mention crime type and station instead."
    )
    try:
        raw = await call_llm(
            model_key="MODEL_ANSWER",
            prompt=prompt,
            system_prompt=_TICKER_SYSTEM,
            max_tokens=512,
        )
        # Strip leading/trailing whitespace and quotes
        text = raw.strip().strip('"').strip("'").strip()
        return text if text else None
    except Exception as e:
        _log(f"LLM ticker call failed: {e}")
        return None
