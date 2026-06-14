"""
Media resolver — for any result rows that carry a fir_id, look up attached
evidence_media records and emit placeholder signed URLs.

Step 5 will swap the placeholder URL for a real Catalyst Stratus signed URL.
"""

from db.connection import execute_query


def _collect_fir_ids(results: list[dict]) -> list[int]:
    """Pull unique, valid integer fir_ids from query results."""
    seen: set[int] = set()
    out: list[int] = []
    for row in results:
        if not isinstance(row, dict):
            continue
        v = row.get("fir_id")
        if v is None:
            continue
        try:
            ivd = int(v)
        except (ValueError, TypeError):
            continue
        if ivd in seen:
            continue
        seen.add(ivd)
        out.append(ivd)
    return out


async def resolve_media(results: list[dict]) -> list[dict]:
    """
    Find attached media for every fir_id present in `results`. Returns a list of:
        {
          "media_type": str,
          "url": str,             # placeholder route until Step 5
          "description": str,
          "fir_id": int,
        }

    Returns [] when nothing applies (empty results, no fir_id column,
    no matching media rows).
    Runs exactly one DB query.
    """
    if not results:
        return []

    fir_ids = _collect_fir_ids(results)
    if not fir_ids:
        return []

    # Build a parameterized IN clause — never interpolate ids into SQL.
    placeholders = ",".join(["%s"] * len(fir_ids))
    sql = (
        "SELECT media_id, fir_id, media_type, file_name, "
        "stratus_folder_id, stratus_file_id, description "
        "FROM evidence_media "
        f"WHERE fir_id IN ({placeholders})"
    )
    rows = await execute_query(sql, tuple(fir_ids))

    out: list[dict] = []
    for r in rows:
        out.append(
            {
                "media_type": r.get("media_type"),
                "url": f"/api/media/{r.get('stratus_file_id')}",
                "description": r.get("description") or r.get("file_name") or "",
                "fir_id": r.get("fir_id"),
            }
        )
    return out
