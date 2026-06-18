"""
PDF export endpoint.
Renders a chat session as HTML and converts to PDF via Catalyst SmartBrowz.
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from auth.simple_auth import get_current_officer
from db.chat_store import get_messages_for_session, verify_session_owner
from db.connection import execute_query
import httpx
from config.settings import get
from datetime import datetime
import io

router = APIRouter()


def _build_html(officer_name: str, badge_number: str, title: str, messages: list[dict]) -> str:
    """
    Build a clean, print-ready HTML string for the chat session.
    """
    messages_html = ""
    for msg in messages:
        if msg["role"] == "user":
            messages_html += f"""
            <div class="message user">
                <div class="bubble">{msg["content"]}</div>
            </div>"""
        else:
            content = msg["content"].replace('\n', '<br>')
            messages_html += f"""
            <div class="message assistant">
                <div class="label">ASSISTANT</div>
                <div class="content">{content}</div>"""

            # Add table if present
            if msg.get("table_data"):
                rows = msg["table_data"]
                if rows:
                    cols = list(rows[0].keys())
                    thead = "".join(f"<th>{c}</th>" for c in cols)
                    tbody = ""
                    for row in rows[:50]:  # max 50 rows in PDF
                        cells = "".join(f"<td>{row.get(c, '')}</td>" for c in cols)
                        tbody += f"<tr>{cells}</tr>"
                    messages_html += f"""
                    <table>
                        <thead><tr>{thead}</tr></thead>
                        <tbody>{tbody}</tbody>
                    </table>"""

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
  table {{ width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 11px; }}
  th {{ background: #cc785c; color: #fff; padding: 5px 8px; text-align: left; }}
  td {{ border: 1px solid #e0d9d0; padding: 5px 8px; }}
  tr:nth-child(even) td {{ background: #faf9f5; }}
  .footer {{ margin-top: 40px; font-size: 10px; color: #999; border-top: 1px solid #e0d9d0; padding-top: 12px; }}
</style>
</head>
<body>
  <div class="header">
    <h1>KSP Crime Intelligence — Conversation Export</h1>
    <p>Officer: {officer_name} ({badge_number}) &nbsp;|&nbsp; Session: {title} &nbsp;|&nbsp; Exported: {export_date}</p>
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
    try:
        smartbrowz_url = get("SMARTBROWZ_URL")
        async with httpx.AsyncClient() as client:
            response = await client.post(
                smartbrowz_url,
                headers={
                    "Authorization": f"Bearer {get('CATALYST_API_TOKEN')}",
                    "Content-Type": "application/json",
                    "CATALYST-ORG": get("CATALYST_ORG_ID"),
                },
                json={"html": html, "output": "pdf"},
                timeout=30.0
            )
            if response.status_code == 200:
                pdf_bytes = response.content
            else:
                # SmartBrowz failed — return HTML as fallback (downloadable)
                # This lets you demo the feature even if SmartBrowz API path is off
                return StreamingResponse(
                    io.BytesIO(html.encode()),
                    media_type="text/html",
                    headers={"Content-Disposition": f'attachment; filename="KSP-{session_id}.html"'}
                )
    except Exception:
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
