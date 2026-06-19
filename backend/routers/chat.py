"""
Chat routes.

POST /api/chat        — non-streaming JSON response (kept for testing/fallback)
GET  /api/chat/stream — SSE: status events + token-by-token answer streaming

Both are protected. The SSE endpoint accepts the JWT either via the standard
Authorization header or as a `?token=...` query parameter so EventSource clients
can authenticate without setting custom headers.
"""

import sys
import json
import asyncio
from uuid import uuid4
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from pipeline.query_pipeline import run_pipeline
from graph.network_builder import build_graph_for_fir, build_graph_for_accused
from conversation.history import get_history, save_turn
from conversation.session_store import create_session
from auth.simple_auth import get_current_officer, get_current_officer_sse
from db.connection import execute_query
from db.chat_store import (
    create_session as create_chat_session_row,
    update_session_timestamp,
    save_message_pair,
    get_sessions_for_officer,
    get_messages_for_session,
    verify_session_owner,
)

router = APIRouter()


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=500)
    session_id: str = Field(..., min_length=1, max_length=128)


class ChatResponse(BaseModel):
    answer_text: str
    table_data: list[dict]
    media_attachments: list[dict]
    sql_generated: str
    graph_available: bool
    error: str | None = None


class SessionMetadata(BaseModel):
    session_id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int


class SessionListResponse(BaseModel):
    sessions: list[SessionMetadata]


class Message(BaseModel):
    message_id: int | str
    role: str
    content: str
    sql_generated: str = ""
    has_table: bool = False
    has_media: bool = False
    graph_available: bool = False
    table_data: list[dict] = Field(default_factory=list)
    media_attachments: list[dict] = Field(default_factory=list)
    created_at: str | None = None


class MessagesResponse(BaseModel):
    messages: list[Message]


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _sse(event: dict) -> str:
    """Format a single SSE message. Must end with a blank line."""
    return f"data: {json.dumps(event, default=str)}\n\n"


async def _persist_turn(session_id: str, officer: dict, question: str, result, session_exists: bool) -> None:
    """
    Persist a completed pipeline turn to MySQL (Step 4).

    Creates the chat_sessions row on the first message of a session, saves the
    user + assistant message pair (with rich data to NoSQL when present), and
    bumps the session's updated_at / message_count.

    `session_exists` is the ownership/existence result already computed by the
    caller's authorization gate, so we avoid a duplicate existence query.

    Never raises — persistence failures are logged and non-fatal so the chat
    keeps working even when the Data Store is unavailable.
    """
    try:
        if not session_exists:
            await create_chat_session_row(
                session_id, officer["officer_id"], question[:60]
            )

        await save_message_pair(
            session_id=session_id,
            question=question,
            answer_text=result.answer_text,
            sql_generated=result.sql_generated,
            has_table=bool(result.table_data),
            has_media=bool(result.media_attachments),
            graph_available=result.graph_available,
            table_data=result.table_data,
            media_attachments=result.media_attachments,
        )
        await update_session_timestamp(session_id)
    except Exception as e:
        _log(f"_persist_turn failed (non-fatal): {e}")


async def _authorize_session_write(session_id: str, officer_id: int) -> bool:
    """
    Authorization gate for chat write paths (POST /api/chat and the SSE stream).

    Prevents BOLA/IDOR (OWASP API1:2023): an authenticated officer must not be
    able to write turns into another officer's session by supplying its
    session_id. Returns the existence flag (True if the session already exists
    and is owned by this officer) so the caller can pass it to `_persist_turn`
    without a second existence query.

    Raises HTTP 404 (not 403) when the session exists but belongs to another
    officer — we never reveal that a foreign session exists. A not-yet-existing
    session is allowed (create-or-append: the officer owns it on creation).

    Returns True when the session already exists (and is owned by this officer),
    False when it does not yet exist.
    """
    rows = await execute_query(
        "SELECT officer_id FROM chat_sessions WHERE session_id = %s",
        (session_id,),
    )
    if rows and rows[0]["officer_id"] != officer_id:
        raise HTTPException(status_code=404, detail="Session not found.")
    return bool(rows)


@router.get("/api/graph/fir/{fir_id}")
async def graph_by_fir(
    fir_id: int,
    officer: dict = Depends(get_current_officer),
) -> dict:
    """
    Return a vis.js-compatible network graph centered on a FIR.

    No ownership check: FIR/accused data is station-scoped, not officer-scoped —
    any authenticated officer may view any case's network (unlike chat sessions,
    which are officer-owned). The `get_current_officer` auth gate is sufficient.

    Always HTTP 200 with `{"nodes": [...], "edges": [...]}` — the builder returns
    an empty graph on error rather than raising, so this never 500s.
    """
    return await build_graph_for_fir(fir_id)


@router.get("/api/graph/accused/{accused_id}")
async def graph_by_accused(
    accused_id: int,
    officer: dict = Depends(get_current_officer),
) -> dict:
    """
    Return a vis.js-compatible network graph centered on an accused person.
    Same station-scoped authorization model as `graph_by_fir`. Always HTTP 200.
    """
    return await build_graph_for_accused(accused_id)


@router.get("/api/chat/sessions", response_model=SessionListResponse)
async def list_chat_sessions(
    officer: dict = Depends(get_current_officer),
) -> SessionListResponse:
    """
    List all chat sessions for the authenticated officer, ordered by
    updated_at descending (most recent first).

    Step 4: now reads from MySQL (chat_sessions) instead of NoSQL. Authentication
    (401) is enforced by `get_current_officer`. `get_sessions_for_officer` never
    raises — it returns [] on any DB error — so this endpoint always returns
    HTTP 200 with whatever sessions are available.
    """
    officer_id = officer["officer_id"]

    rows = await get_sessions_for_officer(officer_id, limit=30)

    sessions = [
        SessionMetadata(
            session_id=row.get("session_id", ""),
            title=row.get("title", ""),
            created_at=row.get("created_at") or "",
            updated_at=row.get("updated_at") or "",
            message_count=row.get("message_count", 0) or 0,
        )
        for row in rows
    ]

    return SessionListResponse(sessions=sessions)


@router.post(
    "/api/chat/sessions",
    response_model=SessionMetadata,
    status_code=201,
)
async def create_chat_session(
    officer: dict = Depends(get_current_officer),
) -> SessionMetadata:
    """
    Create a new chat session for the authenticated officer and return its
    metadata with HTTP 201.

    Authentication (401) is enforced by `get_current_officer`. The new session
    is persisted via `create_session`, which writes the in-memory fallback
    first and then attempts the NoSQL POST — it never raises, so this endpoint
    always succeeds once the officer is authenticated.

    The stored document uses `id` as the session_id key; we map it to
    `session_id` in the response.
    """
    officer_id = officer["officer_id"]

    session_id = f"sess-{uuid4()}"
    now = datetime.now(timezone.utc).isoformat()

    document = {
        "id": session_id,
        "officer_id": officer_id,
        "title": "New chat",
        "created_at": now,
        "updated_at": now,
        "message_count": 0,
    }

    stored = await create_session(document)

    return SessionMetadata(
        session_id=stored.get("id", session_id),
        title=stored.get("title", "New chat"),
        created_at=stored.get("created_at", now),
        updated_at=stored.get("updated_at", now),
        message_count=stored.get("message_count", 0),
    )


@router.get(
    "/api/chat/sessions/{session_id}/messages",
    response_model=MessagesResponse,
)
async def get_session_messages(
    session_id: str,
    officer: dict = Depends(get_current_officer),
) -> MessagesResponse:
    """
    Load all messages for a session (Step 4: now backed by MySQL + NoSQL).

    Authentication (401) is enforced by `get_current_officer`. Ownership is
    verified against chat_sessions.officer_id: officers can only read their own
    sessions, and a mismatch (or missing session) returns 404 so we never reveal
    that another officer's session exists.

    Messages are returned oldest-first, ready for direct frontend consumption.
    Rich data (table_data, media_attachments) is hydrated from NoSQL for
    assistant messages that carry it.
    """
    owned = await verify_session_owner(session_id, officer["officer_id"])
    if not owned:
        raise HTTPException(status_code=404, detail="Session not found.")

    rows = await get_messages_for_session(session_id)

    messages = [
        Message(
            message_id=row["message_id"],
            role=row["role"],
            content=row["content"],
            sql_generated=row.get("sql_generated", ""),
            has_table=row.get("has_table", False),
            has_media=row.get("has_media", False),
            graph_available=row.get("graph_available", False),
            table_data=row.get("table_data", []),
            media_attachments=row.get("media_attachments", []),
            created_at=row.get("created_at"),
        )
        for row in rows
    ]

    return MessagesResponse(messages=messages)


@router.post("/api/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    officer: dict = Depends(get_current_officer),
) -> ChatResponse:
    """
    Run the user's question through the full NL2SQL pipeline.
    Always returns HTTP 200 — pipeline failures are surfaced via the `error`
    field on the response.
    """
    question = request.question.strip()
    if not question:
        return ChatResponse(
            answer_text="Please enter a question.",
            table_data=[],
            media_attachments=[],
            sql_generated="",
            graph_available=False,
            error="Empty question.",
        )

    # Object-level authorization gate (BOLA/IDOR) before any pipeline work.
    session_exists = await _authorize_session_write(
        request.session_id, officer["officer_id"]
    )

    try:
        history = await get_history(request.session_id)
    except Exception as e:
        _log(f"get_history failed (using empty): {e}")
        history = []

    try:
        result = await run_pipeline(question=question, history=history, officer=officer)
    except Exception as e:
        _log(f"chat router unexpected error: {e}")
        return ChatResponse(
            answer_text="An unexpected error occurred. Please try again.",
            table_data=[],
            media_attachments=[],
            sql_generated="",
            graph_available=False,
            error=str(e),
        )

    if not result.error:
        try:
            await save_turn(
                request.session_id,
                question,
                result.answer_text,
                assistant_sql=result.sql_generated,
                assistant_table=result.table_data,
            )
        except Exception as e:
            _log(f"save_turn failed (non-fatal): {e}")

        # Step 4: persist session + message pair to MySQL (NoSQL for rich data).
        await _persist_turn(request.session_id, officer, question, result, session_exists)

    return ChatResponse(
        answer_text=result.answer_text,
        table_data=result.table_data,
        media_attachments=result.media_attachments,
        sql_generated=result.sql_generated,
        graph_available=result.graph_available,
        error=result.error,
    )


@router.get("/api/chat/stream")
async def chat_stream(
    question: str = Query(..., min_length=1, max_length=500),
    session_id: str = Query(..., min_length=1, max_length=128),
    officer: dict = Depends(get_current_officer_sse),
):
    """
    Server-Sent Events stream.

    Catalyst QuickML doesn't support true LLM streaming (one POST returns the
    full response), so we simulate streaming by:
      1. Emitting `status` events while the pipeline runs
      2. Running the pipeline (DB + 2 LLM calls — typically 60-120 seconds)
      3. Splitting the answer into whitespace-delimited tokens and yielding
         each one as a `token` event with a small inter-token delay

    Event shapes:
      {"type":"status","content":"..."}
      {"type":"token","content":"..."}
      {"type":"table","data":[...]}
      {"type":"media","attachments":[...]}
      {"type":"graph_available"}
      {"type":"sql","content":"..."}
      {"type":"error","message":"..."}
      {"type":"done"}
    """
    q = question.strip()
    if not q:
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    # Object-level authorization gate (BOLA/IDOR) before opening the stream, so
    # a forged/foreign session_id returns a clean HTTP 404 rather than a 200
    # SSE stream carrying an error event.
    session_exists = await _authorize_session_write(
        session_id, officer["officer_id"]
    )

    async def event_generator():
        try:
            yield _sse({"type": "status", "content": "Analyzing your question..."})
            await asyncio.sleep(0.05)

            try:
                history = await get_history(session_id)
            except Exception as e:
                _log(f"get_history failed in stream (using empty): {e}")
                history = []

            yield _sse({"type": "status", "content": "Generating database query..."})
            await asyncio.sleep(0.05)

            try:
                result = await run_pipeline(question=q, history=history, officer=officer)
            except Exception as e:
                _log(f"run_pipeline crashed in stream: {e}")
                yield _sse(
                    {
                        "type": "error",
                        "message": "An unexpected error occurred while processing your question.",
                    }
                )
                yield _sse({"type": "done"})
                return

            if result.sql_generated:
                yield _sse({"type": "sql", "content": result.sql_generated})

            if result.error:
                yield _sse({"type": "error", "message": result.error})
                # Still emit the answer_text (which is the user-friendly explainer),
                # but skip it if it duplicates the error message verbatim.
                if result.answer_text and result.answer_text != result.error:
                    for token in _tokenize(result.answer_text):
                        yield _sse({"type": "token", "content": token})
                        await asyncio.sleep(0.02)
                yield _sse({"type": "done"})
                return

            yield _sse({"type": "status", "content": "Formatting answer..."})
            await asyncio.sleep(0.05)

            for token in _tokenize(result.answer_text):
                yield _sse({"type": "token", "content": token})
                await asyncio.sleep(0.03)

            if result.table_data:
                yield _sse({"type": "table", "data": result.table_data})

            if result.media_attachments:
                yield _sse(
                    {"type": "media", "attachments": result.media_attachments}
                )

            if result.graph_available:
                yield _sse({"type": "graph_available"})

            try:
                await save_turn(
                    session_id,
                    q,
                    result.answer_text,
                    assistant_sql=result.sql_generated,
                    assistant_table=result.table_data,
                )
            except Exception as e:
                _log(f"save_turn failed in stream (non-fatal): {e}")

            # Step 4: persist session + message pair to MySQL (NoSQL for rich data).
            await _persist_turn(session_id, officer, q, result, session_exists)

            yield _sse({"type": "done"})

        except asyncio.CancelledError:
            # Client disconnected — exit cleanly.
            raise
        except Exception as e:
            _log(f"SSE stream unexpected error: {e}")
            yield _sse(
                {"type": "error", "message": "An unexpected error occurred."}
            )
            yield _sse({"type": "done"})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


def _tokenize(text: str) -> list[str]:
    """
    Split `text` into space-preserving tokens for token-by-token streaming.
    Each returned token (except possibly the last) ends with the trailing space.
    """
    if not text:
        return []
    words = text.split(" ")
    out: list[str] = []
    last = len(words) - 1
    for i, w in enumerate(words):
        out.append(w if i == last else w + " ")
    return out
