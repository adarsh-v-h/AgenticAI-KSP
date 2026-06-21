
"""
HTML export endpoint - renders chat session as downloadable HTML file.
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from auth.simple_auth import get_current_officer
from db.chat_store import get_messages_for_session, verify_session_owner
from db.connection import execute_query
from conversation.history import get_history
from datetime import datetime
import io
import html as html_lib

router = APIRouter()


def _escape(value) -> str:
    if value is None:
        return ""
    return html_lib.escape(str(value), quote=True)


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
    for t in table_turns:
        c = t.get("content")
        if isinstance(c, str):
            tables_by_content.setdefault(c, []).append(t["table"])
    assistant_tables = [t["table"] for t in table_turns]
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


@router.post("/api/chat/sessions/{session_id}/export")
async def export_session_pdf(
    session_id: str,
    officer: dict = Depends(get_current_officer),
):
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
        "SELECT full_name, badge_number FROM officers WHERE officer_id = %s",
        (officer["officer_id"],),
    )
    officer_name = officer_rows[0]["full_name"] if officer_rows else "Officer"
    badge_number = officer_rows[0]["badge_number"] if officer_rows else ""

    output = _build_html(officer_name, badge_number, title, messages)
    filename = f"KSP-{session_id[:8]}.html"
    return StreamingResponse(
        io.BytesIO(output.encode("utf-8")),
        media_type="text/html",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
