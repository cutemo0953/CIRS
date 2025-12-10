# CIRS (Community Inventory Resilience System) v1.4 Development Specification

**Version:** 1.4
**Target Environment:** Raspberry Pi (Backend) + Mobile PWA (Frontend)
**Network Topology:** Raspberry Pi as Appliance (Ethernet to Mesh Router or WiFi Hotspot)
**Core Philosophy:** Offline-First, Community-Scale, High Resilience

---

## 1. System Overview

### 1.1 What is CIRS?

CIRS 是社區級災難韌性管理系統，整合：
- **物資管理**（誰拿了什麼、何時拿）
- **人員管理**（報到、檢傷分類）
- **互助通訊**（尋人、求助、公告）

### 1.2 Target Users

| 角色 | 說明 | 權限 |
|------|------|------|
| Admin | 里長、指揮官、廠長 | 全部功能 + 廣播 |
| Staff | 志工、工作人員 | 物資發放、人員報到 |
| Medic | 醫護人員 | 檢傷分類 |
| Public | 災民、社區居民 | 查看、領物資、留言 |

### 1.3 Relationship with HIRS/MIRS

```
同一台 Raspberry Pi 可同時運行：

┌─────────────────────────────────────────────────┐
│  Raspberry Pi (192.168.x.x)                     │
├─────────────────────────────────────────────────┤
│  Port 8000: MIRS (醫療站庫存)                    │
│  Port 8080: HIRS (家庭物資 - 選配)               │
│  Port 8090: CIRS (社區管理)                      │
└─────────────────────────────────────────────────┘

資料獨立：各系統使用獨立 SQLite 檔案，ID 不衝突
```

---

## 2. Design System

### 2.1 Color Palette

延續 HIRS/MIRS 風格，以綠色為主調：

```css
/* Primary - 綠色系 (Normal Mode) */
--color-primary-600: #4c826b;    /* 主色 */
--color-primary-400: #a6c3ac;    /* 次要 */
--color-primary-100: #eaf3d7;    /* 背景 */

/* Neutral - 大地色系 */
--color-neutral-600: #8f7e61;    /* 文字強調 */
--color-neutral-200: #eee2d3;    /* 卡片背景 */

/* Cool Neutral - 冷色輔助 */
--color-cool-100: #e8ebf1;       /* 淺灰背景 */
--color-cool-400: #a0b1cd;       /* 邊框、次要 */

/* Alert - 警戒色 (Emergency Mode) */
--color-alert-red: #dc2626;      /* 緊急 */
--color-alert-orange: #ea580c;   /* 警告 */
--color-alert-yellow: #ca8a04;   /* 注意 */

/* Triage Colors */
--triage-green: #22c55e;         /* 輕傷 */
--triage-yellow: #eab308;        /* 延遲 */
--triage-red: #ef4444;           /* 立即 */
--triage-black: #1f2937;         /* 死亡 */
```

### 2.2 Icons

使用 Heroicons (Outline style)，不使用 Unicode emoji。

```html
<!-- 常用圖示 -->
<svg class="w-6 h-6"><!-- heroicon: home --></svg>
<svg class="w-6 h-6"><!-- heroicon: archive-box --></svg>
<svg class="w-6 h-6"><!-- heroicon: users --></svg>
<svg class="w-6 h-6"><!-- heroicon: chat-bubble-left-right --></svg>
<svg class="w-6 h-6"><!-- heroicon: megaphone --></svg>
<svg class="w-6 h-6"><!-- heroicon: exclamation-triangle --></svg>
```

### 2.3 Typography

```css
font-family: system-ui, -apple-system, sans-serif;
```

---

## 3. Tech Stack

### 3.1 Frontend

| 技術 | 用途 |
|------|------|
| Alpine.js | 響應式狀態管理 |
| Tailwind CSS | 樣式框架 |
| IndexedDB | 離線資料儲存 |
| Service Worker | PWA 離線快取 |

### 3.2 Backend

| 技術 | 用途 |
|------|------|
| Python FastAPI | REST API |
| SQLite | 資料庫 (WAL 模式) |
| Uvicorn | ASGI Server |

### 3.3 SQLite 優化設定

**重要**：Raspberry Pi 在災難現場可能面臨高並發請求，必須正確設定 SQLite。

```python
# backend/database.py
import sqlite3
from contextlib import contextmanager
import threading

# 全域 Lock 防止並發寫入衝突
db_lock = threading.Lock()

def get_connection():
    conn = sqlite3.connect(
        "data/cirs.db",
        check_same_thread=False,
        timeout=30.0  # 等待 Lock 最多 30 秒
    )
    conn.row_factory = sqlite3.Row

    # 關鍵優化設定
    conn.execute("PRAGMA journal_mode=WAL;")       # Write-Ahead Logging，大幅提升並發性能
    conn.execute("PRAGMA synchronous=NORMAL;")     # 平衡性能與安全
    conn.execute("PRAGMA cache_size=-64000;")      # 64MB cache
    conn.execute("PRAGMA temp_store=MEMORY;")      # 暫存放記憶體
    conn.execute("PRAGMA mmap_size=268435456;")    # 256MB mmap

    return conn

@contextmanager
def get_db():
    """Thread-safe database connection with write lock"""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

@contextmanager
def write_db():
    """Serialized write operations to prevent 'database is locked'"""
    with db_lock:
        with get_db() as conn:
            yield conn
```

**WAL 模式優點**：
- 讀取不會被寫入阻塞
- 多個讀取可以同時進行
- 寫入失敗時不會損壞資料庫

### 3.4 Communication

| 方式 | 用途 |
|------|------|
| REST API | CRUD 操作 |
| Polling (5-10s) | 留言板更新 |
| SSE (選配) | 即時公告推播 |

### 3.5 時間同步 (RTC)

**重要**：Raspberry Pi 4/5 沒有內建 RTC 電池，斷電後時間會重置。

#### 硬體解決方案 (強烈建議)

購買 DS3231 RTC 模組 (約 NT$50-100)：

```bash
# 安裝 RTC 支援
sudo apt install -y i2c-tools

# 啟用 I2C
sudo raspi-config  # Interface Options → I2C → Enable

# 偵測 RTC
sudo i2cdetect -y 1  # 應該看到 0x68

# 設定 DS3231
echo "dtoverlay=i2c-rtc,ds3231" | sudo tee -a /boot/config.txt

# 移除 fake-hwclock
sudo apt remove -y fake-hwclock
sudo update-rc.d -f fake-hwclock remove

# 重開機後同步時間
sudo hwclock -w  # 寫入 RTC
sudo hwclock -r  # 讀取 RTC
```

#### DS3231 RTC 模組安裝指南

**購買資訊**：
- 模組名稱：DS3231 RTC Module (I2C)
- 價格：約 NT$50-100
- 購買管道：蝦皮、露天、電子材料行

**硬體接線** (Raspberry Pi GPIO)：

```
DS3231 模組          Raspberry Pi
─────────────        ─────────────
VCC  ──────────────→ Pin 1 (3.3V)
GND  ──────────────→ Pin 6 (GND)
SDA  ──────────────→ Pin 3 (GPIO 2, SDA)
SCL  ──────────────→ Pin 5 (GPIO 3, SCL)
```

```
Raspberry Pi GPIO 針腳圖 (僅顯示相關針腳):

   3.3V [1] [2] 5V
SDA/GPIO2 [3] [4] 5V
SCL/GPIO3 [5] [6] GND
          ...
```

**軟體設定**：

```bash
# 1. 安裝 I2C 工具
sudo apt update
sudo apt install -y i2c-tools python3-smbus

# 2. 啟用 I2C 介面
sudo raspi-config
# → Interface Options → I2C → Yes → Finish

# 3. 重開機
sudo reboot

# 4. 偵測 RTC 模組 (應該看到 0x68)
sudo i2cdetect -y 1
#      0  1  2  3  4  5  6  7  8  9  a  b  c  d  e  f
# 60: -- -- -- -- -- -- -- -- 68 -- -- -- -- -- -- --

# 5. 載入 RTC 驅動 (加入 /boot/config.txt)
echo "dtoverlay=i2c-rtc,ds3231" | sudo tee -a /boot/config.txt

# 6. 移除 fake-hwclock (Pi 預設的假時鐘)
sudo apt remove -y fake-hwclock
sudo update-rc.d -f fake-hwclock remove
sudo systemctl disable fake-hwclock

# 7. 修改 hwclock-set 腳本
sudo nano /lib/udev/hwclock-set
# 註解掉以下三行 (在前面加 #):
#if [ -e /run/systemd/system ] ; then
#    exit 0
#fi

# 8. 重開機
sudo reboot

# 9. 確認 RTC 運作
sudo hwclock -r  # 讀取 RTC 時間
date             # 讀取系統時間

# 10. 如果系統時間正確，寫入 RTC
sudo hwclock -w

# 11. 測試：斷電重開後確認時間正確
```

**驗證腳本** (可加入 CIRS 安裝流程)：

```bash
#!/bin/bash
# /home/pi/CIRS/scripts/check_rtc.sh

echo "檢查 RTC 模組..."

# 檢查 I2C 裝置
if sudo i2cdetect -y 1 | grep -q "68"; then
    echo "✓ DS3231 RTC 模組已偵測到"
else
    echo "✗ 未偵測到 RTC 模組，請檢查接線"
    exit 1
fi

# 檢查時間差異
RTC_TIME=$(sudo hwclock -r)
SYS_TIME=$(date)
echo "RTC 時間: $RTC_TIME"
echo "系統時間: $SYS_TIME"

# 如果時間差異超過 1 分鐘，警告
RTC_EPOCH=$(sudo hwclock -r --utc | xargs -I {} date -d "{}" +%s 2>/dev/null || echo 0)
SYS_EPOCH=$(date +%s)
DIFF=$((SYS_EPOCH - RTC_EPOCH))
DIFF=${DIFF#-}  # 取絕對值

if [ "$DIFF" -gt 60 ]; then
    echo "⚠ 時間差異過大 (${DIFF} 秒)，建議同步"
    echo "  執行: sudo hwclock -w  (寫入系統時間到 RTC)"
else
    echo "✓ 時間同步正常"
fi
```

#### 軟體解決方案 (備用)

如果沒有 RTC 模組，提供 API 讓前端同步時間：

```python
# backend/routes/system.py
from fastapi import APIRouter
from datetime import datetime
import subprocess

router = APIRouter()

@router.get("/api/system/time")
def get_time():
    """取得伺服器時間"""
    return {"time": datetime.now().isoformat(), "timezone": "Asia/Taipei"}

@router.post("/api/system/time")
def sync_time(client_time: str):
    """從客戶端同步時間 (需 Admin 權限)"""
    try:
        # 解析 ISO 格式時間
        dt = datetime.fromisoformat(client_time.replace('Z', '+00:00'))
        # 設定系統時間 (需要 sudo 權限)
        subprocess.run(['sudo', 'date', '-s', dt.strftime('%Y-%m-%d %H:%M:%S')], check=True)
        return {"success": True, "synced_to": dt.isoformat()}
    except Exception as e:
        return {"success": False, "error": str(e)}
```

前端自動同步：

```javascript
// 連上 Portal 時自動同步時間
async function syncServerTime() {
    try {
        const res = await fetch('/api/system/time');
        const data = await res.json();
        const serverTime = new Date(data.time);
        const clientTime = new Date();
        const diff = Math.abs(serverTime - clientTime);

        // 如果差異超過 5 分鐘，提示管理員同步
        if (diff > 5 * 60 * 1000) {
            console.warn('伺服器時間與手機時間差異過大:', diff / 1000, '秒');
            // 顯示提示讓 Admin 同步時間
        }
    } catch (e) {
        console.error('無法取得伺服器時間');
    }
}
```

---

## 4. Database Schema (SQLite)

### 4.1 Inventory (物資表)

```sql
CREATE TABLE inventory (
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
```

### 4.2 Person (人員表)

```sql
CREATE TABLE person (
    id TEXT PRIMARY KEY,             -- 8字元隨機ID (如: 'a1b2c3d4')
    display_name TEXT NOT NULL,
    phone_hash TEXT UNIQUE,          -- 手機號碼 hash (選填，用於查詢)
    role TEXT DEFAULT 'public',      -- 'admin', 'staff', 'medic', 'public'
    pin_hash TEXT,                   -- 有 PIN 才能操作 (bcrypt hash)
    triage_status TEXT,              -- 'GREEN', 'YELLOW', 'RED', 'BLACK', NULL
    current_location TEXT,           -- 目前位置
    metadata JSON,                   -- {"blood_type": "O", "allergies": "無", "notes": "輪椅"}
    checked_in_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 預設帳號 (PIN 皆為 1234)
-- bcrypt hash for '1234': $2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/X4.V0jlKfM1c4QGPC
INSERT INTO person (id, display_name, role, pin_hash) VALUES
    ('admin001', '管理員', 'admin', '$2b$12$...'),   -- 全部權限 + 站點設定 + 刪除
    ('staff001', '志工小明', 'staff', '$2b$12$...'), -- 入庫/出庫/報到/設備檢查
    ('medic001', '醫護小華', 'medic', '$2b$12$...'); -- 檢傷分類 + staff 權限
```

### 4.3 EventLog (事件紀錄表)

所有操作的 Source of Truth。

```sql
CREATE TABLE event_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,        -- 見下方 Event Types
    person_id TEXT,                  -- FK to person.id (誰被操作)
    operator_id TEXT,                -- FK to person.id (誰執行操作)
    item_id INTEGER,                 -- FK to inventory.id (物資相關)
    quantity_change REAL,            -- +10, -5 (領取為負)
    status_value TEXT,               -- 'GREEN', 'CHECKED_IN', 'ZONE_A'
    location TEXT,
    notes TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Index for faster queries
CREATE INDEX idx_event_person ON event_log(person_id);
CREATE INDEX idx_event_type ON event_log(event_type);
CREATE INDEX idx_event_time ON event_log(timestamp);
```

**Event Types:**

| event_type | 說明 | 關鍵欄位 |
|------------|------|----------|
| `CHECK_IN` | 報到 | person_id, location |
| `CHECK_OUT` | 離開 | person_id |
| `TRIAGE` | 檢傷分類 | person_id, status_value, operator_id |
| `RESOURCE_IN` | 物資入庫 | item_id, quantity_change (+) |
| `RESOURCE_OUT` | 物資發放 | item_id, quantity_change (-), person_id |
| `MOVE` | 人員移動 | person_id, location |
| `ROLE_CHANGE` | 角色變更 | person_id, status_value (new role) |

### 4.4 Message (留言板)

```sql
CREATE TABLE message (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_type TEXT DEFAULT 'post', -- 'broadcast' (官方公告), 'post' (一般留言), 'reply' (回覆)
    category TEXT,                    -- 'seek_person', 'seek_item', 'offer_help', 'report', 'general', 'reply'
    content TEXT NOT NULL,
    author_name TEXT,                 -- 顯示名稱 (可匿名)
    author_id TEXT,                   -- FK to person.id (可為 NULL)
    parent_id INTEGER,                -- FK to message.id (回覆用)
    image_data TEXT,                  -- Base64 壓縮圖片 (< 500KB)
    is_pinned BOOLEAN DEFAULT FALSE,  -- 置頂
    is_resolved BOOLEAN DEFAULT FALSE,-- 已解決 (尋人找到了)
    client_ip TEXT,                   -- 防搗亂用
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME               -- TTL: 預設 3 天後過期
);

-- Auto-cleanup: 保留最近 1000 則或 3 天內
CREATE TRIGGER cleanup_old_messages
AFTER INSERT ON message
BEGIN
    DELETE FROM message
    WHERE id NOT IN (
        SELECT id FROM message ORDER BY created_at DESC LIMIT 1000
    ) AND created_at < datetime('now', '-3 days');
END;
```

### 4.5 Config (系統設定)

```sql
CREATE TABLE config (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 預設設定
INSERT INTO config (key, value) VALUES
    ('site_name', '社區避難中心'),
    ('emergency_mode', 'false'),
    ('current_broadcast', ''),
    ('water_per_person_per_day', '3'),    -- 公升
    ('food_per_person_per_day', '2100'),  -- 大卡
    ('polling_interval', '5000');          -- 毫秒
```

---

## 5. API Endpoints

### 5.1 Authentication

```
POST /api/auth/login
Body: { "person_id": "admin001", "pin": "1234" }
Response: { "token": "...", "person": {...}, "expires_in": 86400 }

POST /api/auth/verify
Header: Authorization: Bearer <token>
Response: { "valid": true, "person": {...} }
```

### 5.2 Inventory

```
GET    /api/inventory                    # 列出所有物資
GET    /api/inventory/:id                # 單一物資
POST   /api/inventory                    # 新增物資 (Staff+)
PUT    /api/inventory/:id                # 更新物資 (Staff+)
DELETE /api/inventory/:id                # 刪除物資 (Admin)

POST   /api/inventory/:id/distribute     # 發放物資
Body: { "person_id": "a1b2c3d4", "quantity": 2, "notes": "領取飲用水" }
```

### 5.3 Person

```
GET    /api/person                       # 列出所有人員 (Staff+)
GET    /api/person/:id                   # 單一人員
POST   /api/person                       # 新增人員 (報到)
PUT    /api/person/:id                   # 更新人員 (Staff+)

POST   /api/person/:id/checkin           # 報到
POST   /api/person/:id/checkout          # 離開
POST   /api/person/:id/triage            # 檢傷分類 (Medic+)
Body: { "status": "YELLOW", "notes": "左腿骨折" }

POST   /api/person/:id/role              # 變更角色 (Admin)
Body: { "role": "medic" }
```

### 5.4 Events

```
GET    /api/events                       # 事件列表 (可篩選)
Query: ?type=RESOURCE_OUT&person_id=xxx&from=2024-01-01

GET    /api/events/person/:id            # 某人的所有事件
GET    /api/events/item/:id              # 某物資的所有事件
```

### 5.5 Messages (留言板)

```
GET    /api/messages                     # 最新 50 則 (含回覆)
Query: ?category=seek_person&limit=20&offset=0
Response: {
    "messages": [
        {
            "id": 1,
            "content": "...",
            "replies": [
                { "id": 10, "content": "回覆內容", "author_name": "匿名" }
            ]
        }
    ]
}

GET    /api/messages/broadcast           # 目前置頂公告

POST   /api/messages                     # 發布留言
Body: {
    "content": "尋找黃金獵犬...",
    "category": "seek_item",
    "author_name": "王小明",
    "image_data": "data:image/jpeg;base64,..."  // 選填
}

POST   /api/messages/broadcast           # 發布公告 (Admin)
Body: { "content": "物資車 14:00 抵達", "is_pinned": true }

POST   /api/messages/:id/reply           # 回覆留言 (v1.1 新增)
Body: { "content": "回覆內容", "author_name": "匿名" }

POST   /api/messages/:id/resolve         # 標記已解決/取消解決 (v1.1 改為 POST)
Body: { "is_resolved": true }

DELETE /api/messages/:id                 # 刪除 (Admin only)
```

### 5.6 Sync & Stats

```
GET    /api/sync                         # 完整資料 dump (初次載入)
Response: {
    "inventory": [...],
    "config": {...},
    "broadcast": "...",
    "timestamp": "..."
}

POST   /api/sync                         # 離線事件同步
Body: { "events": [...] }                # IndexedDB queue

GET    /api/stats                        # 統計資料
Response: {
    "headcount": { "total": 150, "GREEN": 120, "YELLOW": 20, "RED": 8, "BLACK": 2 },
    "survival_days": { "water": 5.2, "food": 4.8 },
    "inventory_alerts": [...]            # 低於安全庫存的物資
}
```

---

## 6. Frontend Modules

### 6.1 App Shell

```
底部導航 (4 Tabs):
┌─────────────────────────────────────┐
│                                     │
│         [頁面內容區域]               │
│                                     │
├─────────┬─────────┬─────────┬───────┤
│  首頁   │  物資   │  人員   │ 留言板 │
│  home   │ archive │ users   │ chat  │
└─────────┴─────────┴─────────┴───────┘
```

### 6.2 Home (首頁)

```
┌─────────────────────────────────────┐
│ 🔔 [置頂公告輪播]                    │  ← 官方廣播
├─────────────────────────────────────┤
│                                     │
│  ┌─────────┐  ┌─────────┐          │
│  │ 在場人數 │  │ 維生天數 │          │
│  │   150   │  │ 💧5 🍚4  │          │
│  └─────────┘  └─────────┘          │
│                                     │
│  ┌─────────────────────────────┐   │
│  │ 物資警示                     │   │  ← 低於安全庫存
│  │ ⚠️ 飲用水剩 50 瓶           │   │
│  │ ⚠️ 醫療手套剩 20 雙         │   │
│  └─────────────────────────────┘   │
│                                     │
│  [快速報到]  [物資發放]  [發布公告]  │  ← 快捷操作
│                                     │
└─────────────────────────────────────┘
```

### 6.3 Inventory (物資)

```
┌─────────────────────────────────────┐
│ 🔍 搜尋...          [+ 新增] [篩選] │
├─────────────────────────────────────┤
│ 分類: [全部] [水] [食物] [醫療] ... │
├─────────────────────────────────────┤
│ ┌─────────────────────────────────┐ │
│ │ 礦泉水 (600ml)                  │ │
│ │ 數量: 120 瓶  📍倉庫A           │ │
│ │ ⚠️ 安全庫存: 100               │ │
│ │ [發放] [編輯] [紀錄]            │ │
│ └─────────────────────────────────┘ │
│ ┌─────────────────────────────────┐ │
│ │ 泡麵                            │ │
│ │ 數量: 50 箱  📍倉庫B            │ │
│ │ 效期: 2025-06-01 (剩180天)      │ │
│ │ [發放] [編輯] [紀錄]            │ │
│ └─────────────────────────────────┘ │
└─────────────────────────────────────┘

[發放 Modal]
┌─────────────────────────────────────┐
│ 發放物資: 礦泉水                     │
├─────────────────────────────────────┤
│ 領取人: [掃描/輸入 ID] ____________ │
│ 數量:   [-] 2 [+]                   │
│ 備註:   ___________________________  │
│                                     │
│        [取消]  [確認發放]            │
└─────────────────────────────────────┘
```

### 6.4 People (人員)

```
┌─────────────────────────────────────┐
│ 🔍 搜尋姓名/ID...    [+ 報到] [篩選] │
├─────────────────────────────────────┤
│ 狀態: [全部] [🟢120] [🟡20] [🔴8]   │
├─────────────────────────────────────┤
│ ┌─────────────────────────────────┐ │
│ │ 🟢 王小明 (a1b2c3d4)            │ │
│ │    報到: 今天 09:30             │ │
│ │    位置: 主收容區               │ │
│ │    [檢傷] [發物資] [詳情]       │ │
│ └─────────────────────────────────┘ │
│ ┌─────────────────────────────────┐ │
│ │ 🟡 李大華 (b2c3d4e5)            │ │
│ │    報到: 今天 10:15             │ │
│ │    狀態: 左腿骨折               │ │
│ │    [檢傷] [發物資] [詳情]       │ │
│ └─────────────────────────────────┘ │
└─────────────────────────────────────┘

[檢傷分類 Modal - START Protocol]
┌─────────────────────────────────────┐
│ 檢傷分類: 王小明                     │
├─────────────────────────────────────┤
│                                     │
│  ┌────────┐  ┌────────┐            │
│  │  🟢    │  │  🟡    │            │
│  │ 輕傷   │  │ 延遲   │            │
│  │ Minor  │  │Delayed │            │
│  └────────┘  └────────┘            │
│                                     │
│  ┌────────┐  ┌────────┐            │
│  │  🔴    │  │  ⚫    │            │
│  │ 立即   │  │ 死亡   │            │
│  │Immediat│  │Deceased│            │
│  └────────┘  └────────┘            │
│                                     │
│ 備註: _____________________________  │
│                                     │
└─────────────────────────────────────┘
```

### 6.5 Messages (留言板)

```
┌─────────────────────────────────────┐
│ 📢 官方公告                          │
│ ┌─────────────────────────────────┐ │
│ │ 物資車將於 14:00 抵達大門口      │ │
│ │ - 管理員 · 10分鐘前              │ │
│ └─────────────────────────────────┘ │
├─────────────────────────────────────┤
│ 分類: [全部] [尋人] [互助] [回報]   │
├─────────────────────────────────────┤
│ ┌─────────────────────────────────┐ │
│ │ 🔍 尋人                          │ │
│ │ 有人看到黃金獵犬嗎？名叫旺財     │ │
│ │ [圖片縮圖]                       │ │
│ │ - 王小明 · 30分鐘前   [已找到✓]  │ │
│ └─────────────────────────────────┘ │
│ ┌─────────────────────────────────┐ │
│ │ 🤝 互助                          │ │
│ │ 我有多的3號電池，誰需要？        │ │
│ │ - 匿名 · 1小時前                 │ │
│ └─────────────────────────────────┘ │
│ ┌─────────────────────────────────┐ │
│ │ ⚠️ 狀況回報                      │ │
│ │ 3樓廁所水管破裂                  │ │
│ │ - 匿名 · 2小時前                 │ │
│ └─────────────────────────────────┘ │
├─────────────────────────────────────┤
│ [📝 發布留言]                        │
└─────────────────────────────────────┘

[發布留言 Modal]
┌─────────────────────────────────────┐
│ 發布留言                            │
├─────────────────────────────────────┤
│ 分類: [尋人▼]                       │
│       ├ 尋人                        │
│       ├ 尋物                        │
│       ├ 互助                        │
│       ├ 狀況回報                    │
│       └ 其他                        │
│                                     │
│ 內容:                               │
│ ┌─────────────────────────────────┐ │
│ │                                 │ │
│ │                                 │ │
│ └─────────────────────────────────┘ │
│                                     │
│ 顯示名稱: [匿名▼] 或 輸入___        │
│                                     │
│ [📷 附加圖片]  (自動壓縮<500KB)     │
│                                     │
│        [取消]  [發布]               │
└─────────────────────────────────────┘
```

### 6.6 Settings (設定)

```
┌─────────────────────────────────────┐
│ 設定                                │
├─────────────────────────────────────┤
│ 站點資訊                            │
│ ├ 名稱: 社區避難中心                │
│ └ [編輯]                           │
├─────────────────────────────────────┤
│ 帳號管理 (Admin)                    │
│ ├ 目前身份: 管理員                  │
│ ├ [變更 PIN]                       │
│ └ [管理人員權限]                   │
├─────────────────────────────────────┤
│ 資料管理                            │
│ ├ [匯出資料庫]                     │
│ ├ [匯入資料庫]                     │
│ └ [清除所有資料]                   │
├─────────────────────────────────────┤
│ 關於                                │
│ ├ CIRS v1.0                        │
│ ├ 後端: http://192.168.x.x:8090    │
│ └ 連線狀態: 🟢 已連線               │
└─────────────────────────────────────┘
```

---

## 7. Offline Sync Strategy

### 7.1 Store-and-Forward Pattern

```javascript
// IndexedDB 結構
const DB_STORES = {
    'inventory': { keyPath: 'id' },
    'person': { keyPath: 'id' },
    'messages': { keyPath: 'id' },
    'sync_queue': { keyPath: 'id', autoIncrement: true },
    'config': { keyPath: 'key' }
};

// Sync Queue Entry
{
    id: 1,
    action: 'CREATE' | 'UPDATE' | 'DELETE',
    table: 'inventory' | 'person' | 'event_log' | 'message',
    payload: { ... },
    timestamp: '2024-12-08T10:30:00Z',
    synced: false,
    retry_count: 0
}
```

### 7.2 Conflict Resolution

**策略：Last-Write-Wins (LWW)**

```javascript
// 同步時比較 timestamp
if (local.timestamp > server.timestamp) {
    // 推送本地變更到 server
} else {
    // 接受 server 版本
}
```

### 7.3 Sync Flow

```
1. App 啟動
   └─→ GET /api/sync (下載最新資料)
   └─→ 存入 IndexedDB

2. 使用者操作 (離線)
   └─→ 寫入 IndexedDB
   └─→ 加入 sync_queue

3. 偵測到網路
   └─→ POST /api/sync (上傳 queue)
   └─→ 標記 synced: true
   └─→ GET /api/sync (拉取其他裝置變更)

4. 背景 Polling (每 5-10 秒)
   └─→ GET /api/messages (留言板更新)
   └─→ GET /api/messages/broadcast (公告)
```

---

## 8. Security Considerations

### 8.1 Authentication

- PIN 使用 bcrypt hash 儲存
- Token 使用 JWT，有效期 24 小時
- 敏感操作需驗證 Token

### 8.2 Authorization

```python
# 權限矩陣
PERMISSIONS = {
    'admin': ['*'],  # 全部權限
    'staff': ['inventory:read', 'inventory:write', 'person:read', 'person:checkin', 'message:*'],
    'medic': ['person:read', 'person:triage', 'message:*'],
    'public': ['inventory:read', 'person:read:self', 'message:read', 'message:create']
}
```

### 8.3 Anti-Abuse

- 留言板記錄 IP，可封鎖濫用者
- 圖片上傳限制 500KB
- Rate limiting: 每分鐘最多 10 則留言

### 8.4 圖片上傳壓縮

**前端壓縮**：在上傳前使用 Canvas 壓縮圖片，避免塞爆頻寬。

```javascript
// 圖片壓縮函數
async function compressImage(file, maxWidth = 1024, maxHeight = 1024, quality = 0.7) {
    return new Promise((resolve) => {
        const reader = new FileReader();
        reader.onload = (e) => {
            const img = new Image();
            img.onload = () => {
                const canvas = document.createElement('canvas');
                let { width, height } = img;

                // 限制最大尺寸
                if (width > maxWidth) {
                    height = (height * maxWidth) / width;
                    width = maxWidth;
                }
                if (height > maxHeight) {
                    width = (width * maxHeight) / height;
                    height = maxHeight;
                }

                canvas.width = width;
                canvas.height = height;

                const ctx = canvas.getContext('2d');
                ctx.drawImage(img, 0, 0, width, height);

                // 壓縮為 JPEG
                canvas.toBlob(
                    (blob) => {
                        // 如果還是太大，降低品質重試
                        if (blob.size > 500 * 1024 && quality > 0.3) {
                            compressImage(file, maxWidth, maxHeight, quality - 0.1)
                                .then(resolve);
                        } else {
                            resolve(blob);
                        }
                    },
                    'image/jpeg',
                    quality
                );
            };
            img.src = e.target.result;
        };
        reader.readAsDataURL(file);
    });
}

// 使用範例
async function handleImageUpload(file) {
    if (file.size > 500 * 1024) {
        const compressed = await compressImage(file);
        console.log(`壓縮: ${file.size} → ${compressed.size} bytes`);
        return compressed;
    }
    return file;
}
```

**限制規格**：
| 項目 | 限制 |
|------|------|
| 最大檔案大小 | 500 KB |
| 最大解析度 | 1024 x 1024 px |
| 格式 | JPEG (自動轉換) |
| 品質 | 70% (自動調整) |

---

## 9. Deployment

### 9.1 Directory Structure

```
~/CIRS/
├── backend/
│   ├── main.py              # FastAPI 入口
│   ├── models.py            # SQLAlchemy models
│   ├── routes/
│   │   ├── auth.py
│   │   ├── inventory.py
│   │   ├── person.py
│   │   ├── events.py
│   │   ├── messages.py
│   │   └── sync.py
│   ├── database.py          # SQLite 連線
│   ├── requirements.txt
│   └── data/
│       └── cirs.db          # SQLite 檔案
│
├── frontend/
│   ├── index.html           # PWA 主檔案
│   ├── manifest.json
│   ├── sw.js                # Service Worker
│   └── assets/
│       └── icons/
│
└── README.md
```

### 9.2 Systemd Service

```ini
# /etc/systemd/system/cirs.service
[Unit]
Description=CIRS - Community Inventory Resilience System
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/CIRS/backend
ExecStart=/usr/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port 8090
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### 9.3 Nginx (Optional)

```nginx
# /etc/nginx/sites-available/cirs
server {
    listen 8090;
    server_name _;

    # API
    location /api/ {
        proxy_pass http://127.0.0.1:8091/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # Frontend
    location / {
        root /home/pi/CIRS/frontend;
        index index.html;
        try_files $uri $uri/ /index.html;
    }
}
```

---

## 10. Implementation Checklist

### Phase 1: Foundation

- [ ] 建立 GitHub repo `cutemo0953/CIRS`
- [ ] 建立目錄結構
- [ ] SQLite schema 建立
- [ ] FastAPI 基礎 CRUD
- [ ] 基礎認證 (PIN + JWT)

### Phase 2: Core Features

- [ ] Inventory CRUD + 發放紀錄
- [ ] Person CRUD + 報到/檢傷
- [ ] EventLog 完整實作
- [ ] 前端 Alpine.js shell

### Phase 3: Communication

- [ ] Message board API
- [ ] 前端留言板 UI
- [ ] Polling 機制
- [ ] 圖片上傳壓縮

### Phase 4: Offline & Sync

- [ ] IndexedDB wrapper
- [ ] Sync queue 實作
- [ ] Service Worker
- [ ] 衝突解決

### Phase 5: Polish

- [ ] PWA manifest + icons
- [ ] 離線狀態 UI
- [ ] Error handling
- [ ] 效能優化

---

## 11. Prompt for Claude Code

```
我要開發 CIRS v1.0 (Community Inventory Resilience System)。
請嚴格依照 CIRS_DEV_SPEC.md 規格書。

關鍵約束：
1. Offline-First: 前端必須能在沒有後端的情況下運作 (IndexedDB)
2. 技術棧: Alpine.js + Tailwind CSS (前端), FastAPI + SQLite (後端)
3. 色系: 以綠色 #4c826b 為主，警戒功能用紅/橘色
4. 圖示: 使用 Heroicons (outline)，不使用 emoji
5. 網路: 後端運行在 Raspberry Pi，靜態 IP (如 192.168.1.200:8090)
6. 與 MIRS 共存: CIRS 使用獨立的 SQLite 檔案，port 8090

請先建立 Python 後端的 SQLite models 和基礎 API 結構。
```

---

## 12. Portal (統一入口頁面)

### 12.1 概述

Portal 是 Raspberry Pi 的統一入口，整合所有服務。

```
http://192.168.x.x/  (Port 80)
```

### 12.2 UI 設計

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│              韌性中樞 Resilience Hub                         │
│                 [社區避難中心]                               │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│  最新公告                                              [展開]│
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ 目前發電機運作正常，請節約用電，僅供照明使用。            │ │
│ │                                      - 管理員 · 10分鐘前 │ │
│ └─────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   ┌───────────────┐    ┌───────────────┐                   │
│   │   [users]     │    │ [archive-box] │                   │
│   │   人員報到     │    │   物資管理     │                   │
│   │   Identity    │    │   Inventory   │                   │
│   │               │    │               │                   │
│   │  志工/管理員   │    │   志工/倉管    │                   │
│   └───────────────┘    └───────────────┘                   │
│                                                             │
│   ┌───────────────┐    ┌───────────────┐                   │
│   │    [chat]     │    │   [folder]    │                   │
│   │  互助留言板    │    │  防災資料庫    │                   │
│   │ Communication │    │  File Server  │                   │
│   │               │    │               │                   │
│   │    所有人     │    │    所有人      │                   │
│   └───────────────┘    └───────────────┘                   │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│  即時狀態                                                   │
│  ├ 在場人數: 150 人                                        │
│  ├ 維生天數: 水 5天 · 糧 4天                               │
│  └ 網路狀態: 外網中斷 · 內網正常                            │
└─────────────────────────────────────────────────────────────┘
```

### 12.5 網路狀態偵測

`navigator.onLine` 只能偵測是否連上 Router，無法判斷外網是否通。

```javascript
// 網路狀態偵測
const NetworkStatus = {
    lan: false,      // 內網 (連上 Pi)
    internet: false, // 外網 (連上 Internet)

    async check() {
        // 1. 檢查內網 (嘗試連 CIRS API)
        try {
            const res = await fetch('/api/system/time', { timeout: 3000 });
            this.lan = res.ok;
        } catch {
            this.lan = false;
        }

        // 2. 檢查外網 (嘗試連 Google 204)
        try {
            const res = await fetch('https://www.google.com/generate_204', {
                mode: 'no-cors',
                cache: 'no-store'
            });
            this.internet = true;
        } catch {
            this.internet = false;
        }

        return { lan: this.lan, internet: this.internet };
    },

    getStatusText() {
        if (this.lan && this.internet) return '內網正常 · 外網正常';
        if (this.lan && !this.internet) return '內網正常 · 外網中斷';
        if (!this.lan && this.internet) return '內網中斷 · 外網正常';
        return '內網中斷 · 外網中斷';
    },

    getStatusColor() {
        if (this.lan) return 'text-green-600';
        return 'text-red-600';
    }
};

// 每 30 秒檢查一次
setInterval(() => NetworkStatus.check(), 30000);
```

### 12.3 功能模組對照

| 模組 | 圖示 (Heroicon) | Port | 說明 |
|------|-----------------|------|------|
| 人員報到 | `users` | :8090/people | 災民登記、檢傷分類 |
| 物資管理 | `archive-box` | :8090/inventory | 庫存查詢、領料紀錄 |
| 互助留言板 | `chat-bubble-left-right` | :8090/messages | 尋人、回報、互助 |
| 防災資料庫 | `folder-open` | :8090/files | 離線文件下載 |
| MIRS | `beaker` | :8000 | 醫療庫存 (選配) |

### 12.4 Nginx 設定

```nginx
# /etc/nginx/sites-available/resilience-hub
server {
    listen 80 default_server;
    server_name _;

    # Portal 首頁
    location = / {
        root /home/pi/CIRS/portal;
        index index.html;
    }

    # CIRS API
    location /api/ {
        proxy_pass http://127.0.0.1:8091/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # CIRS Frontend
    location /cirs/ {
        alias /home/pi/CIRS/frontend/;
        try_files $uri $uri/ /cirs/index.html;
    }

    # MIRS (如有)
    location /mirs/ {
        proxy_pass http://127.0.0.1:8000/;
    }

    # File Server (靜態檔案)
    location /files/ {
        alias /home/pi/CIRS/files/;
        autoindex on;
        autoindex_format json;  # API 用
    }

    # 靜態資源快取
    location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff2)$ {
        expires 7d;
        add_header Cache-Control "public, immutable";
    }
}
```

---

## 13. HIRS-CIRS 同步機制

### 13.1 概述

讓 CIRS 發放的物資可同步到個人 HIRS，實現「社區-個人」雙向記錄。

```
┌─────────────────┐                    ┌─────────────────┐
│      CIRS       │   發放封包 (QR)    │   個人 HIRS     │
│   (社區站點)     │ ────────────────→ │    (手機)       │
│                 │                    │                 │
│  記錄: 誰領了    │                    │  記錄: 從哪領的  │
│       什麼物資   │                    │       領了什麼   │
└─────────────────┘                    └─────────────────┘
```

### 13.2 同步封包格式

```json
{
  "type": "CIRS_DISTRIBUTION",
  "version": "1.0",
  "source": {
    "station_id": "station_001",
    "station_name": "社區避難中心",
    "station_ip": "192.168.1.200"
  },
  "recipient": {
    "cirs_id": "a1b2c3d4",
    "display_name": "王小明"
  },
  "items": [
    {
      "name": "礦泉水 600ml",
      "quantity": 6,
      "unit": "瓶",
      "category": "water"
    },
    {
      "name": "泡麵",
      "quantity": 2,
      "unit": "包",
      "category": "food"
    }
  ],
  "distributed_at": "2024-12-08T14:30:00+08:00",
  "operator": {
    "id": "staff001",
    "name": "志工A"
  },
  "event_id": 12345,
  "checksum": "sha256:abc123..."
}
```

### 13.3 CIRS 發放流程

```
1. 志工選擇物資、輸入數量
2. 掃描/輸入領取人 ID
3. 確認發放
   ├─→ 扣除 CIRS 庫存
   ├─→ 寫入 EventLog
   └─→ 產生發放封包 QR Code

4. 顯示發放完成畫面
   ┌─────────────────────────────────┐
   │ 發放完成                        │
   │                                 │
   │ 領取人: 王小明 (a1b2c3d4)       │
   │ 物資: 礦泉水 x6, 泡麵 x2        │
   │                                 │
   │ ┌─────────────────────────────┐ │
   │ │       [QR CODE]             │ │
   │ │                             │ │
   │ │   用 HIRS App 掃描          │ │
   │ │   同步到個人庫存             │ │
   │ └─────────────────────────────┘ │
   │                                 │
   │  [列印收據]  [下一位]           │
   └─────────────────────────────────┘
```

### 13.4 HIRS 升級需求

HIRS v1.2 需新增以下功能以支援 CIRS 同步：

#### 13.4.1 新增資料結構

```javascript
// LocalStorage 新增欄位
{
  // 現有欄位
  inventory: [...],
  settings: {...},

  // 新增: 身份綁定
  identity: {
    cirs_id: "a1b2c3d4",          // CIRS 發的 ID (可為 null)
    display_name: "王小明",
    phone_hash: "sha256:xxx",     // 選填
    linked_stations: [            // 曾綁定的站點
      {
        station_id: "station_001",
        station_name: "社區避難中心",
        linked_at: "2024-12-08"
      }
    ]
  },

  // 新增: 領取記錄
  received_log: [
    {
      id: "evt_12345",
      source: {
        station_id: "station_001",
        station_name: "社區避難中心"
      },
      items: [
        { name: "礦泉水", qty: 6, unit: "瓶", category: "water" }
      ],
      received_at: "2024-12-08T14:30:00+08:00",
      operator: "志工A",
      synced_at: "2024-12-08T14:31:00+08:00"
    }
  ]
}
```

#### 13.4.2 新增功能

| 功能 | 說明 | 位置 |
|------|------|------|
| 綁定 CIRS ID | 掃描 CIRS 站點 QR 綁定身份 | 設定頁 |
| 掃描發放封包 | 掃描 QR 匯入領取記錄 | 首頁快捷 / 設定頁 |
| 領取記錄列表 | 顯示從各站點領取的物資 | 新增「記錄」Tab |
| 自動入庫 | 領取物資自動加入 HIRS 庫存 | 掃描後自動 |

#### 13.4.3 UI 變更

```
新增「記錄」Tab 或在設定頁加入：

┌─────────────────────────────────────┐
│ 領取記錄                            │
├─────────────────────────────────────┤
│ ┌─────────────────────────────────┐ │
│ │ 社區避難中心                    │ │
│ │ 2024-12-08 14:30                │ │
│ │ ├ 礦泉水 x 6 瓶                 │ │
│ │ └ 泡麵 x 2 包                   │ │
│ │ 經手人: 志工A                   │ │
│ └─────────────────────────────────┘ │
│ ┌─────────────────────────────────┐ │
│ │ 社區避難中心                    │ │
│ │ 2024-12-07 09:15                │ │
│ │ └ 毛毯 x 1 件                   │ │
│ │ 經手人: 志工B                   │ │
│ └─────────────────────────────────┘ │
└─────────────────────────────────────┘
```

### 13.5 API 新增

```
# CIRS 端
GET  /api/distribution/:event_id/qr   # 產生發放封包 QR Code
POST /api/distribution/:event_id/print # 列印收據

# 驗證封包 (HIRS 可用來驗證)
POST /api/distribution/verify
Body: { "checksum": "sha256:abc123..." }
Response: { "valid": true, "event": {...} }
```

---

## 14. File Server (防災資料庫)

### 14.1 概述

提供離線可用的防災文件下載，如地圖、急救手冊、聯絡清單等。

### 14.2 目錄結構

```
~/CIRS/files/
├── maps/
│   ├── shelter_map.pdf          # 避難所地圖
│   ├── evacuation_routes.pdf    # 疏散路線
│   └── local_area.png           # 周邊地圖
├── manuals/
│   ├── first_aid.pdf            # 急救手冊
│   ├── cpr_guide.pdf            # CPR 指南
│   └── disaster_prep.pdf        # 防災準備
├── contacts/
│   ├── emergency_contacts.pdf   # 緊急聯絡
│   └── volunteer_list.pdf       # 志工名單
└── templates/
    ├── checkin_form.pdf         # 報到表單
    └── resource_request.pdf     # 物資申請單
```

### 14.3 UI 設計

```
┌─────────────────────────────────────┐
│ 防災資料庫                          │
├─────────────────────────────────────┤
│ 分類: [全部] [地圖] [手冊] [聯絡]   │
├─────────────────────────────────────┤
│ ┌─────────────────────────────────┐ │
│ │ [document] 避難所地圖           │ │
│ │ PDF · 2.3 MB                    │ │
│ │ [下載] [預覽]                   │ │
│ └─────────────────────────────────┘ │
│ ┌─────────────────────────────────┐ │
│ │ [document] 急救手冊             │ │
│ │ PDF · 5.1 MB                    │ │
│ │ [下載] [預覽]                   │ │
│ └─────────────────────────────────┘ │
│ ┌─────────────────────────────────┐ │
│ │ [document] 緊急聯絡清單         │ │
│ │ PDF · 156 KB                    │ │
│ │ [下載] [預覽]                   │ │
│ └─────────────────────────────────┘ │
└─────────────────────────────────────┘
```

### 14.4 API

```
GET /api/files                    # 列出所有檔案
Response: {
  "files": [
    {
      "name": "shelter_map.pdf",
      "path": "/files/maps/shelter_map.pdf",
      "category": "maps",
      "size": 2400000,
      "updated_at": "2024-12-01"
    }
  ]
}

GET /files/{path}                 # 直接下載檔案 (Nginx 靜態)
```

---

## 15. 資料備份與清理機制

### 15.1 概述

Raspberry Pi SD 卡空間有限，需要自動備份與清理機制。

### 15.2 儲存空間規劃

| 項目 | 預估大小 | 說明 |
|------|----------|------|
| CIRS SQLite | 10-50 MB | 依人數/事件量 |
| 圖片 (留言板) | 100-500 MB | 每張 <500KB |
| File Server | 50-200 MB | PDF/圖片 |
| 系統保留 | 2 GB | OS + 應用 |
| **建議總量** | **<4 GB** | SD 卡 16GB 安全 |

### 15.3 外接硬碟備份架構

```
┌─────────────────────────────────────────────────────────┐
│  Raspberry Pi                                           │
│  ┌─────────────────┐                                   │
│  │  SD Card        │                                   │
│  │  /home/pi/CIRS/ │                                   │
│  │  └─ data/       │                                   │
│  │     └─ cirs.db  │  ←── 主資料庫 (即時寫入)          │
│  └────────┬────────┘                                   │
│           │ 每日備份                                    │
│           ▼                                             │
│  ┌─────────────────┐                                   │
│  │  USB 外接硬碟    │                                   │
│  │  /mnt/backup/   │                                   │
│  │  └─ cirs/       │                                   │
│  │     ├─ 2024-12-08_cirs.db                          │
│  │     ├─ 2024-12-07_cirs.db                          │
│  │     └─ ...      │  ←── 保留 30 天                   │
│  └─────────────────┘                                   │
└─────────────────────────────────────────────────────────┘
```

### 15.4 備份腳本

```bash
#!/bin/bash
# /home/pi/CIRS/scripts/backup.sh

# 設定
CIRS_DB="/home/pi/CIRS/backend/data/cirs.db"
BACKUP_DIR="/mnt/backup/cirs"
RETENTION_DAYS=30
DATE=$(date +%Y-%m-%d)

# 確認外接硬碟已掛載
if ! mountpoint -q /mnt/backup; then
    echo "錯誤: 外接硬碟未掛載"
    exit 1
fi

# 建立備份目錄
mkdir -p "$BACKUP_DIR"

# 備份 SQLite (使用 .backup 確保一致性)
sqlite3 "$CIRS_DB" ".backup '$BACKUP_DIR/${DATE}_cirs.db'"

# 壓縮備份
gzip -f "$BACKUP_DIR/${DATE}_cirs.db"

# 清理舊備份 (保留 30 天)
find "$BACKUP_DIR" -name "*.db.gz" -mtime +$RETENTION_DAYS -delete

# 記錄
echo "$(date): 備份完成 - ${DATE}_cirs.db.gz" >> "$BACKUP_DIR/backup.log"
```

### 15.5 自動清理機制

```sql
-- 清理策略 (加入 cirs.db)

-- 1. EventLog: 保留 90 天
DELETE FROM event_log
WHERE timestamp < datetime('now', '-90 days');

-- 2. Messages: 保留 1000 則或 7 天 (已有 trigger)
-- 見 4.4 節

-- 3. 已解決的尋人留言: 3 天後刪除
DELETE FROM message
WHERE is_resolved = TRUE
AND created_at < datetime('now', '-3 days');
```

### 15.6 清理腳本

```bash
#!/bin/bash
# /home/pi/CIRS/scripts/cleanup.sh

CIRS_DB="/home/pi/CIRS/backend/data/cirs.db"

echo "開始清理..."

# EventLog 保留 90 天
sqlite3 "$CIRS_DB" "DELETE FROM event_log WHERE timestamp < datetime('now', '-90 days');"
echo "EventLog 已清理"

# 已解決留言 3 天後刪除
sqlite3 "$CIRS_DB" "DELETE FROM message WHERE is_resolved = TRUE AND created_at < datetime('now', '-3 days');"
echo "已解決留言已清理"

# VACUUM 壓縮資料庫
sqlite3 "$CIRS_DB" "VACUUM;"
echo "資料庫已壓縮"

# 顯示大小
echo "資料庫大小: $(du -h $CIRS_DB | cut -f1)"
```

### 15.7 Cron 排程

```bash
# /etc/cron.d/cirs-maintenance

# 每天凌晨 3 點備份
0 3 * * * pi /home/pi/CIRS/scripts/backup.sh >> /var/log/cirs-backup.log 2>&1

# 每天凌晨 4 點清理
0 4 * * * pi /home/pi/CIRS/scripts/cleanup.sh >> /var/log/cirs-cleanup.log 2>&1
```

### 15.8 外接硬碟設定

```bash
# 1. 找到硬碟
lsblk

# 2. 格式化 (如果是新硬碟)
sudo mkfs.ext4 /dev/sda1

# 3. 建立掛載點
sudo mkdir -p /mnt/backup

# 4. 取得 UUID
sudo blkid /dev/sda1

# 5. 設定自動掛載 (/etc/fstab)
UUID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx /mnt/backup ext4 defaults,nofail 0 2

# 6. 掛載
sudo mount -a

# 7. 設定權限
sudo chown -R pi:pi /mnt/backup
```

### 15.9 資料恢復流程

```bash
# 從備份恢復

# 1. 停止服務
sudo systemctl stop cirs

# 2. 備份當前資料庫 (以防萬一)
cp /home/pi/CIRS/backend/data/cirs.db /home/pi/CIRS/backend/data/cirs.db.broken

# 3. 解壓縮備份
gunzip -c /mnt/backup/cirs/2024-12-07_cirs.db.gz > /home/pi/CIRS/backend/data/cirs.db

# 4. 重啟服務
sudo systemctl start cirs

# 5. 驗證
curl http://localhost:8091/api/stats
```

### 15.10 管理介面 (Admin)

```
設定 → 資料管理

┌─────────────────────────────────────┐
│ 資料管理                            │
├─────────────────────────────────────┤
│ 儲存空間                            │
│ ├ 資料庫: 45.2 MB                  │
│ ├ 圖片: 128.5 MB                   │
│ └ 總計: 173.7 MB / 4 GB            │
│   [██████░░░░░░░░░░░░░░] 4.3%      │
├─────────────────────────────────────┤
│ 備份狀態                            │
│ ├ 外接硬碟: 已連接 (500 GB)        │
│ ├ 上次備份: 2024-12-08 03:00       │
│ └ 備份數量: 30 個                   │
│                                     │
│ [立即備份]  [查看備份列表]          │
├─────────────────────────────────────┤
│ 清理選項                            │
│ ├ EventLog 保留天數: [90] 天       │
│ ├ 留言保留數量: [1000] 則          │
│ └ 已解決留言: [3] 天後刪除         │
│                                     │
│ [執行清理]  [VACUUM 壓縮]           │
├─────────────────────────────────────┤
│ 危險區域                            │
│ [匯出完整資料庫]                    │
│ [匯入資料庫]                        │
│ [清除所有資料] ← 需二次確認         │
└─────────────────────────────────────┘
```

---

## 16. 更新的 Implementation Checklist

### Phase 1: Foundation
- [ ] 建立 GitHub repo `cutemo0953/CIRS`
- [ ] 建立目錄結構
- [ ] SQLite schema 建立
- [ ] FastAPI 基礎 CRUD
- [ ] 基礎認證 (PIN + JWT)

### Phase 2: Core Features
- [ ] Inventory CRUD + 發放紀錄
- [ ] Person CRUD + 報到/檢傷
- [ ] EventLog 完整實作
- [ ] 前端 Alpine.js shell

### Phase 3: Communication
- [ ] Message board API
- [ ] 前端留言板 UI
- [ ] Polling 機制
- [ ] 圖片上傳壓縮

### Phase 4: Portal & Files
- [ ] Portal 入口頁面
- [ ] File Server 模組
- [ ] Nginx 統一路由

### Phase 5: HIRS Integration
- [ ] 發放封包 QR 產生
- [ ] HIRS v1.2 升級 (identity + received_log)
- [ ] 掃描匯入功能
- [ ] 自動入庫邏輯

### Phase 6: Backup & Maintenance
- [ ] 備份腳本
- [ ] 清理腳本
- [ ] Cron 排程
- [ ] 管理介面 UI

### Phase 7: Offline & Sync
- [ ] IndexedDB wrapper
- [ ] Sync queue 實作
- [ ] Service Worker
- [ ] 衝突解決

### Phase 8: Polish
- [ ] PWA manifest + icons
- [ ] 離線狀態 UI
- [ ] Error handling
- [ ] 效能優化

---

## 18. 更新的 Prompt for Claude Code

```
我要開發 CIRS v1.0 (Community Inventory Resilience System)。
請嚴格依照 CIRS_DEV_SPEC.md 規格書。

關鍵約束：
1. Offline-First: 前端必須能在沒有後端的情況下運作 (IndexedDB)
2. 技術棧: Alpine.js + Tailwind CSS (前端), FastAPI + SQLite (後端)
3. 色系: 以綠色 #4c826b 為主，警戒功能用紅/橘色
4. 圖示: 使用 Heroicons (outline)，不使用 emoji
5. 網路: 後端運行在 Raspberry Pi，靜態 IP (如 192.168.1.200:8090)
6. 與 MIRS 共存: CIRS 使用獨立的 SQLite 檔案，port 8090
7. Portal: 統一入口頁面在 port 80
8. HIRS 整合: 物資發放需產生 QR 封包供個人 HIRS 掃描同步
9. 備份機制: 支援外接硬碟每日備份，資料庫保留 90 天 EventLog

Additional Instructions:
- SQLite 必須設定 PRAGMA journal_mode=WAL 以處理並發請求
- 使用 threading.Lock 序列化寫入操作，避免 'database is locked' 錯誤
- 提供 /api/system/time endpoint 讓前端同步時間 (Pi 可能沒有 RTC)
- 圖片上傳前端必須壓縮至 1024x1024 / 500KB 以下
- Nginx 設定需包含 try_files fallback 以支援 SPA 路由

請先建立 Python 後端的 SQLite models 和基礎 API 結構。
```

---

**Version:** 1.3
**Last Updated:** 2024-12
**Author:** De Novo Orthopedics Inc. / 谷盺生物科技股份有限公司

---

## Changelog

### v1.4 (2024-12) - Dual-Track Architecture
- **Architecture**: 實施 Dual-Track 策略，明確分離 Portal（公共看板）和 Frontend（操作台）
  - Portal = 公共資訊看板（唯讀、交通燈系統、無需登入）
  - Frontend = 操作人員控制台（需認證、資料密集、CRUD 操作）
- **Portal**: 重構為純公共看板
  - 移除管理員登入、備份、設定等功能
  - 新增交通燈狀態系統（綠/黃/紅）
  - 四大指標：收容人數、飲用水、糧食、設備狀態
  - 燈號邏輯：>3 天=綠、1-3 天=黃、<1 天=紅
  - 公告自動從新 API 取得
  - 新增狀態說明圖例
  - 保留防災資料庫、互助留言（唯讀連結）
- **Frontend**: 強化為操作人員專用控制台
  - 統計列「收容人數」改為「在場人數」(checked_in)
  - 新增系統按鈕（齒輪圖示，Admin 專用）
  - 系統下拉選單：資料備份、站點設定、API 文件
  - 備份管理整合至 Frontend（從 Portal 移除）
- **API**: 新增 `GET /api/public/status` 輕量公開端點
  - 回傳交通燈狀態：shelter、water、food、equipment
  - 包含收容容量和人數
  - 包含當前公告內容
  - 無需認證，供 Portal 使用

### v1.3 (2024-12)
- **Messages**: 新增「找物」(seek_item) 篩選按鈕和紫色標籤
- **Messages**: 即時統計改為顯示「待解決」數量（非今日留言數）
- **Messages**: 新增置頂留言功能（管理員可置頂重要公告）
- **Person**: 批次退場流程 - 支援多人同時辦理離站
  - 退場原因：正常離站 / 轉送醫院 / 其他
  - 可填寫去向和備註
  - 一家人可一起離站，類似出院流程
- **Portal**: 新增備份管理 UI（管理員專用）
  - 支援本機 / 下載 / USB 三種備份目標
  - 可選加密備份（需設定密碼）
  - 顯示備份歷史記錄
- **API**: POST `/api/messages/:id/pin` 置頂/取消置頂留言
- **API**: POST `/api/person/batch-checkout` 批次退場

### v1.2 (2024-12)
- **Frontend**: 設備範本功能 - 預設 7 組常用範本
  - 電力設備組（發電機、UPS、照明）
  - 通訊設備組（對講機、擴音器、行動電源）
  - 醫療設備組（血壓計、輪椅、AED）
  - 收容基本設備（折疊床、睡袋、桌椅）
  - 炊事設備組（瓦斯爐、鍋具、飲水機）
  - 衛生設備組（移動廁所、消毒設備）
  - 救援工具組（油壓剪、繩索、安全帽）
- **Frontend**: 設備範本可自訂新增、編輯、刪除（管理員）
- **Frontend**: 套用範本可批次建立設備，含預設檢查週期
- **Frontend**: 物資發放按鈕改用大地色系 (amber-600)
- **Frontend**: 人員清單區域/檢傷按鈕改用 primary 色系
- **Frontend**: 新增單人快速移動區域功能
- **Frontend**: 新增物資紀錄查詢（管理員）

### v1.1 (2024-12)
- **Database**: 新增 `parent_id` 欄位支援留言回覆
- **API**: Messages resolve 改為 POST 方法
- **API**: 新增 `/api/messages/:id/reply` 回覆路由
- **API**: GET messages 回傳含 `replies` 陣列
- **Accounts**: 預設新增 staff001 (志工) 和 medic001 (醫護) 帳號
- **Frontend**: 設備管理新增檢查/編輯/刪除按鈕和統計
- **Frontend**: 留言板新增回覆/解決/刪除功能
- **Frontend**: 入庫/發放按鈕移至底部固定列
- **Frontend**: 即時統計灰階顯示在上方
- **Portal**: 管理員可編輯站點名稱和廣播公告

### v1.0 (2024-12)
- 初始版本
