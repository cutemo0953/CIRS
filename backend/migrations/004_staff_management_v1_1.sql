-- Migration 004: Staff Management v1.1
-- Date: 2025-12-17
-- Description: Add staff management tables and columns for self-service onboarding,
--              verification status, and weighted resilience calculation.

-- ============================================
-- 1. Add new columns to person table
-- ============================================

-- Staff role (職能類別)
ALTER TABLE person ADD COLUMN staff_role TEXT;

-- Staff status (工作狀態)
ALTER TABLE person ADD COLUMN staff_status TEXT DEFAULT 'OFF_DUTY';

-- Verification status (驗證狀態)
ALTER TABLE person ADD COLUMN verification_status TEXT DEFAULT 'UNVERIFIED';
ALTER TABLE person ADD COLUMN verified_at DATETIME;
ALTER TABLE person ADD COLUMN verified_by TEXT;

-- Shift tracking (班次追蹤)
ALTER TABLE person ADD COLUMN shift_start DATETIME;
ALTER TABLE person ADD COLUMN shift_end DATETIME;
ALTER TABLE person ADD COLUMN expected_hours REAL;

-- Additional info
ALTER TABLE person ADD COLUMN skills TEXT;
ALTER TABLE person ADD COLUMN emergency_contact TEXT;
ALTER TABLE person ADD COLUMN certification TEXT;

-- ============================================
-- 2. Create indexes for new columns
-- ============================================
CREATE INDEX IF NOT EXISTS idx_person_staff_role ON person(staff_role);
CREATE INDEX IF NOT EXISTS idx_person_staff_status ON person(staff_status);
CREATE INDEX IF NOT EXISTS idx_person_verification ON person(verification_status);

-- ============================================
-- 3. Create staff_join_requests table
-- ============================================
CREATE TABLE IF NOT EXISTS staff_join_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    qr_token TEXT UNIQUE NOT NULL,

    display_name TEXT NOT NULL,
    phone TEXT,
    claimed_role TEXT NOT NULL,
    skills TEXT,
    expected_hours REAL DEFAULT 4,
    notes TEXT,

    status TEXT DEFAULT 'PENDING',

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NOT NULL,
    processed_at DATETIME,
    processed_by TEXT,

    person_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_join_request_token ON staff_join_requests(qr_token);
CREATE INDEX IF NOT EXISTS idx_join_request_status ON staff_join_requests(status);
CREATE INDEX IF NOT EXISTS idx_join_request_expires ON staff_join_requests(expires_at);

-- ============================================
-- 4. Create staff_badge_tokens table
-- ============================================
CREATE TABLE IF NOT EXISTS staff_badge_tokens (
    token_id TEXT PRIMARY KEY,
    person_id TEXT NOT NULL,

    issued_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NOT NULL,
    is_revoked INTEGER DEFAULT 0,

    FOREIGN KEY (person_id) REFERENCES person(id)
);

CREATE INDEX IF NOT EXISTS idx_badge_token_person ON staff_badge_tokens(person_id);
CREATE INDEX IF NOT EXISTS idx_badge_token_expires ON staff_badge_tokens(expires_at);

-- ============================================
-- 5. Create staff_role_config table
-- ============================================
CREATE TABLE IF NOT EXISTS staff_role_config (
    role_code TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    display_name_en TEXT,
    color_hex TEXT NOT NULL,
    icon_name TEXT,
    resilience_weight REAL DEFAULT 1.0,
    requires_verification INTEGER DEFAULT 0,
    sort_order INTEGER DEFAULT 0
);

-- Insert default role configs
INSERT OR IGNORE INTO staff_role_config (role_code, display_name, display_name_en, color_hex, icon_name, resilience_weight, requires_verification, sort_order) VALUES
    ('MEDIC', '醫師', 'Doctor', '#E53935', 'medical_services', 1.0, 1, 1),
    ('NURSE', '護理師', 'Nurse', '#E91E63', 'vaccines', 1.0, 1, 2),
    ('VOLUNTEER', '志工', 'Volunteer', '#4CAF50', 'volunteer_activism', 1.0, 0, 3),
    ('ADMIN', '行政人員', 'Admin', '#FFC107', 'assignment_ind', 1.0, 0, 4),
    ('SECURITY', '保全人員', 'Security', '#2196F3', 'security', 1.0, 0, 5),
    ('COORDINATOR', '指揮官', 'Coordinator', '#9C27B0', 'campaign', 1.0, 1, 6);

-- ============================================
-- 6. Migrate existing person data
-- ============================================

-- Map existing roles to staff_role
UPDATE person SET staff_role = 'NURSE' WHERE role = 'medic' AND staff_role IS NULL;
UPDATE person SET staff_role = 'COORDINATOR' WHERE role = 'admin' AND staff_role IS NULL;
UPDATE person SET staff_role = 'VOLUNTEER' WHERE role = 'staff' AND staff_role IS NULL;

-- Set staff_status based on checked_in_at
UPDATE person
SET staff_status = 'ACTIVE'
WHERE staff_role IS NOT NULL
  AND checked_in_at IS NOT NULL
  AND (staff_status IS NULL OR staff_status = 'OFF_DUTY');

-- Set verification_status for existing staff
UPDATE person
SET verification_status = 'VERIFIED',
    verified_at = CURRENT_TIMESTAMP
WHERE staff_role IS NOT NULL
  AND role IN ('admin', 'medic')
  AND verification_status = 'UNVERIFIED';

-- ============================================
-- Done
-- ============================================
