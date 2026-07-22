"""
Enforces station-level row visibility on LLM-generated SQL before execution.
Runs after generate_sql()/validate_sql() succeed, before execute_query().

The LLM's output is never trusted as the actual security boundary -- this
is a deterministic rewrite, not a prompt instruction.

Relies on CaseMaster always being present in every generated query
(schema_catalog.py's always_include=True on CaseMaster guarantees this).
"""
import re
from auth.role_guard import get_scoped_unit_ids

SQL_KEYWORDS = (
    r"WHERE|JOIN|LEFT|RIGHT|INNER|OUTER|CROSS|STRAIGHT_JOIN|ON|GROUP|HAVING|"
    r"ORDER|LIMIT|UNION|USING|SET|AS|END"
)

_CASEMASTER_REF_RE = re.compile(
    r"\b(?:FROM|JOIN)\s+`?CaseMaster`?"
    r"(?:\s+(?:AS\s+)?`?(?!(?:" + SQL_KEYWORDS + r")\b)([A-Za-z_][A-Za-z0-9_]*)`?)?",
    re.IGNORECASE
)


class StationScopeError(Exception):
    """Raised when a query can't be confidently scoped. Caller must fail closed."""


def _casemaster_alias(sql: str) -> str | None:
    """Extract the alias of CaseMaster from the FROM/JOIN clause, or None if not found."""
    m = _CASEMASTER_REF_RE.search(sql)
    if not m:
        return None
    return m.group(1) or "CaseMaster"


def _find_top_level_clause(sql: str) -> tuple[str | None, int]:
    """
    Find top-level WHERE or boundary clause (GROUP BY, HAVING, ORDER BY, LIMIT, UNION).
    Ignores subqueries in parentheses and string literals.
    Returns (clause_name, index) or (None, -1).
    """
    in_single = False
    in_double = False
    in_backtick = False
    paren_depth = 0

    n = len(sql)
    clauses = ["WHERE", "GROUP BY", "HAVING", "ORDER BY", "LIMIT", "UNION"]

    i = 0
    while i < n:
        char = sql[i]

        if char == "'" and not in_double and not in_backtick:
            in_single = not in_single
            i += 1
            continue
        elif char == '"' and not in_single and not in_backtick:
            in_double = not in_double
            i += 1
            continue
        elif char == "`" and not in_single and not in_double:
            in_backtick = not in_backtick
            i += 1
            continue

        if in_single or in_double or in_backtick:
            i += 1
            continue

        if char == "(":
            paren_depth += 1
            i += 1
            continue
        elif char == ")":
            if paren_depth > 0:
                paren_depth -= 1
            i += 1
            continue

        if paren_depth == 0:
            prev_is_word = (i > 0 and (sql[i - 1].isalnum() or sql[i - 1] == "_"))
            if not prev_is_word:
                for clause in clauses:
                    kw_len = len(clause)
                    if sql[i : i + kw_len].upper() == clause:
                        next_char = sql[i + kw_len] if (i + kw_len < n) else " "
                        if not (next_char.isalnum() or next_char == "_"):
                            return clause, i
        i += 1
    return None, -1


# CONTRACT
# takes:  sql (str) — the LLM-generated SQL string, officer (dict) — authenticated officer's JWT payload
# returns: (tuple[str, bool]) — (possibly-rewritten sql, was_scoped)
# raises:  StationScopeError — when CaseMaster's alias can't be located
async def enforce_station_scope(sql: str, officer: dict) -> tuple[str, bool]:
    """
    Returns (possibly-rewritten sql, was_scoped).
    was_scoped is False only when the officer's role is unrestricted
    (analyst/policymaker) -- nothing to inject in that case.
    Raises StationScopeError if CaseMaster's alias can't be located; the
    caller must refuse to execute rather than run an unscoped query for a
    role that should be restricted.
    """
    scoped_ids = await get_scoped_unit_ids(officer)
    if scoped_ids is None:
        return sql, False

    alias = _casemaster_alias(sql)
    if alias is None:
        raise StationScopeError(
            "Could not locate CaseMaster in generated SQL to apply station scope"
        )

    if not scoped_ids:
        scoped_ids = [-1]  # officer has no assigned station -- show nothing, not everything

    # Values are integers sourced from get_scoped_unit_ids()'s own DB
    # lookup, never from user input -- safe to interpolate directly
    # after the int() cast, no injection surface.
    placeholders = ",".join(str(int(i)) for i in scoped_ids)
    condition = f"{alias}.PoliceStationID IN ({placeholders})"

    clause_name, idx = _find_top_level_clause(sql)

    if clause_name == "WHERE":
        # Insert condition right after WHERE clause starts: WHERE <condition> AND ...
        insert_at = idx + len("WHERE")
        rewritten = sql[:insert_at] + f" {condition} AND" + sql[insert_at:]
    elif clause_name in ("GROUP BY", "HAVING", "ORDER BY", "LIMIT", "UNION"):
        # Insert WHERE <condition> before boundary
        rewritten = sql[:idx].rstrip() + f" WHERE {condition} " + sql[idx:]
    else:
        # No top-level WHERE or boundary — append WHERE at the end
        rewritten = sql.rstrip() + f" WHERE {condition}"

    return rewritten, True

