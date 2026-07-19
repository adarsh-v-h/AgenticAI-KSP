"""
Persistent chat storage.
Sessions and message metadata -> Catalyst Data Store (MySQL).
Rich message data (table_data) -> MySQL table_data_json column.
"""
import json
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from db.connection import execute_query, execute_write


# CONTRACT
# takes:  msg (any) — message to log to stderr
# returns: nothing
# raises:  nothing
def _log(msg):
    print(msg, file=sys.stderr, flush=True)


# CONTRACT
# takes:  dt (datetime | None) — a naive datetime as returned by MySQL (server
#          timezone is UTC, see db/connection.py's aiomysql pool), or None
# returns: (str | None) — ISO 8601 string with an explicit UTC offset, or None
# raises:  nothing
def _utc_iso(dt) -> str | None:
    """
    MySQL TIMESTAMP columns come back from aiomysql as naive datetime objects
    (no tzinfo), even though the server's time_zone is UTC. Calling
    `.isoformat()` directly on them produces a string with no offset (e.g.
    "2026-07-19T05:23:19"), which JS `Date` parses as *local* time rather than
    UTC — this is what caused session timestamps to show the wrong clock time
    in the sidebar. Attaching `timezone.utc` before formatting fixes that.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


# ponytail: single serializer helper, ceiling: one chat payload shape, upgrade: replace with a shared JSON encoder if more stores adopt it.
# CONTRACT
# takes:  obj (any) — object that json.dumps cannot serialize natively
# returns: (str | float) — ISO string for dates/times, float for Decimals
# raises:  TypeError — when the object type is not handled
def _serialize(obj):
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, timedelta):
        total = int(obj.total_seconds())
        h, rem = divmod(total, 3600)
        m, s = divmod(rem, 60)
        return f"{h:02}:{m:02}:{s:02}"
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


# CONTRACT
# takes:  session_id (str) — unique session identifier,
#          officer_id (int) — ID of the officer who owns the session,
#          title (str) — display title for the session (truncated to 60 chars)
# returns: (bool) — True on success, False on failure
# raises:  nothing (catches all exceptions internally)
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


# CONTRACT
# takes:  session_id (str) — session to update,
#          increment_count (bool) — whether to also increment message_count by 2
# returns: nothing
# raises:  nothing (catches all exceptions internally)
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


# CONTRACT
# takes:  officer_id (int) — ID of the officer whose sessions to retrieve,
#          limit (int) — maximum number of sessions to return
# returns: (list[dict]) — list of session metadata dicts ordered by most recently updated
# raises:  nothing (catches all exceptions, returns empty list on failure)
async def get_sessions_for_officer(officer_id: int, limit: int = 30) -> list[dict]:
    try:
        rows = await execute_query(
            """SELECT session_id, title, created_at, updated_at, message_count
               FROM chat_sessions
               WHERE officer_id = %s AND is_active = TRUE AND message_count > 0
               ORDER BY updated_at DESC
               LIMIT %s""",
            (officer_id, limit)
        )
        return [
            {
                "session_id": row["session_id"],
                "title": row["title"],
                "message_count": row["message_count"],
                "created_at": _utc_iso(row["created_at"]),
                "updated_at": _utc_iso(row["updated_at"]),
            }
            for row in rows
        ]
    except Exception as e:
        _log(f"WARNING: Failed to load sessions for officer {officer_id}: {e}")
        return []


# CONTRACT
# takes:  session_id (str) — session to verify ownership of,
#          officer_id (int) — expected owner's ID
# returns: (bool) — True if the officer owns the session, False otherwise
# raises:  nothing (catches all exceptions, returns False on failure)
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


# CONTRACT
# takes:  session_id (str) — session to save messages to,
#          question (str) — the user's question text,
#          answer_text (str) — the assistant's answer text,
#          sql_generated (str) — SQL query that was generated (empty if none),
#          has_table (bool) — whether the response includes tabular data,
#          has_media (bool) — whether the response includes media attachments,
#          graph_available (bool) — whether a graph visualization is available,
#          table_data (list[dict]) — raw query result rows to persist,
#          media_attachments (list[dict]) — media references for the response,
#          assistant_follow_ups (list | None) — suggested follow-up questions
# returns: (int | None) — the assistant message's row ID, or None on failure
# raises:  nothing (catches all exceptions internally)
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
    assistant_follow_ups: list | None = None,
) -> int | None:
    try:
        table_json = None
        if has_table and table_data:
            table_json = json.dumps(table_data, default=_serialize)

        follow_ups_json = None
        if assistant_follow_ups:
            follow_ups_json = json.dumps(assistant_follow_ups, default=_serialize)

        await execute_write(
            """INSERT INTO chat_messages
               (session_id, role, content)
               VALUES (%s, 'user', %s)""",
            (session_id, question)
        )

        assistant_id = await execute_write(
            """INSERT INTO chat_messages
               (session_id, role, content, sql_generated,
                has_table, has_media, graph_available, table_data_json, follow_ups_json)
               VALUES (%s, 'assistant', %s, %s, %s, %s, %s, %s, %s)""",
            (
                session_id, answer_text, sql_generated or "",
                has_table, has_media, graph_available, table_json, follow_ups_json
            )
        )

        return assistant_id

    except Exception as e:
        _log(f"WARNING: Failed to save message pair for session {session_id}: {e}")
        return None


# CONTRACT
# takes:  session_id (str) — session whose messages to retrieve
# returns: (list[dict]) — ordered list of message dicts with parsed table_data and follow_ups
# raises:  nothing (catches all exceptions, returns empty list on failure)
async def get_messages_for_session(session_id: str) -> list[dict]:
    try:
        rows = await execute_query(
            """SELECT message_id, role, content, sql_generated,
                      has_table, has_media, graph_available,
                      table_data_json, follow_ups_json, created_at
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

            suggested_follow_ups = []
            if row.get("follow_ups_json"):
                try:
                    suggested_follow_ups = json.loads(row["follow_ups_json"])
                except Exception:
                    suggested_follow_ups = []

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
                "suggested_follow_ups": suggested_follow_ups,
                "created_at": _utc_iso(row["created_at"]),
            }
            messages.append(msg)

        return messages

    except Exception as e:
        _log(f"WARNING: Failed to load messages for session {session_id}: {e}")
        return []


# CONTRACT
# takes:  message_id (int) — message row ID to look up,
#          officer_id (int) — EmployeeID of the requesting officer
# returns: (dict | None) — evidence trail row scoped to the officer, or None if not found/not owned/no trail
# raises:  nothing (catches all exceptions, returns None on failure)
async def get_evidence_trail_for_message(message_id: int, officer_id: int) -> dict | None:
    """
    Returns the chat_evidence_trail row for a message, scoped to the
    requesting officer via a join through chat_messages -> chat_sessions.
    Returns None if the message doesn't exist, belongs to another officer,
    or has no evidence trail row.
    """
    try:
        rows = await execute_query(
            """SELECT et.trail_id, et.message_id, et.sql_executed, et.tables_queried,
                      et.row_count, et.case_ids_referenced, et.created_at
               FROM chat_evidence_trail et
               JOIN chat_messages cm ON cm.message_id = et.message_id
               JOIN chat_sessions cs ON cs.session_id = cm.session_id
               WHERE et.message_id = %s AND cs.officer_id = %s""",
            (message_id, officer_id)
        )
        if not rows:
            return None
        row = rows[0]
        row["created_at"] = str(row["created_at"]) if row.get("created_at") else None
        return row
    except Exception as e:
        _log(f"WARNING: get_evidence_trail_for_message failed: {e}")
        return None
