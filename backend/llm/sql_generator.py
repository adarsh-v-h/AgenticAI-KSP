"""
SQL generation chain — runs the schema-aware SQL prompt through Qwen Coder
with a two-attempt self-correction loop.
"""

import sys

from llm.client import call_llm, LLMError
from llm.prompts import build_sql_prompt, build_correction_prompt
from pipeline.sql_validator import validate_sql, sanitize_sql
from db.schema_catalog import get_schema_for_tables, get_few_shot_examples

MAX_ATTEMPTS = 2


class SQLGenerationError(Exception):
    """Raised when SQL cannot be generated after all retries."""
    pass


class CannotAnswerError(Exception):
    """Raised when the LLM signals the question cannot be answered from the DB."""
    pass


def _log(msg: str) -> None:
    """Single-channel logger so we don't sprinkle prints everywhere."""
    print(msg, file=sys.stderr, flush=True)


async def generate_sql(
    question: str,
    table_names: list[str],
    history: list[dict] | None,
) -> str:
    """
    Generate a valid SQL query for `question` using `table_names` as the
    candidate schema scope. Retries up to MAX_ATTEMPTS times — the second
    attempt is a correction call seeded with the validation error.

    Returns:
        Sanitized, validated SQL string ready for execute_query.

    Raises:
        CannotAnswerError: model returned the CANNOT_ANSWER sentinel.
        SQLGenerationError: validation failed on every attempt.
        LLMError: underlying LLM API call itself failed.
    """
    schema = get_schema_for_tables(table_names)
    few_shots = get_few_shot_examples(table_names)

    last_sql = ""
    last_error = ""

    for attempt in range(1, MAX_ATTEMPTS + 1):
        if attempt == 1:
            system_prompt, user_prompt = build_sql_prompt(
                question=question,
                schema=schema,
                few_shots=few_shots,
                history=history,
            )
        else:
            system_prompt, user_prompt = build_correction_prompt(
                original_sql=last_sql,
                error=last_error,
                schema=schema,
            )

        # Bubble LLMError up — those are infra failures, not retry-worthy here.
        raw = await call_llm(
            model_key="MODEL_SQL",
            prompt=user_prompt,
            system_prompt=system_prompt,
            max_tokens=4000,
        )

        cleaned = sanitize_sql(raw)

        if cleaned.strip().upper() == "CANNOT_ANSWER":
            _log(f"SQL generation attempt {attempt}/{MAX_ATTEMPTS}: CANNOT_ANSWER")
            raise CannotAnswerError(
                "The question cannot be answered from the available database schema."
            )

        result = validate_sql(cleaned)
        if result.is_valid:
            _log(f"SQL generation attempt {attempt}/{MAX_ATTEMPTS}: success")
            return cleaned

        last_sql = cleaned
        last_error = result.error or "Unknown validation error"
        _log(
            f"SQL generation attempt {attempt}/{MAX_ATTEMPTS}: failed — {last_error}"
        )

    raise SQLGenerationError(
        f"Could not generate a valid SQL query after {MAX_ATTEMPTS} attempts. "
        f"Last error: {last_error}"
    )
