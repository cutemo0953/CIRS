-- CIRS Database Schema v2.0
-- SQLite with WAL mode
-- Updated: 2025-12-17 (Staff Management v1.1)

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
    role TEXT DEFAULT 'public',      -- 'admin', 'staff', 'medic', 'public' (系統權限)
    pin_hash TEXT,                   -- bcrypt hash (有PIN才能操作)
    triage_status TEXT,              -- 'GREEN', 'YELLOW', 'RED', 'BLACK', NULL
    current_location TEXT,           -- 目前位置
    photo_data TEXT,                 -- Base64 照片 (無法辨識身分時拍照)
    physical_desc TEXT,              -- 外觀特徵描述
    id_status TEXT DEFAULT 'confirmed', -- 'confirmed', 'unidentified', 'pending'
    metadata TEXT,                   -- JSON: {"blood_type": "O", "allergies": "無", "emergency_contact": "..."}
    checked_in_at DATETIME,

    -- Staff Management v1.1 欄位
    staff_role TEXT,                 -- 職能: 'MEDIC', 'NURSE', 'VOLUNTEER', 'ADMIN', 'SECURITY', 'COORDINATOR'
    staff_status TEXT DEFAULT 'OFF_DUTY', -- 'ACTIVE', 'STANDBY', 'OFF_DUTY', 'ON_LEAVE'
    verification_status TEXT DEFAULT 'UNVERIFIED', -- 'UNVERIFIED', 'VERIFIED'
    verified_at DATETIME,            -- 驗證時間
    verified_by TEXT,                -- 驗證者 person_id
    shift_start DATETIME,            -- 本班開始時間
    shift_end DATETIME,              -- 本班預計結束 (用於缺口預測)
    expected_hours REAL,             -- 預計工作時數
    skills TEXT,                     -- JSON: 技能標籤
    emergency_contact TEXT,          -- 緊急聯絡人
    certification TEXT,              -- JSON: 證照資訊

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_person_role ON person(role);
CREATE INDEX IF NOT EXISTS idx_person_triage ON person(triage_status);
CREATE INDEX IF NOT EXISTS idx_person_national_id ON person(national_id_hash);
CREATE INDEX IF NOT EXISTS idx_person_id_status ON person(id_status);
CREATE INDEX IF NOT EXISTS idx_person_staff_role ON person(staff_role);
CREATE INDEX IF NOT EXISTS idx_person_staff_status ON person(staff_status);
CREATE INDEX IF NOT EXISTS idx_person_verification ON person(verification_status);

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
-- 8. Zone (區域管理)
-- ============================================
CREATE TABLE IF NOT EXISTS zone (
    id TEXT PRIMARY KEY,             -- 區域代碼: 'zone_medical_1'
    name TEXT NOT NULL,              -- 顯示名稱: '醫療區 A'
    zone_type TEXT NOT NULL,         -- 'shelter', 'medical', 'service', 'restricted'
    capacity INTEGER DEFAULT 0,      -- 容量上限 (0=無限制)
    description TEXT,                -- 說明
    icon TEXT,                       -- 圖示 emoji
    sort_order INTEGER DEFAULT 0,    -- 排序順序
    is_active INTEGER DEFAULT 1,     -- 是否啟用
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_zone_type ON zone(zone_type);
CREATE INDEX IF NOT EXISTS idx_zone_active ON zone(is_active);

-- ============================================
-- 9. Inventory Standards (物資標準 v2.0)
-- ============================================
CREATE TABLE IF NOT EXISTS inventory_standards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,              -- 'WATER', 'FOOD', 'MEDICAL', 'POWER', 'DAILY'
    item_name TEXT NOT NULL,
    item_code TEXT UNIQUE,               -- 標準化代碼

    -- 計算模式 (不允許 NULL)
    calc_mode TEXT NOT NULL DEFAULT 'PER_PERSON_DAY',
    -- ENUM: 'PER_PERSON_DAY', 'PER_N_PEOPLE', 'FIXED_MIN', 'CUSTOM_FORMULA'

    calc_params TEXT NOT NULL DEFAULT '{}',  -- JSON

    -- 韌性類別 (用於 Lifeline 分組)
    resilience_category TEXT,            -- 'WATER', 'FOOD', 'POWER', 'MEDICAL', 'STAFF'

    -- 容量/消耗設定
    capacity_per_unit REAL,              -- 每單位容量
    capacity_unit TEXT,                  -- 'ml', 'L', 'kcal', 'Wh'
    consumption_rate REAL,               -- 每人每天消耗率
    consumption_unit TEXT,               -- 'L/day', 'kcal/day'

    -- 描述
    description TEXT,
    description_en TEXT,

    -- 元資料
    is_essential INTEGER DEFAULT 0,
    sort_order INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_inv_std_category ON inventory_standards(category);
CREATE INDEX IF NOT EXISTS idx_inv_std_resilience ON inventory_standards(resilience_category);

-- ============================================
-- 10. Staffing Rules (人力配置規則 v2.0)
-- ============================================
CREATE TABLE IF NOT EXISTS staffing_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role_code TEXT NOT NULL UNIQUE,      -- 'MEDIC', 'VOLUNTEER', 'ADMIN', 'SECURITY'
    role_name TEXT NOT NULL,
    role_name_en TEXT,

    -- 計算規則
    calc_mode TEXT NOT NULL DEFAULT 'PER_N_PEOPLE',
    calc_params TEXT NOT NULL,           -- JSON

    rounding_mode TEXT DEFAULT 'CEILING', -- 'CEILING', 'FLOOR', 'ROUND'

    -- 依賴設定
    depends_on_role TEXT,

    -- UI 設定
    icon TEXT,
    color TEXT,
    sort_order INTEGER DEFAULT 0,

    -- 元資料
    is_essential INTEGER DEFAULT 1,
    description TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ============================================
-- 11. Resilience Configuration (韌性設定 v2.0)
-- ============================================
CREATE TABLE IF NOT EXISTS resilience_config (
    station_id TEXT PRIMARY KEY,

    -- 目標設定
    isolation_target_days INTEGER DEFAULT 3,
    isolation_source TEXT DEFAULT 'manual',

    -- 人口設定
    population_count INTEGER DEFAULT 0,
    population_label TEXT DEFAULT '收容人數',
    special_needs TEXT DEFAULT '{}',     -- JSON

    -- 閾值設定
    threshold_safe REAL DEFAULT 1.2,
    threshold_warning REAL DEFAULT 1.0,

    -- 計算權重
    weight_weakest REAL DEFAULT 0.6,
    weight_average REAL DEFAULT 0.4,

    -- 規則版本
    rules_version TEXT DEFAULT 'v2.0',

    -- Profile 連結
    water_profile_id INTEGER,
    food_profile_id INTEGER,
    power_profile_id INTEGER,
    staff_profile_id INTEGER,

    -- 元資料
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_by TEXT
);

-- ============================================
-- 12. Resilience History (韌性計算快照 v2.0)
-- ============================================
CREATE TABLE IF NOT EXISTS resilience_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    station_id TEXT NOT NULL,

    calc_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,

    input_snapshot TEXT NOT NULL,        -- JSON
    result_snapshot TEXT NOT NULL,       -- JSON

    rules_version TEXT NOT NULL,
    input_hash TEXT,
    result_hash TEXT,

    calc_duration_ms INTEGER,
    triggered_by TEXT DEFAULT 'MANUAL',

    FOREIGN KEY (station_id) REFERENCES resilience_config(station_id)
);

CREATE INDEX IF NOT EXISTS idx_res_hist_station ON resilience_history(station_id);
CREATE INDEX IF NOT EXISTS idx_res_hist_time ON resilience_history(calc_timestamp);

-- ============================================
-- 13. Shelter Network (避難所網路 v2.0)
-- ============================================
CREATE TABLE IF NOT EXISTS shelter_network (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    local_station_id TEXT NOT NULL,
    remote_station_id TEXT NOT NULL,
    remote_station_name TEXT,
    remote_ip TEXT,
    remote_port INTEGER DEFAULT 8090,

    connection_status TEXT DEFAULT 'UNKNOWN',
    last_sync_at DATETIME,
    last_heartbeat DATETIME,

    data_confidence_score INTEGER DEFAULT 100,

    remote_population INTEGER DEFAULT 0,
    remote_capacity INTEGER DEFAULT 0,
    remote_score INTEGER DEFAULT 0,

    sync_enabled INTEGER DEFAULT 1,
    sync_interval_minutes INTEGER DEFAULT 30,

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(local_station_id, remote_station_id)
);

CREATE INDEX IF NOT EXISTS idx_shelter_net_status ON shelter_network(connection_status);

-- ============================================
-- 14. Staff Join Requests (自助登錄申請 v1.1)
-- ============================================
CREATE TABLE IF NOT EXISTS staff_join_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    qr_token TEXT UNIQUE NOT NULL,   -- 'JR-{uuid[:12]}'

    -- 申請資料
    display_name TEXT NOT NULL,
    phone TEXT,
    claimed_role TEXT NOT NULL,      -- 自稱職能: 'VOLUNTEER', 'MEDIC', etc.
    skills TEXT,                     -- JSON: 技能標籤
    expected_hours REAL DEFAULT 4,
    notes TEXT,

    -- 狀態
    status TEXT DEFAULT 'PENDING',   -- 'PENDING', 'APPROVED', 'REJECTED', 'EXPIRED'

    -- 時間戳
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NOT NULL,    -- 30 分鐘後過期
    processed_at DATETIME,
    processed_by TEXT,               -- Admin person_id

    -- 核准後關聯
    person_id TEXT                   -- 核准後建立的 person.id
);

CREATE INDEX IF NOT EXISTS idx_join_request_token ON staff_join_requests(qr_token);
CREATE INDEX IF NOT EXISTS idx_join_request_status ON staff_join_requests(status);
CREATE INDEX IF NOT EXISTS idx_join_request_expires ON staff_join_requests(expires_at);

-- ============================================
-- 15. Staff Badge Tokens (快速回鍋通行證 v1.1)
-- ============================================
CREATE TABLE IF NOT EXISTS staff_badge_tokens (
    token_id TEXT PRIMARY KEY,       -- 'BT-{uuid[:12]}'
    person_id TEXT NOT NULL,

    issued_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NOT NULL,    -- 12 小時後過期
    is_revoked INTEGER DEFAULT 0,

    FOREIGN KEY (person_id) REFERENCES person(id)
);

CREATE INDEX IF NOT EXISTS idx_badge_token_person ON staff_badge_tokens(person_id);
CREATE INDEX IF NOT EXISTS idx_badge_token_expires ON staff_badge_tokens(expires_at);

-- ============================================
-- 16. Staff Role Config (職能 UI 設定 v1.1)
-- ============================================
CREATE TABLE IF NOT EXISTS staff_role_config (
    role_code TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    display_name_en TEXT,
    color_hex TEXT NOT NULL,
    icon_name TEXT,
    resilience_weight REAL DEFAULT 1.0,
    requires_verification INTEGER DEFAULT 0,  -- 是否需要證照驗證
    sort_order INTEGER DEFAULT 0
);

-- ============================================
-- 17. Satellite Pairing Codes (配對碼 v1.1)
-- ============================================
CREATE TABLE IF NOT EXISTS satellite_pairing_codes (
    code TEXT PRIMARY KEY,               -- 6 位大寫字母數字: 'XYZ123'
    hub_name TEXT NOT NULL,
    allowed_roles TEXT DEFAULT 'volunteer',  -- v1.3.1: 允許角色 (volunteer,admin)
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NOT NULL,        -- 5 分鐘後過期
    used_at DATETIME,                    -- 使用時間
    used_by_device_id TEXT               -- 使用的 device_id
);

CREATE INDEX IF NOT EXISTS idx_pairing_code_expires ON satellite_pairing_codes(expires_at);

-- ============================================
-- 18. Action Logs (冪等性日誌 v1.1)
-- ============================================
CREATE TABLE IF NOT EXISTS action_logs (
    action_id TEXT PRIMARY KEY,          -- UUID，確保冪等性
    batch_id TEXT,                       -- 批次 ID
    action_type TEXT NOT NULL,           -- 'DISPENSE', 'CHECK_IN', 'CHECK_OUT'
    device_id TEXT,                      -- 執行裝置 ID
    payload TEXT,                        -- JSON payload
    processed_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_action_logs_batch ON action_logs(batch_id);
CREATE INDEX IF NOT EXISTS idx_action_logs_device ON action_logs(device_id);
CREATE INDEX IF NOT EXISTS idx_action_logs_time ON action_logs(processed_at);

-- ============================================
-- 19. Satellite Devices (已配對裝置 v1.4)
-- ============================================
CREATE TABLE IF NOT EXISTS satellite_devices (
    device_id TEXT PRIMARY KEY,          -- 裝置 ID (由 PWA 生成)
    device_name TEXT,                    -- 裝置名稱 (可選，由管理員設定)
    allowed_roles TEXT DEFAULT 'volunteer',  -- 允許角色
    is_revoked INTEGER DEFAULT 0,        -- 是否已撤銷
    is_blacklisted INTEGER DEFAULT 0,    -- 是否黑名單
    last_activity_at DATETIME,           -- 最後活動時間
    paired_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    revoked_at DATETIME,                 -- 撤銷時間
    revoked_by TEXT,                     -- 撤銷者 person_id
    revoke_reason TEXT,                  -- 撤銷原因
    user_agent TEXT,                     -- 裝置 User-Agent
    ip_address TEXT                      -- 配對時 IP
);

CREATE INDEX IF NOT EXISTS idx_satellite_devices_revoked ON satellite_devices(is_revoked);
CREATE INDEX IF NOT EXISTS idx_satellite_devices_blacklist ON satellite_devices(is_blacklisted);
CREATE INDEX IF NOT EXISTS idx_satellite_devices_activity ON satellite_devices(last_activity_at);

-- ============================================
-- 20. 預設資料
-- ============================================

-- 預設設定
INSERT OR IGNORE INTO config (key, value) VALUES
    ('site_name', '社區避難中心'),
    ('emergency_mode', 'false'),
    ('current_broadcast', ''),
    ('water_per_person_per_day', '3'),
    ('food_per_person_per_day', '2100'),
    ('polling_interval', '5000');

-- 預設物資標準 (v2.0)
INSERT OR IGNORE INTO inventory_standards (category, item_name, item_code, calc_mode, calc_params, resilience_category, capacity_per_unit, capacity_unit, consumption_rate, consumption_unit, description, is_essential) VALUES
    -- 飲水
    ('WATER', '飲用水', 'WATER-DRINK', 'PER_PERSON_DAY', '{"rate": 3.0, "unit": "L"}', 'WATER', 0.6, 'L', 3.0, 'L/day', '內政部標準: 每人每天 3 公升', 1),
    ('WATER', '生活用水', 'WATER-DAILY', 'PER_PERSON_DAY', '{"rate": 10.0, "unit": "L"}', 'WATER', 20.0, 'L', 10.0, 'L/day', '洗漱、沖廁等生活用水', 0),
    -- 食物
    ('FOOD', '主食熱量', 'FOOD-MAIN', 'PER_PERSON_DAY', '{"rate": 1800, "unit": "kcal"}', 'FOOD', NULL, 'kcal', 1800, 'kcal/day', '成人每日基本熱量需求', 1),
    ('FOOD', '嬰兒奶粉', 'FOOD-BABY', 'CUSTOM_FORMULA', '{"formula": "baby_count * 6", "unit": "罐"}', 'FOOD', NULL, '罐', NULL, NULL, '每嬰兒每天約需 6 餐', 0),
    -- 醫療
    ('MEDICAL', '急救包', 'MED-FIRSTAID', 'PER_N_PEOPLE', '{"n": 50, "qty": 1, "unit": "組"}', 'MEDICAL', NULL, '組', NULL, NULL, '每 50 人配置 1 組急救包', 1),
    ('MEDICAL', 'N95 口罩', 'MED-MASK-N95', 'PER_PERSON_DAY', '{"rate": 1, "unit": "個"}', 'MEDICAL', NULL, '個', 1.0, '個/day', '傳染病防護用', 0),
    -- 電力
    ('POWER', '行動電源站', 'PWR-STATION', 'FIXED_MIN', '{"min_qty": 1, "unit": "台"}', 'POWER', NULL, 'Wh', NULL, NULL, '至少需要 1 台備用電源', 1),
    ('POWER', '發電機', 'PWR-GENERATOR', 'FIXED_MIN', '{"min_qty": 1, "unit": "台"}', 'POWER', NULL, 'L', NULL, NULL, '至少需要 1 台發電機', 1),
    -- 日用品
    ('DAILY', '毛毯', 'DAILY-BLANKET', 'PER_N_PEOPLE', '{"n": 1, "qty": 1, "unit": "件"}', NULL, NULL, '件', NULL, NULL, '每人 1 件', 0),
    ('DAILY', '睡袋', 'DAILY-SLEEPBAG', 'PER_N_PEOPLE', '{"n": 2, "qty": 1, "unit": "個"}', NULL, NULL, '個', NULL, NULL, '每 2 人 1 個', 0);

-- 預設人力配置規則 (v2.0)
INSERT OR IGNORE INTO staffing_rules (role_code, role_name, role_name_en, calc_mode, calc_params, rounding_mode, description, is_essential, sort_order) VALUES
    ('MEDIC', '醫護人員', 'Medical Staff', 'PER_N_PEOPLE', '{"n": 100, "qty": 1}', 'CEILING', '每 100 人至少需要 1 位醫護', 1, 1),
    ('VOLUNTEER', '志工', 'Volunteer', 'PER_N_PEOPLE', '{"n": 30, "qty": 1}', 'CEILING', '每 30 人需要 1 位志工', 1, 2),
    ('ADMIN', '行政人員', 'Admin Staff', 'FIXED_MIN', '{"min_qty": 2}', 'CEILING', '至少需要 2 位行政人員', 1, 3),
    ('SECURITY', '保全人員', 'Security', 'PER_SHIFT', '{"qty_per_shift": 1, "shifts_per_day": 3}', 'CEILING', '24 小時輪班，每班 1 人', 0, 4),
    ('COOK', '廚房人員', 'Kitchen Staff', 'PER_N_PEOPLE', '{"n": 50, "qty": 1}', 'CEILING', '每 50 人需要 1 位廚房人員', 0, 5);

-- 預設韌性設定
INSERT OR IGNORE INTO resilience_config (station_id, isolation_target_days, population_count, population_label) VALUES
    ('default', 3, 0, '收容人數');

-- 預設帳號 (PIN 皆為: 1234)
-- bcrypt hash for '1234': $2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/X4.V0jlKfM1c4QGPC
INSERT OR IGNORE INTO person (id, display_name, role, pin_hash, staff_role, staff_status, verification_status) VALUES
    ('admin001', '管理員', 'admin', '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/X4.V0jlKfM1c4QGPC', 'COORDINATOR', 'ACTIVE', 'VERIFIED'),
    ('staff001', '志工小明', 'staff', '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/X4.V0jlKfM1c4QGPC', 'VOLUNTEER', 'ACTIVE', 'VERIFIED'),
    ('medic001', '醫護小華', 'medic', '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/X4.V0jlKfM1c4QGPC', 'NURSE', 'ACTIVE', 'VERIFIED');

-- 預設職能 UI 設定 (Staff Role Config v1.1)
INSERT OR IGNORE INTO staff_role_config (role_code, display_name, display_name_en, color_hex, icon_name, resilience_weight, requires_verification, sort_order) VALUES
    ('MEDIC', '醫師', 'Doctor', '#E53935', 'medical_services', 1.0, 1, 1),
    ('NURSE', '護理師', 'Nurse', '#E91E63', 'vaccines', 1.0, 1, 2),
    ('VOLUNTEER', '志工', 'Volunteer', '#4CAF50', 'volunteer_activism', 1.0, 0, 3),
    ('ADMIN', '行政人員', 'Admin', '#FFC107', 'assignment_ind', 1.0, 0, 4),
    ('SECURITY', '保全人員', 'Security', '#2196F3', 'security', 1.0, 0, 5),
    ('COORDINATOR', '指揮官', 'Coordinator', '#9C27B0', 'campaign', 1.0, 1, 6);

-- 預設區域 (icon 使用 heroicon 名稱)
INSERT OR IGNORE INTO zone (id, name, zone_type, capacity, description, icon, sort_order) VALUES
    -- 收容區域
    ('rest_area', '休息區', 'shelter', 100, '一般收容民眾休息區', 'moon', 10),
    ('dining_area', '用餐區', 'shelter', 80, '用餐及飲水供應區', 'cake', 11),
    ('family_area', '家庭區', 'shelter', 50, '有幼兒/長者的家庭優先', 'user-group', 12),
    ('elderly_area', '長者區', 'shelter', 30, '行動不便者及長者專區', 'heart', 13),
    ('children_area', '兒童區', 'shelter', 40, '兒童遊戲及照護區', 'face-smile', 14),
    -- 醫療區域
    ('triage_area', '檢傷區', 'medical', 20, 'START 檢傷分類處', 'clipboard-document-check', 20),
    ('green_area', '輕傷區', 'medical', 50, 'GREEN - 可延後處理', 'check-circle', 21),
    ('yellow_area', '中傷區', 'medical', 30, 'YELLOW - 需優先處理', 'exclamation-triangle', 22),
    ('red_area', '重傷區', 'medical', 10, 'RED - 立即處理', 'exclamation-circle', 23),
    ('observation_area', '觀察區', 'medical', 20, '症狀觀察及隔離區', 'eye', 24),
    -- 服務區域
    ('registration', '報到處', 'service', 0, '人員報到登記', 'clipboard-document-list', 30),
    ('supply_station', '物資發放區', 'service', 0, '物資領取處', 'cube', 31),
    ('info_desk', '服務台', 'service', 0, '諮詢及協助', 'information-circle', 32),
    -- 管制區域
    ('warehouse', '倉庫', 'restricted', 0, '物資儲存區 (管制)', 'building-storefront', 40),
    ('office', '辦公室', 'restricted', 0, '行政管理區 (管制)', 'building-office', 41),
    ('equipment_room', '設備間', 'restricted', 0, '發電機/通訊設備 (管制)', 'cog-6-tooth', 42);
