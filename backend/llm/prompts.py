"""
All system prompts and prompt builders used by the SQL and answer chains.
Keep prompts in one place so they're easy to tune in one pass.
"""

import json

SQL_SYSTEM_PROMPT = """You are an expert MySQL query writer for the Karnataka State Police secure crime database.
Your ONLY job is to write a valid MySQL SELECT query based on the user's question.

STRICT RULES:
1. Only write SELECT statements. NEVER write INSERT, UPDATE, DELETE, DROP, CREATE, ALTER, or TRUNCATE.
2. Only use tables and columns from the schema provided in the user message. Do NOT reference old tables like `fir_master`, `officers`, `cases_theft`, `cases_assault`, `case_relationships` etc.
3. Always use proper, explicit JOINs when querying case-related tables — they must be joined to CaseMaster on CaseMasterID.
4. Return ONLY the raw SQL query. No explanation. No markdown. No backticks around the whole query. No semicolon at the end.
5. If the question cannot be answered with the available schema, return exactly: CANNOT_ANSWER
6. Use LIMIT 50 on queries that could return many rows unless the user asks for all records or for a count/aggregate.
7. For name searches, use LIKE '%name%' to handle partial matches.
8. Always use table aliases for clarity in JOINs (e.g., `CaseMaster AS cm`).
9. The table name `Rank` is a MySQL reserved word — always escape it as `Rank` (with backticks) when selecting or joining on it.
10. Subqueries and CTEs are allowed and encouraged for set-based comparisons (e.g. `WITH ...`, `IN (SELECT ...)`).
11. Column values and casing in this database:
    - Table and column names must be exact PascalCase as in the schema (e.g. CaseMaster, AccusedName, etc.).
    - CaseStatusMaster.CaseStatusName values are: 'Open', 'Under Investigation', 'Charge Sheeted', 'Closed'.
    - Employee.role ENUM values are: 'investigator', 'analyst', 'supervisor', 'policymaker'.
12. Use `CrimeSubHead.CrimeHeadName` to filter by crime type (e.g., 'Theft', 'Murder', 'Assault'), not a raw case_type column.
13. Use a `LEFT JOIN ArrestSurrender` and filter `WHERE ArrestSurrender.ArrestSurrenderID IS NULL` to represent accused who are still at large (no arrest/surrender record exists).
14. When the user's question is a FOLLOW-UP that refines a previous turn, you MUST preserve the prior turn's filter clauses (the WHERE predicates and JOINs that scoped the previous result) and add the new refinement on top.
"""

ANSWER_SYSTEM_PROMPT = """You are a professional police intelligence assistant helping Karnataka State Police officers.
You receive raw database query results and must format them as a clear, concise, professional answer.

RULES:
1. Be direct and concise. Officers are busy.
2. NEVER format results as a markdown table. The structured rows are rendered separately by the UI as an HTML table — duplicating them in your prose creates visual clutter. Your reply MUST NOT contain any pipe-separated row lines (lines that start and end with `|`) and MUST NOT contain a `|---|` divider line. Instead, write a 1–2 sentence prose summary of the result set: total count, the most useful pattern (top category, common location, status mix), and any single-record highlight when relevant.
3. If media attachments exist, mention them: "This case has 2 attached photos and 1 video."
4. Never add information not present in the data.
5. Never speculate. If data is insufficient, say so clearly.
6. Use plain professional English. No technical jargon.
7. Refer to the database records naturally — say "case" not "row", "officer" not "record".
8. If zero results were returned, say clearly that no matching records were found.
9. Markdown lists, **bold**, and inline emphasis are fine for non-tabular prose. Do not use them to reconstruct a table.
"""

CORRECTION_SYSTEM_PROMPT = """You are an expert MySQL query writer.
The SQL query you previously generated had an error.
Your job is to fix it and return only the corrected SQL query.
No explanation. No markdown. No backticks around the whole query. Just the fixed SQL.
Pay attention to: column/table names that don't exist in the schema, ENUM literal casing (must be lowercase), reserved-word columns like `rank` (escape with backticks), and missing JOINs.
"""


def _format_history_for_prompt(
    history: list[dict],
    max_turns: int = 2,
    max_chars: int = 100,
) -> str:
    """
    Compress recent conversation history into a short context block.
    Each entry in `history` is expected to be a dict with at least a 'role'
    key ('user' or 'assistant') and a 'content' string.
    Returns "" if history is empty/None.

    Used by the answer formatter — it doesn't need prior SQL, just enough
    text to keep tone/coreference consistent.
    """
    if not history:
        return ""

    # Take the last `max_turns` user/assistant pairs.
    pairs = []
    last_user = None
    for turn in history:
        role = (turn.get("role") or "").lower()
        content = (turn.get("content") or "").strip()
        if not content:
            continue
        if role == "user":
            last_user = content
        elif role == "assistant" and last_user is not None:
            pairs.append((last_user, content))
            last_user = None

    if not pairs:
        return ""

    pairs = pairs[-max_turns:]
    lines = []
    for q, a in pairs:
        a_short = a[:max_chars] + ("…" if len(a) > max_chars else "")
        lines.append(f"Officer asked: {q}")
        lines.append(f"System answered about: {a_short}")
    return "\n".join(lines)


def _format_history_for_sql_prompt(
    history: list[dict],
    max_turns: int = 2,
    max_answer_chars: int = 240,
) -> str:
    """
    History block for the SQL generator. Includes the prior SQL when
    available so the model can preserve filter clauses on follow-up turns
    (Bug 3a). Falls back to the answer text only when no SQL was stored.
    """
    if not history:
        return ""

    pairs: list[tuple[str, str, str]] = []
    last_user = None
    for turn in history:
        role = (turn.get("role") or "").lower()
        content = (turn.get("content") or "").strip()
        if not content:
            continue
        if role == "user":
            last_user = content
        elif role == "assistant" and last_user is not None:
            sql = (turn.get("sql") or "").strip()
            pairs.append((last_user, content, sql))
            last_user = None

    if not pairs:
        return ""

    pairs = pairs[-max_turns:]
    lines: list[str] = []
    for q, a, sql in pairs:
        lines.append(f"Officer asked: {q}")
        a_short = a[:max_answer_chars] + ("…" if len(a) > max_answer_chars else "")
        lines.append(f"System answered: {a_short}")
        if sql:
            lines.append("SQL used previously:")
            lines.append(sql)
    return "\n".join(lines)


def _format_officer_for_prompt(officer: dict | None) -> str:
    """
    Build a short identity block describing the authenticated employee so the
    SQL generator can resolve first-person references ("I", "me", "my cases").

    Returns "" when no employee context is available.
    """
    if not officer:
        return ""
    employee_id = officer.get("EmployeeID") or officer.get("officer_id")
    if employee_id is None:
        return ""
    kgid = (officer.get("KGID") or officer.get("badge_number") or "").strip()
    name = (officer.get("FirstName") or officer.get("full_name") or "").strip()
    descriptor = ", ".join(p for p in (name, f"KGID {kgid}" if kgid else "") if p)
    who = f" ({descriptor})" if descriptor else ""
    return (
        "Current officer context:\n"
        f"The logged-in employee is EmployeeID = {employee_id}{who}.\n"
        "ONLY use this id when the question refers to the logged-in officer/employee in "
        "the FIRST PERSON (\"I\", \"me\", \"my\", \"cases I am handling\", "
        "\"assigned to me\"): filter on "
        f"CaseMaster.PolicePersonID = {employee_id} and never emit a "
        "placeholder like <current_employee_id>.\n"
        "If the question names a DIFFERENT person (e.g. \"cases handled by "
        "Harish Kumar\"), IGNORE this id and match that person by name instead "
        "(join Employee and filter e.FirstName LIKE '%name%')."
    )


def build_sql_prompt(
    question: str,
    schema: str,
    few_shots: str,
    history: list[dict] | None,
    officer: dict | None = None,
) -> tuple[str, str]:
    """
    Build (system_prompt, prompt) for the SQL generation LLM call.

    `officer`, when provided, carries the authenticated officer's identity
    (at least `officer_id`, optionally `badge_number`/`full_name`). It is
    injected so first-person questions like "cases I am handling" resolve to
    `investigating_officer_id = <officer_id>` instead of a literal placeholder.
    """
    history_block = _format_history_for_sql_prompt(history or [])
    officer_block = _format_officer_for_prompt(officer)
    # Keep system_prompt SHORT — 7B Coder 500s with large system prompts
    sys_p = SQL_SYSTEM_PROMPT  # no schema injection here

    parts = [f"DATABASE SCHEMA:\n{schema}\n", f"EXAMPLE QUERIES:\n{few_shots}\n"]
    if officer_block:
        parts.append(officer_block + "\n")
    if history_block:
        parts.append(
            "Previous context (use this to preserve filter clauses on follow-up questions):\n"
            f"{history_block}\n"
        )
        parts.append(f"Current question: {question}\n")
    else:
        parts.append(f"Question: {question}\n")
    parts.append("Write the MySQL SELECT query:")

    user_p = "\n".join(parts)
    return sys_p, user_p


def _truncate_for_answer(results: list[dict], max_rows: int = 50, max_field_chars: int = 200) -> list[dict]:
    """Trim results to `max_rows` rows and clip long string fields."""
    trimmed = []
    for row in results[:max_rows]:
        new_row = {}
        for k, v in row.items():
            if isinstance(v, str) and len(v) > max_field_chars:
                new_row[k] = v[:max_field_chars] + "…"
            else:
                new_row[k] = v
        trimmed.append(new_row)
    return trimmed


def _summarize_media(media_refs: list[dict]) -> str:
    if not media_refs:
        return "None"
    counts: dict[str, int] = {}
    for m in media_refs:
        t = m.get("media_type") or "unknown"
        counts[t] = counts.get(t, 0) + 1
    parts = [f"{n} {t}" for t, n in counts.items()]
    return f"{len(media_refs)} attachment(s): " + ", ".join(parts)


def build_answer_prompt(
    question: str,
    results: list[dict],
    media_refs: list[dict],
    history: list[dict] | None,
) -> tuple[str, str]:
    """
    Build (system_prompt, prompt) for the answer-formatting LLM call.
    """
    truncated = _truncate_for_answer(results)
    n_total = len(results)

    # Use default=str so dates/decimals serialize cleanly.
    try:
        results_json = json.dumps(truncated, indent=2, default=str)
    except Exception:
        results_json = str(truncated)

    media_summary = _summarize_media(media_refs or [])

    history_block = _format_history_for_prompt(history or [])
    history_part = f"Previous context:\n{history_block}\n\n" if history_block else ""

    user_p = (
        f"{history_part}"
        f"Officer's question: {question}\n\n"
        f"Query results ({n_total} record(s) found"
    )
    if n_total > len(truncated):
        user_p += f", showing first {len(truncated)}"
    user_p += "):\n"
    user_p += results_json + "\n\n"
    user_p += f"Media attachments: {media_summary}\n\n"
    user_p += (
        "Format a clear, professional answer for the officer. "
        "Remember: 1–2 sentence prose summary only — the rows are already "
        "displayed in a separate table by the UI, so do NOT include any "
        "markdown table (no `|`-separated rows, no `|---|` divider)."
    )

    return ANSWER_SYSTEM_PROMPT, user_p


def build_correction_prompt(
    original_sql: str,
    error: str,
    schema: str,
    officer: dict | None = None,
) -> tuple[str, str]:
    """
    Build (system_prompt, prompt) for the SQL correction call.
    """
    officer_block = _format_officer_for_prompt(officer)
    officer_part = f"{officer_block}\n\n" if officer_block else ""
    user_p = (
        "The following SQL query is invalid:\n"
        f"{original_sql}\n\n"
        f"Error: {error}\n\n"
        f"{officer_part}"
        "Schema for reference:\n"
        f"{schema}\n\n"
        "Write the corrected SQL query only."
    )
    return CORRECTION_SYSTEM_PROMPT, user_p


# --------------------------------------------------------------------------- #
# Intent routing + direct conversational answers
# --------------------------------------------------------------------------- #

ROUTER_SYSTEM_PROMPT = """You are a routing classifier for a Karnataka State Police crime-database assistant.
Decide whether the officer's latest message needs a NEW database query, or can be answered without one.

Reply with EXACTLY one word — either SQL or DIRECT. No punctuation, no explanation.

Choose SQL when the message asks for specific records, counts, lists, statistics, or any crime data that is NOT already present in the recent conversation.

Choose DIRECT when the message:
- refers to or asks about data already shown in the recent conversation. Referential words like "those", "them", "that", "these", "the ones", "it", "the third one", "the above" almost always mean the answer is already in context — choose DIRECT,
- asks to filter, sort, rank, count, or pick from results ALREADY shown (e.g. "which of those is open", "which is the oldest", "sort them by date") AND recent query results are available in context,
- asks for analysis, insight, or interpretation of already-retrieved results,
- is a greeting, thanks, or small talk,
- is a general question that does not require crime records.

Key rule: if recent query results ARE available in context and the message refers to them, choose DIRECT — do not re-query data the officer already has.

When there is no recent data in context and the message asks for crime data, choose SQL."""


DIRECT_ANSWER_SYSTEM_PROMPT = """You are a professional police intelligence assistant for Karnataka State Police officers.
Answer the officer's question using ONLY the recent conversation and any query results provided below.

RULES:
1. Be direct, concise, and professional. Officers are busy.
2. When recent query results are provided, base your answer strictly on that data — surface patterns, counts, notable records, and status mix that are actually present in the rows.
3. NEVER invent facts, numbers, trends, percentages, dates, or comparisons that are not directly present in the provided data or conversation. Do NOT say things like "a 15% increase from last month" unless that exact figure appears in the data. If the data is a single count or too thin to draw an insight from, simply state what the data shows and stop.
4. If the information needed is not in the conversation or the provided results, say so plainly and suggest the officer ask for it as a new query (e.g. "I don't have that detail — ask me to pull it and I'll query the database.").
5. NEVER output a markdown table (no `|`-separated rows, no `|---|` divider). The earlier results are already shown to the officer separately.
6. Use plain professional English. Markdown lists, **bold**, and inline emphasis are fine for prose.
7. For greetings or general questions, respond naturally and briefly."""


def build_router_prompt(
    question: str,
    history: list[dict] | None,
    has_recent_data: bool,
) -> tuple[str, str]:
    """
    Build (system_prompt, prompt) for the intent router classification call.
    Keeps context small so the decision is fast.
    """
    history_block = _format_history_for_prompt(history or [])
    parts = []
    if history_block:
        parts.append(f"Recent conversation:\n{history_block}\n")
    parts.append(
        f"Recent query results are available in context: "
        f"{'yes' if has_recent_data else 'no'}\n"
    )
    parts.append(f"Officer's latest message: {question}\n")
    parts.append("Answer with one word — SQL or DIRECT:")
    return ROUTER_SYSTEM_PROMPT, "\n".join(parts)


def build_direct_answer_prompt(
    question: str,
    history: list[dict] | None,
    recent_table: list[dict] | None,
) -> tuple[str, str]:
    """
    Build (system_prompt, prompt) for a direct conversational answer that skips
    SQL — used for follow-ups about already-retrieved data, requests for
    insight, and general questions. Includes a richer slice of history than the
    router plus the most recent query results when available.
    """
    history_block = _format_history_for_prompt(history or [], max_turns=4, max_chars=400)
    parts = []
    if history_block:
        parts.append(f"Recent conversation:\n{history_block}\n")
    if recent_table:
        truncated = _truncate_for_answer(recent_table, max_rows=30)
        try:
            rows_json = json.dumps(truncated, indent=2, default=str)
        except Exception:
            rows_json = str(truncated)
        parts.append(
            f"Most recent query results ({len(recent_table)} record(s)):\n{rows_json}\n"
        )
    parts.append(f"Officer's question: {question}\n")
    parts.append("Answer the question professionally:")
    return DIRECT_ANSWER_SYSTEM_PROMPT, "\n".join(parts)
