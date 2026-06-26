# MIGRATE.md — Migrating to the Official KSP FIR Schema

> **Context:** KSP has provided an official ER diagram (`Police_FIR_ER_Diagram.pdf`) — a real, production-grade schema with proper normalization (lookup tables for caste/religion/occupation/act/section, hierarchical police units, employee/rank/designation structure). Our hackathon schema (`fir_master`, `accused`, `victims`, `cases_theft`, etc.) was a reasonable simplification, but now that the real schema exists, we migrate to it.
>
> **This is a big, structural change.** Table names change, column names change, the "split case tables by type" design is replaced by a single `CaseMaster` table with classification via lookup tables (`CrimeHead`/`CrimeSubHead`/`Act`/`Section`), and several new lookup tables are introduced that didn't exist before (caste, religion, occupation, court, district, state, unit hierarchy, rank/designation).
>
> **Read this entire file before touching any code.** Migration touches: the DDL schema, the seed data, the schema catalog used by the NL2SQL pipeline, the SQL system prompt's few-shot examples, several backend modules built in BLUEPRINT2 (risk scoring, analytics, decision support), and a few frontend field-name references. Do it in the order given — don't jump ahead.

---

## 1. The Core Mapping — Old Schema → New Schema

This is the single most important table in this document. Every other section refers back to this.

| Old table | Old key field | New table | New key field | Notes |
|---|---|---|---|---|
| `fir_master` | `fir_id` | `CaseMaster` | `CaseMasterID` | Central case record — same role, different structure |
| `accused` | `accused_id` | `Accused` | `AccusedMasterID` | Renamed, fewer denormalized fields |
| `victims` | `victim_id` | `Victim` | `VictimMasterID` | Renamed |
| *(none — complainant didn't exist as a concept)* | — | `ComplainantDetails` | `ComplainantID` | **New entity.** Complainant ≠ victim in the real schema — a complainant files the FIR, may or may not be the victim |
| `officers` | `officer_id` | `Employee` | `EmployeeID` | Renamed, restructured — rank/designation/unit are now separate lookup tables, not inline enums |
| `case_relationships` | `rel_id` | *(no direct equivalent)* | — | **Not in the official schema.** Network graph relationships become a derived/computed concept — see Section 7 |
| `evidence_media` | `media_id` | *(no direct equivalent)* | — | **Not in the official schema.** Evidence media is out of scope for this migration — see Section 8 |
| `cases_theft`, `cases_assault`, `cases_vehicle_theft`, `cases_fraud`, `cases_cybercrime`, `cases_missing_person`, `cases_drug_offense` | various | **Merged into `CaseMaster` + `CrimeHead`/`CrimeSubHead`** | — | **Biggest structural change.** No more per-type tables. Crime type is now a classification (`CrimeMajorHeadID` → `CrimeMinorHeadID`), not a table split. See Section 4. |

### New tables that didn't exist in our hackathon schema at all

These are pure additions — there's no "old equivalent," they're new concepts the real schema introduces:

- `ArrestSurrender` — arrest/surrender events, separate from the accused record itself (an accused can have multiple arrest events historically)
- `ActSectionAssociation` — legal acts/sections charged in a case (IPC sections etc.) — genuinely new, we had nothing like this
- `Act`, `Section` — the legal reference tables
- `CrimeHead`, `CrimeSubHead`, `CrimeHeadActSection` — crime classification hierarchy
- `CaseCategory`, `GravityOffence`, `CaseStatusMaster` — lookup tables for case metadata
- `CasteMaster`, `ReligionMaster`, `OccupationMaster` — demographic lookup tables (these directly serve **PS1 Section 4 — Sociological Crime Insights**, which we'd marked as 0% done — this migration partially unlocks it)
- `Court`, `District`, `State`, `Unit`, `UnitType` — geographic/organizational hierarchy
- `Rank`, `Designation` — employee classification
- `ChargesheetDetails` — chargesheet outcome tracking

---

## 2. Decision: What We Migrate Now vs. Defer

Given hackathon time constraints, we don't need to model the *entire* ER diagram on day one. Here's the honest split:

### Migrate now (core path — chat pipeline depends on these)
`CaseMaster`, `Accused`, `Victim`, `ComplainantDetails`, `Employee`, `Rank`, `Designation`, `Unit`, `UnitType`, `District`, `State`, `CaseCategory`, `GravityOffence`, `CaseStatusMaster`, `CrimeHead`, `CrimeSubHead`, `Act`, `Section`, `ActSectionAssociation`, `ArrestSurrender`.

### Migrate now, smaller lookup tables (cheap, high value for PS1 Section 4)
`CasteMaster`, `ReligionMaster`, `OccupationMaster`, `Court`.

### Defer (low value for the demo, or genuinely complex)
`CrimeHeadActSection` (a mapping table between crime heads and legal sections — useful for legal compliance tooling, not for the chatbot demo), `ChargesheetDetails` (chargesheet workflow — only matters if we demo case outcome tracking, can add later), `inv_arrestsurrenderaccused` junction table (the many-to-many between ArrestSurrender and Accused — for the hackathon, treat ArrestSurrender as effectively one-to-one with Accused via the existing `AccusedMasterID` FK already on `ArrestSurrender`, skip the junction table complexity), `Inv_OccuranceTime` (the PDF references this as a 1:1 child of CaseMaster, but `IncidentFromDate`/`IncidentToDate`/lat/long are already inline on `CaseMaster` per the column table — no separate table needed).

This split keeps the migration scoped to what the chatbot actually needs to keep working, while still picking up the sociological/demographic lookup tables that meaningfully extend what the platform can answer.

---

## 3. New Schema DDL

Run this entire block against a **fresh** database or a backed-up copy — do not run against your current `ksp_crime_db` until you've read Section 9 (data migration) in full.

```sql
-- ── Geographic / organizational hierarchy ──────────────────────────────────

CREATE TABLE State (
    StateID         INT AUTO_INCREMENT PRIMARY KEY,
    StateName       VARCHAR(100) NOT NULL,
    NationalityID   INT,
    Active          BIT DEFAULT 1
);

CREATE TABLE District (
    DistrictID      INT AUTO_INCREMENT PRIMARY KEY,
    DistrictName    VARCHAR(100) NOT NULL,
    StateID         INT NOT NULL,
    Active          BIT DEFAULT 1,
    FOREIGN KEY (StateID) REFERENCES State(StateID)
);

CREATE TABLE UnitType (
    UnitTypeID      INT AUTO_INCREMENT PRIMARY KEY,
    UnitTypeName    VARCHAR(100) NOT NULL,
    CityDistState   VARCHAR(20),
    Hierarchy       INT,
    Active          BIT DEFAULT 1
);

CREATE TABLE Unit (
    UnitID          INT AUTO_INCREMENT PRIMARY KEY,
    UnitName        VARCHAR(150) NOT NULL,
    TypeID          INT,
    ParentUnit      INT,
    NationalityID   INT,
    StateID         INT,
    DistrictID      INT,
    Active          BIT DEFAULT 1,
    FOREIGN KEY (TypeID) REFERENCES UnitType(UnitTypeID),
    FOREIGN KEY (StateID) REFERENCES State(StateID),
    FOREIGN KEY (DistrictID) REFERENCES District(DistrictID),
    FOREIGN KEY (ParentUnit) REFERENCES Unit(UnitID)
);

CREATE TABLE Court (
    CourtID         INT AUTO_INCREMENT PRIMARY KEY,
    CourtName       VARCHAR(150) NOT NULL,
    DistrictID      INT,
    StateID         INT,
    Active          BIT DEFAULT 1,
    FOREIGN KEY (DistrictID) REFERENCES District(DistrictID),
    FOREIGN KEY (StateID) REFERENCES State(StateID)
);

-- ── Employee / rank structure ───────────────────────────────────────────────

CREATE TABLE Rank (
    RankID          INT AUTO_INCREMENT PRIMARY KEY,
    RankName        VARCHAR(50) NOT NULL,
    Hierarchy       INT,
    Active          BIT DEFAULT 1
);

CREATE TABLE Designation (
    DesignationID   INT AUTO_INCREMENT PRIMARY KEY,
    DesignationName VARCHAR(100) NOT NULL,
    Active          BIT DEFAULT 1,
    SortOrder       INT
);

CREATE TABLE Employee (
    EmployeeID              INT AUTO_INCREMENT PRIMARY KEY,
    DistrictID              INT,
    UnitID                  INT,
    RankID                  INT,
    DesignationID           INT,
    KGID                    VARCHAR(30) UNIQUE,
    FirstName               VARCHAR(100) NOT NULL,
    EmployeeDOB             DATE,
    GenderID                INT,
    BloodGroupID            INT,
    PhysicallyChallenged    BIT DEFAULT 0,
    AppointmentDate         DATE,
    -- Added for our app's auth needs — NOT in original ER diagram but required
    -- since we authenticate against an employee record (see Section 6).
    role                    ENUM('investigator','analyst','supervisor','policymaker')
                            NOT NULL DEFAULT 'investigator',
    is_active               BOOLEAN DEFAULT TRUE,

    FOREIGN KEY (DistrictID) REFERENCES District(DistrictID),
    FOREIGN KEY (UnitID) REFERENCES Unit(UnitID),
    FOREIGN KEY (RankID) REFERENCES Rank(RankID),
    FOREIGN KEY (DesignationID) REFERENCES Designation(DesignationID)
);

-- ── Crime classification ────────────────────────────────────────────────────

CREATE TABLE CrimeHead (
    CrimeHeadID     INT AUTO_INCREMENT PRIMARY KEY,
    CrimeGroupName  VARCHAR(150) NOT NULL,
    Active          BIT DEFAULT 1
);

CREATE TABLE CrimeSubHead (
    CrimeSubHeadID  INT AUTO_INCREMENT PRIMARY KEY,
    CrimeHeadID     INT NOT NULL,
    CrimeHeadName   VARCHAR(150) NOT NULL,
    SeqID           INT,
    FOREIGN KEY (CrimeHeadID) REFERENCES CrimeHead(CrimeHeadID)
);

CREATE TABLE CaseCategory (
    CaseCategoryID  INT AUTO_INCREMENT PRIMARY KEY,
    LookupValue     VARCHAR(50) NOT NULL          -- 'FIR', 'UDR', 'PAR', 'Zero FIR'
);

CREATE TABLE GravityOffence (
    GravityOffenceID INT AUTO_INCREMENT PRIMARY KEY,
    LookupValue      VARCHAR(50) NOT NULL          -- 'Heinous', 'Non-Heinous'
);

CREATE TABLE CaseStatusMaster (
    CaseStatusID    INT AUTO_INCREMENT PRIMARY KEY,
    CaseStatusName  VARCHAR(80) NOT NULL           -- 'Under Investigation', 'Charge Sheeted', 'Closed'
);

-- ── Legal acts / sections ───────────────────────────────────────────────────

CREATE TABLE Act (
    ActCode         VARCHAR(20) PRIMARY KEY,       -- e.g. 'IPC', 'NDPS'
    ActDescription  VARCHAR(200) NOT NULL,
    ShortName       VARCHAR(50),
    Active          BIT DEFAULT 1
);

CREATE TABLE Section (
    ActCode             VARCHAR(20) NOT NULL,
    SectionCode         VARCHAR(20) NOT NULL,
    SectionDescription  VARCHAR(300),
    Active              BIT DEFAULT 1,
    PRIMARY KEY (ActCode, SectionCode),
    FOREIGN KEY (ActCode) REFERENCES Act(ActCode)
);

-- ── Demographic lookup tables (Section 4 — sociological insights) ──────────

CREATE TABLE CasteMaster (
    caste_master_id     INT AUTO_INCREMENT PRIMARY KEY,
    caste_master_name   VARCHAR(100) NOT NULL
);

CREATE TABLE ReligionMaster (
    ReligionID      INT AUTO_INCREMENT PRIMARY KEY,
    ReligionName    VARCHAR(100) NOT NULL
);

CREATE TABLE OccupationMaster (
    OccupationID    INT AUTO_INCREMENT PRIMARY KEY,
    OccupationName  VARCHAR(100) NOT NULL
);

-- ── Core case tables ─────────────────────────────────────────────────────────

CREATE TABLE CaseMaster (
    CaseMasterID            INT AUTO_INCREMENT PRIMARY KEY,
    CrimeNo                 VARCHAR(30) UNIQUE NOT NULL,
    CaseNo                  VARCHAR(20),
    CrimeRegisteredDate     DATE NOT NULL,
    PolicePersonID          INT NOT NULL,
    PoliceStationID         INT NOT NULL,
    CaseCategoryID          INT,
    GravityOffenceID        INT,
    CrimeMajorHeadID        INT,
    CrimeMinorHeadID        INT,
    CaseStatusID            INT,
    CourtID                 INT,
    IncidentFromDate        DATETIME,
    IncidentToDate          DATETIME,
    InfoReceivedPSDate      DATETIME,
    latitude                DECIMAL(10,8),
    longitude               DECIMAL(11,8),
    BriefFacts               TEXT,
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    FOREIGN KEY (PolicePersonID) REFERENCES Employee(EmployeeID),
    FOREIGN KEY (PoliceStationID) REFERENCES Unit(UnitID),
    FOREIGN KEY (CaseCategoryID) REFERENCES CaseCategory(CaseCategoryID),
    FOREIGN KEY (GravityOffenceID) REFERENCES GravityOffence(GravityOffenceID),
    FOREIGN KEY (CrimeMajorHeadID) REFERENCES CrimeHead(CrimeHeadID),
    FOREIGN KEY (CrimeMinorHeadID) REFERENCES CrimeSubHead(CrimeSubHeadID),
    FOREIGN KEY (CaseStatusID) REFERENCES CaseStatusMaster(CaseStatusID),
    FOREIGN KEY (CourtID) REFERENCES Court(CourtID)
);

CREATE INDEX idx_casemaster_status ON CaseMaster(CaseStatusID);
CREATE INDEX idx_casemaster_crimehead ON CaseMaster(CrimeMajorHeadID, CrimeMinorHeadID);
CREATE INDEX idx_casemaster_date ON CaseMaster(CrimeRegisteredDate);

CREATE TABLE ComplainantDetails (
    ComplainantID       INT AUTO_INCREMENT PRIMARY KEY,
    CaseMasterID        INT NOT NULL,
    ComplainantName     VARCHAR(150) NOT NULL,
    AgeYear             INT,
    OccupationID        INT,
    ReligionID          INT,
    CasteID             INT,
    GenderID            INT,
    FOREIGN KEY (CaseMasterID) REFERENCES CaseMaster(CaseMasterID),
    FOREIGN KEY (OccupationID) REFERENCES OccupationMaster(OccupationID),
    FOREIGN KEY (ReligionID) REFERENCES ReligionMaster(ReligionID),
    FOREIGN KEY (CasteID) REFERENCES CasteMaster(caste_master_id)
);

CREATE INDEX idx_complainant_case ON ComplainantDetails(CaseMasterID);

CREATE TABLE Victim (
    VictimMasterID      INT AUTO_INCREMENT PRIMARY KEY,
    CaseMasterID        INT NOT NULL,
    VictimName          VARCHAR(150),
    AgeYear             INT,
    GenderID            INT,
    VictimPolice        BIT DEFAULT 0,
    FOREIGN KEY (CaseMasterID) REFERENCES CaseMaster(CaseMasterID)
);

CREATE INDEX idx_victim_case ON Victim(CaseMasterID);

CREATE TABLE Accused (
    AccusedMasterID     INT AUTO_INCREMENT PRIMARY KEY,
    CaseMasterID        INT NOT NULL,
    AccusedName         VARCHAR(150),
    AgeYear             INT,
    GenderID            INT,
    PersonID            VARCHAR(10),          -- 'A1', 'A2', etc.
    FOREIGN KEY (CaseMasterID) REFERENCES CaseMaster(CaseMasterID)
);

CREATE INDEX idx_accused_case ON Accused(CaseMasterID);
CREATE INDEX idx_accused_name ON Accused(AccusedName);

CREATE TABLE ActSectionAssociation (
    CaseMasterID    INT NOT NULL,
    ActID           VARCHAR(20) NOT NULL,
    SectionID       VARCHAR(20) NOT NULL,
    ActOrderID      INT,
    SectionOrderID  INT,
    FOREIGN KEY (CaseMasterID) REFERENCES CaseMaster(CaseMasterID),
    FOREIGN KEY (ActID) REFERENCES Act(ActCode),
    FOREIGN KEY (ActID, SectionID) REFERENCES Section(ActCode, SectionCode)
);

CREATE INDEX idx_actsection_case ON ActSectionAssociation(CaseMasterID);

CREATE TABLE ArrestSurrender (
    ArrestSurrenderID       INT AUTO_INCREMENT PRIMARY KEY,
    CaseMasterID            INT NOT NULL,
    ArrestSurrenderTypeID   INT,                -- lookup: 1=Arrest, 2=Surrender
    ArrestSurrenderDate     DATE,
    ArrestSurrenderStateId  INT,
    ArrestSurrenderDistrictId INT,
    PoliceStationID         INT,
    IOID                    INT,
    CourtID                 INT,
    AccusedMasterID         INT,
    IsAccused               BIT DEFAULT 1,
    IsComplainantAccused    BIT DEFAULT 0,
    FOREIGN KEY (CaseMasterID) REFERENCES CaseMaster(CaseMasterID),
    FOREIGN KEY (ArrestSurrenderStateId) REFERENCES State(StateID),
    FOREIGN KEY (ArrestSurrenderDistrictId) REFERENCES District(DistrictID),
    FOREIGN KEY (PoliceStationID) REFERENCES Unit(UnitID),
    FOREIGN KEY (IOID) REFERENCES Employee(EmployeeID),
    FOREIGN KEY (CourtID) REFERENCES Court(CourtID),
    FOREIGN KEY (AccusedMasterID) REFERENCES Accused(AccusedMasterID)
);

CREATE INDEX idx_arrestsurrender_case ON ArrestSurrender(CaseMasterID);
CREATE INDEX idx_arrestsurrender_accused ON ArrestSurrender(AccusedMasterID);
```

> **Note on `BIT` type:** MySQL's `BIT(1)` behaves like a boolean but returns as `bytes` (`b'\x01'`/`b'\x00'`) through most Python MySQL drivers, not `True`/`False`. This will bite you in `execute_query` result handling if not addressed — see Section 6.4.

---

## 4. The Big Conceptual Shift: Case-Type Tables → Crime Classification

This is the part of the migration that actually changes how the NL2SQL pipeline thinks, not just table names.

**Old design:** `case_type` was an ENUM directly on `fir_master`, and each type had its own detail table (`cases_theft`, `cases_assault`, etc.) with type-specific columns (`stolen_items`, `weapon_used`, `vehicle_make`...).

**New design:** Crime type is a **two-level classification** via `CrimeHead` (major head, e.g. "Crimes Against Property") → `CrimeSubHead` (minor head, e.g. "Theft", "Burglary", "Robbery"). There are **no more type-specific detail tables** in the official schema — a theft case and an assault case live in the exact same `CaseMaster` row, distinguished only by their `CrimeMinorHeadID`.

### What this means for the pipeline

1. **The schema linker no longer picks "which case table to join."** It now always queries `CaseMaster` and optionally joins `CrimeHead`/`CrimeSubHead` to filter or display the crime type by name.
2. **Type-specific facts (stolen items, weapon used, vehicle registration) have no official home in this schema.** The ER diagram doesn't model them. Two honest options:
   - **(a) Drop them** — `BriefFacts` (free text) on `CaseMaster` is where this detail now lives, unstructured. The chatbot can still surface it via text search/LLM summarization of `BriefFacts`, just not via structured columns.
   - **(b) Keep a lightweight supplementary table** — create one optional `CaseDetailExtra` table (`CaseMasterID`, `DetailKey`, `DetailValue`) as a flexible key-value extension, populated only when we have that data. This isn't in the official ER diagram, so flag it clearly as a local addition if you add it.

   **Recommendation: go with (a) for now.** Don't invent schema the police department didn't ask for. Use `BriefFacts` and let the LLM do its job — this is actually a more realistic test of the NL2SQL pipeline's text-reasoning capability anyway.

### Suggested `CrimeHead` / `CrimeSubHead` seed mapping (to replicate your old case types)

```sql
INSERT INTO CrimeHead (CrimeGroupName) VALUES
  ('Crimes Against Property'),      -- CrimeHeadID 1
  ('Crimes Against Person'),        -- CrimeHeadID 2
  ('Cyber Crimes'),                 -- CrimeHeadID 3
  ('Crimes Against Society');       -- CrimeHeadID 4

INSERT INTO CrimeSubHead (CrimeHeadID, CrimeHeadName, SeqID) VALUES
  (1, 'Theft', 1),
  (1, 'Robbery', 2),
  (1, 'Vehicle Theft', 3),
  (1, 'Fraud', 4),
  (2, 'Assault', 1),
  (2, 'Murder', 2),
  (2, 'Domestic Violence', 3),
  (2, 'Missing Person', 4),
  (3, 'Phishing', 1),
  (3, 'Online Harassment', 2),
  (3, 'Identity Theft', 3),
  (3, 'Hacking', 4),
  (4, 'Drug Offense', 1);
```

This gives you a CrimeMinorHeadID for each of your old `case_type` values — use this mapping when migrating seed data (Section 5).

---

## 5. Seed Data Migration

### Files to update

```
backend/db/
├── schema.sql              ← REPLACE entirely with Section 3's DDL
└── seed.py                  ← REWRITE — significant changes
```

### `seed.py` rewrite plan

```python
"""
Seed data for the official KSP schema.
Order matters — lookup tables first, then Employee, then CaseMaster
and everything that references it.
"""

async def seed_lookup_tables(conn):
    """
    Insert in this order (respects FK dependencies):
    1. State (1 row: Karnataka)
    2. District (a handful: Bengaluru Urban, Bengaluru Rural, Mysuru, etc.)
    3. UnitType (Police Station, Circle Office, District Office)
    4. Unit (your old "station_code" concept — one row per station,
       e.g. "Koramangala Police Station", linked to District + UnitType)
    5. Court (2-3 sample courts per district)
    6. Rank (Constable, Head Constable, ASI, SI, PI, Inspector, DySP, SP —
       same values as your old officers.rank ENUM, now as rows)
    7. Designation (Investigating Officer, SHO, Beat Officer, etc.)
    8. CrimeHead, CrimeSubHead (per Section 4's mapping above)
    9. CaseCategory (FIR, UDR, Zero FIR, PAR)
    10. GravityOffence (Heinous, Non-Heinous)
    11. CaseStatusMaster (Under Investigation, Charge Sheeted, Closed, Open)
        — map your old status ENUM values here
    12. Act (IPC, NDPS, IT Act — at minimum)
    13. Section (a handful of real sections per Act — e.g. IPC 379 (theft),
        IPC 302 (murder), IPC 392 (robbery) — these add legal realism)
    14. CasteMaster (use Karnataka's actual caste category list at a
        reasonable level of generality — e.g. General, OBC, SC, ST, etc.
        — keep this respectful and at category level, not granular)
    15. ReligionMaster (Hindu, Muslim, Christian, Sikh, Jain, Buddhist, Other)
    16. OccupationMaster (Farmer, Government Employee, Private Employee,
        Business Owner, Student, Unemployed, Homemaker, Other)
    """

async def seed_employees(conn) -> list[int]:
    """
    Replaces seed_officers(). Insert 10 employees.
    Map old officer fields:
      old badge_number  -> KGID
      old full_name     -> FirstName (the ER diagram only has FirstName,
                          no LastName column - if you want a full name,
                          either put the whole name in FirstName, which
                          is what the diagram supports, or flag this as
                          a local addition; recommend just using FirstName
                          for the whole name to stay faithful to the diagram)
      old rank ENUM     -> look up RankID from the Rank table
      old department    -> DesignationID (closest match)
      old date_joined   -> AppointmentDate
      old is_active     -> is_active (kept - added column, not in original)
    Assign each employee a UnitID (their station) and DistrictID.
    Assign `role` (our auth addition) the same way BLUEPRINT2 did -
    mostly 'investigator', a few 'supervisor'/'analyst'.
    Return list of EmployeeIDs.
    """

async def seed_cases(conn, employee_ids: list[int]) -> list[int]:
    """
    Replaces seed_fir_master(). Insert 220 cases into CaseMaster.

    CrimeNo generation - follow the REAL format from the ER diagram:
      1-digit Case Category Code + 4-digit DistrictID + 4-digit UnitID
      + 4-digit Year + 5-digit running serial
      Example: 104430006202600001
    This is genuinely more realistic than the old "FIR/2024/KOR/0042" format
    - generate it properly, it's a nice authenticity detail for the demo.

    CaseNo = last 9 digits of CrimeNo (per the spec: YYYY + 5-digit serial).

    Map old case_type ENUM -> CrimeMajorHeadID + CrimeMinorHeadID using the
    Section 4 mapping table.

    Map old status ENUM -> CaseStatusID (look up from CaseStatusMaster).

    Map old incident_date/incident_time -> IncidentFromDate (combine into
    DATETIME). IncidentToDate can equal IncidentFromDate for single-moment
    incidents (most crimes), or be later for ongoing situations (kidnapping,
    missing person spanning days).

    Map old description -> BriefFacts.
    Map old incident_lat/incident_lng -> latitude/longitude directly.

    PolicePersonID = random pick from employee_ids.
    PoliceStationID = that employee's UnitID.

    CrimeRegisteredDate = old date_filed.
    InfoReceivedPSDate = same as CrimeRegisteredDate for simplicity (or a
    few hours/days earlier, for cases where the incident predates the report).

    Return list of CaseMasterIDs.
    """

async def seed_complainants(conn, case_ids: list[int]):
    """
    NEW - didn't exist before. Insert one complainant per case.
    For most cases, the complainant is the victim's family member or the
    victim themself. Assign realistic CasteID/ReligionID/OccupationID/GenderID
    from the lookup tables - this is what unlocks PS1 Section 4 sociological
    analysis, so make this data varied and realistic, not all-the-same.
    """

async def seed_victims(conn, case_ids: list[int]):
    """
    Replaces seed_victims(). Same logic, new table/column names.
    VictimPolice: set to 1 for a small number of cases (a victim who is
    also a police officer) to make that flag demonstrable.
    """

async def seed_accused(conn, case_ids: list[int]):
    """
    Replaces seed_accused(). CRITICAL - preserve your repeat-offender
    demo data exactly as before:
      - "Mahesh Gowda" / alias concept is GONE from the new schema
        (Accused table has no `alias` column). Put "Mahesh Gowda (alias
        Bullet Mahesh)" directly in AccusedName as a single string, since
        that's the only field available, OR track alias as a local addition
        if you want to preserve queryability - flag this choice clearly.
      - Assign PersonID as 'A1', 'A2' etc. per case (resets per case, not
        global - per the schema's own description: "Accused Sorting like
        A1, A2, A3").
      - Still create the same 8-FIR-spanning Mahesh Gowda, 5-FIR Ravi Kumar,
        etc. - same demo richness, just against CaseMasterID instead of fir_id.
    """

async def seed_act_sections(conn, case_ids: list[int]):
    """
    NEW - didn't exist before. For each case, assign 1-3 relevant IPC
    sections based on its crime type (e.g. theft -> IPC 379, murder -> IPC 302,
    robbery -> IPC 392). This is a nice realism addition and also gives the
    chatbot something genuinely new and interesting to query
    ("what section was used in case X").
    """

async def seed_arrest_surrender(conn, case_ids: list[int], employee_ids: list[int]):
    """
    Replaces the old accused.arrest_status/arrest_date fields, which don't
    exist on the new Accused table. Insert one ArrestSurrender row for each
    accused who was arrested (skip 'at_large' ones - no row means no arrest
    yet, which is the natural way to represent "still at large" in this
    schema - there's no explicit status enum for it).
    Link AccusedMasterID, set ArrestSurrenderDate, IOID (investigating
    officer), PoliceStationID, CourtID.
    """
```

> **What's genuinely lost in this migration, be upfront about it:** `alias`, `prior_fir_count` (denormalized — now must be computed via COUNT query each time instead of stored), `id_type`/`id_number` (Aadhaar/PAN — not in the official schema), `arrest_status` as an explicit enum (now inferred from presence/absence of an ArrestSurrender row), and all the type-specific fields (`stolen_items`, `weapon_used`, `vehicle_make`, etc. — folded into `BriefFacts` free text per Section 4's decision). None of this blocks the demo, but be ready to explain these tradeoffs if asked — they're the natural cost of moving to a real, externally-specified schema instead of one designed purely for hackathon convenience.

---

## 6. Pipeline & Backend Code Changes

### 6.1 `backend/db/schema_catalog.py` — full rewrite of `SCHEMA_CATALOG`

This is the second most important file in the whole migration — the NL2SQL pipeline's schema linker reads this to decide which tables to inject into the LLM prompt.

```python
SCHEMA_CATALOG = {
    "CaseMaster": {
        "description": "Central case/FIR registry. Every case starts here. Crime type is classified via CrimeMajorHeadID/CrimeMinorHeadID, not a type column.",
        "columns": {
            "CaseMasterID": "INT PRIMARY KEY",
            "CrimeNo": "VARCHAR(30) UNIQUE - structured crime number",
            "CaseNo": "VARCHAR(20)",
            "CrimeRegisteredDate": "DATE",
            "PolicePersonID": "INT FK -> Employee.EmployeeID",
            "PoliceStationID": "INT FK -> Unit.UnitID",
            "CaseCategoryID": "INT FK -> CaseCategory.CaseCategoryID (FIR/UDR/PAR/Zero FIR)",
            "GravityOffenceID": "INT FK -> GravityOffence.GravityOffenceID",
            "CrimeMajorHeadID": "INT FK -> CrimeHead.CrimeHeadID",
            "CrimeMinorHeadID": "INT FK -> CrimeSubHead.CrimeSubHeadID - the actual crime type, e.g. Theft, Murder",
            "CaseStatusID": "INT FK -> CaseStatusMaster.CaseStatusID",
            "CourtID": "INT FK -> Court.CourtID",
            "IncidentFromDate": "DATETIME",
            "IncidentToDate": "DATETIME",
            "latitude": "DECIMAL(10,8)",
            "longitude": "DECIMAL(11,8)",
            "BriefFacts": "TEXT - free text summary, search here for type-specific details like weapon, stolen items, etc."
        },
        "keywords": ["case", "fir", "crime", "filed", "registered", "incident", "location", "status", "all cases"],
        "always_include": True
    },
    "Accused": {
        "description": "Accused persons linked to a case.",
        "columns": {
            "AccusedMasterID": "INT PRIMARY KEY",
            "CaseMasterID": "INT FK -> CaseMaster.CaseMasterID",
            "AccusedName": "VARCHAR(150)",
            "AgeYear": "INT",
            "GenderID": "INT - M/F/T lookup",
            "PersonID": "VARCHAR(10) - e.g. A1, A2"
        },
        "keywords": ["accused", "suspect", "offender", "person", "name", "criminal"]
    },
    "Victim": {
        "description": "Victims linked to a case.",
        "columns": {
            "VictimMasterID": "INT PRIMARY KEY",
            "CaseMasterID": "INT FK -> CaseMaster.CaseMasterID",
            "VictimName": "VARCHAR(150)",
            "AgeYear": "INT",
            "GenderID": "INT",
            "VictimPolice": "BIT - 1 if the victim is a police officer"
        },
        "keywords": ["victim", "injured", "affected"]
    },
    "ComplainantDetails": {
        "description": "The person who filed the FIR. May or may not be the victim. Includes demographic data for sociological analysis.",
        "columns": {
            "ComplainantID": "INT PRIMARY KEY",
            "CaseMasterID": "INT FK -> CaseMaster.CaseMasterID",
            "ComplainantName": "VARCHAR(150)",
            "AgeYear": "INT",
            "OccupationID": "INT FK -> OccupationMaster.OccupationID",
            "ReligionID": "INT FK -> ReligionMaster.ReligionID",
            "CasteID": "INT FK -> CasteMaster.caste_master_id",
            "GenderID": "INT"
        },
        "keywords": ["complainant", "filed by", "reported by", "who reported", "occupation", "religion", "caste", "demographic"]
    },
    "ArrestSurrender": {
        "description": "Arrest or surrender events. Presence of a row for an accused means they've been arrested/surrendered; absence means still at large.",
        "columns": {
            "ArrestSurrenderID": "INT PRIMARY KEY",
            "CaseMasterID": "INT FK -> CaseMaster.CaseMasterID",
            "AccusedMasterID": "INT FK -> Accused.AccusedMasterID",
            "ArrestSurrenderDate": "DATE",
            "IOID": "INT FK -> Employee.EmployeeID - investigating officer who made the arrest",
            "CourtID": "INT FK -> Court.CourtID"
        },
        "keywords": ["arrest", "arrested", "surrender", "at large", "custody", "caught"]
    },
    "ActSectionAssociation": {
        "description": "Legal acts and sections charged in a case (e.g. IPC 302 for murder).",
        "columns": {
            "CaseMasterID": "INT FK -> CaseMaster.CaseMasterID",
            "ActID": "VARCHAR(20) FK -> Act.ActCode",
            "SectionID": "VARCHAR(20) FK -> Section.SectionCode"
        },
        "keywords": ["section", "act", "ipc", "charged", "legal", "law"]
    },
    "CrimeHead": {
        "description": "Major crime classification (e.g. Crimes Against Property).",
        "columns": {"CrimeHeadID": "INT PRIMARY KEY", "CrimeGroupName": "VARCHAR(150)"},
        "keywords": ["crime group", "major crime", "category of crime"]
    },
    "CrimeSubHead": {
        "description": "Minor crime classification - the actual crime type (Theft, Murder, etc.).",
        "columns": {"CrimeSubHeadID": "INT PRIMARY KEY", "CrimeHeadID": "INT FK", "CrimeHeadName": "VARCHAR(150) - the crime type name"},
        "keywords": ["theft", "murder", "robbery", "assault", "fraud", "crime type", "kind of crime"]
    },
    "CaseStatusMaster": {
        "description": "Case status lookup (Open, Under Investigation, Closed, Charge Sheeted).",
        "columns": {"CaseStatusID": "INT PRIMARY KEY", "CaseStatusName": "VARCHAR(80)"},
        "keywords": ["status", "open", "closed", "under investigation", "chargesheeted"]
    },
    "Employee": {
        "description": "Police employees/officers.",
        "columns": {
            "EmployeeID": "INT PRIMARY KEY", "FirstName": "VARCHAR(100)",
            "RankID": "INT FK -> Rank.RankID", "UnitID": "INT FK -> Unit.UnitID",
            "KGID": "VARCHAR(30) - government employee ID"
        },
        "keywords": ["officer", "employee", "investigating officer", "rank", "assigned", "IO"]
    },
    "Rank": {
        "description": "Police rank lookup.",
        "columns": {"RankID": "INT PRIMARY KEY", "RankName": "VARCHAR(50)"},
        "keywords": ["rank", "constable", "inspector", "SI", "PI", "DSP"]
    },
    "Unit": {
        "description": "Police station / organizational unit.",
        "columns": {"UnitID": "INT PRIMARY KEY", "UnitName": "VARCHAR(150)", "DistrictID": "INT FK"},
        "keywords": ["station", "police station", "unit"]
    },
    "District": {
        "description": "District lookup.",
        "columns": {"DistrictID": "INT PRIMARY KEY", "DistrictName": "VARCHAR(100)"},
        "keywords": ["district"]
    },
    "Court": {
        "description": "Court where cases are tried.",
        "columns": {"CourtID": "INT PRIMARY KEY", "CourtName": "VARCHAR(150)"},
        "keywords": ["court", "tried", "hearing"]
    },
    "CasteMaster": {
        "description": "Caste lookup, linked from ComplainantDetails for demographic analysis.",
        "columns": {"caste_master_id": "INT PRIMARY KEY", "caste_master_name": "VARCHAR(100)"},
        "keywords": ["caste", "demographic"]
    },
    "ReligionMaster": {
        "description": "Religion lookup.",
        "columns": {"ReligionID": "INT PRIMARY KEY", "ReligionName": "VARCHAR(100)"},
        "keywords": ["religion", "demographic"]
    },
    "OccupationMaster": {
        "description": "Occupation lookup.",
        "columns": {"OccupationID": "INT PRIMARY KEY", "OccupationName": "VARCHAR(100)"},
        "keywords": ["occupation", "profession", "job", "demographic"]
    },
    "Act": {
        "description": "Legal act lookup (IPC, NDPS, etc.)",
        "columns": {"ActCode": "VARCHAR(20) PRIMARY KEY", "ActDescription": "VARCHAR(200)"},
        "keywords": ["act", "ipc", "ndps", "law"]
    },
    "Section": {
        "description": "Legal section lookup, child of Act.",
        "columns": {"ActCode": "VARCHAR(20) FK", "SectionCode": "VARCHAR(20)", "SectionDescription": "VARCHAR(300)"},
        "keywords": ["section", "ipc section"]
    }
}
```

> **Note:** the case-type tables (`cases_theft`, `cases_assault`, etc.) are **gone entirely** from this catalog. Don't leave them in — the schema linker will try to inject a table that no longer exists, which would break SQL generation immediately.

### 6.2 Few-shot examples in `get_few_shot_examples()` — full rewrite

Every example query needs rewriting against the new table/column names. At minimum, rewrite these patterns:

```sql
-- Q: How many cases are open?
SELECT COUNT(*) AS open_cases
FROM CaseMaster cm
JOIN CaseStatusMaster cs ON cs.CaseStatusID = cm.CaseStatusID
WHERE cs.CaseStatusName = 'Open'

-- Q: Show me all theft cases.
SELECT cm.CaseMasterID, cm.CrimeNo, cm.CrimeRegisteredDate
FROM CaseMaster cm
JOIN CrimeSubHead csh ON csh.CrimeSubHeadID = cm.CrimeMinorHeadID
WHERE csh.CrimeHeadName = 'Theft'
LIMIT 50

-- Q: Show me all cases involving [name].
SELECT cm.CaseMasterID, cm.CrimeNo, cm.CrimeRegisteredDate, a.AccusedName
FROM Accused a
JOIN CaseMaster cm ON cm.CaseMasterID = a.CaseMasterID
WHERE a.AccusedName LIKE '%[name]%'

-- Q: Which accused are still at large?
SELECT DISTINCT a.AccusedMasterID, a.AccusedName
FROM Accused a
LEFT JOIN ArrestSurrender ar ON ar.AccusedMasterID = a.AccusedMasterID
WHERE ar.ArrestSurrenderID IS NULL

-- Q: What IPC sections were used in case [CrimeNo]?
SELECT s.SectionCode, s.SectionDescription
FROM ActSectionAssociation asa
JOIN CaseMaster cm ON cm.CaseMasterID = asa.CaseMasterID
JOIN Section s ON s.ActCode = asa.ActID AND s.SectionCode = asa.SectionID
WHERE cm.CrimeNo = '[CrimeNo]'
```

Build out the full set of ~12-15 examples following this pattern, covering each major table combination, the same way the original `get_few_shot_examples()` did.

### 6.3 `SQL_SYSTEM_PROMPT` update

Add these new rules given the schema's distinctive naming convention:

```
10. Table and column names in this schema use PascalCase (e.g. CaseMaster,
    AccusedName), not snake_case. Always match the exact casing shown in
    the schema provided.
11. "At large" status has no explicit column - an accused is at large if
    NO row exists for them in ArrestSurrender. Use LEFT JOIN ... WHERE
    ... IS NULL for this, not a status column comparison.
12. Crime type is never a column value to filter directly - it's reached
    via CrimeSubHead.CrimeHeadName, requiring a JOIN through CaseMaster.CrimeMinorHeadID.
```

### 6.4 `db/connection.py` — handle `BIT` columns

aiomysql may return `BIT` columns as `bytes` rather than booleans. Add a small normalization step in `execute_query`:

```python
def _normalize_bit_fields(row: dict) -> dict:
    """
    aiomysql can return BIT(1) columns as b'\\x01'/b'\\x00' instead of bool.
    Normalize any single-byte bytes value to a proper Python bool so
    downstream JSON serialization and the LLM's view of the data don't
    show garbled byte strings.
    """
    return {
        k: (v == b'\x01' if isinstance(v, bytes) and len(v) == 1 else v)
        for k, v in row.items()
    }

# Apply this to every row in execute_query's return path:
# return [_normalize_bit_fields(row) for row in rows]
```

### 6.5 BLUEPRINT2 modules — update table/column references

Every module built in `BLUEPRINT2.md` queries the old schema directly. Update each:

- **`profiling/risk_scoring.py`** — `accused` → `Accused`, `accused_id` → `AccusedMasterID`, `fir_master` → `CaseMaster` joined via `CaseMasterID`. The `arrest_status == 'at_large'` check becomes a `LEFT JOIN ArrestSurrender ... IS NULL` check (see 6.3's rule 11). `prior_fir_count` no longer exists as a stored column — compute it live: `SELECT COUNT(*) FROM Accused WHERE AccusedName = %s`.
- **`analytics/trend_analytics.py`** — `fir_master.date_filed` → `CaseMaster.CrimeRegisteredDate`, `case_type` grouping → `JOIN CrimeSubHead ON CrimeMinorHeadID` then `GROUP BY CrimeHeadName`, `incident_location` (which no longer exists as a free-text field) → either use `latitude`/`longitude` reverse-geocoded, or fall back to grouping by `Unit.UnitName` (the police station) as the closest available "location" concept.
- **`decision_support/case_timeline.py`** — rebuild entirely around `CaseMaster.CrimeRegisteredDate`, `ArrestSurrender.ArrestSurrenderDate`, and `ChargesheetDetails.csdate` (if migrated) as the timeline events — the old per-type "recovery_date" events no longer exist (see Section 4's decision to drop type-specific fields).
- **`decision_support/similar_cases.py`** — `case_type` similarity becomes `CrimeMinorHeadID` equality; `incident_location` similarity becomes `PoliceStationID` equality.
- **`auth/role_guard.py` and `auth/simple_auth.py`** — `officers` → `Employee`, `officer_id` → `EmployeeID`, `badge_number` → `KGID`, `full_name` → `FirstName`.
- **`graph/network_builder.py`** — this is the trickiest one. `case_relationships` **does not exist** in the official schema at all. See Section 7.

### 6.6 `routers/*.py` — update every reference

Search for and update every occurrence of the old field/table names across all routers (`chat.py`, `profiling.py`, `analytics.py`, `decision_support.py`, `export.py`, `voice.py`). This is mechanical but extensive — recommend a careful find-and-replace pass per file rather than a blind global replace, since some names (`status`, `description`) are common English words that might appear in unrelated contexts (log messages, docstrings).

---

## 7. The Network Graph Problem

`case_relationships` was a hackathon invention — a clean way to model "these accused are linked" or "these cases share a pattern." **The official ER diagram has no equivalent table.** This needs a decision, not just a rename.

### Option A — Derive relationships computationally, no new table

Build the graph from existing data at query time instead of a stored relationships table:

- **Co-accused links**: two `Accused` rows sharing the same `CaseMasterID` → linked as co-accused
- **Repeat offender links**: two `CaseMaster` rows where an `Accused.AccusedName` matches across both → linked as "same person, different case"
- **Same MO links**: two `CaseMaster` rows sharing the same `CrimeMinorHeadID` AND same `PoliceStationID` within a time window → loosely linked as "possible pattern"

This requires rewriting `network_builder.py`'s `_fetch_relationships()` to run these derivation queries instead of reading a `case_relationships` table. More query complexity, but stays faithful to the official schema with zero unauthorized additions.

### Option B — Keep `case_relationships` as a clearly-flagged local extension

Add it back as an extra table not in the official ER diagram, referencing the new `CaseMasterID`/`AccusedMasterID` keys instead of the old `fir_id`/`accused_id`. Document clearly (in code comments and in any presentation) that this is a derived/cached table our system maintains for performance, not part of KSP's official schema.

**Recommendation: Option A for the demo.** It's more defensible if anyone from KSP asks "where does this table come from" — the honest answer becomes "nowhere, it's computed live from your own schema," which is a stronger answer than "we added a table you didn't ask for."

```python
# network_builder.py - Option A sketch
async def _fetch_co_accused_links(case_master_id: int) -> list[dict]:
    """Other accused in the SAME case - trivially co-accused."""
    return await execute_query(
        """SELECT a2.AccusedMasterID, a2.AccusedName
           FROM Accused a1 JOIN Accused a2
             ON a1.CaseMasterID = a2.CaseMasterID AND a1.AccusedMasterID != a2.AccusedMasterID
           WHERE a1.CaseMasterID = %s""",
        (case_master_id,)
    )

async def _fetch_repeat_appearances(accused_name: str) -> list[dict]:
    """Other cases featuring an accused with the same name."""
    return await execute_query(
        """SELECT cm.CaseMasterID, cm.CrimeNo, a.AccusedMasterID
           FROM Accused a JOIN CaseMaster cm ON cm.CaseMasterID = a.CaseMasterID
           WHERE a.AccusedName = %s""",
        (accused_name,)
    )
```

Rebuild `build_graph_for_fir`/`build_graph_for_accused` to call these instead of `_fetch_relationships`, and adjust node/edge labeling (`relationship_type` becomes a derived string like `"co_accused"` or `"repeat_offender"` set in Python, not read from a DB column).

---

## 8. Evidence Media — Same Treatment as the Graph

`evidence_media` also has no equivalent in the official ER diagram. Given the SmartBrowz/media-viewer work was already a "nice to have" feature built on hackathon-invented data:

**Recommendation: keep `evidence_media` exactly as-is, but repoint its foreign key.** Change `fir_id INT FK -> fir_master.fir_id` to `case_master_id INT FK -> CaseMaster.CaseMasterID`. Flag in code comments that this table is a local addition, not part of KSP's official schema — same honesty principle as the graph table decision, but here we're choosing to keep it since media viewing has no computed/derived alternative (you can't "derive" a photo from other data).

```sql
-- Local addition - not in official KSP ER diagram. Tracks evidence files.
CREATE TABLE evidence_media (
    media_id          INT AUTO_INCREMENT PRIMARY KEY,
    case_master_id    INT NOT NULL,
    media_type        ENUM('image','audio','video','document') NOT NULL,
    file_name         VARCHAR(200) NOT NULL,
    stratus_folder_id VARCHAR(100) NOT NULL,
    stratus_file_id   VARCHAR(100) NOT NULL,
    description       VARCHAR(500),
    uploaded_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (case_master_id) REFERENCES CaseMaster(CaseMasterID)
);
```

---

## 9. Migration Execution Order

Do not skip steps. Each one assumes the previous succeeded.

1. **Back up current data first** — even though it's seed data, preserve it in case anything needs cross-referencing:
   ```bash
   mysqldump -u adarsh -proot ksp_crime_db > backup_pre_migration_$(date +%Y%m%d).sql
   ```
2. **Create a NEW database** for the migration rather than dropping the old one — keeps a rollback path:
   ```bash
   mysql -u adarsh -proot -e "CREATE DATABASE ksp_crime_db_v2;"
   ```
3. **Apply the new DDL** (Section 3) to `ksp_crime_db_v2`.
4. **Update `.env`**: `DB_NAME=ksp_crime_db_v2` — keep `DB_NAME=ksp_crime_db` commented out next to it for easy rollback.
5. **Rewrite and run `seed.py`** per Section 5. Verify counts:
   ```sql
   SELECT COUNT(*) FROM CaseMaster;     -- expect 220
   SELECT COUNT(*) FROM Accused;        -- expect 260+
   SELECT COUNT(*) FROM Employee;       -- expect 10
   ```
6. **Verify your demo star survived the migration**:
   ```sql
   SELECT AccusedName, COUNT(*) FROM Accused GROUP BY AccusedName ORDER BY COUNT(*) DESC LIMIT 5;
   ```
   Expect "Mahesh Gowda" (or whatever string you used per Section 5's alias note) at the top with 8.
7. **Rewrite `schema_catalog.py`** per Section 6.1.
8. **Rewrite few-shot examples and system prompt** per Sections 6.2-6.3.
9. **Add the `BIT` normalization** per Section 6.4.
10. **Rewrite `network_builder.py`** per Section 7 (Option A).
11. **Update `evidence_media`'s FK** per Section 8.
12. **Update every BLUEPRINT2 module** per Section 6.5 — do these one at a time, testing each endpoint with curl before moving to the next, exactly like the original Step 1-5 discipline.
13. **Update `auth/simple_auth.py`** per Section 6.5's Employee/KGID renames — test login still works.
14. **Run the original Step 2 verification tests** (the 6 curl tests from `OneToTwo.md`) against the new schema — they should all still pass, just returning PascalCase field names now instead of snake_case.
15. **Only after everything above passes**, consider renaming `ksp_crime_db_v2` back to the primary name, or just keep using `_v2` and update `.env` permanently.

---

## 10. What Changes for the Frontend

Minimal, if the backend's JSON response shape stays consistent (it should — `table_data` is still just an array of dicts, just with different key names now). The few places that need attention:

- Anywhere the frontend hardcodes a field name for special handling (check `TableRenderer.jsx`, `MediaViewer.jsx`, `CaseDetailPanel.jsx` for any reference to `fir_id` specifically — these need to become `CaseMasterID`)
- `RiskBadge.jsx`'s API call used `accusedId` as a route param — still valid as a concept, just confirm the backend route still accepts an integer ID the same way (it will, just referring to `AccusedMasterID` now)
- Suggested questions in `WelcomeScreen.jsx` reference "Mahesh Gowda" by name — no change needed, the name itself didn't change

---

## What This Migration Deliberately Does Not Do

- Does not implement `inv_arrestsurrenderaccused` junction table, `Inv_OccuranceTime`, `CrimeHeadActSection`, or `ChargesheetDetails` — deferred per Section 2, can be added later without disrupting anything built here
- Does not invent new schema beyond `evidence_media` (kept, repointed) — the graph table is deliberately removed in favor of computed relationships, staying faithful to what KSP actually specified
- Does not change the LLM models, the auth pattern, the SSE streaming mechanism, voice pipeline, or any Catalyst service integration — this migration is scoped purely to the database layer and the pipeline code that reads it
