# MIGRATE STEP 1 — Planning, Core Mapping, and Initial Schema

> Run this file first. It defines the migration mapping, the scope decisions, and the first part of the official KSP schema DDL.

## 1. Why this split exists

This migration is large. We split it into four ordered files so each step is smaller and easier to run in sequence:

1. `MIGRATE_STEP1.md`
2. `MIGRATE_STEP2.md`
3. `MIGRATE_STEP3.md`
4. `MIGRATE_STEP4.md`

Do not skip steps. Each step assumes the previous one is complete.

## 2. Core Mapping — Old Schema → New Schema

This is the single most important table in the migration.

| Old table | Old key field | New table | New key field | Notes |
|---|---|---|---|---|
| `fir_master` | `fir_id` | `CaseMaster` | `CaseMasterID` | Central case record — same role, different structure |
| `accused` | `accused_id` | `Accused` | `AccusedMasterID` | Renamed, fewer denormalized fields |
| `victims` | `victim_id` | `Victim` | `VictimMasterID` | Renamed |
| *(none — complainant didn't exist as a concept)* | — | `ComplainantDetails` | `ComplainantID` | New entity. Complainant ≠ victim |
| `officers` | `officer_id` | `Employee` | `EmployeeID` | Renamed and restructured |
| `case_relationships` | `rel_id` | *(no direct equivalent)* | — | Not in the official schema |
| `evidence_media` | `media_id` | *(no direct equivalent)* | — | Not in the official schema |
| `cases_theft`, `cases_assault`, `cases_vehicle_theft`, `cases_fraud`, `cases_cybercrime`, `cases_missing_person`, `cases_drug_offense` | various | Merged into `CaseMaster` + `CrimeHead`/`CrimeSubHead` | — | No more per-type tables |

### New tables that did not exist before

These are additions required by the official KSP schema:

- `ArrestSurrender`
- `ActSectionAssociation`
- `Act`, `Section`
- `CrimeHead`, `CrimeSubHead`
- `CaseCategory`, `GravityOffence`, `CaseStatusMaster`
- `CasteMaster`, `ReligionMaster`, `OccupationMaster`
- `Court`, `District`, `State`, `Unit`, `UnitType`
- `Rank`, `Designation`

## 3. What to migrate now vs defer

### Migrate now

These tables are required for the chat pipeline and the demo:

- `CaseMaster`, `Accused`, `Victim`, `ComplainantDetails`
- `Employee`, `Rank`, `Designation`, `Unit`, `UnitType`, `District`, `State`
- `CaseCategory`, `GravityOffence`, `CaseStatusMaster`
- `CrimeHead`, `CrimeSubHead`, `Act`, `Section`, `ActSectionAssociation`, `ArrestSurrender`
- `CasteMaster`, `ReligionMaster`, `OccupationMaster`, `Court`

### Defer

These are low-value or complex additions that are not needed for the initial demo:

- `CrimeHeadActSection`
- `ChargesheetDetails`
- `inv_arrestsurrenderaccused` junction table
- `Inv_OccuranceTime`

## 4. Initial Schema DDL

Apply these tables first against a fresh database. This is the first DDL block to run.

```sql
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
    role                    ENUM('investigator','analyst','supervisor','policymaker')
                            NOT NULL DEFAULT 'investigator',
    is_active               BOOLEAN DEFAULT TRUE,
    FOREIGN KEY (DistrictID) REFERENCES District(DistrictID),
    FOREIGN KEY (UnitID) REFERENCES Unit(UnitID),
    FOREIGN KEY (RankID) REFERENCES Rank(RankID),
    FOREIGN KEY (DesignationID) REFERENCES Designation(DesignationID)
);

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
    LookupValue     VARCHAR(50) NOT NULL
);

CREATE TABLE GravityOffence (
    GravityOffenceID INT AUTO_INCREMENT PRIMARY KEY,
    LookupValue      VARCHAR(50) NOT NULL
);

CREATE TABLE CaseStatusMaster (
    CaseStatusID    INT AUTO_INCREMENT PRIMARY KEY,
    CaseStatusName  VARCHAR(80) NOT NULL
);

CREATE TABLE Act (
    ActCode         VARCHAR(20) PRIMARY KEY,
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
```

## 5. What to verify before Step 2

- Confirm the new database is fresh and unused.
- Confirm the DDL above runs cleanly.
- Confirm you have a backup of the existing database before making any production changes.
