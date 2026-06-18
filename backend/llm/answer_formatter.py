"""
Answer formatter — runs the raw query results through Qwen 14B Instruct to
produce a clean natural-language reply for the officer.
"""

import sys

from llm.client import call_llm
from llm.prompts import (
    build_answer_prompt,
    build_router_prompt,
    build_direct_answer_prompt,
)


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


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
