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

CREATE TABLE `Rank` (
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
    role                    ENUM('investigator','analyst','supervisor','policymaker') NOT NULL DEFAULT 'investigator',
    is_active               BOOLEAN DEFAULT TRUE,
    FOREIGN KEY (DistrictID) REFERENCES District(DistrictID),
    FOREIGN KEY (UnitID) REFERENCES Unit(UnitID),
    FOREIGN KEY (RankID) REFERENCES `Rank`(RankID),
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

-- Step 2 tables — core case tables

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
    ArrestSurrenderID         INT AUTO_INCREMENT PRIMARY KEY,
    CaseMasterID              INT NOT NULL,
    ArrestSurrenderTypeID     INT,
    ArrestSurrenderDate       DATE,
    ArrestSurrenderStateId    INT,
    ArrestSurrenderDistrictId INT,
    PoliceStationID           INT,
    IOID                      INT,
    CourtID                   INT,
    AccusedMasterID           INT,
    IsAccused                 BIT DEFAULT 1,
    IsComplainantAccused      BIT DEFAULT 0,
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

CREATE TABLE evidence_media (
    media_id INT AUTO_INCREMENT PRIMARY KEY,
    case_master_id INT NOT NULL,
    media_type ENUM('image','audio','video','document') NOT NULL,
    file_name VARCHAR(200) NOT NULL,
    stratus_folder_id VARCHAR(100) NOT NULL,
    stratus_file_id VARCHAR(100) NOT NULL,
    description VARCHAR(500) DEFAULT NULL,
    uploaded_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_media_case (case_master_id),
    FOREIGN KEY (case_master_id) REFERENCES CaseMaster(CaseMasterID)
);

CREATE TABLE chat_sessions (
    session_id VARCHAR(36) PRIMARY KEY,
    officer_id INT NOT NULL,
    title VARCHAR(200) NOT NULL DEFAULT 'Untitled Chat',
    created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    message_count INT DEFAULT 0,
    is_active TINYINT(1) DEFAULT 1,
    KEY idx_sessions_officer (officer_id, updated_at),
    FOREIGN KEY (officer_id) REFERENCES Employee(EmployeeID)
);

CREATE TABLE chat_messages (
    message_id INT AUTO_INCREMENT PRIMARY KEY,
    session_id VARCHAR(36) NOT NULL,
    role ENUM('user', 'assistant') NOT NULL,
    content TEXT NOT NULL,
    sql_generated TEXT,
    has_table TINYINT(1) DEFAULT 0,
    has_media TINYINT(1) DEFAULT 0,
    graph_available TINYINT(1) DEFAULT 0,
    created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
    table_data_json MEDIUMTEXT,
    KEY idx_messages_session (session_id, created_at),
    FOREIGN KEY (session_id) REFERENCES chat_sessions(session_id)
);
