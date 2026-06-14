"""
Query pipeline — orchestrates the full NL2SQL chain end-to-end.

Order of operations:
  1. schema_linker.select_relevant_tables(question)
  2. sql_generator.generate_sql(question, tables, history)   [retry loop inside]
  3. db.connection.execute_query(sql)
  4. media_resolver.resolve_media(results)
  5. graph_available probe (single COUNT against case_relationships)
  6. answer_formatter.format_answer(...)
  7. Return PipelineResponse (always — even on errors).
"""

import sys
import time
from dataclasses import dataclass, field

from pipeline.schema_linker import select_relevant_tables
from llm.sql_generator import generate_sql, SQLGenerationError, CannotAnswerError
from db.connection import execute_query
from pipeline.media_resolver import resolve_media
from llm.answer_formatter import format_answer
from llm.client import LLMError


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


@dataclass
class PipelineResponse:
    answer_text: str = ""
    table_data: list[dict] = field(default_factory=list)
    media_attachments: list[dict] = field(default_factory=list)
    sql_generated: str = ""
    graph_available: bool = False
    error: str | None = None


def _has_fir_id(results: list[dict]) -> bool:
    if not results:
        return False
    first = results[0]
    return isinstance(first, dict) and "fir_id" in first


def _collect_fir_ids(results: list[dict]) -> list[int]:
    seen: set[int] = set()
    out: list[int] = []
    for row in results:
        if not isinstance(row, dict):
            continue
        v = row.get("fir_id")
        if v is None:
            continue
        try:
            iv = int(v)
        except (ValueError, TypeError):
            continue
        if iv in seen:
            continue
        seen.add(iv)
        out.append(iv)
    return out


async def _check_graph_available(fir_ids: list[int]) -> bool:
    if not fir_ids:
        return False
    placeholders = ",".join(["%s"] * len(fir_ids))
    sql = (
        "SELECT COUNT(*) AS c FROM case_relationships "
        f"WHERE (entity_a_type = 'fir' AND entity_a_id IN ({placeholders})) "
        f"   OR (entity_b_type = 'fir' AND entity_b_id IN ({placeholders}))"
    )
    try:
        rows = await execute_query(sql, tuple(fir_ids) + tuple(fir_ids))
        if not rows:
            return False
        count = rows[0].get("c") or rows[0].get("COUNT(*)") or 0
        return int(count) > 0
    except Exception as e:
        _log(f"graph availability check failed: {e}")
        return False


async def run_pipeline(
    question: str, history: list[dict] | None = None
) -> PipelineResponse:
    """
    Run the full pipeline. This function never raises — every failure path
    fills `error` (and a user-friendly `answer_text`) on the response.
    """
    history = history or []
    start = time.monotonic()
    response = PipelineResponse()

    # 1. Schema linker
    try:
        tables = select_relevant_tables(question)
    except Exception as e:
        _log(f"schema_linker failed: {e}")
        response.error = "Internal error while analyzing the question."
        response.answer_text = (
            "I couldn't analyze that question. Please try rephrasing it."
        )
        return response

    # 2. SQL generation (with retry loop)
    try:
        sql = await generate_sql(
            question=question, table_names=tables, history=history
        )
    except CannotAnswerError:
        elapsed = time.monotonic() - start
        _log(
            f"Pipeline completed in {elapsed:.1f}s — tables: {tables}, "
            f"rows: 0 (CANNOT_ANSWER)"
        )
        response.answer_text = (
            "I can't answer that question from the available crime database. "
            "Please rephrase or ask about FIRs, accused persons, victims, "
            "officers, or specific case details."
        )
        return response
    except SQLGenerationError as e:
        _log(f"sql generation failed: {e}")
        response.error = "Could not generate a valid query for this question."
        response.answer_text = (
            "I couldn't translate that into a valid database query. "
            "Try rephrasing — for example, ask about a specific case type, "
            "a person, or a date range."
        )
        return response
    except LLMError as e:
        _log(f"sql generation LLM error: {e}")
        response.error = "The SQL generation service is unavailable."
        response.answer_text = (
            "The SQL generation service is unavailable right now. Please try again."
        )
        return response
    except Exception as e:
        _log(f"sql generation unexpected error: {e}")
        response.error = "Internal error during SQL generation."
        response.answer_text = "Something went wrong generating the query."
        return response

    response.sql_generated = sql

    # 3. Execute SQL
    try:
        results = await execute_query(sql)
    except Exception as e:
        _log(f"db execute_query failed: {e}")
        response.error = f"Database query failed: {e}"
        response.answer_text = (
            "The database couldn't run that query. It may be malformed — please "
            "rephrase your question."
        )
        return response

    response.table_data = results

    # 4. Media resolver — only if results carry a fir_id column
    media: list[dict] = []
    fir_ids: list[int] = []
    if results and _has_fir_id(results):
        fir_ids = _collect_fir_ids(results)
        try:
            media = await resolve_media(results)
        except Exception as e:
            _log(f"media_resolver failed (non-fatal): {e}")
            media = []

    response.media_attachments = media

    # 5. Graph availability probe
    if fir_ids:
        response.graph_available = await _check_graph_available(fir_ids)

    # 6. Answer formatter — never let a formatter failure kill the pipeline
    try:
        response.answer_text = await format_answer(
            question=question,
            results=results,
            media_attachments=media,
            history=history,
        )
    except LLMError as e:
        _log(f"answer formatter LLM error (using fallback): {e}")
        response.answer_text = (
            f"Query completed. Found {len(results)} record"
            f"{'s' if len(results) != 1 else ''}."
        )
    except Exception as e:
        _log(f"answer formatter unexpected error (using fallback): {e}")
        response.answer_text = (
            f"Query completed. Found {len(results)} record"
            f"{'s' if len(results) != 1 else ''}."
        )

    elapsed = time.monotonic() - start
    _log(
        f"Pipeline completed in {elapsed:.1f}s — tables: {tables}, "
        f"rows: {len(results)}"
    )
    return response
