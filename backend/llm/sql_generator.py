"""
SQL generation chain — runs the schema-aware SQL prompt through Qwen Coder
with a self-correction budget shared across the whole SQL chain.

Total LLM calls per turn are capped at MAX_ATTEMPTS=2 (initial + at most one
correction). The correction can be triggered by either:
  - validate_sql() failure on the initial SQL, or
  - a MySQL execution error on the initial SQL (driven from the pipeline via
    `correct_sql_after_execution_error`).
The pipeline tracks how many calls have been used so the two paths cannot
combined exceed the budget.
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
    officer: dict | None = None,
) -> tuple[str, int]:
    """
    Generate a valid SQL query for `question` using `table_names` as the
    candidate schema scope. Retries up to MAX_ATTEMPTS times — the second
    attempt is a correction call seeded with the validation error.

    Returns:
        (sanitized_sql, attempts_used) — `attempts_used` is the number of
        LLM calls this function consumed (1 if first attempt validated, 2 if
        a correction call was needed). The caller uses this to honour the
        shared MAX_ATTEMPTS budget when deciding whether to fire an
        execution-error correction.

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
                officer=officer,
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
            return cleaned, attempt

        last_sql = cleaned
        last_error = result.error or "Unknown validation error"
        _log(
            f"SQL generation attempt {attempt}/{MAX_ATTEMPTS}: failed — {last_error}"
        )

    raise SQLGenerationError(
        f"Could not generate a valid SQL query after {MAX_ATTEMPTS} attempts. "
        f"Last error: {last_error}"
    )


async def correct_sql_after_execution_error(
    original_sql: str,
    db_error: str,
    table_names: list[str],
    officer: dict | None = None,
) -> str:
    """
    Issue a single corrective LLM call after a MySQL execution error.

    The caller (query_pipeline) is responsible for honouring the shared
    MAX_ATTEMPTS budget; this helper performs exactly one LLM call, validates
    the output, and returns the cleaned SQL.

    Returns:
        Sanitized, validated SQL string ready for execute_query.

    Raises:
        SQLGenerationError: corrected SQL is empty / fails validation /
            is CANNOT_ANSWER.
        LLMError: underlying LLM API call itself failed.
    """
    schema = get_schema_for_tables(table_names)
    system_prompt, user_prompt = build_correction_prompt(
        original_sql=original_sql,
        error=db_error,
        schema=schema,
        officer=officer,
    )

    raw = await call_llm(
        model_key="MODEL_SQL",
        prompt=user_prompt,
        system_prompt=system_prompt,
        max_tokens=4000,
    )

    cleaned = sanitize_sql(raw)

    if cleaned.strip().upper() == "CANNOT_ANSWER":
        _log("SQL execution-error correction: CANNOT_ANSWER")
        raise SQLGenerationError("Model could not correct the failing query.")

    result = validate_sql(cleaned)
    if not result.is_valid:
        _log(
            f"SQL execution-error correction failed validation: {result.error}"
        )
        raise SQLGenerationError(
            f"Corrected SQL failed validation: {result.error}"
        )

    _log("SQL execution-error correction: success")
    return cleaned
