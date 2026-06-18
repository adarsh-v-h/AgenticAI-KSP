-- KSP Crime Intelligence DB Schema
-- Run this once against Catalyst Data Store
-- All tables for a single police station scope
-- Safe to re-run (IF NOT EXISTS on all tables)

CREATE TABLE IF NOT EXISTS officers (
    officer_id        INT AUTO_INCREMENT PRIMARY KEY,
    badge_number      VARCHAR(20) NOT NULL UNIQUE,
    full_name         VARCHAR(100) NOT NULL,
    `rank`            ENUM('Constable','Head Constable','ASI','SI','PI','Inspector','DySP','SP') NOT NULL,
    department        VARCHAR(50),
    phone             VARCHAR(15),
    email             VARCHAR(100),
    date_joined       DATE,
    is_active         BOOLEAN DEFAULT TRUE,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fir_master (
    fir_id            INT AUTO_INCREMENT PRIMARY KEY,
    fir_number        VARCHAR(30) NOT NULL UNIQUE,   -- e.g. "FIR/2024/KOR/0042"
    station_code      VARCHAR(20) NOT NULL,
    date_filed        DATE NOT NULL,
    time_filed        TIME NOT NULL,
    case_type         ENUM(
                        'theft','robbery','assault','murder','fraud',
                        'cybercrime','missing_person','vehicle_theft',
                        'drug_offense','domestic_violence','other'
                      ) NOT NULL,
    incident_date     DATE,
    incident_time     TIME,
    incident_location VARCHAR(200),
    incident_lat      DECIMAL(10, 8),
    incident_lng      DECIMAL(11, 8),
    description       TEXT,
    status            ENUM('open','under_investigation','closed','chargesheeted') DEFAULT 'open',
    investigating_officer_id INT,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    FOREIGN KEY (investigating_officer_id) REFERENCES officers(officer_id),
    INDEX idx_fir_case_type (case_type),
    INDEX idx_fir_status (status),
    INDEX idx_fir_date (date_filed)
);

CREATE TABLE IF NOT EXISTS accused (
    accused_id        INT AUTO_INCREMENT PRIMARY KEY,
    fir_id            INT NOT NULL,
    full_name         VARCHAR(100),
    alias             VARCHAR(100),
    age               INT,
    gender            ENUM('male','female','other','unknown') DEFAULT 'unknown',
    address           TEXT,
    phone             VARCHAR(15),
    id_type           VARCHAR(30),         -- Aadhaar, PAN, etc.
    id_number         VARCHAR(50),
    prior_fir_count   INT DEFAULT 0,       -- denormalized for fast risk queries
    arrest_status     ENUM('arrested','at_large','unknown') DEFAULT 'unknown',
    arrest_date       DATE,
    notes             TEXT,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (fir_id) REFERENCES fir_master(fir_id),
    INDEX idx_accused_fir (fir_id),
    INDEX idx_accused_name (full_name)
);

CREATE TABLE IF NOT EXISTS victims (
    victim_id         INT AUTO_INCREMENT PRIMARY KEY,
    fir_id            INT NOT NULL,
    full_name         VARCHAR(100),
    age               INT,
    gender            ENUM('male','female','other','unknown') DEFAULT 'unknown',
    address           TEXT,
    phone             VARCHAR(15),
    injury_description TEXT,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (fir_id) REFERENCES fir_master(fir_id),
    INDEX idx_victims_fir (fir_id)
);

CREATE TABLE IF NOT EXISTS cases_theft (
    theft_id          INT AUTO_INCREMENT PRIMARY KEY,
    fir_id            INT NOT NULL UNIQUE,
    stolen_items      TEXT,               -- JSON array as text: ["laptop","phone"]
    estimated_value   DECIMAL(12,2),
    recovered         BOOLEAN DEFAULT FALSE,
    recovery_date     DATE,
    recovery_notes    TEXT,

    FOREIGN KEY (fir_id) REFERENCES fir_master(fir_id)
);

CREATE TABLE IF NOT EXISTS cases_assault (
    assault_id        INT AUTO_INCREMENT PRIMARY KEY,
    fir_id            INT NOT NULL UNIQUE,
    weapon_used       VARCHAR(100),
    injury_severity   ENUM('minor','moderate','severe','fatal') DEFAULT 'minor',
    motive            VARCHAR(200),
    witnesses_count   INT DEFAULT 0,

    FOREIGN KEY (fir_id) REFERENCES fir_master(fir_id)
);

CREATE TABLE IF NOT EXISTS cases_vehicle_theft (
    vt_id             INT AUTO_INCREMENT PRIMARY KEY,
    fir_id            INT NOT NULL UNIQUE,
    vehicle_type      ENUM('two_wheeler','car','truck','auto','other'),
    vehicle_make      VARCHAR(50),
    vehicle_model     VARCHAR(50),
    registration_no   VARCHAR(20),
    color             VARCHAR(30),
    recovered         BOOLEAN DEFAULT FALSE,
    recovery_date     DATE,
    recovery_location VARCHAR(200),

    FOREIGN KEY (fir_id) REFERENCES fir_master(fir_id)
);

CREATE TABLE IF NOT EXISTS cases_fraud (
    fraud_id          INT AUTO_INCREMENT PRIMARY KEY,
    fir_id            INT NOT NULL UNIQUE,
    fraud_type        ENUM('online','offline','banking','property','other'),
    amount_defrauded  DECIMAL(14,2),
    amount_recovered  DECIMAL(14,2) DEFAULT 0,
    method_used       TEXT,
    account_numbers   TEXT,               -- JSON array as text

    FOREIGN KEY (fir_id) REFERENCES fir_master(fir_id)
);

CREATE TABLE IF NOT EXISTS cases_cybercrime (
    cyber_id          INT AUTO_INCREMENT PRIMARY KEY,
    fir_id            INT NOT NULL UNIQUE,
    cyber_type        ENUM('phishing','hacking','online_harassment','identity_theft','other'),
    platform          VARCHAR(100),       -- WhatsApp, Instagram, email, etc.
    financial_loss    DECIMAL(14,2) DEFAULT 0,
    digital_evidence  TEXT,               -- JSON: IP addresses, device IDs, URLs

    FOREIGN KEY (fir_id) REFERENCES fir_master(fir_id)
);

CREATE TABLE IF NOT EXISTS cases_missing_person (
    mp_id             INT AUTO_INCREMENT PRIMARY KEY,
    fir_id            INT NOT NULL UNIQUE,
    missing_since     DATE,
    last_seen_location VARCHAR(200),
    physical_description TEXT,
    found             BOOLEAN DEFAULT FALSE,
    found_date        DATE,
    found_location    VARCHAR(200),
    found_condition   ENUM('safe','injured','deceased','unknown'),

    FOREIGN KEY (fir_id) REFERENCES fir_master(fir_id)
);

CREATE TABLE IF NOT EXISTS cases_drug_offense (
    drug_id           INT AUTO_INCREMENT PRIMARY KEY,
    fir_id            INT NOT NULL UNIQUE,
    drug_type         VARCHAR(100),
    quantity_seized   VARCHAR(100),
    estimated_street_value DECIMAL(12,2),
    source_location   VARCHAR(200),

    FOREIGN KEY (fir_id) REFERENCES fir_master(fir_id)
);

CREATE TABLE IF NOT EXISTS case_relationships (
    rel_id            INT AUTO_INCREMENT PRIMARY KEY,
    entity_a_type     ENUM('accused','fir','victim','officer') NOT NULL,
    entity_a_id       INT NOT NULL,
    entity_b_type     ENUM('accused','fir','victim','officer') NOT NULL,
    entity_b_id       INT NOT NULL,
    relationship_type ENUM(
                        'co_accused','repeat_location','same_modus_operandi',
                        'linked_gang','victim_of_same_accused','related_case'
                      ) NOT NULL,
    notes             TEXT,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_rel_a (entity_a_type, entity_a_id),
    INDEX idx_rel_b (entity_b_type, entity_b_id)
);

CREATE TABLE IF NOT EXISTS evidence_media (
    media_id          INT AUTO_INCREMENT PRIMARY KEY,
    fir_id            INT NOT NULL,
    media_type        ENUM('image','audio','video','document') NOT NULL,
    file_name         VARCHAR(200) NOT NULL,
    stratus_folder_id VARCHAR(100) NOT NULL,   -- Catalyst Stratus folder ID
    stratus_file_id   VARCHAR(100) NOT NULL,   -- Catalyst Stratus file ID
    description       VARCHAR(500),
    uploaded_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (fir_id) REFERENCES fir_master(fir_id),
    INDEX idx_media_fir (fir_id)
);

-- Chat sessions — one row per conversation (Step 4: persistent storage)
CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id      VARCHAR(36) PRIMARY KEY,
    officer_id      INT NOT NULL,
    title           VARCHAR(200) NOT NULL DEFAULT 'Untitled Chat',
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    message_count   INT DEFAULT 0,
    is_active       BOOLEAN DEFAULT TRUE,
    FOREIGN KEY (officer_id) REFERENCES officers(officer_id),
    INDEX idx_sessions_officer (officer_id, updated_at)
);

-- Chat messages — one row per turn (user question OR assistant answer)
CREATE TABLE IF NOT EXISTS chat_messages (
    message_id      INT AUTO_INCREMENT PRIMARY KEY,
    session_id      VARCHAR(36) NOT NULL,
    role            ENUM('user', 'assistant') NOT NULL,
    content         TEXT NOT NULL,
    sql_generated   TEXT,
    has_table       BOOLEAN DEFAULT FALSE,
    has_media       BOOLEAN DEFAULT FALSE,
    graph_available BOOLEAN DEFAULT FALSE,
    table_data_json MEDIUMTEXT DEFAULT NULL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES chat_sessions(session_id),
    INDEX idx_messages_session (session_id, created_at)
);
