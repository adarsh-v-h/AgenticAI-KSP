"""
Schema catalog — table descriptions, columns, and keywords for the schema linker.
Used by:
  - pipeline.schema_linker.select_relevant_tables()
  - get_schema_for_tables() to build a compact LLM prompt string
  - get_few_shot_examples() to inject example NL->SQL pairs
"""

# Maximum compact-schema size (chars) injected into the LLM SQL prompt.
# Keep modest — Qwen Coder 7B context is finite and prompt cost == latency.
_MAX_SCHEMA_CHARS = 3000

SCHEMA_CATALOG = {
    "CaseMaster": {
        "description": "Central case/FIR registry. Every case starts here.",
        "columns": {
            "CaseMasterID": "INT PRIMARY KEY",
            "CrimeNo": "VARCHAR(30) UNIQUE - structured crime number",
            "CaseNo": "VARCHAR(20)",
            "CrimeRegisteredDate": "DATE",
            "PolicePersonID": "INT FK -> Employee.EmployeeID",
            "PoliceStationID": "INT FK -> Unit.UnitID",
            "CaseCategoryID": "INT FK -> CaseCategory.CaseCategoryID",
            "GravityOffenceID": "INT FK -> GravityOffence.GravityOffenceID",
            "CrimeMajorHeadID": "INT FK -> CrimeHead.CrimeHeadID",
            "CrimeMinorHeadID": "INT FK -> CrimeSubHead.CrimeSubHeadID",
            "CaseStatusID": "INT FK -> CaseStatusMaster.CaseStatusID",
            "CourtID": "INT FK -> Court.CourtID",
            "IncidentFromDate": "DATETIME",
            "IncidentToDate": "DATETIME",
            "latitude": "DECIMAL(10,8)",
            "longitude": "DECIMAL(11,8)",
            "BriefFacts": "TEXT - free text summary"
        },
        "keywords": ["case", "fir", "crime", "registered", "status", "incident", "all cases"],
        "always_include": True
    },
    "Accused": {
        "description": "Accused persons linked to cases. One case can have multiple accused.",
        "columns": {
            "AccusedMasterID": "INT PRIMARY KEY",
            "CaseMasterID": "INT FK -> CaseMaster.CaseMasterID",
            "AccusedName": "VARCHAR(150)",
            "AgeYear": "INT",
            "GenderID": "INT",
            "PersonID": "VARCHAR(10)"
        },
        "keywords": ["accused", "suspect", "offender", "criminal", "name", "repeat", "prior", "habitual", "gang"]
    },
    "Victim": {
        "description": "Victims linked to cases. One case can have multiple victims.",
        "columns": {
            "VictimID": "INT PRIMARY KEY",
            "CaseMasterID": "INT FK -> CaseMaster.CaseMasterID",
            "VictimName": "VARCHAR(150)",
            "AgeYear": "INT",
            "GenderID": "INT",
            "VictimPolice": "BIT"
        },
        "keywords": ["victim", "injured", "affected", "hurt", "attacked", "dead"]
    },
    "ComplainantDetails": {
        "description": "Complainants who filed the cases.",
        "columns": {
            "ComplainantDetailsID": "INT PRIMARY KEY",
            "CaseMasterID": "INT FK -> CaseMaster.CaseMasterID",
            "ComplainantName": "VARCHAR(150)",
            "MobileNo": "VARCHAR(15)",
            "GenderID": "INT"
        },
        "keywords": ["complainant", "reporter", "filed by", "complaint"]
    },
    "Employee": {
        "description": "Police employees/officers at the station.",
        "columns": {
            "EmployeeID": "INT PRIMARY KEY",
            "DistrictID": "INT FK -> District.DistrictID",
            "UnitID": "INT FK -> Unit.UnitID",
            "RankID": "INT FK -> `Rank`.RankID",
            "DesignationID": "INT FK -> Designation.DesignationID",
            "KGID": "VARCHAR(30) UNIQUE",
            "FirstName": "VARCHAR(100)",
            "EmployeeDOB": "DATE",
            "GenderID": "INT",
            "BloodGroupID": "INT",
            "PhysicallyChallenged": "BIT",
            "AppointmentDate": "DATE",
            "role": "ENUM('investigator', 'analyst', 'supervisor', 'policymaker')",
            "is_active": "BOOLEAN"
        },
        "keywords": ["employee", "officer", "inspector", "constable", "si", "pi", "asi", "dysp", "assigned", "investigating", "staff", "head constable"]
    },
    "`Rank`": {
        "description": "Police ranks (escaped with backticks).",
        "columns": {
            "RankID": "INT PRIMARY KEY",
            "RankName": "VARCHAR(50)",
            "Hierarchy": "INT",
            "Active": "BIT"
        },
        "keywords": ["rank", "hierarchy"]
    },
    "Unit": {
        "description": "Police units / stations.",
        "columns": {
            "UnitID": "INT PRIMARY KEY",
            "UnitName": "VARCHAR(150)",
            "TypeID": "INT FK -> UnitType.UnitTypeID",
            "ParentUnit": "INT FK -> Unit.UnitID",
            "NationalityID": "INT",
            "StateID": "INT FK -> State.StateID",
            "DistrictID": "INT FK -> District.DistrictID",
            "Active": "BIT"
        },
        "keywords": ["unit", "station", "police station", "ps"]
    },
    "District": {
        "description": "Districts.",
        "columns": {
            "DistrictID": "INT PRIMARY KEY",
            "DistrictName": "VARCHAR(100)",
            "StateID": "INT FK -> State.StateID",
            "Active": "BIT"
        },
        "keywords": ["district", "area"]
    },
    "Court": {
        "description": "Courts of law.",
        "columns": {
            "CourtID": "INT PRIMARY KEY",
            "CourtName": "VARCHAR(150)",
            "DistrictID": "INT FK -> District.DistrictID",
            "StateID": "INT FK -> State.StateID",
            "Active": "BIT"
        },
        "keywords": ["court", "judge", "trial"]
    },
    "CrimeHead": {
        "description": "Major heads of crime groups.",
        "columns": {
            "CrimeHeadID": "INT PRIMARY KEY",
            "CrimeGroupName": "VARCHAR(150)",
            "Active": "BIT"
        },
        "keywords": ["crime head", "crime group"]
    },
    "CrimeSubHead": {
        "description": "Minor heads of crime categories (crime types). Join with CrimeHead on CrimeHeadID.",
        "columns": {
            "CrimeSubHeadID": "INT PRIMARY KEY",
            "CrimeHeadID": "INT FK -> CrimeHead.CrimeHeadID",
            "CrimeHeadName": "VARCHAR(150) - name of the crime type (e.g., 'Theft', 'Murder', 'Assault')",
            "SeqID": "INT"
        },
        "keywords": ["crime subhead", "crime type", "theft", "murder", "assault", "robbery", "fraud", "cybercrime", "missing", "drugs"]
    },
    "CaseStatusMaster": {
        "description": "Case status lookup (e.g., Open, Under Investigation, Closed, Chargesheeted).",
        "columns": {
            "CaseStatusID": "INT PRIMARY KEY",
            "CaseStatusName": "VARCHAR(80)"
        },
        "keywords": ["status", "open", "closed", "chargesheeted", "under investigation"]
    },
    "CaseCategory": {
        "description": "Case category lookup.",
        "columns": {
            "CaseCategoryID": "INT PRIMARY KEY",
            "LookupValue": "VARCHAR(50)"
        },
        "keywords": ["category"]
    },
    "GravityOffence": {
        "description": "Gravity of offence lookup.",
        "columns": {
            "GravityOffenceID": "INT PRIMARY KEY",
            "LookupValue": "VARCHAR(50)"
        },
        "keywords": ["gravity", "heinous", "non-heinous"]
    },
    "Act": {
        "description": "Acts (laws) under which sections are charged.",
        "columns": {
            "ActCode": "VARCHAR(20) PRIMARY KEY",
            "ActDescription": "VARCHAR(200)",
            "ShortName": "VARCHAR(50)",
            "Active": "BIT"
        },
        "keywords": ["act", "law", "ipc", "crpc", "bns"]
    },
    "Section": {
        "description": "Sections of acts charged. Join with Act on ActCode.",
        "columns": {
            "ActCode": "VARCHAR(20) PRIMARY KEY FK -> Act.ActCode",
            "SectionCode": "VARCHAR(20) PRIMARY KEY",
            "SectionDescription": "VARCHAR(300)",
            "Active": "BIT"
        },
        "keywords": ["section", "ipc section", "bns section"]
    },
    "ActSectionAssociation": {
        "description": "Links cases to acts and sections charged.",
        "columns": {
            "CaseMasterID": "INT FK -> CaseMaster.CaseMasterID",
            "ActID": "VARCHAR(20) FK -> Act.ActCode",
            "SectionID": "VARCHAR(20) FK -> Section.SectionCode",
            "ActOrderID": "INT",
            "SectionOrderID": "INT"
        },
        "keywords": ["act section", "charged under", "section charged"]
    },
    "ArrestSurrender": {
        "description": "Arrest or surrender details of accused. Join with Accused to find who is arrested or still at large.",
        "columns": {
            "ArrestSurrenderID": "INT PRIMARY KEY",
            "CaseMasterID": "INT FK -> CaseMaster.CaseMasterID",
            "ArrestSurrenderTypeID": "INT",
            "ArrestSurrenderDate": "DATE",
            "ArrestSurrenderStateId": "INT FK -> State.StateID",
            "ArrestSurrenderDistrictId": "INT FK -> District.DistrictID",
            "PoliceStationID": "INT FK -> Unit.UnitID",
            "IOID": "INT FK -> Employee.EmployeeID",
            "CourtID": "INT FK -> Court.CourtID",
            "AccusedMasterID": "INT FK -> Accused.AccusedMasterID",
            "IsAccused": "BIT",
            "IsComplainantAccused": "BIT"
        },
        "keywords": ["arrest", "surrender", "arrested", "at large", "investigating officer"]
    },
    "CasteMaster": {
        "description": "Caste lookup table.",
        "columns": {
            "caste_master_id": "INT PRIMARY KEY",
            "caste_master_name": "VARCHAR(100)"
        },
        "keywords": ["caste", "sociological"]
    },
    "ReligionMaster": {
        "description": "Religion lookup table.",
        "columns": {
            "ReligionID": "INT PRIMARY KEY",
            "ReligionName": "VARCHAR(100)"
        },
        "keywords": ["religion"]
    },
    "OccupationMaster": {
        "description": "Occupation lookup table.",
        "columns": {
            "OccupationID": "INT PRIMARY KEY",
            "OccupationName": "VARCHAR(100)"
        },
        "keywords": ["occupation", "profession"]
    }
}


def _format_table(name: str, meta: dict, max_col_chars: int | None = None) -> str:
    """Build the per-table block for a schema string."""
    lines = [f"TABLE: {name}", f"Description: {meta['description']}", "Columns:"]
    for col_name, col_desc in meta["columns"].items():
        if max_col_chars is not None and len(col_desc) > max_col_chars:
            col_desc = col_desc[: max_col_chars - 1].rstrip() + "…"
        lines.append(f"  - {col_name}: {col_desc}")
    return "\n".join(lines)


def get_schema_for_tables(table_names: list[str]) -> str:
    """
    Build a compact schema string for LLM prompt injection.

    Always includes CaseMaster (even if not in table_names) and lists it first.
    Output is capped at _MAX_SCHEMA_CHARS — column descriptions are progressively
    truncated to fit; table names and column names are never dropped.
    """
    seen = set()
    ordered = []

    # Always include CaseMaster first.
    if "CaseMaster" in SCHEMA_CATALOG:
        ordered.append("CaseMaster")
        seen.add("CaseMaster")

    for t in table_names:
        if t in SCHEMA_CATALOG and t not in seen:
            ordered.append(t)
            seen.add(t)

    # First pass: full descriptions.
    blocks = [_format_table(t, SCHEMA_CATALOG[t]) for t in ordered]
    out = "\n\n".join(blocks)
    if len(out) <= _MAX_SCHEMA_CHARS:
        return out

    # Progressively truncate column descriptions until under the cap.
    for cap in (80, 60, 40, 30):
        blocks = [
            _format_table(t, SCHEMA_CATALOG[t], max_col_chars=cap) for t in ordered
        ]
        out = "\n\n".join(blocks)
        if len(out) <= _MAX_SCHEMA_CHARS:
            return out

    # Last resort: hard-truncate.
    return out[:_MAX_SCHEMA_CHARS]


# Few-shot bank — (relevant_tables_set, question, sql) tuples.
# `relevant_tables` lists which tables in the question's selected set make this
# example useful. We always score against the user's table set.
_FEW_SHOT_BANK: list[dict] = [
    {
        "tables": {"CaseMaster"},
        "q": "How many cases are open?",
        "sql": (
            "SELECT COUNT(*) AS open_cases\n"
            "FROM CaseMaster AS cm\n"
            "JOIN CaseStatusMaster AS csm ON csm.CaseStatusID = cm.CaseStatusID\n"
            "WHERE csm.CaseStatusName = 'Open'"
        ),
    },
    {
        "tables": {"CaseMaster"},
        "q": "Show me the last 5 cases registered.",
        "sql": (
            "SELECT cm.CaseMasterID, cm.CrimeNo, cm.BriefFacts, cm.CrimeRegisteredDate\n"
            "FROM CaseMaster AS cm\n"
            "ORDER BY cm.CrimeRegisteredDate DESC\n"
            "LIMIT 5"
        ),
    },
    {
        "tables": {"CaseMaster"},
        "q": "How many cases were registered in 2024?",
        "sql": (
            "SELECT COUNT(*) AS cases_in_2024\n"
            "FROM CaseMaster AS cm\n"
            "WHERE YEAR(cm.CrimeRegisteredDate) = 2024"
        ),
    },
    {
        "tables": {"CaseMaster", "CrimeSubHead"},
        "q": "How many theft cases are still open?",
        "sql": (
            "SELECT COUNT(*) AS open_theft_cases\n"
            "FROM CaseMaster AS cm\n"
            "JOIN CaseStatusMaster AS csm ON csm.CaseStatusID = cm.CaseStatusID\n"
            "JOIN CrimeSubHead AS csh ON csh.CrimeSubHeadID = cm.CrimeMinorHeadID\n"
            "WHERE csm.CaseStatusName = 'Open' AND csh.CrimeHeadName = 'Theft'"
        ),
    },
    {
        "tables": {"CaseMaster", "CrimeSubHead"},
        "q": "List theft cases.",
        "sql": (
            "SELECT cm.CaseMasterID, cm.CrimeNo, cm.BriefFacts, cm.CrimeRegisteredDate\n"
            "FROM CaseMaster AS cm\n"
            "JOIN CrimeSubHead AS csh ON csh.CrimeSubHeadID = cm.CrimeMinorHeadID\n"
            "WHERE csh.CrimeHeadName = 'Theft'\n"
            "ORDER BY cm.CrimeRegisteredDate DESC\n"
            "LIMIT 50"
        ),
    },
    {
        "tables": {"CaseMaster", "Accused"},
        "q": "Show me all cases involving Mahesh Gowda.",
        "sql": (
            "SELECT cm.CaseMasterID, cm.CrimeNo, cm.BriefFacts, a.AccusedName\n"
            "FROM CaseMaster AS cm\n"
            "JOIN Accused AS a ON a.CaseMasterID = cm.CaseMasterID\n"
            "WHERE a.AccusedName LIKE '%Mahesh Gowda%'\n"
            "ORDER BY cm.CrimeRegisteredDate DESC\n"
            "LIMIT 50"
        ),
    },
    {
        "tables": {"Accused"},
        "q": "Who are the top 5 accused with the most cases?",
        "sql": (
            "SELECT a.AccusedName, COUNT(DISTINCT a.CaseMasterID) AS case_count\n"
            "FROM Accused AS a\n"
            "WHERE a.AccusedName IS NOT NULL\n"
            "GROUP BY a.AccusedName\n"
            "ORDER BY case_count DESC\n"
            "LIMIT 5"
        ),
    },
    {
        "tables": {"CaseMaster", "Accused", "ArrestSurrender"},
        "q": "Which accused are still at large?",
        "sql": (
            "SELECT a.AccusedMasterID, a.AccusedName, cm.CrimeNo\n"
            "FROM Accused AS a\n"
            "JOIN CaseMaster AS cm ON cm.CaseMasterID = a.CaseMasterID\n"
            "LEFT JOIN ArrestSurrender AS ar ON ar.AccusedMasterID = a.AccusedMasterID\n"
            "WHERE ar.ArrestSurrenderID IS NULL\n"
            "LIMIT 50"
        ),
    },
    {
        "tables": {"CaseMaster", "ActSectionAssociation", "Section"},
        "q": "What sections were charged in case CrimeNo FIR/2024/KOR/0042?",
        "sql": (
            "SELECT s.SectionCode, s.SectionDescription\n"
            "FROM ActSectionAssociation AS asa\n"
            "JOIN CaseMaster AS cm ON cm.CaseMasterID = asa.CaseMasterID\n"
            "JOIN Section AS s ON s.ActCode = asa.ActID AND s.SectionCode = asa.SectionID\n"
            "WHERE cm.CrimeNo = 'FIR/2024/KOR/0042'"
        ),
    },
    {
        "tables": {"CaseMaster", "Employee", "`Rank`"},
        "q": "Which officer is investigating the most cases?",
        "sql": (
            "SELECT e.FirstName, r.RankName, COUNT(cm.CaseMasterID) AS case_count\n"
            "FROM Employee AS e\n"
            "LEFT JOIN `Rank` AS r ON e.RankID = r.RankID\n"
            "JOIN CaseMaster AS cm ON cm.PolicePersonID = e.EmployeeID\n"
            "GROUP BY e.EmployeeID, e.FirstName, r.RankName\n"
            "ORDER BY case_count DESC\n"
            "LIMIT 5"
        ),
    },
    {
        "tables": {"CaseMaster", "Employee"},
        "q": "Give me cases handled by Harish Kumar.",
        "sql": (
            "SELECT cm.CaseMasterID, cm.CrimeNo, cm.BriefFacts, cm.CrimeRegisteredDate\n"
            "FROM CaseMaster AS cm\n"
            "JOIN Employee AS e ON e.EmployeeID = cm.PolicePersonID\n"
            "WHERE e.FirstName LIKE '%Harish Kumar%'\n"
            "ORDER BY cm.CrimeRegisteredDate DESC\n"
            "LIMIT 50"
        ),
    },
]


def get_few_shot_examples(table_names: list[str]) -> str:
    """
    Return exactly 3 example NL->SQL pairs relevant to the selected tables.

    Scoring: each example earns +1 for every table it shares with the caller's
    selected set. Ties broken by example order in the bank (stable).
    """
    selected = set(table_names) | {"CaseMaster"}

    scored = []
    for idx, ex in enumerate(_FEW_SHOT_BANK):
        score = len(ex["tables"] & selected)
        # Penalize examples that reference tables NOT selected — those would
        # confuse the LLM into using tables we didn't include in the schema.
        unknown = ex["tables"] - selected
        if unknown:
            score -= len(unknown)
        scored.append((score, idx, ex))

    scored.sort(key=lambda x: (-x[0], x[1]))
    chosen = [ex for _score, _idx, ex in scored[:3]]

    blocks = []
    for ex in chosen:
        blocks.append(f"-- Q: {ex['q']}\n-- SQL:\n{ex['sql']}")
    return "\n\n".join(blocks)


# A handy export for the validator to use without re-importing this dict.
ALLOWED_TABLES: list[str] = list(SCHEMA_CATALOG.keys())
