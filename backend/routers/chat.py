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

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from pipeline.query_pipeline import run_pipeline
from conversation.history import get_history, save_turn
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


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _sse(event: dict) -> str:
    """Format a single SSE message. Must end with a blank line."""
    return f"data: {json.dumps(event, default=str)}\n\n"


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
        result = await run_pipeline(question=question, history=history)
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
            await save_turn(request.session_id, question, result.answer_text)
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
                result = await run_pipeline(question=q, history=history)
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
                # Still emit the answer_text (which is the user-friendly explainer)
                if result.answer_text:
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
                await save_turn(session_id, q, result.answer_text)
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
