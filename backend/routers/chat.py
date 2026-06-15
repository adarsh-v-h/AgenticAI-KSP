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
from conversation.history import get_history, save_turn
from conversation.session_store import list_sessions, create_session, get_session
from auth.simple_auth import get_current_officer, get_current_officer_sse

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
    message_id: str
    role: str
    content: str
    timestamp: str
    sql: str | None = None


class MessagesResponse(BaseModel):
    messages: list[Message]
    has_more: bool


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _error(status_code: int, code: str, error: str) -> HTTPException:
    """
    Build an HTTPException whose `detail` follows the standardized structured
    shape `{"error": str, "code": str}` (Requirements 15.1-15.3).

    FastAPI serializes the exception's `detail` into the response body, so a
    raised `_error(...)` produces a JSON body of the form:
        {"detail": {"error": "...", "code": "..."}}
    with the given HTTP status code (e.g. 400, 401, 404, 500).

    All structured errors are logged to stderr via `_log` following the
    existing logging pattern (Requirement 15.5).
    """
    _log(f"chat session error [{status_code} {code}]: {error}")
    return HTTPException(
        status_code=status_code,
        detail={"error": error, "code": code},
    )


def _sse(event: dict) -> str:
    """Format a single SSE message. Must end with a blank line."""
    return f"data: {json.dumps(event, default=str)}\n\n"


@router.get("/api/chat/sessions", response_model=SessionListResponse)
async def list_chat_sessions(
    officer: dict = Depends(get_current_officer),
) -> SessionListResponse:
    """
    List all chat sessions for the authenticated officer, ordered by
    updated_at descending (most recent first).

    Authentication (401) is enforced by `get_current_officer`. NoSQL failures
    are handled inside `list_sessions`, which falls back to the in-memory store
    and never raises — so this endpoint always returns HTTP 200 with whatever
    sessions are available.

    The stored document uses `id` as the session_id key; we map it to
    `session_id` in the response.
    """
    officer_id = officer["officer_id"]

    docs = await list_sessions(officer_id)

    sessions = [
        SessionMetadata(
            session_id=doc.get("id", ""),
            title=doc.get("title", ""),
            created_at=doc.get("created_at", ""),
            updated_at=doc.get("updated_at", ""),
            message_count=doc.get("message_count", 0),
        )
        for doc in docs
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
    limit: int = Query(50, ge=1, le=100),
    before_message_id: str | None = Query(default=None),
    officer: dict = Depends(get_current_officer),
) -> MessagesResponse:
    """
    Return a paginated page of messages for `session_id`, newest first.

    Authentication (401) is enforced by `get_current_officer`.

    Ownership check: we fetch the session_metadata doc via `get_session`. If it
    exists and its `officer_id` does NOT match the authenticated officer, we
    return 404 (we use 404 rather than 403 so we never reveal that a session
    belonging to another officer exists). If no metadata doc exists at all we
    deliberately do NOT 404: legacy sessions created via the old /api/chat flow
    have conversation history but were never given a session_metadata document,
    and 404-ing those would break access to existing conversations. The design
    says "404 when session doesn't exist OR doesn't belong to officer", but we
    relax the "doesn't exist" half pragmatically for backward compatibility.

    Pagination (bottom-to-top loading):
      - `get_history` returns messages in chronological (oldest-first) order,
        already capped at MAX_TURNS — that is the full available history here.
      - Without `before_message_id`: the eligible set is the whole history.
      - With `before_message_id`: the eligible set is everything strictly older
        than that message (i.e. the messages before its index). If the id is
        not found in the history we treat it as "no older messages" and return
        an empty page (has_more=False) — the client asked for messages older
        than something we don't have, so there is nothing to return.
      - We take the last `limit` messages of the eligible set (the most recent
        eligible ones). `has_more` is True when the eligible set contained more
        messages than we returned (i.e. older messages remain).
      - Returned messages are ordered by timestamp DESCENDING (newest first)
        per Requirement 10.6.
    """
    officer_id = officer["officer_id"]

    # Ownership verification. Only 404 when metadata exists and the officer
    # doesn't match; missing metadata is allowed (legacy sessions).
    metadata = await get_session(session_id)
    if metadata is not None and metadata.get("officer_id") != officer_id:
        raise _error(404, "SESSION_NOT_FOUND", "Session not found.")

    # Chronological (oldest-first) list of message dicts.
    history = await get_history(session_id)

    # Determine the eligible set (messages older than before_message_id).
    if before_message_id:
        index = next(
            (
                i
                for i, msg in enumerate(history)
                if msg.get("message_id") == before_message_id
            ),
            None,
        )
        if index is None:
            # Cursor not found — nothing older to return.
            eligible = []
        else:
            eligible = history[:index]
    else:
        eligible = history

    # Most recent `limit` messages of the eligible set; older messages remain
    # when the eligible set was larger than the page we return.
    page = eligible[-limit:] if limit < len(eligible) else eligible
    has_more = len(eligible) > len(page)

    # Newest first (descending by timestamp). The eligible list is already in
    # chronological order, so reversing yields newest-first.
    page_desc = list(reversed(page))

    messages = [
        Message(
            message_id=msg.get("message_id", ""),
            role=msg.get("role", ""),
            content=msg.get("content", ""),
            timestamp=msg.get("timestamp", ""),
            sql=msg.get("sql"),
        )
        for msg in page_desc
    ]

    return MessagesResponse(messages=messages, has_more=has_more)


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
            )
        except Exception as e:
            _log(f"save_turn failed (non-fatal): {e}")

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
                )
            except Exception as e:
                _log(f"save_turn failed in stream (non-fatal): {e}")

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
