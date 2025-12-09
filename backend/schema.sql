-- CIRS Database Schema v1.0
-- SQLite with WAL mode

-- ============================================
-- 1. Inventory (物資表)
-- ============================================
CREATE TABLE IF NOT EXISTS inventory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    specification TEXT,              -- 規格：'600ml', '5公斤裝', 'AA電池'
    category TEXT NOT NULL,          -- 'water', 'food', 'medical', 'power', 'daily', 'equipment', 'other'
    quantity REAL DEFAULT 0,
    unit TEXT,                       -- '瓶', '箱', '個', '公斤'
    location TEXT,                   -- '倉庫A', '入口處'
    expiry_date DATE,
    min_quantity REAL DEFAULT 0,     -- 安全庫存
    tags TEXT,                       -- JSON: ["急救", "嬰兒用品"]
    notes TEXT,
    -- Equipment-specific fields
    last_check_date DATE,            -- 設備最後檢查日期
    check_interval_days INTEGER,     -- 檢查週期（天）
    check_status TEXT,               -- 'OK', 'NEEDS_REPAIR', 'OUT_OF_SERVICE'
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_inventory_category ON inventory(category);
CREATE INDEX IF NOT EXISTS idx_inventory_expiry ON inventory(expiry_date);
CREATE INDEX IF NOT EXISTS idx_inventory_check ON inventory(last_check_date);

-- ============================================
-- 2. Person (人員表)
-- ============================================
CREATE TABLE IF NOT EXISTS person (
    id TEXT PRIMARY KEY,             -- 系統序號 (如: 'P0001') - 對外顯示
    national_id_hash TEXT UNIQUE,    -- 身分證字號 hash (隱私保護，可為空)
    display_name TEXT NOT NULL,
    phone_hash TEXT,                 -- 手機號碼 hash (選填)
    role TEXT DEFAULT 'public',      -- 'admin', 'staff', 'medic', 'public'
    pin_hash TEXT,                   -- bcrypt hash (有PIN才能操作)
    triage_status TEXT,              -- 'GREEN', 'YELLOW', 'RED', 'BLACK', NULL
    current_location TEXT,           -- 目前位置
    photo_data TEXT,                 -- Base64 照片 (無法辨識身分時拍照)
    physical_desc TEXT,              -- 外觀特徵描述
    id_status TEXT DEFAULT 'confirmed', -- 'confirmed', 'unidentified', 'pending'
    metadata TEXT,                   -- JSON: {"blood_type": "O", "allergies": "無", "emergency_contact": "..."}
    checked_in_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_person_role ON person(role);
CREATE INDEX IF NOT EXISTS idx_person_triage ON person(triage_status);
CREATE INDEX IF NOT EXISTS idx_person_national_id ON person(national_id_hash);
CREATE INDEX IF NOT EXISTS idx_person_id_status ON person(id_status);

-- ============================================
-- 3. EventLog (事件紀錄表)
-- ============================================
CREATE TABLE IF NOT EXISTS event_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,        -- 'CHECK_IN', 'CHECK_OUT', 'TRIAGE', 'RESOURCE_IN', 'RESOURCE_OUT', 'MOVE', 'ROLE_CHANGE'
    person_id TEXT,                  -- FK to person.id (誰被操作)
    operator_id TEXT,                -- FK to person.id (誰執行操作)
    item_id INTEGER,                 -- FK to inventory.id (物資相關)
    quantity_change REAL,            -- +10, -5 (領取為負)
    status_value TEXT,               -- 'GREEN', 'CHECKED_IN', 'ZONE_A'
    location TEXT,
    notes TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_event_person ON event_log(person_id);
CREATE INDEX IF NOT EXISTS idx_event_type ON event_log(event_type);
CREATE INDEX IF NOT EXISTS idx_event_time ON event_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_event_item ON event_log(item_id);

-- ============================================
-- 4. Message (留言板)
-- ============================================
CREATE TABLE IF NOT EXISTS message (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_type TEXT DEFAULT 'post', -- 'broadcast' (官方公告), 'post' (一般留言), 'reply' (回覆)
    category TEXT,                    -- 'seek_person', 'seek_item', 'offer_help', 'report', 'general', 'reply'
    content TEXT NOT NULL,
    author_name TEXT,                 -- 顯示名稱 (可匿名)
    author_id TEXT,                   -- FK to person.id (可為 NULL)
    parent_id INTEGER,                -- FK to message.id (回覆用)
    image_data TEXT,                  -- Base64 壓縮圖片 (< 500KB)
    is_pinned INTEGER DEFAULT 0,      -- 置頂
    is_resolved INTEGER DEFAULT 0,    -- 已解決
    client_ip TEXT,                   -- 防搗亂用
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME               -- TTL: 預設 3 天後過期
);

CREATE INDEX IF NOT EXISTS idx_message_type ON message(message_type);
CREATE INDEX IF NOT EXISTS idx_message_category ON message(category);
CREATE INDEX IF NOT EXISTS idx_message_created ON message(created_at);

-- Auto-cleanup trigger: 保留最近 1000 則或 3 天內
CREATE TRIGGER IF NOT EXISTS cleanup_old_messages
AFTER INSERT ON message
BEGIN
    DELETE FROM message
    WHERE id NOT IN (
        SELECT id FROM message ORDER BY created_at DESC LIMIT 1000
    ) AND created_at < datetime('now', '-3 days')
    AND is_pinned = 0;
END;

-- ============================================
-- 5. Config (系統設定)
-- ============================================
CREATE TABLE IF NOT EXISTS config (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ============================================
-- 6. Audit Log (審計記錄 - 敏感操作)
-- ============================================
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_type TEXT NOT NULL,       -- 'PERSON_UPDATE', 'PERSON_DELETE', 'ID_CONFIRM', 'BACKUP', 'RESTORE'
    target_type TEXT,                -- 'person', 'inventory', 'system'
    target_id TEXT,                  -- 被操作的對象 ID
    operator_id TEXT NOT NULL,       -- 操作者 ID (必須登入)
    reason_code TEXT,                -- 預設原因代碼: 'TYPO', 'ID_CONFIRMED', 'DUPLICATE', 'OTHER'
    reason_text TEXT,                -- 詳細原因說明
    old_value TEXT,                  -- 修改前的值 (JSON)
    new_value TEXT,                  -- 修改後的值 (JSON)
    ip_address TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action_type);
CREATE INDEX IF NOT EXISTS idx_audit_target ON audit_log(target_type, target_id);
CREATE INDEX IF NOT EXISTS idx_audit_operator ON audit_log(operator_id);
CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_log(timestamp);

-- ============================================
-- 7. Backup Log (備份記錄)
-- ============================================
CREATE TABLE IF NOT EXISTS backup_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    backup_type TEXT NOT NULL,       -- 'manual', 'scheduled', 'usb'
    file_path TEXT,                  -- 備份檔案路徑
    file_size INTEGER,               -- 檔案大小 (bytes)
    checksum TEXT,                   -- SHA-256 校驗碼
    encrypted INTEGER DEFAULT 1,     -- 是否加密
    operator_id TEXT,                -- 操作者 ID
    status TEXT DEFAULT 'success',   -- 'success', 'failed', 'partial'
    notes TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_backup_time ON backup_log(timestamp);

-- ============================================
-- 8. 預設資料
-- ============================================

-- 預設設定
INSERT OR IGNORE INTO config (key, value) VALUES
    ('site_name', '社區避難中心'),
    ('emergency_mode', 'false'),
    ('current_broadcast', ''),
    ('water_per_person_per_day', '3'),
    ('food_per_person_per_day', '2100'),
    ('polling_interval', '5000');

-- 預設帳號 (PIN 皆為: 1234)
-- bcrypt hash for '1234': $2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/X4.V0jlKfM1c4QGPC
INSERT OR IGNORE INTO person (id, display_name, role, pin_hash) VALUES
    ('admin001', '管理員', 'admin', '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/X4.V0jlKfM1c4QGPC'),
    ('staff001', '志工小明', 'staff', '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/X4.V0jlKfM1c4QGPC'),
    ('medic001', '醫護小華', 'medic', '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/X4.V0jlKfM1c4QGPC');
