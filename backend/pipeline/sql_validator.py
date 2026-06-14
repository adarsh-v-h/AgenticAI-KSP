"""
SQL validator — last line of defense before any LLM-generated SQL is executed.

Checks (in order):
  1. Non-empty after sanitize.
  2. Not the special CANNOT_ANSWER sentinel.
  3. Starts with SELECT.
  4. No forbidden keywords (DROP, DELETE, UPDATE, INSERT, ...).
  5. Every table referenced after FROM/JOIN is in ALLOWED_TABLES.

The connection layer enforces the SELECT-only rule a second time. This module
also strips markdown fences and stray backticks from raw LLM output.
"""

import re
import sys
import os
from dataclasses import dataclass

# Allow running this file directly for self-test.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_THIS_DIR)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from db.schema_catalog import ALLOWED_TABLES  # noqa: E402


FORBIDDEN_KEYWORDS = [
    "drop", "delete", "update", "insert", "create", "alter",
    "truncate", "replace", "merge", "grant", "revoke",
    "--", ";--", "/*", "*/", "xp_", "exec(", "execute(",
    "union select", "1=1", " or 1", "'; ", "load_file", "into outfile",
]

# Words that contain "create"/"update" etc. as substrings but are legitimate
# column names. We run forbidden-keyword detection only on a "tokenized" copy
# of the SQL where these column-name fragments have been stripped.
_BENIGN_TOKENS_PATTERN = re.compile(
    r"\b(?:created_at|updated_at|created_by|updated_by|date_created|date_updated)\b",
    re.IGNORECASE,
)


@dataclass
class ValidationResult:
    is_valid: bool
    error: str | None = None


def sanitize_sql(sql: str) -> str:
    """
    Clean up the raw LLM output:
      - strip whitespace
      - strip leading/trailing markdown code fences (```sql ... ```)
      - strip stray surrounding backticks
      - drop trailing semicolons
    Backticks INSIDE the SQL (e.g. `rank`) are preserved.
    """
    if not sql:
        return ""

    text = sql.strip()

    # Strip a leading ```sql (or ```mysql, ```) fence.
    fence = re.match(r"^```(?:sql|mysql)?\s*\n?", text, flags=re.IGNORECASE)
    if fence:
        text = text[fence.end():]
    # Strip a trailing ``` fence.
    if text.endswith("```"):
        text = text[: -3]
    text = text.strip()

    # Strip a single pair of wrapping backticks (only if the whole thing is wrapped).
    if text.startswith("`") and text.endswith("`") and text.count("`") == 2:
        text = text[1:-1].strip()

    # Drop trailing semicolons (one or more).
    while text.endswith(";"):
        text = text[:-1].rstrip()

    return text.strip()


def _extract_tables(sql: str) -> list[str]:
    """
    Pull out table names that appear after FROM and JOIN clauses.

    This is a regex pass — not a real parser. It accepts simple identifiers
    optionally backtick-quoted, optionally followed by an alias. Anything
    weirder we just skip; MySQL itself catches malformed cases at execute time.
    """
    pattern = re.compile(
        r"\b(?:from|join)\s+([`\"]?[a-zA-Z_][a-zA-Z0-9_]*[`\"]?)",
        re.IGNORECASE,
    )
    raw = pattern.findall(sql)
    cleaned = []
    for r in raw:
        name = r.strip("`\"")
        if name:
            cleaned.append(name)
    return cleaned


def validate_sql(sql: str, allowed_tables: list[str] | None = None) -> ValidationResult:
    """
    Validate a sanitized (or near-sanitized) SQL string. Returns a
    ValidationResult; never raises.
    """
    if allowed_tables is None:
        allowed_tables = ALLOWED_TABLES

    if sql is None:
        return ValidationResult(False, "SQL is None.")

    cleaned = sanitize_sql(sql)
    if not cleaned:
        return ValidationResult(False, "SQL is empty.")

    if cleaned.strip().upper() == "CANNOT_ANSWER":
        return ValidationResult(False, "Model returned CANNOT_ANSWER.")

    upper = cleaned.upper().lstrip()
    if not upper.startswith("SELECT") and not upper.startswith("WITH "):
        return ValidationResult(False, "SQL must start with SELECT.")

    # Block multi-statement payloads — the easiest injection vector.
    # `;` only legal as a trailing semicolon; sanitize already strips trailing.
    if ";" in cleaned:
        return ValidationResult(
            False,
            "Multiple statements detected (semicolon inside query is not allowed).",
        )

    # Run forbidden-keyword search on a copy with column-name false positives stripped.
    scrub = _BENIGN_TOKENS_PATTERN.sub(" ", cleaned).lower()
    for kw in FORBIDDEN_KEYWORDS:
        if kw in scrub:
            return ValidationResult(
                False, f"Forbidden keyword/sequence detected: '{kw}'."
            )

    # Table allow-list check.
    referenced = _extract_tables(cleaned)
    if referenced:
        allowed = {t.lower() for t in allowed_tables}
        for tbl in referenced:
            if tbl.lower() not in allowed:
                return ValidationResult(
                    False, f"Unknown table referenced: '{tbl}'."
                )

    return ValidationResult(True, None)


if __name__ == "__main__":
    cases = [
        ("SELECT * FROM fir_master", True),
        ("DROP TABLE fir_master", False),
        ("SELECT * FROM fir_master; DROP TABLE accused", False),
        ("select fir_id from fir_master where status = 'open'", True),
        ("UPDATE fir_master SET status = 'closed'", False),
        ("```sql\nSELECT * FROM fir_master\n```", True),
        ("SELECT created_at FROM fir_master", True),  # no false positive on "create"
        ("SELECT * FROM secret_table", False),  # unknown table
        ("", False),
        ("CANNOT_ANSWER", False),
        (
            "SELECT f.fir_number FROM fir_master f JOIN accused a ON a.fir_id = f.fir_id WHERE a.full_name LIKE '%Mahesh%'",
            True,
        ),
        ("SELECT * FROM fir_master WHERE 1=1", False),  # injection-y
    ]

    failed = 0
    for sql, expected in cases:
        cleaned = sanitize_sql(sql)
        result = validate_sql(cleaned)
        ok = result.is_valid == expected
        status = "PASS" if ok else "FAIL"
        if not ok:
            failed += 1
        print(f"[{status}] expected={expected} got={result.is_valid} :: {sql[:60]}")
        if not ok:
            print(f"        cleaned: {cleaned!r}")
            print(f"        error:   {result.error}")

    print(f"\n{len(cases) - failed}/{len(cases)} validator tests passed.")
    sys.exit(0 if failed == 0 else 1)
