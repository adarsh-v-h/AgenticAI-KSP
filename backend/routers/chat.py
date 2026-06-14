"""
POST /api/chat — non-streaming chat endpoint.

Step 2 keeps history empty. Step 3 will plug NoSQL-backed history in here.
"""

import sys
from fastapi import APIRouter
from pydantic import BaseModel, Field

from pipeline.query_pipeline import run_pipeline

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


@router.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """
    Run the user's question through the full NL2SQL pipeline.
    Always returns HTTP 200 — pipeline failures are surfaced via the `error`
    field on the response so the frontend can render them inline.
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
        result = await run_pipeline(question=question, history=[])
    except Exception as e:  # last-resort safety net
        _log(f"chat router unexpected error: {e}")
        return ChatResponse(
            answer_text="An unexpected error occurred. Please try again.",
            table_data=[],
            media_attachments=[],
            sql_generated="",
            graph_available=False,
            error=str(e),
        )

    return ChatResponse(
        answer_text=result.answer_text,
        table_data=result.table_data,
        media_attachments=result.media_attachments,
        sql_generated=result.sql_generated,
        graph_available=result.graph_available,
        error=result.error,
    )
