"""
Shared utility for date predicate extraction and rewriting across Rule 7 and Rule 11.
"""
import re

_DATE_PREDICATE_RE = re.compile(
    r"\b(?:YEAR\s*\(\s*`?(?:[A-Za-z0-9_]+\.)?`?(?P<year_col>CrimeRegisteredDate|FIRDate|DateOfOccurrence|Date_Of_Occurrence)`?\s*\)\s*(?P<year_op>=|>=|<=|>|<)\s*(?P<year_val>\d{4}))|"
    r"\b(?:`?(?:[A-Za-z0-9_]+\.)?`?(?P<date_col>CrimeRegisteredDate|FIRDate|DateOfOccurrence|Date_Of_Occurrence)`?\s*(?P<date_op>=|>=|<=|>|<)\s*['\"](?P<date_val>\d{4}-\d{2}-\d{2})['\"])",
    re.IGNORECASE
)


# CONTRACT
# takes:  sql (str) — generated SQL string to inspect for date predicates
# returns: (dict | None) — extracted date filter dict or None if no date filter found
# raises:  nothing
def extract_date_predicate(sql: str) -> dict | None:
    """
    Extract date column, operator, and value from a SQL string.
    Returns dict like:
      {"column": "CrimeRegisteredDate", "operator": "=", "value": "2026", "raw_clause": "..."}
    or None if no date predicate is found.
    """
    if not sql:
        return None

    m = _DATE_PREDICATE_RE.search(sql)
    if not m:
        return None

    gd = m.groupdict()
    if gd.get("year_col"):
        col = gd["year_col"]
        op = gd["year_op"]
        val = gd["year_val"]
    else:
        col = gd["date_col"]
        op = gd["date_op"]
        val = gd["date_val"]

    return {
        "column": col,
        "operator": op,
        "value": val,
        "raw_clause": m.group(0)
    }


# CONTRACT
# takes:  sql (str) — original SQL string, new_year (int) — target year to substitute
# returns: (str) — rewritten SQL string with new year inserted
# raises:  nothing
def rewrite_date_predicate(sql: str, new_year: int) -> str:
    """
    Rewrite the date predicate in SQL to use `new_year`.
    Returns original SQL if no date predicate matches.
    """
    if not sql:
        return sql

    def _replace(m: re.Match) -> str:
        gd = m.groupdict()
        if gd.get("year_col"):
            raw = m.group(0)
            val = gd["year_val"]
            return raw.replace(val, str(new_year))
        elif gd.get("date_col"):
            raw = m.group(0)
            val = gd["date_val"]
            new_date = f"{new_year}{val[4:]}"
            return raw.replace(val, new_date)
        return m.group(0)

    return _DATE_PREDICATE_RE.sub(_replace, sql)
