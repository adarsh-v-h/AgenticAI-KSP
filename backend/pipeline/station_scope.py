"""
Enforces station-level row visibility on LLM-generated SQL before execution.
Runs after generate_sql()/validate_sql() succeed, before execute_query().

The LLM's output is never trusted as the actual security boundary -- this
is a deterministic rewrite, not a prompt instruction.
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

_EMPLOYEE_REF_RE = re.compile(
    r"\b(?:FROM|JOIN)\s+`?Employee`?"
    r"(?:\s+(?:AS\s+)?`?(?!(?:" + SQL_KEYWORDS + r")\b)([A-Za-z_][A-Za-z0-9_]*)`?)?",
    re.IGNORECASE
)

_WIDE_SCOPE_KEYWORDS = (
    "karnataka", "state", "all stations", "district", "statewide", "all cases"
)
_FIRST_PERSON_KEYWORDS = (
    "my", "i'm", "assigned to me", "i am", "my station", "me"
)


class StationScopeError(Exception):
    """Raised when a query can't be confidently scoped. Caller must fail closed."""


def _casemaster_alias(sql: str) -> str | None:
    """Extract the alias of CaseMaster from the FROM/JOIN clause, or None if not found."""
    m = _CASEMASTER_REF_RE.search(sql)
    if not m:
        return None
    return m.group(1) or "CaseMaster"


def _employee_alias(sql: str) -> str | None:
    """Extract the alias of Employee from the FROM/JOIN clause, or None if not found."""
    m = _EMPLOYEE_REF_RE.search(sql)
    if not m:
        return None
    return m.group(1) or "Employee"


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


def _compute_scope_disclaimer_needed(question: str, was_scoped: bool) -> bool:
    """
    Determines whether a scope disclosure disclaimer should be shown.
    Returns True if:
      - was_scoped is True (officer is restricted)
      - user question contains a wide-scope keyword ("all cases", "statewide", etc.)
      - user question DOES NOT contain first-person keywords ("my", "assigned to me")
    """
    if not was_scoped or not question:
        return False

    q_lower = question.lower()
    has_wide_scope = any(kw in q_lower for kw in _WIDE_SCOPE_KEYWORDS)
    has_first_person = any(kw in q_lower for kw in _FIRST_PERSON_KEYWORDS)

    return has_wide_scope and not has_first_person


# CONTRACT
# takes:  sql (str) — the LLM-generated SQL string, officer (dict) — authenticated officer's JWT payload, question (str) — natural language user question
# returns: (tuple[str, bool, bool]) — (possibly-rewritten sql, was_scoped, scope_disclaimer_needed)
# raises:  StationScopeError — when neither CaseMaster nor Employee alias can be located
async def enforce_station_scope(sql: str, officer: dict, question: str = "") -> tuple[str, bool, bool]:
    """
    Returns (possibly-rewritten sql, was_scoped, scope_disclaimer_needed).
    was_scoped is False only when the officer's role is unrestricted
    (analyst/policymaker) -- nothing to inject in that case.
    Raises StationScopeError if neither CaseMaster nor Employee alias can be located.
    """
    scoped_ids = await get_scoped_unit_ids(officer)
    if scoped_ids is None:
        return sql, False, False

    if not scoped_ids:
        scoped_ids = [-1]  # officer has no assigned station -- show nothing, not everything

    placeholders = ",".join(str(int(i)) for i in scoped_ids)
    employee_id = officer.get("EmployeeID") or officer.get("officer_id")

    cm_alias = _casemaster_alias(sql)
    emp_alias = _employee_alias(sql)

    if cm_alias:
        # Check if PolicePersonID filter is present for assigned case protection (Rule 5)
        has_person_id_filter = bool(employee_id and re.search(r"\bPolicePersonID\s*=", sql, re.IGNORECASE))
        if has_person_id_filter:
            condition = f"({cm_alias}.PoliceStationID IN ({placeholders}) OR {cm_alias}.PolicePersonID = {int(employee_id)})"
        else:
            condition = f"{cm_alias}.PoliceStationID IN ({placeholders})"
    elif emp_alias:
        # Rule 3: Secondary scoping on Employee.UnitID when querying Employee directly
        condition = f"{emp_alias}.UnitID IN ({placeholders})"
    else:
        raise StationScopeError(
            "Could not locate CaseMaster or Employee in generated SQL to apply station scope"
        )

    clause_name, idx = _find_top_level_clause(sql)

    if clause_name == "WHERE":
        insert_at = idx + len("WHERE")
        rewritten = sql[:insert_at] + f" {condition} AND" + sql[insert_at:]
    elif clause_name in ("GROUP BY", "HAVING", "ORDER BY", "LIMIT", "UNION"):
        rewritten = sql[:idx].rstrip() + f" WHERE {condition} " + sql[idx:]
    else:
        rewritten = sql.rstrip() + f" WHERE {condition}"

    disclaimer_needed = _compute_scope_disclaimer_needed(question, was_scoped=True)
    return rewritten, True, disclaimer_needed
