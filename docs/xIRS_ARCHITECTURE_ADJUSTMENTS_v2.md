# xIRS 架構調整計畫 v2.0

**基於**: ChatGPT 架構分析回饋 (含二次修正)
**日期**: 2025-12-22
**狀態**: 修正完成，待實作

---

## 0. 修正摘要 (基於 ChatGPT 二次回饋)

| # | 問題 | 修正 |
|---|------|------|
| 1 | 路徑命名不一致 | 定義 Canonical Path Scheme |
| 2 | DB 歸屬命名含混 | 改用 `xirs_hub.db` |
| 3 | tasks 表缺欄位 | 加入 idempotency + lifecycle |
| 4 | +100 魔術數字 | 改用 effective_priority 公式 |
| 5 | Roadmap 順序風險 | 5D-core 先於 5C |
| 6 | patient_ref 無規格 | 定義 token spec |
| 7 | Mode Switcher 無權限 | 加入 role-based gate |

---

## 1. Canonical Path Scheme (修正 #1)

### 1.1 統一 URL 規則

**規則**: 所有 PWA 使用 `/{mode}/` 格式，不加 `/frontend/` 前綴

| Mode | Canonical URL | 檔案位置 | 說明 |
|------|---------------|----------|------|
| Admin Console | `/admin/` | `/frontend/admin/` | Hub 管理主頁 |
| Station Mode | `/station/` | `/frontend/station/` | 分站物資管理 |
| Runner Mode | `/runner/` | `/frontend/runner/` | Blind Carrier |
| Doctor Mode | `/doctor/` | `/frontend/doctor/` | 處方開立 |
| Pharmacy Mode | `/pharmacy/` | `/frontend/pharmacy/` | 藥局調劑 (或擴展 Station) |
| Portal | `/portal/` | `/portal/` | 公開狀態看板 |
| Tasking | `/admin/tasking/` | `/frontend/admin/tasking/` | 任務指派 |

### 1.2 Backend Mount 修正

```python
# main.py - 統一 mount 規則
if not IS_VERCEL:
    # PWA modes - 統一使用 /{mode}/ 格式
    app.mount("/station", StaticFiles(directory=str(STATION_DIR), html=True))
    app.mount("/runner", StaticFiles(directory=str(RUNNER_DIR), html=True))
    app.mount("/doctor", StaticFiles(directory=str(DOCTOR_DIR), html=True))
    app.mount("/pharmacy", StaticFiles(directory=str(PHARMACY_DIR), html=True))
    app.mount("/admin", StaticFiles(directory=str(ADMIN_DIR), html=True))

    # Shared assets
    app.mount("/shared", StaticFiles(directory=str(SHARED_DIR)))

    # Legacy (redirect to canonical)
    # /frontend/ → /admin/
```

---

## 2. Database Naming (修正 #2)

### 2.1 命名規則

| 角色 | 資料庫檔案 | 說明 |
|------|-----------|------|
| **Hub (Authority)** | `xirs_hub.db` | 唯一權威資料庫 |
| **CIRS View** | 無獨立 DB | 是 UI/Role 視角，存取同一 xirs_hub.db |
| **MIRS View** | 無獨立 DB | 是 UI/Role 視角，存取同一 xirs_hub.db |
| **PWA Cache** | IndexedDB | 離線快取，非權威來源 |

### 2.2 Migration Path

```python
# database.py
import os
from pathlib import Path

# 新命名
DB_NAME = 'xirs_hub.db'

# Migration: 如果舊檔存在且新檔不存在，改名
def migrate_db_name():
    old_path = DATA_DIR / 'cirs.db'
    new_path = DATA_DIR / DB_NAME
    if old_path.exists() and not new_path.exists():
        old_path.rename(new_path)
        print(f'[DB] Migrated {old_path} → {new_path}')
```

---

## 3. Tasks Table Schema (修正 #3)

### 3.1 完整 Schema

```sql
CREATE TABLE tasks (
    -- Identity
    id TEXT PRIMARY KEY,                    -- UUID v4
    idempotency_key TEXT UNIQUE,            -- 防重複建立 (client-generated)

    -- Domain & Type
    domain TEXT NOT NULL                    -- 'LOGISTICS' | 'CLINICAL'
        CHECK (domain IN ('LOGISTICS', 'CLINICAL')),
    task_type TEXT NOT NULL,                -- 'DELIVERY', 'DISPENSE', 'PRESCRIPTION', etc.

    -- Assignment
    assignee_type TEXT NOT NULL             -- 'STATION' | 'RUNNER' | 'PRESCRIBER' | 'PHARMACIST'
        CHECK (assignee_type IN ('STATION', 'RUNNER', 'PRESCRIBER', 'PHARMACIST')),
    assignee_id TEXT,                       -- NULL = unassigned

    -- Priority (修正 #4)
    base_priority INTEGER DEFAULT 0,        -- User-set priority (0-99)
    -- effective_priority 由 VIEW 計算，不存欄位

    -- Lifecycle
    status TEXT DEFAULT 'PENDING'
        CHECK (status IN ('PENDING', 'ASSIGNED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED', 'EXPIRED')),

    -- Payload
    payload TEXT,                           -- JSON string (SQLite 無原生 JSON type)

    -- Audit
    created_by TEXT NOT NULL,               -- User/system ID
    created_by_role TEXT NOT NULL,          -- 'ADMIN', 'PRESCRIBER', 'SYSTEM'
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME,

    -- Scheduling
    due_at DATETIME,                        -- 期限
    expires_at DATETIME,                    -- 過期後自動 EXPIRED

    -- Concurrency
    version INTEGER DEFAULT 1               -- Optimistic locking
);

-- Indexes (修正 #3)
CREATE INDEX idx_tasks_domain_status_priority
    ON tasks(domain, status, base_priority DESC);
CREATE INDEX idx_tasks_assignee
    ON tasks(assignee_type, assignee_id, status);
CREATE INDEX idx_tasks_idempotency
    ON tasks(idempotency_key);
CREATE INDEX idx_tasks_expires
    ON tasks(expires_at) WHERE expires_at IS NOT NULL;
```

### 3.2 Effective Priority View (修正 #4)

```sql
-- Priority 計算規則 (不用 +100 魔術數字)
CREATE VIEW tasks_with_priority AS
SELECT
    *,
    base_priority + CASE domain
        WHEN 'CLINICAL' THEN 1000  -- CLINICAL 永遠優先
        WHEN 'LOGISTICS' THEN 0
        ELSE 0
    END AS effective_priority
FROM tasks;

-- 查詢時使用 VIEW
SELECT * FROM tasks_with_priority
WHERE status = 'PENDING'
ORDER BY effective_priority DESC, created_at ASC;
```

### 3.3 Idempotency 使用方式

```python
# Client 端生成 idempotency_key
def create_task(task_data: dict, idempotency_key: str):
    """
    idempotency_key 格式建議:
    {client_id}:{action}:{timestamp_ms}:{random_suffix}
    例: STATION-01:DISPENSE:1703232000000:a1b2c3
    """
    try:
        cursor.execute("""
            INSERT INTO tasks (id, idempotency_key, ...)
            VALUES (?, ?, ...)
        """, (uuid4(), idempotency_key, ...))
    except sqlite3.IntegrityError:
        # idempotency_key 已存在，返回既有任務
        return get_task_by_idempotency_key(idempotency_key)
```

---

## 4. Roadmap 順序調整 (修正 #5)

### 4.1 修正後順序

```
Phase 5D-core: Hub Prescriber API (先做)
├── prescribers 表格 + CRUD API
├── 憑證發行 (sign with Hub key)
├── 憑證撤銷清單 (revocation list)
└── GET /api/prescriber/certs (供 Pharmacy 下載)

Phase 5C: Pharmacy Station Extension
├── 掃描 Rx QR + 驗證簽章
├── 驗證 prescriber cert (從 5D-core 取得)
├── 調劑流程 UI
└── 產生 DISPENSE_RECORD

Phase 5D-full: Hub Rx/Dispense/Tasks Integration
├── rx_orders 表格 + ingest API
├── dispense_records 表格 + ingest API
├── tasks 表格 + API
└── Ops/Tasking UI

Phase 5E: CIRS/MIRS UI Integration
├── Mode Switcher (role-gated)
├── Dashboard xIRS 入口
└── patient_ref token 實作
```

### 4.2 依賴關係圖

```
                    ┌─────────────────┐
                    │   5D-core       │
                    │ (Prescriber API)│
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
     ┌────────────┐  ┌────────────┐  ┌────────────┐
     │    5C      │  │  5D-full   │  │    5E      │
     │ (Pharmacy) │  │ (Rx/Tasks) │  │ (UI Integ) │
     └────────────┘  └────────────┘  └────────────┘
```

---

## 5. Patient Reference Token Spec (修正 #6)

### 5.1 Token 規格

| 項目 | 規格 |
|------|------|
| **格式** | `pref_{random_base62_16}` (例: `pref_A7xK9mQ2vB4wL8nP`) |
| **生成方式** | Cryptographically secure random (非 hash) |
| **長度** | 21 chars (prefix 5 + random 16) |
| **唯一性** | Hub 內全域唯一 |

### 5.2 Mapping 存放

```sql
-- 只存在 Hub DB (xirs_hub.db)
CREATE TABLE patient_refs (
    token TEXT PRIMARY KEY,           -- pref_xxx
    rx_id TEXT NOT NULL,              -- 對應的處方 ID
    person_id TEXT,                   -- CIRS person.id (可選)
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME,              -- 保留期限

    FOREIGN KEY (rx_id) REFERENCES rx_orders(rx_id)
);

CREATE INDEX idx_patient_refs_rx ON patient_refs(rx_id);
CREATE INDEX idx_patient_refs_person ON patient_refs(person_id);
```

### 5.3 保留與離線規則

| 情境 | 規則 |
|------|------|
| **保留期間** | 災難結束後 90 天，或 rx 完成後 30 天 |
| **離線重綁** | Pharmacy 掃描 Rx 時自動查詢/建立 token |
| **CIRS 端** | 只存 token，不存 rx_id 或病歷內容 |
| **查詢方向** | token → rx_id (Hub only)，不可反查 |

### 5.4 API

```
POST /api/patient-ref/create
  Body: { rx_id: "RX-xxx" }
  Response: { token: "pref_xxx" }

GET /api/patient-ref/{token}
  Response: { rx_id: "RX-xxx", status: "FILLED" }
  (需要 Hub 權限)
```

---

## 6. Mode Switcher Role-Gating (修正 #7)

### 6.1 角色權限對照

| Mode | 可存取角色 | 說明 |
|------|-----------|------|
| `/admin/` | `admin`, `hub_admin` | Hub 管理 |
| `/admin/tasking/` | `admin`, `hub_admin` | 任務指派 |
| `/station/` | `admin`, `station_lead` | 分站管理 |
| `/runner/` | `*` (匿名可用) | Blind Carrier |
| `/doctor/` | `admin`, `prescriber` | 需要簽章金鑰 |
| `/pharmacy/` | `admin`, `pharmacist`, `station_lead` | 藥局模式 |
| `/portal/` | `*` (公開) | 狀態看板 |

### 6.2 Mode Switcher 實作

```html
<!-- Header Mode Switcher (role-gated) -->
<div x-data="modeSwitcher()" class="relative">
    <button @click="open = !open" class="flex items-center gap-2 px-3 py-2 rounded-lg hover:bg-gray-100">
        <span x-text="currentModeLabel"></span>
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
        </svg>
    </button>

    <div x-show="open" @click.away="open = false"
         class="absolute right-0 mt-2 w-48 bg-white rounded-xl shadow-lg border z-50">
        <template x-for="mode in availableModes" :key="mode.path">
            <a :href="mode.path"
               class="block px-4 py-2 hover:bg-gray-50 flex items-center gap-2"
               :class="mode.disabled ? 'opacity-50 cursor-not-allowed' : ''">
                <span x-text="mode.icon"></span>
                <span x-text="mode.label"></span>
                <span x-show="mode.disabled" class="text-xs text-gray-400">無權限</span>
            </a>
        </template>
    </div>
</div>

<script>
function modeSwitcher() {
    return {
        open: false,
        currentRole: window.USER_ROLE || 'guest',  // 從 auth context 取得

        allModes: [
            { path: '/admin/', label: '管理控台', icon: '📊', roles: ['admin', 'hub_admin'] },
            { path: '/station/', label: '分站模式', icon: '📦', roles: ['admin', 'station_lead'] },
            { path: '/runner/', label: 'Runner', icon: '🏃', roles: ['*'] },
            { path: '/doctor/', label: '醫師模式', icon: '👨‍⚕️', roles: ['admin', 'prescriber'] },
            { path: '/pharmacy/', label: '藥局模式', icon: '💊', roles: ['admin', 'pharmacist', 'station_lead'] },
            { path: '/admin/tasking/', label: '任務指派', icon: '📋', roles: ['admin', 'hub_admin'] },
        ],

        get availableModes() {
            return this.allModes.map(mode => ({
                ...mode,
                disabled: !this.hasAccess(mode.roles)
            }));
        },

        hasAccess(roles) {
            if (roles.includes('*')) return true;
            return roles.includes(this.currentRole);
        },

        get currentModeLabel() {
            const path = window.location.pathname;
            const mode = this.allModes.find(m => path.startsWith(m.path));
            return mode ? mode.label : '切換模式';
        }
    };
}
</script>
```

### 6.3 重要原則

```
┌─────────────────────────────────────────────────────────────────┐
│  Mode Switcher 只是 Launcher，不是授權機制                      │
│                                                                  │
│  ✓ 依角色顯示/隱藏/禁用選項                                     │
│  ✓ 未授權的 mode 顯示「無權限」並 disabled                      │
│  ✗ 不依賴 UI 隱藏做安全 (API 仍需驗證)                         │
│  ✗ 共用裝置不應預設顯示敏感模式                                 │
│                                                                  │
│  真正的授權在:                                                   │
│  - PWA 內部 (credentials 存在才能操作)                          │
│  - API 端點 (JWT/session 驗證)                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 7. 修正後檔案結構

```
/Users/QmoMBA/Downloads/CIRS/
├── backend/
│   ├── main.py                    # 更新 mount 規則
│   ├── database.py                # 改用 xirs_hub.db
│   ├── data/
│   │   └── xirs_hub.db            # 重新命名
│   └── routes/
│       ├── logistics.py           # 既有
│       ├── prescriber.py          # 5D-core 新增
│       ├── rx.py                  # 5D-full 新增
│       ├── dispense.py            # 5D-full 新增
│       ├── tasks.py               # 5D-full 新增
│       └── patient_ref.py         # 5E 新增
│
├── frontend/
│   ├── admin/                     # 新目錄
│   │   ├── index.html             # Hub 管理主頁
│   │   └── tasking/
│   │       └── index.html         # 任務指派
│   ├── station/                   # 既有
│   ├── runner/                    # 既有
│   ├── doctor/                    # 既有
│   └── pharmacy/                  # 5C 新增 (或擴展 station)
│
└── shared/
    └── js/
        ├── xirs-mode-switcher.js  # 共用 Mode Switcher 元件
        └── ...
```

---

## 8. 實作 Checklist

### Phase 5D-core (先做)

- [ ] 建立 `prescribers` 表格
- [ ] `POST /api/prescriber/register` (Hub 簽發憑證)
- [ ] `GET /api/prescriber/{id}/cert`
- [ ] `GET /api/prescriber/certs` (批次下載)
- [ ] `POST /api/prescriber/{id}/revoke`
- [ ] 撤銷清單 endpoint

### Phase 5C

- [ ] Pharmacy PWA 或擴展 Station
- [ ] 整合 prescriber certs 驗證
- [ ] Rx 掃描 + 簽章驗證
- [ ] 調劑流程 UI
- [ ] DISPENSE_RECORD 產生

### Phase 5D-full

- [ ] 建立 `rx_orders`, `dispense_records`, `tasks`, `patient_refs` 表格
- [ ] Rx/Dispense ingest API
- [ ] Tasks CRUD API
- [ ] patient_ref 產生/查詢 API
- [ ] Ops/Tasking UI

### Phase 5E

- [ ] 統一路徑 (canonical paths)
- [ ] Mode Switcher 元件
- [ ] Role-gating 邏輯
- [ ] Dashboard xIRS 入口

---

**文件版本**: 2.0
**建立日期**: 2025-12-22
**狀態**: 修正完成，待實作
