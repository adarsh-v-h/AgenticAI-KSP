# MIGRATE STEP 3 — Backend Schema, Prompts, and Pipeline Updates

> Run this file third. It updates the NL2SQL schema catalog, the prompt templates, and the backend code that depends on the schema.

## 1. Rewrite `backend/db/schema_catalog.py`

The schema catalog must reflect the new table names and column names exactly. Remove any legacy tables such as `fir_master`, `cases_theft`, and `case_relationships`.

### Required tables in the catalog

- `CaseMaster`
- `Accused`
- `Victim`
- `ComplainantDetails`
- `Employee`
- `Rank`
- `Unit`
- `District`
- `Court`
- `CrimeHead`
- `CrimeSubHead`
- `CaseStatusMaster`
- `CaseCategory`
- `GravityOffence`
- `Act`
- `Section`
- `ActSectionAssociation`
- `ArrestSurrender`
- `CasteMaster`
- `ReligionMaster`
- `OccupationMaster`

### Example catalog entry for `CaseMaster`

```python
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
    "keywords": ["case", "fir", "crime", "registered", "status", "incident"],
    "always_include": True
}
```

## 2. Rewrite few-shot SQL examples

Update `get_few_shot_examples()` to use the new schema. Example rewrites include:

- `SELECT COUNT(*) FROM CaseMaster ... WHERE CaseStatusName = 'Open'`
- `SELECT cm.CaseMasterID, cm.CrimeNo FROM CaseMaster cm JOIN CrimeSubHead csh ON csh.CrimeSubHeadID = cm.CrimeMinorHeadID WHERE csh.CrimeHeadName = 'Theft'`
- `SELECT a.AccusedName FROM Accused a JOIN CaseMaster cm ON cm.CaseMasterID = a.CaseMasterID WHERE a.AccusedName LIKE '%name%'`
- `SELECT a.AccusedMasterID, a.AccusedName FROM Accused a LEFT JOIN ArrestSurrender ar ON ar.AccusedMasterID = a.AccusedMasterID WHERE ar.ArrestSurrenderID IS NULL`
- `SELECT s.SectionCode, s.SectionDescription FROM ActSectionAssociation asa JOIN CaseMaster cm ON cm.CaseMasterID = asa.CaseMasterID JOIN Section s ON s.ActCode = asa.ActID AND s.SectionCode = asa.SectionID WHERE cm.CrimeNo = '...'`

## 3. Update the SQL system prompt rules

Add rules for the new schema style:

- Use exact PascalCase table and column names.
- Use `CrimeSubHead.CrimeHeadName` to filter crime types.
- Use `LEFT JOIN ArrestSurrender ... IS NULL` to represent accused who are still at large.
- Do not use old type-specific tables such as `cases_theft`, `cases_assault`, etc.

## 4. Normalize BIT fields in `backend/db/connection.py`

aiomysql may return `BIT(1)` as `b'\x01'` or `b'\x00'`. Normalize these values before returning rows.

```python

def _normalize_bit_fields(row: dict) -> dict:
    return {
        k: (v == b'\x01' if isinstance(v, bytes) and len(v) == 1 else v)
        for k, v in row.items()
    }
```

Apply this transformation to every row returned by `execute_query()`.

## 5. Update other backend modules

Search and update all legacy schema references across the backend.

### Key areas

- `backend/auth/simple_auth.py`
  - `officers` → `Employee`
  - `officer_id` → `EmployeeID`
  - `badge_number` → `KGID`
  - `full_name` → `FirstName`

- `backend/graph/network_builder.py`
  - Remove reliance on `case_relationships`.

- `backend/routers/*.py`
  - Update table/column names in any SQL queries or route logic.

- Any `BLUEPRINT2` modules that refer to old schema.

## 6. Test as you go

After each change, run a focused backend smoke test:

- does login still work?
- does the chat SQL pipeline still produce valid SQL?
- does the schema linker still choose the right tables?
- does the answer formatter still handle result rows?

This step is mostly implementation and verification, not data migration.
