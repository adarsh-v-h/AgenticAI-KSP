-- KSP Migration Step 1 - Remaining tables
-- Reserved keyword fix: Rank is backtick-escaped throughout

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
