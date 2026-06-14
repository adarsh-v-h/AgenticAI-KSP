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
"""

ANSWER_SYSTEM_PROMPT = """You are a professional police intelligence assistant helping Karnataka State Police officers.
You receive raw database query results and must format them as a clear, concise, professional answer.

RULES:
1. Be direct and concise. Officers are busy.
2. If results have multiple rows, format them as a clean markdown table.
3. If media attachments exist, mention them: "This case has 2 attached photos and 1 video."
4. Never add information not present in the data.
5. Never speculate. If data is insufficient, say so clearly.
6. Use plain professional English. No technical jargon.
7. Refer to the database records naturally — say "case" not "row", "officer" not "record".
8. If zero results were returned, say clearly that no matching records were found.
"""

CORRECTION_SYSTEM_PROMPT = """You are an expert MySQL query writer.
The SQL query you previously generated had an error.
Your job is to fix it and return only the corrected SQL query.
No explanation. No markdown. No backticks around the whole query. Just the fixed SQL.
"""


def _format_history_for_prompt(history: list[dict], max_turns: int = 2) -> str:
    """
    Compress recent conversation history into a short context block.
    Each entry in `history` is expected to be a dict with at least a 'role'
    key ('user' or 'assistant') and a 'content' string.
    Returns "" if history is empty/None.
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
        a_short = a[:100] + ("…" if len(a) > 100 else "")
        lines.append(f"Officer asked: {q}")
        lines.append(f"System answered about: {a_short}")
    return "\n".join(lines)


def build_sql_prompt(
    question: str,
    schema: str,
    few_shots: str,
    history: list[dict] | None,
) -> tuple[str, str]:
    """
    Build (system_prompt, prompt) for the SQL generation LLM call.
    """
    history_block = _format_history_for_prompt(history or [])
    # Keep system_prompt SHORT — 7B Coder 500s with large system prompts
    sys_p = SQL_SYSTEM_PROMPT  # no schema injection here
    if history_block:
        user_p = (
            f"DATABASE SCHEMA:\n{schema}\n\n"
            f"EXAMPLE QUERIES:\n{few_shots}\n\n"
            "Previous context:\n"
            f"{history_block}\n\n"
            f"Current question: {question}\n\n"
            "Write the MySQL SELECT query:"
        )
    else:
        user_p = (
            f"DATABASE SCHEMA:\n{schema}\n\n"
            f"EXAMPLE QUERIES:\n{few_shots}\n\n"
            f"Question: {question}\n\n"
            "Write the MySQL SELECT query:"
        )

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
    user_p += "Format a clear, professional answer for the officer."

    return ANSWER_SYSTEM_PROMPT, user_p


def build_correction_prompt(
    original_sql: str,
    error: str,
    schema: str,
) -> tuple[str, str]:
    """
    Build (system_prompt, prompt) for the SQL correction call.
    """
    user_p = (
        "The following SQL query is invalid:\n"
        f"{original_sql}\n\n"
        f"Error: {error}\n\n"
        "Schema for reference:\n"
        f"{schema}\n\n"
        "Write the corrected SQL query only."
    )
    return CORRECTION_SYSTEM_PROMPT, user_p
