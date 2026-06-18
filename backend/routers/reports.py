"""
Report/file analysis endpoint.

Accepts a small uploaded report as base64 JSON, extracts readable text, and
asks the answer model for recurring themes and case relevance.
"""

import base64
import binascii
import io
import re
import sys
import zipfile
import zlib
from html import unescape
from xml.etree import ElementTree

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth.simple_auth import get_current_officer
from conversation.history import get_history, save_turn
from db.chat_store import (
    create_session as create_chat_session_row,
    save_message_pair,
    update_session_timestamp,
)
from db.connection import execute_query
from llm.client import LLMError, call_llm

router = APIRouter()

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_EXTRACTED_CHARS = 14000


class ReportAnalysisRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=128)
    prompt: str = Field(default="", max_length=800)
    file_name: str = Field(..., min_length=1, max_length=240)
    mime_type: str = Field(default="application/octet-stream", max_length=120)
    data_base64: str = Field(..., min_length=1)


class ReportAnalysisResponse(BaseModel):
    answer_text: str
    extracted_chars: int
    file_name: str
    warning: str | None = None


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _decode_file(data_base64: str) -> bytes:
    try:
        raw = base64.b64decode(data_base64, validate=True)
    except (binascii.Error, ValueError) as e:
        raise HTTPException(status_code=400, detail="Invalid file data.") from e
    if len(raw) > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="File is too large. Maximum size is 5 MB.")
    return raw


def _decode_text(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def _extract_docx_text(raw: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            xml = zf.read("word/document.xml")
    except Exception:
        return ""
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        return ""
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    paragraphs = []
    for para in root.iter(f"{ns}p"):
        parts = [node.text or "" for node in para.iter(f"{ns}t")]
        text = "".join(parts).strip()
        if text:
            paragraphs.append(text)
    return "\n".join(paragraphs)


def _pdf_literal_to_text(value: str) -> str:
    value = value.replace(r"\(", "(").replace(r"\)", ")").replace(r"\\", "\\")
    value = re.sub(r"\\([nrtbf])", " ", value)
    value = re.sub(r"\\[0-7]{1,3}", " ", value)
    return value


def _extract_pdf_text(raw: bytes) -> str:
    chunks = []

    # Try compressed PDF streams first. This handles many generated reports.
    for match in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", raw, re.S):
        stream = match.group(1)
        for candidate in (stream, stream.strip()):
            try:
                chunks.append(zlib.decompress(candidate))
                break
            except zlib.error:
                continue

    # Fall back to scanning raw bytes too.
    chunks.append(raw)

    text_parts = []
    for chunk in chunks:
        text = chunk.decode("latin-1", errors="ignore")
        for literal in re.findall(r"\((.*?)\)\s*T[Jj]", text, re.S):
            text_parts.append(_pdf_literal_to_text(literal))
        for array in re.findall(r"\[(.*?)\]\s*TJ", text, re.S):
            for literal in re.findall(r"\((.*?)\)", array, re.S):
                text_parts.append(_pdf_literal_to_text(literal))

    collapsed = "\n".join(part.strip() for part in text_parts if part.strip())
    return re.sub(r"[ \t]+", " ", collapsed)


def extract_report_text(raw: bytes, file_name: str, mime_type: str) -> str:
    lower_name = file_name.lower()
    lower_type = (mime_type or "").lower()

    if lower_name.endswith(".docx") or "wordprocessingml" in lower_type:
        text = _extract_docx_text(raw)
    elif lower_name.endswith(".pdf") or lower_type == "application/pdf":
        text = _extract_pdf_text(raw)
    else:
        text = _decode_text(raw)
        if lower_name.endswith((".html", ".htm")) or "html" in lower_type:
            text = re.sub(r"<(script|style).*?</\1>", " ", text, flags=re.I | re.S)
            text = re.sub(r"<[^>]+>", " ", text)
            text = unescape(text)

    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text).strip()
    return text[:MAX_EXTRACTED_CHARS]


def build_report_prompt(
    officer_prompt: str,
    file_name: str,
    extracted_text: str,
    history: list[dict],
) -> tuple[str, str]:
    history_lines = []
    for turn in history[-6:]:
        role = turn.get("role")
        content = (turn.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            history_lines.append(f"{role.upper()}: {content[:500]}")
    history_block = "\n".join(history_lines) or "No recent chat context."
    request = officer_prompt.strip() or (
        "Review this report. Identify recurring themes and explain whether they "
        "appear related to the current case context."
    )

    system_prompt = (
        "You are a professional police intelligence assistant for Karnataka "
        "State Police. Analyze uploaded reports using only the report text and "
        "recent chat context. Be concise, evidence-led, and avoid speculation."
    )
    user_prompt = f"""
Officer request:
{request}

Recent chat context:
{history_block}

Uploaded file: {file_name}

Extracted report text:
{extracted_text}

Write a practical intelligence note with:
1. Brief report conclusion.
2. Recurring themes or repeated entities, locations, methods, dates, or behaviors.
3. How those themes may relate to the current case/chat context.
4. Investigative leads or follow-up checks.
5. Caveats where the report text is insufficient.

Do not invent facts. If no recurring theme is visible, say that clearly.
"""
    return system_prompt, user_prompt


async def _persist_report_turn(session_id: str, officer: dict, question: str, answer: str) -> None:
    try:
        existing = await execute_query(
            "SELECT session_id FROM chat_sessions WHERE session_id = %s",
            (session_id,),
        )
        if not existing:
            await create_chat_session_row(
                session_id,
                officer["officer_id"],
                question[:60] or "Uploaded report analysis",
            )
        await save_message_pair(
            session_id=session_id,
            question=question,
            answer_text=answer,
            sql_generated="",
            has_table=False,
            has_media=False,
            graph_available=False,
            table_data=[],
            media_attachments=[],
        )
        await update_session_timestamp(session_id)
    except Exception as e:
        _log(f"report analysis persistence failed (non-fatal): {e}")


@router.post("/api/reports/analyze", response_model=ReportAnalysisResponse)
async def analyze_report(
    request: ReportAnalysisRequest,
    officer: dict = Depends(get_current_officer),
) -> ReportAnalysisResponse:
    raw = _decode_file(request.data_base64)
    extracted = extract_report_text(raw, request.file_name, request.mime_type)
    if not extracted:
        raise HTTPException(
            status_code=400,
            detail="Could not extract readable text from this file. Scanned PDFs need OCR first.",
        )

    history = await get_history(request.session_id)
    system_prompt, user_prompt = build_report_prompt(
        request.prompt,
        request.file_name,
        extracted,
        history,
    )

    try:
        answer = await call_llm(
            model_key="MODEL_ANSWER",
            prompt=user_prompt,
            system_prompt=system_prompt,
            max_tokens=12000,
        )
    except LLMError as e:
        _log(f"report analysis LLM failed: {e}")
        raise HTTPException(status_code=502, detail="Report analysis model failed.") from e

    question = request.prompt.strip() or "Analyze uploaded report"
    question = f"{question}\n\nAttached file: {request.file_name}"
    try:
        await save_turn(
            request.session_id,
            question,
            answer,
            assistant_table=None,
        )
    except Exception as e:
        _log(f"report analysis history save failed (non-fatal): {e}")
    await _persist_report_turn(request.session_id, officer, question, answer)

    warning = None
    if len(extracted) >= MAX_EXTRACTED_CHARS:
        warning = "Only the first part of the report was analyzed because it was long."

    return ReportAnalysisResponse(
        answer_text=answer,
        extracted_chars=len(extracted),
        file_name=request.file_name,
        warning=warning,
    )
