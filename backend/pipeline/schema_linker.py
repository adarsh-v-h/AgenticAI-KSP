"""
Schema linker — picks the smallest set of relevant tables for a question
and captures entity resolution assumptions for Rule 12.
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

_MAX_TABLES = 6

_FUZZY_ASSUMPTIONS = [
    ("vehicle", "Assuming 'vehicle' refers to CrimeSubHead 'Vehicle Theft'"),
    ("cyber", "Assuming 'cyber' refers to CrimeHead 'Cyber Crimes'"),
    ("phishing", "Assuming 'phishing' refers to CrimeSubHead 'Phishing' under Cyber Crimes"),
    ("drug", "Assuming 'drug' refers to CrimeSubHead 'Drug Offense'"),
    ("assault", "Assuming 'assault' refers to CrimeSubHead 'Assault' under Crimes Against Person"),
    ("murder", "Assuming 'murder' refers to CrimeSubHead 'Murder' under Crimes Against Person"),
    ("robbery", "Assuming 'robbery' refers to CrimeSubHead 'Robbery'"),
]


# CONTRACT
# takes:  question_lower (str) — lowercased user question, keyword (str) — keyword to match against
# returns: (bool) — True if the keyword is present in the question respecting word boundaries
# raises:  nothing
def _keyword_matches(question_lower: str, keyword: str) -> bool:
    kw = keyword.lower().strip()
    if not kw:
        return False
    if " " in kw or "-" in kw or "_" in kw:
        return kw in question_lower
    pattern = r"\b" + re.escape(kw) + r"\b"
    return re.search(pattern, question_lower) is not None


# CONTRACT
# takes:  question (str) — natural language question from the user
# returns: (tuple[list[str], list[str]]) — (relevant_table_names, list_of_assumptions)
# raises:  nothing
def select_relevant_tables(question: str) -> tuple[list[str], list[str]]:
    """
    Return a tuple of (table_names, assumptions). CaseMaster always appears first.
    Table names list length is capped at _MAX_TABLES.
    """
    if not question:
        return ["CaseMaster"], []

    q = question.lower()
    assumptions: list[str] = []

    # Rule 12: Capture entity resolution assumptions
    for kw, assumption_text in _FUZZY_ASSUMPTIONS:
        if _keyword_matches(q, kw):
            assumptions.append(assumption_text)

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

    out: list[str] = []
    if "CaseMaster" in always_in:
        out.append("CaseMaster")
        always_in.remove("CaseMaster")
    out.extend(always_in)

    for _, name in scored:
        if name in out:
            continue
        if len(out) >= _MAX_TABLES:
            break
        out.append(name)

    if "Employee" in out:
        for dep in ("Rank", "Designation"):
            if dep in SCHEMA_CATALOG and dep not in out and len(out) < _MAX_TABLES:
                out.append(dep)

    return out, assumptions


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
        tables, asm = select_relevant_tables(q)
        print(f"Q: {q}")
        print(f"   -> tables: {tables}")
        print(f"   -> assumptions: {asm}")
        print()
