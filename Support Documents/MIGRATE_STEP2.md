# MIGRATE STEP 2 — Complete Schema + Seed Data Migration

> Run this file second. It finishes the official schema DDL and rewrites the seed data loader.

## 1. Complete the schema DDL

Continue from Step 1 to create the remaining core case tables.

```sql
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
    BriefFacts              TEXT,
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
    PersonID            VARCHAR(10),
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
    ArrestSurrenderTypeID   INT,
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

## 2. Evidence media note

`evidence_media` is not part of the official ER diagram. If you keep it, repoint the foreign key to `CaseMasterID`. This is a local extension, not official schema.

## 3. Seed script rewrite plan

The old `backend/db/seed.py` must be rewritten entirely.

### What to change

- `seed_officers()` ➜ `seed_employees()`
- `seed_fir_master()` ➜ `seed_cases()`
- `seed_victims()` ➜ `seed_victims()` with `Victim` insert
- `seed_accused()` ➜ `seed_accused()` with `Accused` insert
- Add `seed_complainants()` for `ComplainantDetails`
- Add `seed_act_sections()` for `ActSectionAssociation`
- Add `seed_arrest_surrender()` for `ArrestSurrender`

### Important mapping rules

- Old `fir_id` becomes `CaseMasterID`
- Old `fir_number` becomes `CrimeNo`
- Old `case_type` maps to `CrimeMajorHeadID`/`CrimeMinorHeadID`
- Old `status` maps to `CaseStatusID`
- Old `investigating_officer_id` becomes `PolicePersonID`
- Old `incident_date`/`incident_time` becomes `IncidentFromDate`
- Old `description` becomes `BriefFacts`
- Old `incident_lat`/`incident_lng` becomes `latitude`/`longitude`
- Old `badge_number` becomes `KGID`
- Old `full_name` becomes `FirstName` (store the whole name here)
- Old `rank` becomes `RankID` via lookup table

### Seed order

1. Lookup tables (`State`, `District`, `UnitType`, `Unit`, `Court`, `Rank`, `Designation`, `CrimeHead`, `CrimeSubHead`, `CaseCategory`, `GravityOffence`, `CaseStatusMaster`, `Act`, `Section`, `CasteMaster`, `ReligionMaster`, `OccupationMaster`)
2. `Employee`
3. `CaseMaster`
4. `ComplainantDetails`
5. `Victim`
6. `Accused`
7. `ActSectionAssociation`
8. `ArrestSurrender`

### Repeat offender handling

Preserve the same demo structure as before:
- one repeat offender with 8 cases
- one with 5 cases
- one with 4 cases
- one with 3 cases

If alias data is important, store it in `AccusedName` as a full name plus alias text (because `Accused` has no alias column in the official schema).

### What is lost / moved

- `alias`, `prior_fir_count`, and `id_type` / `id_number` do not exist in the new schema.
- `arrest_status` is now represented by `ArrestSurrender` existence.
- Type-specific columns like `stolen_items`, `weapon_used`, and `vehicle_make` are folded into `BriefFacts`.

## 4. Verify seed migration

After running the rewritten seed script, verify these counts:

```sql
SELECT COUNT(*) FROM CaseMaster;
SELECT COUNT(*) FROM Accused;
SELECT COUNT(*) FROM Employee;
SELECT COUNT(*) FROM Victim;
SELECT COUNT(*) FROM ComplainantDetails;
SELECT COUNT(*) FROM ActSectionAssociation;
```

Also verify the repeat offender names are present and the CaseMasterIDs are populated as expected.
