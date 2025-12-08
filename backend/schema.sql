-- CIRS Database Schema v1.0
-- SQLite with WAL mode

-- ============================================
-- 1. Inventory (物資表)
-- ============================================
CREATE TABLE IF NOT EXISTS inventory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category TEXT NOT NULL,          -- 'water', 'food', 'medical', 'power', 'daily', 'other'
    quantity REAL DEFAULT 0,
    unit TEXT,                       -- '瓶', '箱', '個', '公斤'
    location TEXT,                   -- '倉庫A', '入口處'
    expiry_date DATE,
    min_quantity REAL DEFAULT 0,     -- 安全庫存
    tags TEXT,                       -- JSON: ["急救", "嬰兒用品"]
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_inventory_category ON inventory(category);
CREATE INDEX IF NOT EXISTS idx_inventory_expiry ON inventory(expiry_date);

-- ============================================
-- 2. Person (人員表)
-- ============================================
CREATE TABLE IF NOT EXISTS person (
    id TEXT PRIMARY KEY,             -- 8字元隨機ID (如: 'a1b2c3d4')
    display_name TEXT NOT NULL,
    phone_hash TEXT UNIQUE,          -- 手機號碼 hash (選填)
    role TEXT DEFAULT 'public',      -- 'admin', 'staff', 'medic', 'public'
    pin_hash TEXT,                   -- bcrypt hash (有PIN才能操作)
    triage_status TEXT,              -- 'GREEN', 'YELLOW', 'RED', 'BLACK', NULL
    current_location TEXT,           -- 目前位置
    metadata TEXT,                   -- JSON: {"blood_type": "O", "allergies": "無"}
    checked_in_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_person_role ON person(role);
CREATE INDEX IF NOT EXISTS idx_person_triage ON person(triage_status);

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
    message_type TEXT DEFAULT 'post', -- 'broadcast' (官方公告), 'post' (一般留言)
    category TEXT,                    -- 'seek_person', 'seek_item', 'offer_help', 'report', 'general'
    content TEXT NOT NULL,
    author_name TEXT,                 -- 顯示名稱 (可匿名)
    author_id TEXT,                   -- FK to person.id (可為 NULL)
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
-- 6. 預設資料
-- ============================================

-- 預設設定
INSERT OR IGNORE INTO config (key, value) VALUES
    ('site_name', '社區避難中心'),
    ('emergency_mode', 'false'),
    ('current_broadcast', ''),
    ('water_per_person_per_day', '3'),
    ('food_per_person_per_day', '2100'),
    ('polling_interval', '5000');

-- 預設 Admin 帳號 (PIN: 1234)
-- bcrypt hash for '1234': $2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/X4.V0jlKfM1c4QGPC
INSERT OR IGNORE INTO person (id, display_name, role, pin_hash) VALUES
    ('admin001', '管理員', 'admin', '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/X4.V0jlKfM1c4QGPC');
