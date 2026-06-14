"""
Schema linker — picks the smallest set of relevant tables for a question.

Algorithm (intentionally simple — keyword presence):
  1. Lowercase the question.
  2. For each table in SCHEMA_CATALOG, score it by how many of its keywords
     appear in the question.
  3. Tables marked `always_include: True` are always added.
  4. Cap result at 5 tables (fir_master plus 4 others) to avoid context bloat.
  5. fir_master is always returned first.
"""

import re
import sys
import os

# Make backend root importable when this file is run directly.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_THIS_DIR)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from db.schema_catalog import SCHEMA_CATALOG  # noqa: E402

_MAX_TABLES = 5


def _keyword_matches(question_lower: str, keyword: str) -> bool:
    """
    Match a keyword against the lowercased question.

    Multi-word keywords ("missing person", "co-accused") use plain substring
    match. Single tokens (no spaces, no hyphens) use a word-boundary match so
    short tokens like "si" or "pi" don't match inside "missing" / "phishing".
    """
    kw = keyword.lower().strip()
    if not kw:
        return False
    if " " in kw or "-" in kw or "_" in kw:
        return kw in question_lower
    pattern = r"\b" + re.escape(kw) + r"\b"
    return re.search(pattern, question_lower) is not None


def select_relevant_tables(question: str) -> list[str]:
    """
    Return a list of table names relevant to the question. fir_master always
    appears first. List length is capped at _MAX_TABLES.
    """
    if not question:
        return ["fir_master"]

    q = question.lower()

    scored: list[tuple[int, str]] = []
    always_in: list[str] = []

    for name, meta in SCHEMA_CATALOG.items():
        if meta.get("always_include"):
            always_in.append(name)
            continue

        score = 0
        for kw in meta.get("keywords", []):
            if _keyword_matches(q, kw):
                score += 1
        if score > 0:
            scored.append((score, name))

    scored.sort(key=lambda x: (-x[0], x[1]))

    # Build final list: fir_master first, then any other always_include tables,
    # then the highest-scoring keyword matches up to the cap.
    out: list[str] = []
    if "fir_master" in always_in:
        out.append("fir_master")
        always_in.remove("fir_master")
    out.extend(always_in)

    for _, name in scored:
        if name in out:
            continue
        if len(out) >= _MAX_TABLES:
            break
        out.append(name)

    return out


if __name__ == "__main__":
    test_questions = [
        "Show me all theft cases",
        "Who is Mahesh Gowda",
        "Show CCTV footage for FIR 2024",
        "List vehicle thefts with accused",
        "How many cases are open?",
        "Show me phishing cases on WhatsApp",
        "Which officer is investigating the most cases?",
        "Find missing person cases not yet found",
        "Show me drug offense cases",
        "List all cases linked to the Bullet Mahesh gang",
    ]
    for q in test_questions:
        tables = select_relevant_tables(q)
        print(f"Q: {q}")
        print(f"   -> {tables}")
        print()
