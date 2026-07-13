"""
Writes SQL provenance for chat answers into chat_evidence_trail -- the
"why did the assistant say this" explainability record. The table was created
in Step 1 but nothing wrote to it until this step. Non-fatal by design: a
failure here must never break a chat turn.
"""
import sys
from db.connection import execute_write
from pipeline.sql_validator import extract_tables
from pipeline.media_resolver import collect_case_master_ids


def _log(msg):
    print(f"[evidence_trail] {msg}", file=sys.stderr, flush=True)


async def save_evidence_trail(message_id: int | None, sql_generated: str | None, table_data: list[dict] | None):
    """
    Persists one row per assistant turn that actually ran SQL.
    DIRECT-path answers (no SQL) are skipped entirely -- there's nothing to
    trail, and that's correct, not an error condition.
    """
    if not sql_generated or not message_id:
        return
    try:
        tables_queried = extract_tables(sql_generated)
        case_ids = collect_case_master_ids(table_data) if table_data else []
        await execute_write(
            """INSERT INTO chat_evidence_trail
               (message_id, sql_executed, tables_queried, row_count, case_ids_referenced)
               VALUES (%s, %s, %s, %s, %s)""",
            (
                message_id,
                sql_generated,
                ",".join(tables_queried),
                len(table_data) if table_data else 0,
                ",".join(str(c) for c in case_ids[:100]),
            )
        )
    except Exception as e:
        _log(f"save_evidence_trail failed for message_id={message_id}: {e}")
