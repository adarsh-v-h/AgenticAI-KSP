"""
LLM-generated case brief -- a short investigative summary of a single case,
built from structured CaseMaster/Accused/Victim facts. Uses MODEL_ANSWER via
the same call_llm() interface every other LLM call in the codebase already
uses -- no new model, no new plumbing.
"""
from db.connection import execute_query
from llm.client import call_llm, LLMError
from llm.prompts import build_case_summary_prompt


# CONTRACT
# takes:  case_master_id (int) — CaseMasterID of the case to summarize
# returns: (dict) — {"summary": str, "error": None} on success, or {"summary": None, "error": str} on failure
# raises:  nothing (never raises, errors surfaced in return dict)
async def generate_case_summary(case_master_id: int) -> dict:
    """
    Returns {"summary": str, "error": None} on success, or
    {"summary": None, "error": str} on any failure.
    """
    case_rows = await execute_query(
        """SELECT cm.CrimeNo, cm.CrimeRegisteredDate, cm.BriefFacts,
                  csh.CrimeHeadName, csm.CaseStatusName, u.UnitName
           FROM CaseMaster cm
           JOIN CrimeSubHead csh ON csh.CrimeSubHeadID = cm.CrimeMinorHeadID
           JOIN CaseStatusMaster csm ON csm.CaseStatusID = cm.CaseStatusID
           JOIN Unit u ON u.UnitID = cm.PoliceStationID
           WHERE cm.CaseMasterID = %s""",
        (case_master_id,)
    )
    if not case_rows:
        return {"summary": None, "error": "Case not found"}
    case_row = case_rows[0]

    accused_rows = await execute_query(
        "SELECT AccusedName, AgeYear FROM Accused WHERE CaseMasterID = %s",
        (case_master_id,)
    )
    victim_rows = await execute_query(
        "SELECT VictimName, AgeYear FROM Victim WHERE CaseMasterID = %s",
        (case_master_id,)
    )

    system_prompt, user_prompt = build_case_summary_prompt(case_row, accused_rows, victim_rows)

    try:
        summary = await call_llm("MODEL_ANSWER", user_prompt, system_prompt, max_tokens=4000)
        return {"summary": summary.strip(), "error": None}
    except LLMError:
        return {"summary": None, "error": "Summary generation is temporarily unavailable"}
