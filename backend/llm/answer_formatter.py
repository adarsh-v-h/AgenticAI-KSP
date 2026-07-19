"""
Answer formatter — runs the raw query results through GLM-4.7-Flash to
produce a clean natural-language reply for the officer.
"""

import sys

from llm.client import call_llm, LLMError
from llm.prompts import (
    build_answer_prompt,
    build_router_prompt,
    build_direct_answer_prompt,
)

_RETRY_ROWS = 15
_RETRY_FIELD_CHARS = 80

_FOLLOW_UP_SYSTEM_PROMPT = (
    "You are an investigative assistant helping a police officer analyse case data."
)


# CONTRACT
# takes:  msg (str) — message to log
# returns: nothing
# raises:  nothing
def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# CONTRACT
# takes:  context_block (str) — the case/answer context the suggestions build on,
#          history_block (str) — pre-formatted "Conversation so far: ..." block (may be empty)
# returns: (list[str]) — up to 3 short follow-up question strings (empty list on any failure)
# raises:  nothing (best-effort — callers rely on it never breaking their flow)
async def generate_follow_ups(context_block: str, history_block: str = "") -> list[str]:
    """
    Single source of truth for "suggest 3 follow-up questions" generation, used
    by both the SQL pipeline (query_pipeline) and the RAG path (rag_session).
    Builds one consistent prompt, calls MODEL_ANSWER, and parses exactly 3
    lines. Never raises — returns [] if the LLM call or parsing fails.
    """
    try:
        prompt = (
            f"{history_block}"
            f"{context_block}\n\n"
            f"Suggest exactly 3 short follow-up questions an investigator "
            f"might ask next to deepen this line of inquiry. "
            f"Return only the 3 questions, one per line, no extra text."
        )
        raw = await call_llm(
            model_key="MODEL_ANSWER",
            prompt=prompt,
            system_prompt=_FOLLOW_UP_SYSTEM_PROMPT,
            max_tokens=1024,
        )
        return [line.strip("- ").strip() for line in raw.split("\n") if line.strip()][:3]
    except LLMError as e:
        _log(f"follow-up generation failed (non-fatal): {e}")
        return []
    except Exception as e:  # noqa: BLE001 — best-effort, never break the caller
        _log(f"follow-up generation unexpected error (non-fatal): {e}")
        return []


# CONTRACT
# takes:  question (str) — the user's natural-language question,
#          results (list[dict]) — raw rows from the DB query,
#          media_attachments (list[dict]) — resolved media references for the response,
#          history (list[dict] | None) — prior conversation turns for context
# returns: (str) — natural-language answer formatted from the query results
# raises:  LLMError — when the LLM call fails (non-payload-size errors)
async def format_answer(
    question: str,
    results: list[dict],
    media_attachments: list[dict],
    history: list[dict] | None,
) -> str:
    """
    Format raw DB query results into a natural-language answer.

    - Empty results: still call the LLM so it produces a clean
      "no records" response in the same voice as the rest.
    - More than 50 rows: only the first 50 are sent to the LLM (the prompt
      builder handles the truncation). table_data still carries the full set
      to the frontend.
    """
    system_prompt, user_prompt = build_answer_prompt(
        question=question,
        results=results,
        media_refs=media_attachments,
        history=history,
    )

    try:
        return await call_llm(
        model_key="MODEL_ANSWER",
        prompt=user_prompt,
        system_prompt=system_prompt,
        # max_tokens is the TOTAL budget (input + output) in QuickML. The
        # answer prompt embeds up to 50 rows of JSON results, which can run to
        # a few thousand input tokens, so this must be large enough to hold the
        # prompt PLUS the generated summary. 8000 comfortably covers both.
        max_tokens=8000,
    )
    except Exception as e:
        if "MORE_THAN_MAX_LENGTH" not in str(e):
            raise
        _log(f"answer formatter payload too large, retrying with smaller truncation: {e}")
        system_prompt, user_prompt = build_answer_prompt(
            question=question,
            results=results,
            media_refs=media_attachments,
            history=history,
            max_rows=_RETRY_ROWS,
            max_field_chars=_RETRY_FIELD_CHARS,
        )
        return await call_llm(
            model_key="MODEL_ANSWER",
            prompt=user_prompt,
            system_prompt=system_prompt,
            max_tokens=8000,
        )


# CONTRACT
# takes:  question (str) — the user's natural-language question,
#          history (list[dict] | None) — prior conversation turns for context,
#          has_recent_data (bool) — whether the session has recent query results available
# returns: (str) — routing decision, either "SQL" or "DIRECT"
# raises:  nothing (catches all exceptions, defaults to "SQL")
async def route_intent(
    question: str,
    history: list[dict] | None,
    has_recent_data: bool,
) -> str:
    """
    Classify whether `question` needs a new SQL query ("SQL") or can be answered
    directly from conversation/context ("DIRECT").

    Uses the 14B model with a tiny prompt for a fast, cheap decision. Never
    raises — on any failure it defaults to "SQL" so the pipeline behaves exactly
    as before when routing is unavailable.
    """
    try:
        system_prompt, user_prompt = build_router_prompt(
            question=question, history=history, has_recent_data=has_recent_data
        )
        raw = await call_llm(
            model_key="MODEL_ANSWER",
            prompt=user_prompt,
            system_prompt=system_prompt,
            # QuickML counts max_tokens as TOTAL budget (input + output). The
            # router prompt embeds a short history slice, so this must clear the
            # prompt length plus the one-word answer.
            max_tokens=2048,
        )
        decision = "DIRECT" if "DIRECT" in raw.strip().upper() else "SQL"
        _log(f"router decision: {decision} (raw: {raw.strip()[:40]!r})")
        return decision
    except Exception as e:
        _log(f"router failed (defaulting to SQL): {e}")
        return "SQL"


# CONTRACT
# takes:  question (str) — the user's natural-language question,
#          history (list[dict] | None) — prior conversation turns for context,
#          recent_table (list[dict] | None) — most recent query result rows for grounding
# returns: (str) — natural-language answer generated without running SQL
# raises:  LLMError — when the underlying LLM call fails
async def generate_direct_answer(
    question: str,
    history: list[dict] | None,
    recent_table: list[dict] | None,
) -> str:
    """
    Answer a question WITHOUT running SQL — used for follow-ups about
    already-retrieved data, requests for insight, and general questions.
    Bubbles LLMError up to the caller for fallback handling.
    """
    system_prompt, user_prompt = build_direct_answer_prompt(
        question=question, history=history, recent_table=recent_table
    )
    return await call_llm(
        model_key="MODEL_ANSWER",
        prompt=user_prompt,
        system_prompt=system_prompt,
        max_tokens=8000,
    )
