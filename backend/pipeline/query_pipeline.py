"""
Query pipeline — orchestrates the full NL2SQL chain end-to-end.

Order of operations:
  1. schema_linker.select_relevant_tables(question)
  2. sql_generator.generate_sql(question, tables, history)   [retry loop inside]
  3. db.connection.execute_query(sql)
       — on MySQL execution error, call
         sql_generator.correct_sql_after_execution_error(...) and re-execute,
         provided we still have budget under the shared MAX_ATTEMPTS=2 cap.
  4. media_resolver.resolve_media(results)
  5. graph_available probe (derived from Accused/CaseMaster â€” no case_relationships table)
  6. answer_formatter.format_answer(...)
  7. Return PipelineResponse (always — even on errors).
"""

import sys
import os
import time
from dataclasses import dataclass, field

from pipeline.rule_engine import try_rule_response
from pipeline.schema_linker import select_relevant_tables
from llm.rag_session import RagSession
from llm.sql_generator import (
    generate_sql,
    correct_sql_after_execution_error,
    SQLGenerationError,
    CannotAnswerError,
    MAX_ATTEMPTS,
)
from db.connection import execute_query
from pipeline.media_resolver import resolve_media, collect_case_master_ids
from llm.answer_formatter import format_answer, route_intent, generate_direct_answer, generate_follow_ups
from llm.client import LLMError



_kb_doc_ids_cache: list[str] | None = None
_kb_env_mtime: float = 0.0


# CONTRACT
# takes:  nothing
# returns: (list[str]) — KB document IDs loaded from .env, cached until file changes
# raises:  nothing
def _get_kb_document_ids() -> list[str]:
    """
    Dynamically load KB_DOCUMENT_IDS from .env. Re-reads the file if its
    mtime has changed, so kb_sync.py updates are picked up without a
    server restart.
    """
    global _kb_doc_ids_cache, _kb_env_mtime

    env_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        ".env",
    )
    try:
        current_mtime = os.path.getmtime(env_path)
    except OSError:
        current_mtime = 0.0

    if _kb_doc_ids_cache is not None and current_mtime == _kb_env_mtime:
        return _kb_doc_ids_cache

    # Re-read from .env
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=env_path, override=True)
    _kb_doc_ids_cache = [
        d.strip() for d in os.getenv("KB_DOCUMENT_IDS", "").split(",") if d.strip()
    ]
    _kb_env_mtime = current_mtime
    _log(f"Loaded {len(_kb_doc_ids_cache)} KB document IDs")
    return _kb_doc_ids_cache



# CONTRACT
# takes:  msg (str) — message to log
# returns: nothing
# raises:  nothing
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
    suggested_follow_ups: list[str] = field(default_factory=list)


# Generic "we couldn't run the query" message shown in place of any raw
# MySQL/exception details. Kept short so the streaming UI doesn't repeat
# itself too much; the answer-formatter explainer is the longer fallback
# in `answer_text`.
_GENERIC_DB_ERROR = "I couldn't run that query. Try rephrasing."


# CONTRACT
# takes:  results (list[dict]) — query result rows to check
# returns: (bool) — True if the first result row contains a CaseMasterID key
# raises:  nothing
def _has_case_master_id(results: list[dict]) -> bool:
    if not results:
        return False
    first = results[0]
    return isinstance(first, dict) and ("CaseMasterID" in first or "case_master_id" in first)


# CONTRACT
# takes:  case_master_ids (list[int]) — list of CaseMasterIDs to check
# returns: (bool) — True if any case IDs are present (graph derivable on demand)
# raises:  nothing
async def _check_graph_available(case_master_ids: list[int]) -> bool:
    return bool(case_master_ids)


# CONTRACT
# takes:  history (list[dict]) — conversation history turns
# returns: (list[dict]) — the table snapshot from the most recent assistant turn, or []
# raises:  nothing
def _most_recent_table(history: list[dict]) -> list[dict]:
    """
    Return the most recent assistant turn's stored table snapshot, or [].
    Walks history newest-first so a follow-up can be answered from the last
    result set without re-querying the database.
    """
    return next(
        (turn["table"] for turn in reversed(history or [])
         if (turn.get("role") or "").lower() == "assistant"
         and isinstance(turn.get("table"), list) and turn.get("table")),
        []
    )


# CONTRACT
# takes:  question (str) — user question, history (list[dict]) — conversation history, recent_table (list[dict]) — last result set
# returns: (PipelineResponse) — answer generated without SQL, with error handling
# raises:  nothing (never raises, errors surfaced in response fields)
async def _run_direct(
    question: str, history: list[dict], recent_table: list[dict]
) -> PipelineResponse:
    """
    Answer without SQL — for follow-ups about already-retrieved data, requests
    for insight, and general questions. On LLM failure, returns a friendly
    error response (never raises).
    """
    response = PipelineResponse()
    try:
        response.answer_text = await generate_direct_answer(
            question=question, history=history, recent_table=recent_table
        )
    except LLMError as e:
        _log(f"direct answer LLM error: {e}")
        response.error = "The assistant is unavailable right now."
        response.answer_text = (
            "I'm unable to answer that right now. Please try again in a moment."
        )
    except Exception as e:
        _log(f"direct answer unexpected error: {e}")
        response.error = "Internal error while answering."
        response.answer_text = "Something went wrong. Please try again."
    return response


# CONTRACT
# takes:  question (str) — user question, history (list[dict] | None) — conversation history, officer (dict | None) — authenticated officer JWT payload
# returns: (PipelineResponse) — full pipeline result with answer, table data, media, graph flag
# raises:  nothing (never raises, all failures surfaced via error/answer_text fields)
async def run_pipeline(
    question: str, history: list[dict] | None = None, officer: dict | None = None
) -> PipelineResponse:
    """
    Run the full pipeline. This function never raises — every failure path
    fills `error` (and a user-friendly `answer_text`) on the response.

    `officer`, when provided, carries the authenticated officer's JWT payload
    (EmployeeID, KGID) so first-person questions ("cases I am handling")
    resolve to the correct PolicePersonID.
    """
    history = history or []
    start = time.monotonic()
    response = PipelineResponse()

    # --- Rule engine: intercept trivial messages before any LLM call ---
    rule_answer = try_rule_response(question)
    if rule_answer is not None:
        response.answer_text = rule_answer
        return response

    # --- FIX 1: narrative-intent keyword pre-router ---
    # SQL generation can almost always produce SOME valid query, so
    # CannotAnswerError rarely fires for narrative/summarization questions.
    # Catch these by keyword before SQL is even attempted.
    NARRATIVE_KEYWORDS = (
        "summarize", "summarise", "narrative", "describe how",
        "what do the case reports say", "typically occur",
        "in their own words",
    )
    if any(kw in question.lower() for kw in NARRATIVE_KEYWORDS):
        _log("Narrative keyword detected -- routing directly to RAG")
        try:
            rag_session = RagSession(document_ids=_get_kb_document_ids(), history=history)
            rag_result = await rag_session.ask(question)
        except Exception as e:
            _log(f"Narrative-keyword RAG attempt failed: {e}")
            rag_result = {"grounded": False}
        if rag_result.get("grounded"):
            response.answer_text = rag_result["response"]
            response.suggested_follow_ups = rag_result.get("suggested_follow_ups", [])
            return response
        _log("Narrative-keyword RAG ungrounded -- continuing to normal SQL flow")
    # --- END FIX 1 ---

    # 0. Intent routing — decide whether this turn needs a NEW SQL query or can
    #    be answered directly from conversation + the most recent result set.
    #    Optimization: only route when there IS prior context to refer back to.
    #    On a brand-new chat (no history) there's nothing to answer "directly"
    #    from, so we skip the extra router LLM call and go straight to SQL;
    #    greetings / general first messages still fall back via CANNOT_ANSWER.
    #    Falls back to SQL on any router failure (see route_intent).
    recent_table = _most_recent_table(history)
    if history:
        decision = await route_intent(
            question=question, history=history, has_recent_data=bool(recent_table)
        )
        if decision == "DIRECT":
            direct = await _run_direct(question, history, recent_table)
            elapsed = time.monotonic() - start
            _log(f"Pipeline completed in {elapsed:.1f}s — DIRECT (no SQL)")
            return direct

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

    # 2. SQL generation (with retry loop). attempts_used counts toward the
    #    shared MAX_ATTEMPTS budget; if the initial generation already burned
    #    a correction call (validation failure → corrected), we won't fire a
    #    second correction on execution failure.
    try:
        sql, attempts_used = await generate_sql(
            question=question, table_names=tables, history=history, officer=officer
        )
    except CannotAnswerError:
        # The DB can't answer this - try RAG grounding first (analytical /
        # entity questions), fall back to DIRECT only if RAG is also ungrounded.
        _log("SQL chain returned CANNOT_ANSWER -- trying RAG before DIRECT fallback")
        try:
            rag_session = RagSession(document_ids=_get_kb_document_ids(), history=history)
            rag_result = await rag_session.ask(question)
        except Exception as e:
            _log(f"RAG fallback attempt failed: {e}")
            rag_result = {"grounded": False}

        if rag_result.get("grounded"):
            elapsed = time.monotonic() - start
            _log(f"Pipeline completed in {elapsed:.1f}s -- RAG (CANNOT_ANSWER fallback)")
            response.answer_text = rag_result["response"]
            response.suggested_follow_ups = rag_result.get("suggested_follow_ups", [])
            return response

        _log("RAG also ungrounded -- falling back to DIRECT answer")
        direct = await _run_direct(question, history, recent_table)
        elapsed = time.monotonic() - start
        _log(f"Pipeline completed in {elapsed:.1f}s —  DIRECT (CANNOT_ANSWER fallback)")
        return direct
    except SQLGenerationError as e:
        _log(f"sql generation failed: {e}")
        response.error = "Could not generate a valid query for this question."
        response.answer_text = (
            "I couldn't translate that into a valid database query. "
            "Try rephrasing —  for example, ask about a specific case type, "
            "a person, or a date range."
        )
        return response
    except LLMError as e:
        _log(f"sql generation LLM error: {e} -- trying RAG before hard failure")
        try:
            rag_session = RagSession(document_ids=_get_kb_document_ids(), history=history)
            rag_result = await rag_session.ask(question)
        except Exception as rag_e:
            _log(f"RAG fallback attempt failed: {rag_e}")
            rag_result = {"grounded": False}

        if rag_result.get("grounded"):
            elapsed = time.monotonic() - start
            _log(f"Pipeline completed in {elapsed:.1f}s -- RAG (LLMError fallback)")
            response.answer_text = rag_result["response"]
            response.suggested_follow_ups = rag_result.get("suggested_follow_ups", [])
            return response

        _log(f"sql generation LLM error, RAG also ungrounded: {e}")
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

    # 3. Execute SQL — with one corrective retry on MySQL exceptions, but only
    #    if we still have budget under the MAX_ATTEMPTS=2 cap.
    results = None
    try:
        results = await execute_query(sql)
    except Exception as exec_err:
        # Always log the full exception (including raw MySQL tuple) for ops.
        _log(f"db execute_query failed (attempt 1): {exec_err!r}")

        if attempts_used >= MAX_ATTEMPTS:
            # No budget left — surface a clean, scrubbed message.
            _log(
                "Skipping execution-error correction: SQL chain budget "
                f"exhausted (attempts_used={attempts_used})."
            )
            response.error = _GENERIC_DB_ERROR
            response.answer_text = _GENERIC_DB_ERROR
            return response

        # Try one corrective LLM call.
        try:
            corrected_sql = await correct_sql_after_execution_error(
                original_sql=sql,
                db_error=str(exec_err),
                table_names=tables,
                officer=officer,
            )
        except SQLGenerationError as ce:
            _log(f"execution-error correction failed: {ce}")
            response.error = _GENERIC_DB_ERROR
            response.answer_text = _GENERIC_DB_ERROR
            return response
        except LLMError as ce:
            _log(f"execution-error correction LLM error: {ce}")
            response.error = _GENERIC_DB_ERROR
            response.answer_text = _GENERIC_DB_ERROR
            return response
        except Exception as ce:
            _log(f"execution-error correction unexpected error: {ce!r}")
            response.error = _GENERIC_DB_ERROR
            response.answer_text = _GENERIC_DB_ERROR
            return response

        response.sql_generated = corrected_sql

        try:
            results = await execute_query(corrected_sql)
        except Exception as retry_err:
            _log(f"db execute_query failed (attempt 2 / corrected): {retry_err!r}")
            response.error = _GENERIC_DB_ERROR
            response.answer_text = _GENERIC_DB_ERROR
            return response

    response.table_data = results

    # --- FIX 2: empty-results RAG fallback ---
    # SQL can execute successfully but return 0 rows for a question that
    # DOES have an answer in the narrative case reports (e.g. "stolen
    # vehicles" -- no such column, so SQL returns nothing even though the
    # RAG knowledge base has matching narratives). Try RAG before accepting
    # an empty result as final.
    if not results:
        _log("SQL returned 0 rows -- trying RAG before accepting empty result")
        try:
            rag_session = RagSession(document_ids=_get_kb_document_ids(), history=history)
            rag_result = await rag_session.ask(question)
        except Exception as e:
            import traceback
            _log(f"Empty-results RAG attempt failed: {type(e).__name__}: {e!r}")
            _log(traceback.format_exc())
            rag_result = {"grounded": False}
        if rag_result.get("grounded"):
            response.answer_text = rag_result["response"]
            response.suggested_follow_ups = rag_result.get("suggested_follow_ups", [])
            return response
        _log("Empty-results RAG also ungrounded -- proceeding with empty SQL result")
    # --- END FIX 2 ---

    # 4. Media resolver — only if results carry a CaseMasterID column
    media: list[dict] = []
    case_master_ids: list[int] = []
    if results and _has_case_master_id(results):
        case_master_ids = collect_case_master_ids(results)
        try:
            media = await resolve_media(results)
        except Exception as e:
            _log(f"media_resolver failed (non-fatal): {e}")
            media = []

    response.media_attachments = media

    # 5. Graph availability — edges are derived live from Accused/CaseMaster on demand.
    if case_master_ids:
        response.graph_available = await _check_graph_available(case_master_ids)

    # 6. Answer formatter — never let a formatter failure kill the pipeline
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

    # 7. Suggested follow-ups -- best-effort; never fails the pipeline.
    recent_turns = history[-5:] if history else []
    history_block = ""
    if recent_turns:
        history_lines = "\n".join(
            f"{t.get('role', '?')}: {t.get('content', '')}" for t in recent_turns
        )
        history_block = f"Conversation so far:\n{history_lines}\n\n"

    response.suggested_follow_ups = await generate_follow_ups(
        context_block=f"Question: {question}\nAnswer: {response.answer_text}",
        history_block=history_block,
    )

    elapsed = time.monotonic() - start
    _log(
        f"Pipeline completed in {elapsed:.1f}s — tables: {tables}, "
        f"rows: {len(results)}"
    )
    return response


