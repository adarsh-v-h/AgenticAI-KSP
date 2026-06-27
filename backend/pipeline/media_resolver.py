"""
Media resolver â€” for any result rows that carry a case_master_id, look up attached
evidence_media records and emit placeholder signed URLs.

Step 5 will swap the placeholder URL for a real Catalyst Stratus signed URL.
"""

import hashlib

from db.connection import execute_query


def collect_case_master_ids(results: list[dict]) -> list[int]:
    """Pull unique, valid integer CaseMasterIDs from query results."""
    seen: set[int] = set()
    out: list[int] = []
    for row in results:
        if not isinstance(row, dict):
            continue
        value = row.get("CaseMasterID") or row.get("case_master_id")
        if value is None:
            continue
        try:
            case_id = int(value)
        except (ValueError, TypeError):
            continue
        if case_id not in seen:
            seen.add(case_id)
            out.append(case_id)
    return out


def _stable_seed_value(value: str) -> int:
    """Return a deterministic numeric seed from a string."""
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def _dummy_media_url(media_type: str | None, stratus_file_id: str | None) -> str | None:
    """Map seeded Stratus placeholder IDs to a public dummy media URL."""
    if not stratus_file_id:
        return None

    seed = str(stratus_file_id).replace(" ", "_")
    stable_value = _stable_seed_value(seed)

    if media_type == "image":
        return f"https://picsum.photos/seed/{seed}/680/450"

    video_samples = [
        "https://samplelib.com/lib/preview/mp4/sample-5s.mp4",
        "https://samplelib.com/lib/preview/mp4/sample-10s.mp4",
    ]
    audio_samples = [
        "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3",
        "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-2.mp3",
    ]

    if media_type == "video":
        return video_samples[stable_value % len(video_samples)]
    if media_type == "audio":
        return audio_samples[stable_value % len(audio_samples)]

    return None


async def resolve_media(results: list[dict]) -> list[dict]:
    """
    Find attached media for every CaseMasterID present in `results`. Returns a list of:
        {
          "media_type": str,
          "url": str,
          "description": str,
          "case_master_id": int,
        }

    Returns [] when nothing applies (empty results, no CaseMasterID column,
    no matching media rows).
    Runs exactly one DB query.
    """
    if not results:
        return []

    case_master_ids = collect_case_master_ids(results)
    if not case_master_ids:
        return []

    # Build a parameterized IN clause â€” never interpolate ids into SQL.
    placeholders = ",".join(["%s"] * len(case_master_ids))
    sql = (
        "SELECT media_id, case_master_id, media_type, file_name, "
        "stratus_folder_id, stratus_file_id, description "
        "FROM evidence_media "
        f"WHERE case_master_id IN ({placeholders})"
    )
    rows = await execute_query(sql, tuple(case_master_ids))

    out: list[dict] = []
    for r in rows:
        url = _dummy_media_url(r.get("media_type"), r.get("stratus_file_id"))
        if url is None:
            url = f"/api/media/unavailable?file={r.get('stratus_file_id')}"

        out.append(
            {
                "media_type": r.get("media_type"),
                "url": url,
                "description": r.get("description") or r.get("file_name") or "",
                "case_master_id": r.get("case_master_id"),
            }
        )
    return out


