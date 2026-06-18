"""
Persistent chat storage.
Sessions and message metadata → Catalyst Data Store (MySQL).
Rich message data (table_data, media_attachments) → Catalyst NoSQL.
"""
import json
import sys
import httpx

from db.connection import execute_query, execute_write
from conversation.history import _nosql_headers
from config.settings import get


def _log(msg):
    print(msg, file=sys.stderr, flush=True)


# ── SESSION OPERATIONS ──────────────────────────────────────────────────────

async def create_session(session_id: str, officer_id: int, title: str) -> bool:
    """
    Insert a new session row.
    Title = first 60 chars of the first question.
    Returns True on success, False on error (non-fatal).
    """
    try:
        await execute_write(
            """INSERT IGNORE INTO chat_sessions
               (session_id, officer_id, title)
               VALUES (%s, %s, %s)""",
            (session_id, officer_id, title[:60])
        )
        return True
    except Exception as e:
        _log(f"WARNING: Failed to create session {session_id}: {e}")
        return False


async def update_session_timestamp(session_id: str, increment_count: bool = True):
    """
    Touch updated_at and optionally bump message_count by 2 (one user + one assistant turn).
    Called after every successful pipeline run.
    """
    try:
        if increment_count:
            await execute_write(
                """UPDATE chat_sessions
                   SET updated_at = NOW(), message_count = message_count + 2
                   WHERE session_id = %s""",
                (session_id,)
            )
        else:
            await execute_write(
                "UPDATE chat_sessions SET updated_at = NOW() WHERE session_id = %s",
                (session_id,)
            )
    except Exception as e:
        _log(f"WARNING: Failed to update session timestamp {session_id}: {e}")


async def get_sessions_for_officer(officer_id: int, limit: int = 30) -> list[dict]:
    """
    Load recent sessions for sidebar.
    Returns list of {session_id, title, created_at, updated_at, message_count}.
    Ordered by updated_at DESC — most recent first.
    """
    try:
        rows = await execute_query(
            """SELECT session_id, title, created_at, updated_at, message_count
               FROM chat_sessions
               WHERE officer_id = %s AND is_active = TRUE
               ORDER BY updated_at DESC
               LIMIT %s""",
            (officer_id, limit)
        )
        # Convert datetime objects to ISO strings for JSON serialization
        result = []
        for row in rows:
            result.append({
                "session_id": row["session_id"],
                "title": row["title"],
                "message_count": row["message_count"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
            })
        return result
    except Exception as e:
        _log(f"WARNING: Failed to load sessions for officer {officer_id}: {e}")
        return []


async def verify_session_owner(session_id: str, officer_id: int) -> bool:
    """
    Check that this session belongs to this officer.
    Used before loading messages or exporting PDF.
    Returns True if owned, False if not found or wrong officer.
    """
    try:
        rows = await execute_query(
            "SELECT officer_id FROM chat_sessions WHERE session_id = %s",
            (session_id,)
        )
        if not rows:
            return False
        return rows[0]["officer_id"] == officer_id
    except Exception as e:
        _log(f"WARNING: Failed to verify session owner: {e}")
        return False


# ── MESSAGE OPERATIONS ───────────────────────────────────────────────────────

async def save_message_pair(
    session_id: str,
    question: str,
    answer_text: str,
    sql_generated: str,
    has_table: bool,
    has_media: bool,
    graph_available: bool,
    table_data: list[dict],
    media_attachments: list[dict],
) -> int | None:
    """
    Save one user message + one assistant message after a pipeline run.

    Steps:
    1. INSERT user message row → get user_message_id
    2. INSERT assistant message row → get assistant_message_id
    3. If has_table or has_media: save rich data to NoSQL keyed by assistant_message_id
    4. Return assistant_message_id (used for rich data key)

    Returns None on failure (non-fatal — history still saved in NoSQL).
    """
    try:
        # User message
        await execute_write(
            """INSERT INTO chat_messages
               (session_id, role, content)
               VALUES (%s, 'user', %s)""",
            (session_id, question)
        )

        # Assistant message
        assistant_id = await execute_write(
            """INSERT INTO chat_messages
               (session_id, role, content, sql_generated,
                has_table, has_media, graph_available)
               VALUES (%s, 'assistant', %s, %s, %s, %s, %s)""",
            (
                session_id, answer_text, sql_generated or "",
                has_table, has_media, graph_available
            )
        )

        # Save rich data to NoSQL if needed
        if (has_table or has_media) and assistant_id:
            await save_rich_data(assistant_id, table_data, media_attachments)

        return assistant_id

    except Exception as e:
        _log(f"WARNING: Failed to save message pair for session {session_id}: {e}")
        return None


async def get_messages_for_session(session_id: str) -> list[dict]:
    """
    Load all messages for a session, ordered oldest first.
    For assistant messages with has_table or has_media: fetches rich data from NoSQL.

    Returns list of message dicts ready for frontend consumption:
    {
        message_id, role, content, sql_generated,
        has_table, has_media, graph_available,
        table_data, media_attachments, created_at
    }
    """
    try:
        rows = await execute_query(
            """SELECT message_id, role, content, sql_generated,
                      has_table, has_media, graph_available, created_at
               FROM chat_messages
               WHERE session_id = %s
               ORDER BY created_at ASC
               LIMIT 100""",
            (session_id,)
        )

        messages = []
        for row in rows:
            msg = {
                "message_id": row["message_id"],
                "role": row["role"],
                "content": row["content"],
                "sql_generated": row["sql_generated"] or "",
                "has_table": bool(row["has_table"]),
                "has_media": bool(row["has_media"]),
                "graph_available": bool(row["graph_available"]),
                "table_data": [],
                "media_attachments": [],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            }

            # Load rich data for assistant messages that have it
            if row["role"] == "assistant" and (row["has_table"] or row["has_media"]):
                rich = await load_rich_data(row["message_id"])
                if rich:
                    msg["table_data"] = rich.get("table_data", [])
                    msg["media_attachments"] = rich.get("media_attachments", [])

            messages.append(msg)

        return messages

    except Exception as e:
        _log(f"WARNING: Failed to load messages for session {session_id}: {e}")
        return []


# ── RICH DATA (NoSQL) ────────────────────────────────────────────────────────

async def save_rich_data(message_id: int, table_data: list, media_attachments: list):
    """
    Save table_data and media_attachments to Catalyst NoSQL.
    Key: msg_rich_{message_id}
    Non-fatal — logs on failure.
    """
    try:
        key = f"msg_rich_{message_id}"
        payload = json.dumps({
            "table_data": table_data,
            "media_attachments": media_attachments,
        }, default=str)

        nosql_base = get("NOSQL_BASE_URL").rstrip("/")
        url = f"{nosql_base}/table/message_rich_data/document"

        async with httpx.AsyncClient() as client:
            await client.post(
                url,
                headers=_nosql_headers(),
                json={"data": {"id": key, "payload": payload}},
                timeout=5.0
            )
    except Exception as e:
        _log(f"WARNING: Failed to save rich data for message {message_id}: {e}")


async def load_rich_data(message_id: int) -> dict | None:
    """
    Load rich data for a message from Catalyst NoSQL.
    Returns parsed dict or None on miss/error.
    """
    try:
        key = f"msg_rich_{message_id}"
        nosql_base = get("NOSQL_BASE_URL").rstrip("/")
        url = f"{nosql_base}/table/message_rich_data/document/{key}"

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers=_nosql_headers(),
                timeout=5.0
            )
            if response.status_code == 200:
                data = response.json()
                raw = data.get("data", {}).get("payload")
                if raw:
                    return json.loads(raw)
        return None
    except Exception as e:
        _log(f"WARNING: Failed to load rich data for message {message_id}: {e}")
        return None
