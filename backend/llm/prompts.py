"""
All system prompts and prompt builders used by the SQL and answer chains.
Keep prompts in one place so they're easy to tune in one pass.
"""

import json

SQL_SYSTEM_PROMPT = """You are an expert MySQL query writer for the Karnataka State Police crime database.
Your ONLY job is to write a valid MySQL SELECT query based on the user's question.

STRICT RULES:
1. Only write SELECT statements. NEVER write INSERT, UPDATE, DELETE, DROP, CREATE, ALTER, or TRUNCATE.
2. Only use tables and columns from the schema provided in the user message.
3. Always use proper JOINs when querying case-type tables — they must be joined with fir_master on fir_id.
4. Return ONLY the raw SQL query. No explanation. No markdown. No backticks around the whole query. No semicolon at the end.
5. If the question cannot be answered with the available schema, return exactly: CANNOT_ANSWER
6. Use LIMIT 50 on queries that could return many rows unless the user asks for all records or for a count/aggregate.
7. For name searches, use LIKE '%name%' to handle partial matches.
8. Always use table aliases for clarity in JOINs.
9. The column `rank` in the officers table is a MySQL reserved word — always escape it as `rank` (with backticks) when selecting or filtering on it.
10. Subqueries are allowed and encouraged when they make the query clearer or more accurate. You MAY use:
    - `WHERE col IN (SELECT ...)` and `WHERE col NOT IN (SELECT ...)`
    - Nested SELECTs in the FROM or WHERE clause
    - Common Table Expressions: `WITH name AS (SELECT ...) SELECT ... FROM name`
    - `EXISTS (SELECT ...)` predicates
    Use these when the question asks about things like "accused who appear in more than one FIR" or other set-based comparisons.
11. ENUM column values in this database are stored in LOWERCASE. Always use lowercase literals when filtering on ENUM columns. Examples:
    - case_type IN ('theft','robbery','assault','murder','fraud','cybercrime','missing_person','vehicle_theft','drug_offense','domestic_violence','other')
    - status IN ('open','under_investigation','closed','chargesheeted')
    - arrest_status IN ('arrested','at_large','unknown')
    - gender IN ('male','female','other','unknown')
    Never write 'Robbery' or 'Open' — those will match zero rows.
12. When the user's question is a FOLLOW-UP that refines a previous turn (e.g., "show only the robbery ones", "now filter to closed cases", "just the open ones"), you MUST preserve the prior turn's filter clauses (the WHERE predicates and JOINs that scoped the previous result) and add the new refinement on top. Drop a prior filter only when the user explicitly asks to broaden or replace it. The "Previous context" block in the user message includes the SQL used in the prior turn — start from that filter set.
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
    Build a short identity block describing the authenticated officer so the
    SQL generator can resolve first-person references ("I", "me", "my cases").

    Returns "" when no officer context is available (keeps the prompt clean and
    preserves the previous behaviour for callers that don't pass an officer).
    """
    if not officer:
        return ""
    officer_id = officer.get("officer_id")
    if officer_id is None:
        return ""
    badge = (officer.get("badge_number") or "").strip()
    name = (officer.get("full_name") or "").strip()
    descriptor = ", ".join(p for p in (name, f"badge {badge}" if badge else "") if p)
    who = f" ({descriptor})" if descriptor else ""
    return (
        "Current officer context:\n"
        f"The logged-in officer is officer_id = {officer_id}{who}.\n"
        "ONLY use this id when the question refers to the logged-in officer in "
        "the FIRST PERSON (\"I\", \"me\", \"my\", \"cases I am handling\", "
        "\"assigned to me\"): filter on "
        f"fir_master.investigating_officer_id = {officer_id} and never emit a "
        "placeholder like <current_officer_id>.\n"
        "If the question names a DIFFERENT person (e.g. \"cases handled by "
        "Harish Kumar\"), IGNORE this id and match that person by name instead "
        "(join officers and filter o.full_name LIKE '%name%')."
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
