"""
Query pipeline —  orchestrates the full NL2SQL chain end-to-end.

Order of operations:
  1. schema_linker.select_relevant_tables(question)
  2. sql_generator.generate_sql(question, tables, history)   [retry loop inside]
  3. db.connection.execute_query(sql)
       —  on MySQL execution error, call
         sql_generator.correct_sql_after_execution_error(...) and re-execute,
         provided we still have budget under the shared MAX_ATTEMPTS=2 cap.
  4. media_resolver.resolve_media(results)
  5. graph_available probe (derived from Accused/CaseMaster — no case_relationships table)
  6. answer_formatter.format_answer(...)
  7. Return PipelineResponse (always —  even on errors).
"""

import sys
import os
import time
import re
import hashlib
import json
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
from pipeline.station_scope import enforce_station_scope, StationScopeError
from auth.role_guard import ScopeResolutionError
from pipeline.date_utils import extract_date_predicate, rewrite_date_predicate
from llm.answer_formatter import format_answer, route_intent, generate_direct_answer, generate_follow_ups
from llm.client import LLMError


class PipelineCache:
    def __init__(self, capacity=500, ttl_seconds=300):
        from collections import OrderedDict
        self._cache = OrderedDict()
        self._capacity = capacity
        self._ttl = ttl_seconds

    def get(self, key):
        if key not in self._cache:
            return None
        value, timestamp = self._cache[key]
        if time.monotonic() - timestamp > self._ttl:
            del self._cache[key]
            return None
        self._cache.move_to_end(key)
        return value

    def put(self, key, value):
        if key in self._cache:
            del self._cache[key]
        elif len(self._cache) >= self._capacity:
            self._cache.popitem(last=False)
        self._cache[key] = (value, time.monotonic())  # Use monotonic clock to avoid system clock changes

_pipeline_cache = PipelineCache(capacity=1000, ttl_seconds=300)


def get_pipeline_cache_key(question: str, history: list[dict] | None, officer: dict | None) -> str:
    q_part = question.strip().lower()
    hist_part = ""
    if history:
        clean_hist = [{"role": h.get("role"), "content": h.get("content")} for h in history if isinstance(h, dict)]
        hist_part = json.dumps(clean_hist, sort_keys=True)
    off_part = ""
    if officer:
        off_part = f"{officer.get('unit_id')}-{officer.get('role')}"
    combined = f"{q_part}|||{hist_part}|||{off_part}"
    return hashlib.md5(combined.encode("utf-8")).hexdigest()


# Load KB document IDs once eagerly at module load time to avoid sync file operations on request path.
_kb_doc_ids_cache = [
    d.strip() for d in os.getenv("KB_DOCUMENT_IDS", "").split(",") if d.strip()
]

def _get_kb_document_ids() -> list[str]:
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
    assumptions: list[str] = field(default_factory=list)


_GENERIC_DB_ERROR = "I couldn't run that query. Try rephrasing."
_COMPARISON_KEYWORDS = ("compare", " vs ", " versus ", "comparison", "difference between")

# Placeholder names that DB operators enter when the accused is unidentified.
# Stripping these from frequency-ranking results prevents misleading "Suspect" tops.
_ACCUSED_PLACEHOLDERS: frozenset[str] = frozenset({
    "suspect", "unknown suspect", "unknown", "unidentified",
    "not known", "na", "n/a", "unidentified person", "unknown person",
})


# CONTRACT
# takes:  results (list[dict]) — raw query results
# returns: (list[dict]) — results with placeholder accused names removed, if this looks like an accused-frequency query
# raises:  nothing
def _strip_placeholder_accused(results: list[dict]) -> list[dict]:
    """
    If the result set contains an 'AccusedName' column alongside a count/
    frequency column (e.g. case_count), remove rows where the accused name is
    a generic placeholder. This ensures the UI table only shows real identities.
    """
    if not results:
        return results
    keys = {k.lower() for k in results[0].keys()}
    if "accusedname" not in keys:
        return results
    # Only strip when this is clearly a frequency/count query (has a count column)
    count_cols = {"case_count", "count", "total", "num_cases", "incident_count", "crime_count"}
    if not (keys & count_cols):
        return results
    return [
        row for row in results
        if str(row.get("AccusedName") or "").strip().lower() not in _ACCUSED_PLACEHOLDERS
    ]


def _is_cross_station_comparison(question: str) -> bool:
    """
    Rule 6: Intercept cross-station comparisons requested by restricted officers.
    Triggers ONLY when comparing across different stations/units.
    Does NOT trigger for comparisons of crime types, dates, or demographics within a single station.
    """
    if not question:
        return False
    q_lower = question.lower()

    cross_phrases = (
        "compare stations", "compare police stations", "compare units",
        "station comparison", "unit comparison", "across stations",
        "between stations", "across units", "between units",
        "station vs station", "unit vs unit", "ps vs ps"
    )
    if any(phrase in q_lower for phrase in cross_phrases):
        return True

    has_cmp = any(kw in q_lower for kw in _COMPARISON_KEYWORDS)
    if not has_cmp:
        return False

    if any(fp in q_lower for fp in ("my station", "assigned to me", "in my unit", "at my station", "my ps")):
        return False

    ps_matches = re.findall(r"\b[A-Za-z0-9_-]+\s+(?:ps|police station|unit)\b", q_lower)
    if len(ps_matches) >= 2:
        return True

    return False


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
    return next(
        (turn["table"] for turn in reversed(history or [])
         if (turn.get("role") or "").lower() == "assistant"
         and isinstance(turn.get("table"), list) and turn.get("table")),
        []
    )


# CONTRACT
# takes:  question (str) — user question, history (list[dict]) — conversation history, recent_table (list[dict]) — last result set
# returns: (PipelineResponse) — answer generated without SQL, with error handling
# raises:  nothing
async def _run_direct(
    question: str, history: list[dict], recent_table: list[dict]
) -> PipelineResponse:
    response = PipelineResponse()
    try:
        response.answer_text = await generate_direct_answer(
            question=question, history=history, recent_table=recent_table
        )
    except LLMError as e:
        _log(f"generate_direct_answer LLM error: {e}")
        response.error = "The conversation service is temporarily unavailable."
        response.answer_text = (
            "I couldn't generate an answer right now. Please try again in a moment."
        )
        return response
    except Exception as e:
        _log(f"generate_direct_answer unexpected error: {e}")
        response.error = "Internal error generating answer."
        response.answer_text = "Something went wrong. Please try rephrasing."
        return response

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
    return response


# CONTRACT
# takes:  sql (str) — original SQL query with date predicate, officer (dict | None) — officer context, question (str) — natural language question
# returns: (tuple[list[dict] | None, str | None, str | None]) — (retry_results, rewritten_sql, date_adjustment_note) or (None, None, None) on failure
# raises:  nothing (fallback on any error)
async def _retry_with_latest_date(sql: str, officer: dict | None, question: str = "") -> tuple[list[dict] | None, str | None, str | None]:
    """Rule 7 date fallback retry logic."""
    date_pred = extract_date_predicate(sql)
    if not date_pred:
        return None, None, None

    try:
        max_rows = await execute_query("SELECT MAX(YEAR(CrimeRegisteredDate)) AS max_year FROM CaseMaster")
        if not max_rows or not max_rows[0].get("max_year"):
            return None, None, None
        max_year = int(max_rows[0]["max_year"])
    except Exception as e:
        _log(f"_retry_with_latest_date max year lookup failed: {e}")
        return None, None, None

    rewritten_sql = rewrite_date_predicate(sql, max_year)
    if rewritten_sql == sql:
        return None, None, None

    if officer:
        try:
            rewritten_sql, _, _ = await enforce_station_scope(rewritten_sql, officer, question=question)
        except Exception as e:
            _log(f"_retry_with_latest_date station scope failed: {e}")
            return None, None, None

    try:
        results = await execute_query(rewritten_sql)
        if results:
            note = f"Note: No records matched year {date_pred['value']}. Displaying latest available data from {max_year}."
            return results, rewritten_sql, note
    except Exception as e:
        _log(f"_retry_with_latest_date execution failed: {e}")

    return None, None, None


# CONTRACT
# takes:  question (str) — user question, history (list[dict] | None) — history, recent_table (list[dict]) — recent result table, start (float) — start time, fallback_type (str) — label for logging
# returns: (PipelineResponse) — direct/RAG fallback response
# raises:  nothing
async def _fallback_rag_direct(
    question: str,
    history: list[dict] | None,
    recent_table: list[dict],
    start: float,
    fallback_type: str,
) -> PipelineResponse:
    try:
        rag_session = RagSession(document_ids=_get_kb_document_ids(), history=history)
        rag_result = await rag_session.ask(question)
    except Exception as e:
        _log(f"RAG fallback attempt failed ({fallback_type}): {e}")
        rag_result = {"grounded": False}

    if rag_result.get("grounded"):
        elapsed = time.monotonic() - start
        _log(f"Pipeline completed in {elapsed:.1f}s -- RAG ({fallback_type})")
        response = PipelineResponse()
        response.answer_text = rag_result["response"]
        response.suggested_follow_ups = rag_result.get("suggested_follow_ups", [])
        return response

    _log(f"RAG also ungrounded -- falling back to DIRECT answer ({fallback_type})")
    direct = await _run_direct(question, history or [], recent_table)
    elapsed = time.monotonic() - start
    _log(f"Pipeline completed in {elapsed:.1f}s -- DIRECT ({fallback_type})")
    return direct


# CONTRACT
# takes:  question (str) — natural language user question, history (list[dict] | None) — prior conversation turns, officer (dict | None) — authenticated officer identity
# returns: (PipelineResponse) — complete pipeline response object
# raises:  nothing (never raises — error details captured in PipelineResponse)
async def run_pipeline(
    question: str,
    history: list[dict] | None = None,
    officer: dict | None = None,
) -> PipelineResponse:
    # 1. Check pipeline semantic/exact cache
    cache_key = None
    try:
        cache_key = get_pipeline_cache_key(question, history, officer)
        cached_resp = _pipeline_cache.get(cache_key)
        if cached_resp is not None:
            _log(f"Pipeline CACHE HIT for: {question[:50]}...")
            return cached_resp
    except Exception as e:
        _log(f"WARNING: Pipeline cache lookup failed: {e}")

    start = time.monotonic()
    response = PipelineResponse()

    # Match rule engine (greetings, thanks, help, etc.)
    rule_match = try_rule_response(question)
    if rule_match is not None:
        _log("Rule engine matched question")
        response.answer_text = rule_match
        elapsed = time.monotonic() - start
        _log(f"Pipeline completed in {elapsed:.1f}s — RULE MATCH")
        return response

    # Rule 6: Pre-execution Cross-Station Comparison Intercept
    if officer and officer.get("role") in ("investigator", "supervisor") and _is_cross_station_comparison(question):
        _log("Cross-station comparison intercepted for restricted officer")
        response.answer_text = (
            "Cross-station comparisons are restricted to policymakers. "
            "As an officer, your access is scoped to your assigned station data."
        )
        elapsed = time.monotonic() - start
        _log(f"Pipeline completed in {elapsed:.1f}s — COMPARISON INTERCEPT")
        return response

    # Narrative keyword direct route
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

    recent_table = _most_recent_table(history)
    if history:
        decision = await route_intent(
            question=question, history=history, has_recent_data=bool(recent_table)
        )
        if decision == "DIRECT":
            direct = await _run_direct(question, history, recent_table)
            elapsed = time.monotonic() - start
            _log(f"Pipeline completed in {elapsed:.1f}s — DIRECT (no SQL)")
            return direct

    # 1. Schema linker
    try:
        tables, assumptions = select_relevant_tables(question)
        response.assumptions = assumptions
    except Exception as e:
        _log(f"schema_linker failed: {e}")
        response.error = "Internal error while analyzing the question."
        response.answer_text = "I couldn't analyze that question. Please try rephrasing it."
        return response

    # 2. SQL generation
    try:
        sql, attempts_used = await generate_sql(
            question=question, table_names=tables, history=history, officer=officer
        )
    except CannotAnswerError:
        _log("SQL chain returned CANNOT_ANSWER -- trying RAG before DIRECT fallback")
        return await _fallback_rag_direct(
            question=question,
            history=history,
            recent_table=recent_table,
            start=start,
            fallback_type="CANNOT_ANSWER fallback",
        )
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
        response.answer_text = "The SQL generation service is unavailable right now. Please try again."
        return response
    except Exception as e:
        _log(f"sql generation unexpected error: {e}")
        response.error = "Internal error during SQL generation."
        response.answer_text = "Something went wrong generating the query."
        return response

    response.sql_generated = sql

    # 2a. Enforce station-level row visibility
    was_scoped = False
    scope_disclaimer_needed = False
    if officer:
        try:
            sql, was_scoped, scope_disclaimer_needed = await enforce_station_scope(sql, officer, question=question)
            if was_scoped:
                response.sql_generated = sql
        except ScopeResolutionError as sre:
            _log(f"Scope resolution failed for query: {sre}")
            response.error = "scope_resolution_failed"
            response.answer_text = "Unable to determine your station access scope. Please contact an administrator."
            return response
        except StationScopeError:
            _log("Station scope enforcement failed for query (cannot determine CaseMaster alias) -- trying RAG before DIRECT fallback")
            return await _fallback_rag_direct(
                question=question,
                history=history,
                recent_table=recent_table,
                start=start,
                fallback_type="StationScopeError fallback",
            )

    # 3. Execute SQL
    results = None
    date_note = None
    try:
        results = await execute_query(sql)
    except Exception as exec_err:
        _log(f"db execute_query failed (attempt 1): {exec_err!r}")

        if attempts_used >= MAX_ATTEMPTS:
            _log(f"Skipping execution-error correction: budget exhausted (attempts_used={attempts_used}).")
            response.error = _GENERIC_DB_ERROR
            response.answer_text = _GENERIC_DB_ERROR
            return response

        try:
            corrected_sql = await correct_sql_after_execution_error(
                original_sql=sql,
                db_error=str(exec_err),
                table_names=tables,
                officer=officer,
            )
        except Exception as ce:
            _log(f"execution-error correction failed: {ce!r}")
            response.error = _GENERIC_DB_ERROR
            response.answer_text = _GENERIC_DB_ERROR
            return response

        response.sql_generated = corrected_sql

        if officer:
            try:
                corrected_sql, was_scoped, scope_disclaimer_needed = await enforce_station_scope(corrected_sql, officer, question=question)
                if was_scoped:
                    response.sql_generated = corrected_sql
            except StationScopeError:
                _log("Station scope enforcement failed for corrected query -- trying RAG before DIRECT fallback")
                return await _fallback_rag_direct(
                    question=question,
                    history=history,
                    recent_table=recent_table,
                    start=start,
                    fallback_type="StationScopeError corrected fallback",
                )

        try:
            results = await execute_query(corrected_sql)
        except Exception as retry_err:
            _log(f"db execute_query failed (attempt 2 / corrected): {retry_err!r}")
            response.error = _GENERIC_DB_ERROR
            response.answer_text = _GENERIC_DB_ERROR
            return response

    # Rule 7: Date Fallback Retry if 0 rows returned
    if not results:
        retry_res, retry_sql, note = await _retry_with_latest_date(response.sql_generated, officer, question=question)
        if retry_res:
            results = retry_res
            response.sql_generated = retry_sql
            date_note = note

    # Strip generic placeholder names from accused-frequency ranking results
    # so they don't appear in the UI table or mislead the answer formatter.
    results = _strip_placeholder_accused(results)
    response.table_data = results

    # Empty-results RAG fallback
    if not results:
        _log("SQL returned 0 rows -- trying RAG before accepting empty result")
        try:
            rag_session = RagSession(document_ids=_get_kb_document_ids(), history=history)
            rag_result = await rag_session.ask(question)
        except Exception as e:
            _log(f"Empty-results RAG attempt failed: {e!r}")
            rag_result = {"grounded": False}
        if rag_result.get("grounded"):
            response.answer_text = rag_result["response"]
            response.suggested_follow_ups = rag_result.get("suggested_follow_ups", [])
            return response
        _log("Empty-results RAG also ungrounded -- proceeding with empty SQL result")

    # 4. Media resolver
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

    # 5. Graph availability
    if case_master_ids:
        response.graph_available = await _check_graph_available(case_master_ids)

    # 6. Answer formatter with Rule 11 diagnostics and Rule 12 assumptions
    diagnostics = None
    if not results:
        diagnostics = {
            "active_station_scope": officer.get("unit_name") if (officer and was_scoped) else None,
            "date_filter": extract_date_predicate(response.sql_generated),
        }

    try:
        response.answer_text = await format_answer(
            question=question,
            results=results,
            media_attachments=media,
            history=history,
            officer=officer,
            was_scoped=was_scoped,
            scope_disclaimer_needed=scope_disclaimer_needed,
            diagnostics=diagnostics,
            assumptions=response.assumptions,
            sql=response.sql_generated,
        )
        if date_note:
            response.answer_text = f"{date_note}\n\n{response.answer_text}"
    except LLMError as e:
        _log(f"answer formatter LLM error (using fallback): {e}")
        response.answer_text = f"Query completed. Found {len(results)} record{'s' if len(results) != 1 else ''}."
    except Exception as e:
        _log(f"answer formatter unexpected error (using fallback): {e}")
        response.answer_text = f"Query completed. Found {len(results)} record{'s' if len(results) != 1 else ''}."

    # 7. Suggested follow-ups
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
        f"Pipeline completed in {elapsed:.1f}s — tables: {tables}, "
        f"rows: {len(results)}"
    )

    # Store in pipeline cache
    if cache_key and response and not response.error:
        try:
            _pipeline_cache.put(cache_key, response)
        except Exception as e:
            _log(f"WARNING: Failed to store in pipeline cache: {e}")

    return response
