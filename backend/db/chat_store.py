"""
Persistent chat storage.
Sessions and message metadata ? Catalyst Data Store (MySQL).
Rich message data (table_data) ? MySQL table_data_json column.
"""
import json
import sys
from datetime import date, datetime, timedelta

from db.connection import execute_query, execute_write


def _log(msg):
    print(msg, file=sys.stderr, flush=True)


# ponytail: single serializer helper, ceiling: one chat payload shape, upgrade: replace with a shared JSON encoder if more stores adopt it.
def _serialize(obj):
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, timedelta):
        total = int(obj.total_seconds())
        h, rem = divmod(total, 3600)
        m, s = divmod(rem, 60)
        return f"{h:02}:{m:02}:{s:02}"
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


async def create_session(session_id: str, officer_id: int, title: str) -> bool:
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
    try:
        rows = await execute_query(
            """SELECT session_id, title, created_at, updated_at, message_count
               FROM chat_sessions
               WHERE officer_id = %s AND is_active = TRUE
               ORDER BY updated_at DESC
               LIMIT %s""",
            (officer_id, limit)
        )
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
    try:
        table_json = None
        if has_table and table_data:
            table_json = json.dumps(table_data, default=_serialize)

        await execute_write(
            """INSERT INTO chat_messages
               (session_id, role, content)
               VALUES (%s, 'user', %s)""",
            (session_id, question)
        )

        assistant_id = await execute_write(
            """INSERT INTO chat_messages
               (session_id, role, content, sql_generated,
                has_table, has_media, graph_available, table_data_json)
               VALUES (%s, 'assistant', %s, %s, %s, %s, %s, %s)""",
            (
                session_id, answer_text, sql_generated or "",
                has_table, has_media, graph_available, table_json
            )
        )

        return assistant_id

    except Exception as e:
        _log(f"WARNING: Failed to save message pair for session {session_id}: {e}")
        return None


async def get_messages_for_session(session_id: str) -> list[dict]:
    try:
        rows = await execute_query(
            """SELECT message_id, role, content, sql_generated,
                      has_table, has_media, graph_available,
                      table_data_json, created_at
               FROM chat_messages
               WHERE session_id = %s
               ORDER BY created_at ASC
               LIMIT 100""",
            (session_id,)
        )

        messages = []
        for row in rows:
            table_data = []
            if row.get("table_data_json"):
                try:
                    table_data = json.loads(row["table_data_json"])
                except Exception:
                    table_data = []

            msg = {
                "message_id": row["message_id"],
                "role": row["role"],
                "content": row["content"],
                "sql_generated": row["sql_generated"] or "",
                "has_table": bool(row["has_table"]),
                "has_media": bool(row["has_media"]),
                "graph_available": bool(row["graph_available"]),
                "table_data": table_data,
                "media_attachments": [],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            }
            messages.append(msg)

        return messages

    except Exception as e:
        _log(f"WARNING: Failed to load messages for session {session_id}: {e}")
        return []
