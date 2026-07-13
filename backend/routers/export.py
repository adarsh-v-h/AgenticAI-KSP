"""
Chat session export — PDF (primary) and HTML (fallback) formats.
Uses fpdf2 for PDF generation — pure Python, no system dependencies.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from auth.simple_auth import get_current_officer
from db.chat_store import get_messages_for_session, verify_session_owner
from db.connection import execute_query
from conversation.history import get_history
from datetime import datetime
import io
import html as html_lib

from fpdf import FPDF

router = APIRouter()

# ─── Shared helpers ──────────────────────────────────────────────────────────

# CONTRACT
# takes:  value (Any) — value to HTML-escape for safe rendering
# returns: (str) — HTML-escaped string representation
# raises:  nothing
def _escape(value) -> str:
    if value is None:
        return ""
    return html_lib.escape(str(value), quote=True)


# CONTRACT
# takes:  messages (list) — message dicts from DB, history (list) — conversation history with table snapshots
# returns: (list) — messages with table_data hydrated from history where missing
# raises:  nothing
def _merge_history_tables(messages: list, history: list) -> list:
    table_turns = [
        t for t in history
        if isinstance(t, dict)
        and t.get("role") == "assistant"
        and isinstance(t.get("table"), list)
        and t.get("table")
    ]
    if not table_turns:
        return messages

    tables_by_content = {}
    for turn in table_turns:
        content = turn.get("content")
        if isinstance(content, str):
            tables_by_content.setdefault(content, []).append(turn["table"])

    assistant_tables = [turn["table"] for turn in table_turns]
    merged = []
    table_index = 0
    for msg in messages:
        next_msg = dict(msg)
        if next_msg.get("role") == "assistant":
            content_matches = tables_by_content.get(next_msg.get("content", ""))
            if not next_msg.get("table_data") and content_matches:
                next_msg["table_data"] = content_matches.pop(0)
                next_msg["has_table"] = True
            elif (
                not next_msg.get("table_data")
                and next_msg.get("has_table")
                and table_index < len(assistant_tables)
            ):
                next_msg["table_data"] = assistant_tables[table_index]
                next_msg["has_table"] = True
            if next_msg.get("table_data"):
                table_index += 1
        merged.append(next_msg)
    return merged


# ─── PDF Builder ─────────────────────────────────────────────────────────────

# CONTRACT
# takes:  officer_name (str) — officer's display name, badge_number (str) — KGID,
#          title (str) — session title, messages (list) — message dicts with content and optional table_data
# returns: (bytes) — complete PDF document as bytes
# raises:  nothing
def _build_pdf(officer_name: str, badge_number: str, title: str, messages: list) -> bytes:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    # Header
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(204, 120, 92)  # KSP brand color #cc785c
    pdf.cell(0, 10, "KSP Crime Intelligence", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(100, 100, 100)
    export_date = datetime.now().strftime("%d %B %Y, %I:%M %p")
    pdf.cell(0, 5, f"Officer: {officer_name} ({badge_number})  |  Session: {title}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 5, f"Exported: {export_date}", new_x="LMARGIN", new_y="NEXT")

    # Separator line
    pdf.set_draw_color(204, 120, 92)
    pdf.set_line_width(0.5)
    pdf.line(10, pdf.get_y() + 3, 200, pdf.get_y() + 3)
    pdf.ln(8)

    # Messages
    for msg in messages:
        if msg["role"] == "user":
            _render_user_message(pdf, msg.get("content", ""))
        else:
            _render_assistant_message(pdf, msg)

    # Footer
    pdf.ln(10)
    pdf.set_draw_color(200, 200, 200)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(4)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(150, 150, 150)
    pdf.cell(0, 5, "Karnataka State Police  |  Confidential  |  Not for public distribution", align="C")

    return pdf.output()


# CONTRACT
# takes:  pdf (FPDF) — the PDF document being built, content (str) — user message text
# returns: nothing
# raises:  nothing
def _render_user_message(pdf: FPDF, content: str):
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 5, "OFFICER:", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(30, 30, 30)
    pdf.set_fill_color(240, 235, 227)  # Light beige background
    pdf.multi_cell(0, 5, _safe_text(content), fill=True)
    pdf.ln(4)


# CONTRACT
# takes:  pdf (FPDF) — the PDF document being built, msg (dict) — assistant message dict with content, table_data, sql_generated, media_attachments
# returns: nothing
# raises:  nothing
def _render_assistant_message(pdf: FPDF, msg: dict):
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 5, "ASSISTANT:", new_x="LMARGIN", new_y="NEXT")

    # Answer text
    content = msg.get("content", "")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(30, 30, 30)
    pdf.multi_cell(0, 5, _safe_text(content))

    # Table data
    table_data = msg.get("table_data")
    if table_data and isinstance(table_data, list) and len(table_data) > 0:
        _render_table(pdf, table_data)

    # SQL generated (evidence trail inline)
    sql = msg.get("sql_generated")
    if sql and isinstance(sql, str) and sql.strip():
        pdf.ln(2)
        pdf.set_font("Courier", "", 7)
        pdf.set_text_color(80, 80, 80)
        pdf.set_fill_color(245, 243, 238)
        pdf.multi_cell(0, 3.5, f"Query: {_safe_text(sql.strip())}", fill=True)
        pdf.set_font("Helvetica", "", 10)

    # Media attachments (placeholder)
    media = msg.get("media_attachments")
    if media and isinstance(media, list) and len(media) > 0:
        pdf.ln(2)
        pdf.set_font("Helvetica", "I", 8)
        pdf.set_text_color(120, 120, 120)
        for item in media[:5]:
            media_type = item.get("media_type", "file")
            desc = item.get("description", "")
            pdf.cell(0, 4, f"[Media: {media_type} - {desc}]", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(4)


# CONTRACT
# takes:  pdf (FPDF) — the PDF document being built, rows (list[dict]) — table data rows
# returns: nothing
# raises:  nothing
def _render_table(pdf: FPDF, rows: list[dict]):
    if not rows:
        return

    display_rows = rows[:50]
    cols = list(display_rows[0].keys())

    # Calculate column widths (proportional to content)
    page_width = pdf.w - 20  # margins
    max_cols = min(len(cols), 6)  # cap at 6 columns to fit page
    cols = cols[:max_cols]
    col_width = page_width / max_cols

    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 7)

    # Header row
    pdf.set_fill_color(204, 120, 92)
    pdf.set_text_color(255, 255, 255)
    for col in cols:
        pdf.cell(col_width, 5, _safe_text(str(col))[:20], border=1, fill=True)
    pdf.ln()

    # Data rows
    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(30, 30, 30)
    for i, row in enumerate(display_rows):
        if i % 2 == 0:
            pdf.set_fill_color(250, 249, 245)
        else:
            pdf.set_fill_color(255, 255, 255)
        for col in cols:
            val = str(row.get(col, ""))[:30]
            pdf.cell(col_width, 4.5, _safe_text(val), border=1, fill=True)
        pdf.ln()

    # Footer
    total = len(rows)
    if total > 50:
        footer_text = f"Showing first 50 of {total} records."
    else:
        footer_text = f"{total} record{'s' if total != 1 else ''}."
    pdf.set_font("Helvetica", "I", 7)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 4, footer_text, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)


# CONTRACT
# takes:  text (str) — raw text that may contain characters fpdf2 can't encode
# returns: (str) — text safe for fpdf2 rendering (latin-1 compatible)
# raises:  nothing
def _safe_text(text: str) -> str:
    """Replace characters that fpdf2's default font can't render."""
    if not text:
        return ""
    # fpdf2 with built-in fonts uses latin-1; replace non-latin chars
    return text.encode("latin-1", errors="replace").decode("latin-1")


# ─── HTML Builder (kept as fallback) ─────────────────────────────────────────

# CONTRACT
# takes:  officer_name (str) — officer's display name, badge_number (str) — KGID,
#          title (str) — session title, messages (list) — message dicts
# returns: (str) — complete HTML document string for export
# raises:  nothing
def _build_html(officer_name: str, badge_number: str, title: str, messages: list) -> str:
    messages_html = ""
    for msg in messages:
        if msg["role"] == "user":
            messages_html += (
                '\n<div class="message user">'
                f'\n  <div class="bubble">{_escape(msg["content"])}</div>'
                '\n</div>'
            )
        else:
            content = _escape(msg.get("content") or "").replace("\n", "<br>")
            messages_html += (
                '\n<div class="message assistant">'
                '\n  <div class="label">ASSISTANT</div>'
                f'\n  <div class="content">{content}</div>'
            )
            if msg.get("table_data"):
                rows = msg["table_data"]
                if rows:
                    cols = list(rows[0].keys())
                    thead = "".join(f"<th>{_escape(c)}</th>" for c in cols)
                    tbody = ""
                    for row in rows[:50]:
                        cells = "".join(
                            f"<td>{_escape(row.get(c, ''))}</td>" for c in cols
                        )
                        tbody += f"<tr>{cells}</tr>"
                    count = len(rows)
                    footer = (
                        f"Showing first 50 of {count} records."
                        if count > 50
                        else f"{count} record{'s' if count != 1 else ''}."
                    )
                    messages_html += (
                        '\n<div class="table-wrap">'
                        "\n<table>"
                        f"<thead><tr>{thead}</tr></thead>"
                        f"<tbody>{tbody}</tbody>"
                        "</table>"
                        f'\n<div class="table-footer">{footer}</div>'
                        "\n</div>"
                    )
            messages_html += "\n</div>"

    export_date = datetime.now().strftime("%d %B %Y, %I:%M %p")
    return (
        "<!DOCTYPE html>\n<html>\n<head>\n<meta charset=\"UTF-8\">\n"
        "<title>KSP Export</title>\n<style>\n"
        "body{font-family:Arial,sans-serif;padding:40px;color:#1a1a1a;font-size:13px;max-width:1100px;margin:0 auto}\n"
        ".header{border-bottom:2px solid #cc785c;padding-bottom:16px;margin-bottom:24px}\n"
        ".header h1{font-size:18px;margin:0;color:#cc785c}\n"
        ".header p{font-size:11px;color:#666;margin:4px 0 0}\n"
        ".message{margin-bottom:18px}\n"
        ".message.user{text-align:right}\n"
        ".message.user .bubble{display:inline-block;background:#f0ebe3;padding:10px 14px;border-radius:12px;max-width:80%;font-size:13px}\n"
        ".message.assistant .label{font-size:10px;color:#999;margin-bottom:4px;letter-spacing:.05em}\n"
        ".message.assistant .content{font-size:13px;line-height:1.6}\n"
        ".table-wrap{margin-top:10px;overflow-x:auto}\n"
        "table{width:100%;border-collapse:collapse;font-size:11px}\n"
        "th{background:#cc785c;color:#fff;padding:5px 8px;text-align:left}\n"
        "td{border:1px solid #e0d9d0;padding:5px 8px}\n"
        "tr:nth-child(even) td{background:#faf9f5}\n"
        ".table-footer{font-size:10px;color:#666;margin-top:6px}\n"
        ".footer{margin-top:40px;font-size:10px;color:#999;border-top:1px solid #e0d9d0;padding-top:12px}\n"
        "</style>\n</head>\n<body>\n"
        '<div class="header">\n'
        "<h1>KSP Crime Intelligence - Conversation Export</h1>\n"
        f"<p>Officer: {_escape(officer_name)} ({_escape(badge_number)}) &nbsp;|&nbsp; "
        f"Session: {_escape(title)} &nbsp;|&nbsp; Exported: {export_date}</p>\n"
        "</div>\n"
        + messages_html
        + '\n<div class="footer">\nKarnataka State Police &nbsp;|&nbsp; Confidential &nbsp;|&nbsp; Not for public distribution\n</div>\n</body>\n</html>'
    )


# ─── Route ───────────────────────────────────────────────────────────────────

@router.post("/api/chat/sessions/{session_id}/export")
async def export_session_pdf(
    session_id: str,
    format: str = Query("pdf", pattern="^(pdf|html)$"),
    officer: dict = Depends(get_current_officer),
):
    """
    Export a chat session. Default format is PDF.
    Pass ?format=html for the legacy HTML export.
    """
    owned = await verify_session_owner(session_id, officer["officer_id"])
    if not owned:
        raise HTTPException(status_code=404, detail="Session not found.")

    messages = await get_messages_for_session(session_id)
    if not messages:
        raise HTTPException(status_code=400, detail="No messages to export.")

    history = await get_history(session_id)
    messages = _merge_history_tables(messages, history)

    rows = await execute_query(
        "SELECT title FROM chat_sessions WHERE session_id = %s", (session_id,)
    )
    title = rows[0]["title"] if rows else "Chat Export"

    officer_rows = await execute_query(
        "SELECT FirstName, KGID FROM Employee WHERE EmployeeID = %s",
        (officer["officer_id"],),
    )
    officer_name = officer_rows[0]["FirstName"] if officer_rows else "Officer"
    badge_number = officer_rows[0]["KGID"] if officer_rows else ""

    if format == "html":
        output = _build_html(officer_name, badge_number, title, messages)
        filename = f"KSP-{session_id[:8]}.html"
        return StreamingResponse(
            io.BytesIO(output.encode("utf-8")),
            media_type="text/html",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # PDF (default)
    pdf_bytes = _build_pdf(officer_name, badge_number, title, messages)
    filename = f"KSP-{session_id[:8]}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
