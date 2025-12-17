# CIRS Staff Management Specification v1.1

> 社區避難中心韌性系統 - 工作人員管理規格書
> **Version**: 1.1 (Enhanced Security & Field Ops)
> **Date**: 2025-12-17

## 1. 概述

### 1.1 目的

本規格書定義 CIRS 系統的工作人員管理機制，解決以下問題：

1. **角色系統不統一**：`person.role` 與 `staffing_rules.role_code` 未對齊
2. **登錄瓶頸**：大量志工湧入時，單一管理員無法快速登記
3. **權限濫用風險**：無法區分「自稱專業」與「已驗證專業」

### 1.2 v1.1 核心改進

| 改進項目 | 說明 |
|----------|------|
| **自助登錄 (Self-Service)** | QR Code 讓志工用自己手機填表，解決管理員輸入瓶頸 |
| **驗證分級 (Verification)** | 區分「自稱專業」與「已驗證專業」，防止權限濫用 |
| **加權韌性 (Weighted Resilience)** | 待命人員 (Standby) 納入韌性計算（權重 0.5） |
| **快速通關 (Fast Pass)** | 短效 Token 供回鍋志工快速報到 |
| **缺口預警 (Shortage Forecast)** | 預測即將發生的人力缺口 |

---

## 2. 角色與權限系統

### 2.1 三層角色架構

將「職能 (Function)」、「驗證狀態 (Verification)」與「系統權限 (Permission)」完全分離：

| 層級 | 欄位 | 用途 | 來源 |
|------|------|------|------|
| **職能層** | `staff_role` | 韌性計算、任務分配 | 用戶填寫 (自稱) |
| **驗證層** | `verification_status` | 確認證件/執照已查驗 | 管理員查驗 |
| **權限層** | `role` | 系統操作權限 (API Access) | 管理員核發 |

### 2.2 職能角色定義 (`staff_role`)

| staff_role | 中文名稱 | 顏色 | 圖示 | 說明 |
|------------|----------|------|------|------|
| `MEDIC` | 醫師 | #E53935 (Red) | 🩺 | 具醫師資格 |
| `NURSE` | 護理師 | #E91E63 (Pink) | 💉 | 具護理資格 |
| `VOLUNTEER` | 志工 | #4CAF50 (Green) | 👷 | 一般人力 |
| `ADMIN` | 行政人員 | #FFC107 (Amber) | 📋 | 登記/物資 |
| `SECURITY` | 保全人員 | #2196F3 (Blue) | 🛡️ | 秩序維護 |
| `COORDINATOR` | 指揮官 | #9C27B0 (Purple) | 👔 | 總指揮 |

### 2.3 驗證狀態 (`verification_status`)

| 狀態 | 說明 | 可分配工作 |
|------|------|------------|
| `UNVERIFIED` | 未查驗證件（預設） | 搬運、清潔等低風險工作 |
| `VERIFIED` | 已查驗身分證/醫事執照 | 醫療、安管、個資處理 |

### 2.4 權限升級規則 (Security Policy)

> ⚠️ **嚴格規定**：僅持有 `staff_role` **不代表** 擁有系統操作權限。

```
┌─────────────────────────────────────────────────────────────────┐
│  權限升級流程                                                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  新登錄人員 (任何 staff_role)                                    │
│       │                                                          │
│       ▼                                                          │
│  role = 'staff' (預設)  ←── 只能看基本資訊                       │
│       │                                                          │
│       │  管理員查驗證件                                          │
│       ▼                                                          │
│  verification_status = 'VERIFIED'                                │
│       │                                                          │
│       │  管理員手動升級權限                                      │
│       ▼                                                          │
│  role = 'medic' (可開醫療功能)                                   │
│  role = 'admin' (可改庫存/人員)                                  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. 工作人員狀態管理

### 3.1 狀態定義與韌性權重

| staff_status | 說明 | 韌性權重 | 顏色 |
|--------------|------|----------|------|
| `ACTIVE` | 在值中 (On Duty) | **1.0** | 🟢 Green |
| `STANDBY` | 待命 (On Call) | **0.5** | 🟡 Yellow |
| `OFF_DUTY` | 離班/休息 | **0.0** | ⚫ Gray |
| `ON_LEAVE` | 請假/撤離 | **0.0** | ⚪ White |

### 3.2 加權人力計算公式

```
EffectiveStaff = Σ(Count_Active × 1.0) + Σ(Count_Standby × 0.5)
```

### 3.3 缺口預警邏輯 (Impending Shortage)

當工作人員報到時，填寫 `expected_hours` (預計工時)。
系統計算 `shift_end = clock_in_time + expected_hours`。

**預警觸發條件**：
- `shift_end` 在未來 30 分鐘內
- 該員離班後會導致 `EffectiveStaff < RequiredStaff`
- → 發出 **"Impending Shortage" (即將缺人)** 警報

---

## 4. 登錄與報到流程

### 4.1 流程一：自助登錄 (Self-Service) ⭐推薦

適用於：大量志工湧入時，分散輸入壓力。

```
┌─────────────────────────────────────────────────────────────────┐
│  自助登錄流程                                                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. 掃描：志工掃描牆上的「加入我們」QR Code                      │
│           → 開啟 /staff/join 頁面                                │
│                                                                  │
│  2. 填寫：志工在自己手機填寫                                     │
│           • 姓名、電話                                           │
│           • 專長/職能 (staff_role)                               │
│           • 預計服務時數                                         │
│                                                                  │
│  3. 出示：送出後，手機顯示「待核准 QR Code」                     │
│           (qr_token, 30 分鐘有效)                                │
│                                                                  │
│  4. 核准：管理員掃描該 QR                                        │
│           → 檢查證件 (若為醫護)                                  │
│           → 點擊「核准並上工」                                   │
│           → 系統建立 person 資料，狀態 = ACTIVE                  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 流程二：快速回鍋 (Fast Pass)

適用於：昨天來過，今天又來的志工。

```
┌─────────────────────────────────────────────────────────────────┐
│  快速回鍋流程                                                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. 發證：志工昨日離班時，系統生成 Badge Token                   │
│           (12 小時有效，避免跨日班表問題)                        │
│                                                                  │
│  2. 回鍋：志工今日出示 Badge QR                                  │
│                                                                  │
│  3. 掃描：管理員掃描 → 系統自動 Clock-In                         │
│           • 不改變 staff_role 或權限                             │
│           • 僅更新狀態為 ACTIVE                                  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 4.3 流程三：管理員手動輸入

適用於：志工沒手機、或特殊狀況。

```
┌─────────────────────────────────────────────────────────────────┐
│  手動輸入流程                                                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. 管理員開啟「人員管理」→「新增工作人員」                      │
│  2. 填寫基本資料 + 選擇 staff_role                               │
│  3. (選填) 查驗證件 → 設定 verification_status                   │
│  4. 系統產生 ID，狀態設為 ACTIVE                                 │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 5. 資料庫 Schema

### 5.1 `person` 表擴充

```sql
-- 新增欄位
ALTER TABLE person ADD COLUMN staff_role TEXT;
  -- 'MEDIC', 'NURSE', 'VOLUNTEER', 'ADMIN', 'SECURITY', 'COORDINATOR'

ALTER TABLE person ADD COLUMN staff_status TEXT DEFAULT 'OFF_DUTY';
  -- 'ACTIVE', 'STANDBY', 'OFF_DUTY', 'ON_LEAVE'

ALTER TABLE person ADD COLUMN verification_status TEXT DEFAULT 'UNVERIFIED';
  -- 'UNVERIFIED', 'VERIFIED'

ALTER TABLE person ADD COLUMN verified_at DATETIME;
ALTER TABLE person ADD COLUMN verified_by TEXT;  -- Admin person_id

ALTER TABLE person ADD COLUMN shift_start DATETIME;
ALTER TABLE person ADD COLUMN shift_end DATETIME;  -- 用於缺口預測
ALTER TABLE person ADD COLUMN expected_hours REAL;

ALTER TABLE person ADD COLUMN certification TEXT;  -- JSON: 證照資訊
ALTER TABLE person ADD COLUMN emergency_contact TEXT;
ALTER TABLE person ADD COLUMN skills TEXT;  -- JSON: 技能標籤

-- 索引
CREATE INDEX IF NOT EXISTS idx_person_staff_role ON person(staff_role);
CREATE INDEX IF NOT EXISTS idx_person_staff_status ON person(staff_status);
CREATE INDEX IF NOT EXISTS idx_person_verification ON person(verification_status);
```

### 5.2 `staff_join_requests` 表（自助登錄）

```sql
CREATE TABLE IF NOT EXISTS staff_join_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    qr_token TEXT UNIQUE NOT NULL,

    -- 申請資料
    display_name TEXT NOT NULL,
    phone TEXT,
    claimed_role TEXT NOT NULL,  -- 自稱職能
    skills TEXT,                 -- JSON
    expected_hours REAL DEFAULT 4,
    notes TEXT,

    -- 狀態
    status TEXT DEFAULT 'PENDING',  -- 'PENDING', 'APPROVED', 'REJECTED', 'EXPIRED'

    -- 時間戳
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NOT NULL,  -- 30 分鐘後過期
    processed_at DATETIME,
    processed_by TEXT,  -- Admin person_id

    -- 核准後關聯
    person_id TEXT  -- 核准後建立的 person.id
);

CREATE INDEX IF NOT EXISTS idx_join_request_token ON staff_join_requests(qr_token);
CREATE INDEX IF NOT EXISTS idx_join_request_status ON staff_join_requests(status);
```

### 5.3 `staff_badge_tokens` 表（快速回鍋）

```sql
CREATE TABLE IF NOT EXISTS staff_badge_tokens (
    token_id TEXT PRIMARY KEY,
    person_id TEXT NOT NULL,

    issued_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NOT NULL,  -- 12 小時後過期
    is_revoked INTEGER DEFAULT 0,

    FOREIGN KEY (person_id) REFERENCES person(id)
);

CREATE INDEX IF NOT EXISTS idx_badge_token_person ON staff_badge_tokens(person_id);
CREATE INDEX IF NOT EXISTS idx_badge_token_expires ON staff_badge_tokens(expires_at);
```

### 5.4 `staff_role_config` 表（UI 設定）

```sql
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

-- 預設資料
INSERT OR IGNORE INTO staff_role_config VALUES
('MEDIC', '醫師', 'Doctor', '#E53935', 'medical_services', 1.0, 1, 1),
('NURSE', '護理師', 'Nurse', '#E91E63', 'vaccines', 1.0, 1, 2),
('VOLUNTEER', '志工', 'Volunteer', '#4CAF50', 'volunteer_activism', 1.0, 0, 3),
('ADMIN', '行政人員', 'Admin', '#FFC107', 'assignment_ind', 1.0, 0, 4),
('SECURITY', '保全人員', 'Security', '#2196F3', 'security', 1.0, 0, 5),
('COORDINATOR', '指揮官', 'Coordinator', '#9C27B0', 'campaign', 1.0, 1, 6);
```

### 5.5 資料遷移腳本

```sql
-- 遷移現有資料
UPDATE person SET staff_role = 'MEDIC' WHERE role = 'medic' AND staff_role IS NULL;
UPDATE person SET staff_role = 'ADMIN' WHERE role = 'admin' AND staff_role IS NULL;
UPDATE person SET staff_role = 'VOLUNTEER' WHERE role = 'staff' AND staff_role IS NULL;

-- 設定已報到的工作人員為 ACTIVE
UPDATE person
SET staff_status = 'ACTIVE'
WHERE staff_role IS NOT NULL
  AND checked_in_at IS NOT NULL
  AND staff_status IS NULL;

-- 設定未報到的工作人員為 OFF_DUTY
UPDATE person
SET staff_status = 'OFF_DUTY'
WHERE staff_role IS NOT NULL
  AND checked_in_at IS NULL
  AND staff_status IS NULL;
```

---

## 6. API 設計

### 6.1 自助登錄 API

| Method | Endpoint | 說明 |
|--------|----------|------|
| POST | `/api/staff/join` | 提交自助登錄申請 |
| GET | `/api/staff/join/{token}` | 取得申請詳情 (管理員用) |
| POST | `/api/staff/join/{token}/approve` | 核准申請 |
| POST | `/api/staff/join/{token}/reject` | 拒絕申請 |

#### POST `/api/staff/join`

```python
# Request
{
    "display_name": "王大明",
    "phone": "0912345678",
    "claimed_role": "VOLUNTEER",
    "skills": ["搬運", "烹飪"],
    "expected_hours": 4,
    "notes": "有急救證照"
}

# Response
{
    "qr_token": "JR-abc123def456",
    "expires_at": "2025-12-17T10:30:00",
    "qr_url": "/staff/join/pending?token=JR-abc123def456",
    "message": "請出示此 QR Code 給管理員掃描"
}
```

#### POST `/api/staff/join/{token}/approve`

```python
# Request
{
    "verified": true,  # 是否已查驗證件
    "override_role": null,  # 可覆蓋 claimed_role
    "notes": "已查驗護理師執照"
}

# Response
{
    "success": true,
    "person_id": "P0042",
    "display_name": "王大明",
    "staff_role": "VOLUNTEER",
    "staff_status": "ACTIVE",
    "verification_status": "VERIFIED"
}
```

### 6.2 工作人員管理 API

| Method | Endpoint | 說明 |
|--------|----------|------|
| GET | `/api/staff` | 列出所有工作人員 |
| POST | `/api/staff` | 新增工作人員 (管理員手動) |
| GET | `/api/staff/{id}` | 取得工作人員詳情 |
| PUT | `/api/staff/{id}` | 更新工作人員資料 |
| POST | `/api/staff/{id}/verify` | 驗證工作人員 |

### 6.3 報到/離班 API

| Method | Endpoint | 說明 |
|--------|----------|------|
| POST | `/api/staff/{id}/clock-in` | 報到上班 |
| POST | `/api/staff/{id}/clock-out` | 離班下班 |
| POST | `/api/staff/fast-pass` | Fast Pass 快速報到 |

#### POST `/api/staff/{id}/clock-in`

```python
# Request
{
    "expected_hours": 4,
    "notes": "下午班"
}

# Response
{
    "success": true,
    "staff_status": "ACTIVE",
    "shift_start": "2025-12-17T14:00:00",
    "shift_end": "2025-12-17T18:00:00"
}
```

#### POST `/api/staff/{id}/clock-out`

```python
# Response
{
    "success": true,
    "staff_status": "OFF_DUTY",
    "badge_token": "BT-xyz789",  # Fast Pass Token
    "badge_expires": "2025-12-18T02:00:00",  # 12 小時有效
    "message": "辛苦了！明天可使用快速通關"
}
```

### 6.4 人力狀態 API

| Method | Endpoint | 說明 |
|--------|----------|------|
| GET | `/api/staff/summary` | 人力摘要 |
| GET | `/api/staff/on-duty` | 在值人員列表 |
| GET | `/api/staff/shortages` | 人力缺口分析 |
| GET | `/api/staff/forecast` | 未來 2 小時人力預測 |

#### GET `/api/staff/summary`

```json
{
    "total_registered": 25,
    "active_count": 12,
    "standby_count": 5,
    "effective_staff": 14.5,

    "by_role": {
        "MEDIC": {"active": 1, "standby": 1, "total": 3},
        "NURSE": {"active": 2, "standby": 0, "total": 4},
        "VOLUNTEER": {"active": 6, "standby": 3, "total": 12},
        "ADMIN": {"active": 2, "standby": 1, "total": 4},
        "SECURITY": {"active": 1, "standby": 0, "total": 2}
    },

    "shortages": [
        {"role": "MEDIC", "required": 2, "effective": 1.5, "gap": 0.5},
        {"role": "ADMIN", "required": 3, "effective": 2.5, "gap": 0.5}
    ],

    "impending_shortages": [
        {
            "role": "VOLUNTEER",
            "person_name": "張志工",
            "shift_end": "2025-12-17T15:30:00",
            "minutes_remaining": 25,
            "will_cause_gap": true
        }
    ],

    "coverage_score": 85.0
}
```

---

## 7. 韌性引擎整合

### 7.1 修改 `_calculate_staff()`

```python
def _calculate_staff(self) -> dict:
    """計算人力韌性 - 加權計算 (Active=1.0, Standby=0.5)"""

    # 取得人員統計 (加權)
    cursor = self.conn.execute("""
        SELECT
            staff_role,
            SUM(CASE WHEN staff_status = 'ACTIVE' THEN 1.0 ELSE 0 END) as active_count,
            SUM(CASE WHEN staff_status = 'STANDBY' THEN 0.5 ELSE 0 END) as standby_weight
        FROM person
        WHERE staff_role IS NOT NULL
          AND staff_status IN ('ACTIVE', 'STANDBY')
        GROUP BY staff_role
    """)

    staff_data = {}
    for row in cursor.fetchall():
        role = row['staff_role']
        effective = row['active_count'] + row['standby_weight']
        staff_data[role] = effective

    # 合併醫護類別
    medical_effective = staff_data.get('MEDIC', 0) + staff_data.get('NURSE', 0)

    # 取得需求人數
    required = self._get_required_staff()

    # 計算各類別覆蓋率
    coverage = {}
    for role, req in required.items():
        if role == 'MEDIC':
            actual = medical_effective
        else:
            actual = staff_data.get(role, 0)
        coverage[role] = min(100, (actual / req * 100)) if req > 0 else 100

    # 最低覆蓋率為分數
    min_coverage = min(coverage.values()) if coverage else 0

    # 檢查即將發生的缺口
    impending = self._check_impending_shortages()

    return {
        'category': 'STAFF',
        'score': round(min_coverage, 1),
        'status': self._score_to_status(min_coverage),
        'effective_staff': staff_data,
        'required': required,
        'coverage': coverage,
        'impending_shortages': impending,
        'hours_remaining': self.target_hours if min_coverage >= 100 else 0
    }

def _check_impending_shortages(self) -> list:
    """檢查未來 30 分鐘內即將發生的人力缺口"""
    cursor = self.conn.execute("""
        SELECT p.id, p.display_name, p.staff_role, p.shift_end
        FROM person p
        WHERE p.staff_status = 'ACTIVE'
          AND p.shift_end IS NOT NULL
          AND p.shift_end <= datetime('now', '+30 minutes')
          AND p.shift_end > datetime('now')
        ORDER BY p.shift_end
    """)

    impending = []
    for row in cursor.fetchall():
        impending.append({
            'person_id': row['id'],
            'person_name': row['display_name'],
            'role': row['staff_role'],
            'shift_end': row['shift_end']
        })

    return impending
```

---

## 8. UI 設計

### 8.1 自助登錄頁面 (`/staff/join`)

```
┌─────────────────────────────────────────────────────┐
│  👋 加入救災團隊                                    │
├─────────────────────────────────────────────────────┤
│                                                     │
│  感謝您願意幫忙！請填寫以下資料：                   │
│                                                     │
│  姓名 *                                             │
│  ┌─────────────────────────────────────────────┐   │
│  │                                              │   │
│  └─────────────────────────────────────────────┘   │
│                                                     │
│  聯絡電話 *                                         │
│  ┌─────────────────────────────────────────────┐   │
│  │                                              │   │
│  └─────────────────────────────────────────────┘   │
│                                                     │
│  我可以幫忙 *                                       │
│  ┌─────────────────────────────────────────────┐   │
│  │ ▼ 請選擇                                    │   │
│  │   👷 一般志工 (搬運、清潔、發放)            │   │
│  │   🩺 醫療人員 (需查驗執照)                  │   │
│  │   📋 行政支援 (登記、資料整理)              │   │
│  │   🛡️ 秩序維護 (引導、安全)                  │   │
│  └─────────────────────────────────────────────┘   │
│                                                     │
│  預計可服務時間                                     │
│  ┌───┐                                             │
│  │ 4 │ 小時                                        │
│  └───┘                                             │
│                                                     │
│  其他專長 (選填)                                    │
│  ┌─────────────────────────────────────────────┐   │
│  │ 例：有急救證照、會開車...                    │   │
│  └─────────────────────────────────────────────┘   │
│                                                     │
│            [送出申請]                               │
│                                                     │
└─────────────────────────────────────────────────────┘
```

### 8.2 待核准 QR 頁面

```
┌─────────────────────────────────────────────────────┐
│  ✅ 申請已送出                                      │
├─────────────────────────────────────────────────────┤
│                                                     │
│         ┌─────────────────────┐                    │
│         │                     │                    │
│         │    [QR CODE]        │                    │
│         │                     │                    │
│         └─────────────────────┘                    │
│                                                     │
│  請將此畫面出示給工作人員掃描                       │
│                                                     │
│  王大明                                             │
│  志工 · 預計服務 4 小時                             │
│                                                     │
│  ⏱️ 此 QR Code 將於 28:45 後失效                   │
│                                                     │
└─────────────────────────────────────────────────────┘
```

### 8.3 管理員核准介面

```
┌─────────────────────────────────────────────────────┐
│  📋 志工申請                              [待處理 3] │
├─────────────────────────────────────────────────────┤
│                                                     │
│  ┌─────────────────────────────────────────────┐   │
│  │ 王大明                             ⏱️ 25:30  │   │
│  │ 👷 志工 · 4 小時                             │   │
│  │ 📱 0912-345-678                              │   │
│  │ 備註：有急救證照                             │   │
│  │                                              │   │
│  │ ☐ 已查驗證件                                │   │
│  │                                              │   │
│  │     [拒絕]  [核准並上工]                     │   │
│  └─────────────────────────────────────────────┘   │
│                                                     │
│  ┌─────────────────────────────────────────────┐   │
│  │ 李護理                             ⏱️ 18:20  │   │
│  │ 🩺 醫療人員 · 6 小時                         │   │
│  │ 📱 0923-456-789                              │   │
│  │                                              │   │
│  │ ☑ 已查驗證件 (護理師執照)                   │   │
│  │                                              │   │
│  │     [拒絕]  [核准並上工]                     │   │
│  └─────────────────────────────────────────────┘   │
│                                                     │
└─────────────────────────────────────────────────────┘
```

---

## 9. 實作階段

### Phase 1: 資料層 (Day 1)
- [ ] 執行 schema migration
- [ ] 建立 `staff_join_requests`, `staff_badge_tokens`, `staff_role_config` 表
- [ ] 遷移現有 person 資料

### Phase 2: API 實作 (Day 2-3)
- [ ] 建立 `routes/staff.py`
- [ ] 實作自助登錄 API (`/api/staff/join/*`)
- [ ] 實作 clock-in/clock-out
- [ ] 實作 Fast Pass
- [ ] 實作人力摘要 API

### Phase 3: 韌性引擎整合 (Day 3)
- [ ] 修改 `_calculate_staff()` 支援加權計算
- [ ] 實作 `_check_impending_shortages()`
- [ ] 更新建議邏輯

### Phase 4: PWA UI (Day 4-5)
- [ ] 建立 `/staff/join` 自助登錄頁
- [ ] 建立待核准 QR 頁面
- [ ] 建立管理員核准介面
- [ ] 建立人員管理分頁

### Phase 5: 測試與部署 (Day 6)
- [ ] API 測試
- [ ] 流程測試 (自助登錄 → 核准 → 報到 → 離班)
- [ ] 部署到 Vercel

---

## 附錄 A: 角色權限對照

| staff_role | 預設 role | 升級條件 | 升級後 role |
|------------|-----------|----------|-------------|
| COORDINATOR | staff | VERIFIED | admin |
| ADMIN | staff | VERIFIED | admin |
| MEDIC | staff | VERIFIED | medic |
| NURSE | staff | VERIFIED | medic |
| VOLUNTEER | staff | - | staff |
| SECURITY | staff | - | staff |

---

## 附錄 B: Token 格式

| Token 類型 | 格式 | 有效期 |
|------------|------|--------|
| Join Request | `JR-{uuid4[:12]}` | 30 分鐘 |
| Badge Token | `BT-{uuid4[:12]}` | 12 小時 |

---

*文件版本: v1.1*
*建立日期: 2025-12-17*
*作者: Claude Code + ChatGPT + Gemini + Grok*
