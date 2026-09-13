-- MySQL schema for Hybrid Cloud Configuration Change Impact Analyzer.
-- Run this against a MySQL server, then point DATABASE_URL (see .env.example)
-- at it. SQLAlchemy (db/models.py) can also create these tables
-- automatically on startup -- this file exists so the schema is reviewable
-- on its own, independent of the ORM.

CREATE DATABASE IF NOT EXISTS hybrid_cloud_analyzer
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE hybrid_cloud_analyzer;

CREATE TABLE IF NOT EXISTS analyses (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    created_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    plan_source         VARCHAR(255),
    resource_address    VARCHAR(255),
    resource_type       VARCHAR(100),
    change_action       VARCHAR(50),
    changed_attributes  TEXT,

    affected_count      INT DEFAULT 0,
    impact_level        VARCHAR(20),
    risk_level          VARCHAR(20),
    confidence_score    FLOAT,

    dependency_path     TEXT,
    recommendations     TEXT,

    INDEX idx_resource_address (resource_address),
    INDEX idx_resource_type (resource_type)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS incident_outcomes (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    analysis_id     INT NOT NULL,
    outcome_text    VARCHAR(255),
    was_incident    BOOLEAN DEFAULT FALSE,
    recorded_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (analysis_id) REFERENCES analyses(id) ON DELETE CASCADE
) ENGINE=InnoDB;
