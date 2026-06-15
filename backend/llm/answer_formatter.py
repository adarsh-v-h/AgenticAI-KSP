"""
Answer formatter — runs the raw query results through Qwen 14B Instruct to
produce a clean natural-language reply for the officer.
"""

from llm.client import call_llm  # LLMError bubbles up from call_llm
from llm.prompts import build_answer_prompt


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
