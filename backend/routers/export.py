"""
PDF export endpoint.
Renders a chat session as HTML and converts to PDF via Catalyst SmartBrowz.
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from auth.simple_auth import get_current_officer
from db.chat_store import get_messages_for_session, verify_session_owner
from db.connection import execute_query
from conversation.history import get_history
import sys
import httpx
from config.settings import get
from datetime import datetime
import io
import html

router = APIRouter()


def _escape(value) -> str:
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


def _merge_history_tables(messages: list[dict], history: list[dict]) -> list[dict]:
    """
    Fill missing assistant table_data from conversation-history snapshots.

    The UI can show tables directly from the live stream even when rich message
    persistence is unavailable. Export reloads persisted messages, so use the
    bounded history snapshot as a fallback for older or partially-saved turns.
    """
    table_turns = [
        turn
        for turn in history
        if isinstance(turn, dict)
        and turn.get("role") == "assistant"
        and isinstance(turn.get("table"), list)
        and turn.get("table")
    ]
    if not table_turns:
        return messages

    tables_by_content: dict[str, list[list[dict]]] = {}
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


def _build_html(officer_name: str, badge_number: str, title: str, messages: list[dict]) -> str:
    """
    Build a clean, print-ready HTML string for the chat session.
    """
    messages_html = ""
    for msg in messages:
        if msg["role"] == "user":
            messages_html += f"""
            <div class="message user">
                <div class="bubble">{_escape(msg["content"])}</div>
            </div>"""
        else:
            content = _escape(msg["content"]).replace('\n', '<br>')
            messages_html += f"""
            <div class="message assistant">
                <div class="label">ASSISTANT</div>
                <div class="content">{content}</div>"""

            # Add table if present
            if msg.get("table_data"):
                rows = msg["table_data"]
                if rows:
                    cols = list(rows[0].keys())
                    thead = "".join(f"<th>{_escape(c)}</th>" for c in cols)
                    tbody = ""
                    for row in rows[:50]:  # max 50 rows in PDF
                        cells = "".join(f"<td>{_escape(row.get(c, ''))}</td>" for c in cols)
                        tbody += f"<tr>{cells}</tr>"
                    footer = (
                        f"Showing first 50 of {len(rows)} records."
                        if len(rows) > 50
                        else f"{len(rows)} record{'s' if len(rows) != 1 else ''}."
                    )
                    messages_html += f"""
                    <div class="table-wrap">
                        <table>
                            <thead><tr>{thead}</tr></thead>
                            <tbody>{tbody}</tbody>
                        </table>
                        <div class="table-footer">{footer}</div>
                    </div>"""

            messages_html += "</div>"

    export_date = datetime.now().strftime("%d %B %Y, %I:%M %p")

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  body {{ font-family: Arial, sans-serif; padding: 40px; color: #1a1a1a; font-size: 13px; }}
  .header {{ border-bottom: 2px solid #cc785c; padding-bottom: 16px; margin-bottom: 24px; }}
  .header h1 {{ font-size: 18px; margin: 0; color: #cc785c; }}
  .header p {{ font-size: 11px; color: #666; margin: 4px 0 0; }}
  .message {{ margin-bottom: 18px; }}
  .message.user {{ text-align: right; }}
  .message.user .bubble {{
    display: inline-block; background: #f0ebe3; padding: 10px 14px;
    border-radius: 12px; max-width: 80%; font-size: 13px;
  }}
  .message.assistant .label {{ font-size: 10px; color: #999; margin-bottom: 4px; letter-spacing: 0.05em; }}
  .message.assistant .content {{ font-size: 13px; line-height: 1.6; }}
  .table-wrap {{ margin-top: 10px; overflow-x: auto; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 11px; }}
  th {{ background: #cc785c; color: #fff; padding: 5px 8px; text-align: left; }}
  td {{ border: 1px solid #e0d9d0; padding: 5px 8px; }}
  tr:nth-child(even) td {{ background: #faf9f5; }}
  .table-footer {{ font-size: 10px; color: #666; margin-top: 6px; }}
  .footer {{ margin-top: 40px; font-size: 10px; color: #999; border-top: 1px solid #e0d9d0; padding-top: 12px; }}
</style>
</head>
<body>
  <div class="header">
    <h1>KSP Crime Intelligence — Conversation Export</h1>
    <p>Officer: {_escape(officer_name)} ({_escape(badge_number)}) &nbsp;|&nbsp; Session: {_escape(title)} &nbsp;|&nbsp; Exported: {export_date}</p>
  </div>
  {messages_html}
  <div class="footer">
    Karnataka State Police &nbsp;|&nbsp; Confidential &nbsp;|&nbsp; Not for public distribution
  </div>
</body>
</html>"""


@router.post("/api/chat/sessions/{session_id}/export")
async def export_session_pdf(
    session_id: str,
    officer: dict = Depends(get_current_officer)
):
    """
    Export a chat session as a PDF.
    1. Verify session belongs to this officer.
    2. Load all messages.
    3. Build HTML.
    4. Call Catalyst SmartBrowz to convert to PDF.
    5. Stream PDF back as a file download.
    """
    # Verify ownership
    owned = await verify_session_owner(session_id, officer["officer_id"])
    if not owned:
        raise HTTPException(status_code=404, detail="Session not found.")

    # Load messages
    messages = await get_messages_for_session(session_id)
    if not messages:
        raise HTTPException(status_code=400, detail="No messages to export.")

    # If message_rich_data is missing, recover table snapshots saved for
    # follow-up questions so exported reports still include visible DB rows.
    history = await get_history(session_id)
    messages = _merge_history_tables(messages, history)

    # Get session title
    rows = await execute_query(
        "SELECT title FROM chat_sessions WHERE session_id = %s",
        (session_id,)
    )
    title = rows[0]["title"] if rows else "Chat Export"

    # Get officer info
    officer_rows = await execute_query(
        "SELECT full_name, badge_number FROM officers WHERE officer_id = %s",
        (officer["officer_id"],)
    )
    officer_name = officer_rows[0]["full_name"] if officer_rows else "Officer"
    badge_number = officer_rows[0]["badge_number"] if officer_rows else ""

    # Build HTML
    html = _build_html(officer_name, badge_number, title, messages)

    # Call Catalyst SmartBrowz
    pdf_bytes = None
    try:
        smartbrowz_url = get("SMARTBROWZ_URL")
        async with httpx.AsyncClient() as client:
            response = await client.post(
                smartbrowz_url,
                headers={
                    "Authorization": f"Zoho-oauthtoken {get('CATALYST_API_TOKEN')}",
                    "Content-Type": "application/json",
                    "CATALYST-ORG": get("CATALYST_ORG_ID"),
                },
                json={"html": html, "output": "pdf"},
                timeout=30.0
            )
            if response.status_code == 200:
                pdf_bytes = response.content
            else:
                print(
                    f"ERROR: SmartBrowz PDF generation failed with status {response.status_code}: {response.text}",
                    file=sys.stderr,
                    flush=True
                )
    except Exception as e:
        print(f"ERROR: SmartBrowz connection failed: {e}", file=sys.stderr, flush=True)

    if not pdf_bytes:
        # Fallback: return HTML
        return StreamingResponse(
            io.BytesIO(html.encode()),
            media_type="text/html",
            headers={"Content-Disposition": f'attachment; filename="KSP-{session_id}.html"'}
        )

    filename = f"KSP-Chat-{session_id[:8]}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )
