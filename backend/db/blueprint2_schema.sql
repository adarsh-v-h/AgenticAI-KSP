-- BLUEPRINT2 schema additions - corrected per BLUEPRINT2_PATCH.md Patch 1.
-- Run against the already-migrated ksp_crime_db_v2.

CREATE TABLE IF NOT EXISTS offender_risk_scores (
    AccusedMasterID      INT PRIMARY KEY,
    risk_score           DECIMAL(5,2) NOT NULL,
    risk_tier            ENUM('low', 'medium', 'high', 'critical') NOT NULL,
    contributing_factors TEXT,
    computed_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (AccusedMasterID) REFERENCES Accused(AccusedMasterID)
);

CREATE TABLE IF NOT EXISTS chat_evidence_trail (
    trail_id            INT AUTO_INCREMENT PRIMARY KEY,
    message_id          INT NOT NULL,
    sql_executed        TEXT NOT NULL,
    tables_queried      VARCHAR(300),
    row_count           INT,
    case_ids_referenced VARCHAR(500),
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (message_id) REFERENCES chat_messages(message_id),
    INDEX idx_trail_message (message_id)
);

CREATE TABLE IF NOT EXISTS audit_log (
    log_id          INT AUTO_INCREMENT PRIMARY KEY,
    officer_id      INT NOT NULL,
    action          VARCHAR(50) NOT NULL,
    resource_type   VARCHAR(50),
    resource_id     VARCHAR(50),
    details         TEXT,
    ip_address      VARCHAR(45),
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (officer_id) REFERENCES Employee(EmployeeID),
    INDEX idx_audit_officer (officer_id, created_at),
    INDEX idx_audit_resource (resource_type, resource_id)
);
