# xIRS 架構調整計畫

**基於**: ChatGPT 架構分析回饋
**日期**: 2025-12-22
**狀態**: 待確認

---

## 1. 調整總覽

| # | 項目 | 當前狀態 | 建議調整 | 優先級 |
|---|------|----------|----------|--------|
| A | 任務指派頁面 | 無 | 新增 Hub Ops/Tasking 模組 | P1 |
| B | 導覽模式切換 | 無統一入口 | 加入持久化 Mode Switcher | P1 |
| C | 資料歸屬 | 未實作後端 | Rx/Dispense → MIRS Hub DB | P0 |
| D | 任務領域分離 | 未定義 | LOGISTICS vs CLINICAL domain | P1 |
| E | 醫師角色定位 | 模糊 | 明確為 Prescriber (非 messenger) | P0 |

---

## 2. 詳細調整說明

### A. 任務指派頁面 (Ops/Tasking)

**ChatGPT 建議**: Hub/Admin 需要一級任務指派模組

**實作方案**:

```
┌─────────────────────────────────────────────────────────────────┐
│                   /admin/tasking (新建)                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  任務建立                                                        │
│  ├── 指派對象: Station | Runner | Prescriber | Pharmacist       │
│  ├── 任務領域: LOGISTICS | CLINICAL                             │
│  └── 輸出管道: Manifest/Report (物流) | Rx/Dispense (臨床)      │
│                                                                  │
│  任務佇列                                                        │
│  ├── LOGISTICS tasks (物資調度、Runner 派遣)                    │
│  └── CLINICAL tasks (處方配送、發藥確認)                        │
│                                                                  │
│  優先權規則                                                      │
│  └── CLINICAL > LOGISTICS (同一受指派者)                        │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**檔案新增**:
- `/frontend/admin/tasking.html` 或整合到 CIRS/MIRS 主頁

---

### B. 導覽模式切換

**ChatGPT 建議**: 模式端點應全域化，不綁定入口系統

**實作方案**:

```html
<!-- 加入 CIRS/MIRS Header -->
<nav class="mode-switcher">
  <div class="dropdown">
    <button>切換模式 ▼</button>
    <ul>
      <li><a href="/frontend/">📊 管理控台</a></li>
      <li><a href="/station/">📦 分站模式</a></li>
      <li><a href="/runner/">🏃 Runner 模式</a></li>
      <li><a href="/doctor/">👨‍⚕️ 醫師模式</a></li>
      <li><a href="/admin/tasking">📋 任務指派</a></li>
    </ul>
  </div>
</nav>
```

**規則**: Station 連結不應依賴使用者從 CIRS 或 MIRS 進入

---

### C. 資料歸屬調整

**ChatGPT 建議**: 臨床資料放 Lite CPOE 領域 (MIRS extension)

**調整後架構**:

```
┌─────────────────────────────────────────────────────────────────┐
│                        資料分層                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  xIRS Hub Database (xirs_hub.db)                                │
│  ├── [既有] person, inventory, message, zone, staff...          │
│  ├── [既有] stations, manifests, reports (xIRS Logistics)       │
│  └── [新增] prescribers, rx_orders, dispense_records (CPOE)     │
│                                                                  │
│  CIRS 本站視角                                                   │
│  ├── 直接操作 person, inventory, message                        │
│  ├── 透過 xIRS 同步 manifests ↔ reports                        │
│  └── 只保留 patient_ref 指向 Rx/Dispense (不存病歷)             │
│                                                                  │
│  PWA IndexedDB (離線快取)                                        │
│  ├── Doctor: credentials, issued_rx (本地紀錄)                  │
│  └── Pharmacy: prescriber_certs, dispense_queue (待處理)        │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**關鍵變更**:
1. `rx_orders` 和 `dispense_records` 放 Hub DB (MIRS)
2. CIRS `person` 表只加 `patient_ref` 欄位指向 Rx
3. 不在 CIRS 存病歷內容

---

### D. 任務領域分離

**ChatGPT 建議**: 單一命名空間 + 領域切分

**資料模型**:

```sql
-- 任務表 (新增)
CREATE TABLE tasks (
    id TEXT PRIMARY KEY,
    domain TEXT NOT NULL,           -- 'LOGISTICS' | 'CLINICAL'
    task_type TEXT NOT NULL,        -- 'DELIVERY' | 'DISPENSE' | 'PRESCRIPTION' | ...
    assignee_type TEXT NOT NULL,    -- 'STATION' | 'RUNNER' | 'PRESCRIBER' | 'PHARMACIST'
    assignee_id TEXT,
    priority INTEGER DEFAULT 0,     -- Higher = more urgent
    status TEXT DEFAULT 'PENDING',  -- 'PENDING' | 'ASSIGNED' | 'IN_PROGRESS' | 'COMPLETED'
    payload JSON,                   -- Task-specific data
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME
);

-- 優先權規則 (在應用層實現)
-- 1. CLINICAL domain priority += 100
-- 2. Same assignee: CLINICAL preempts LOGISTICS
-- 3. LOGISTICS can be reassigned without breaking clinical audit
```

---

### E. 醫師角色定位

**ChatGPT 指正**: 醫師不是 "blind messenger"，是 Prescriber

**角色對照表**:

| 角色 | 信任等級 | 能力 | 是否 Blind Carrier |
|------|----------|------|-------------------|
| Hub Admin | Full | 全權管理 | No |
| Prescriber (醫師) | High | 簽章處方 | **No** |
| Pharmacist | High | 驗證+調劑 | No |
| Station Lead | High | 物資管理 | No |
| Runner | **Zero** | 運送封包 | **Yes** |
| Patient | Zero | 攜帶 Rx QR | **Yes** |

**修正**:
- 醫師 (Prescriber) 有簽章金鑰，不是盲傳
- Patient/Runner 才是 Blind Carrier (只搬運不解讀)

---

## 3. 實作順序建議

### Phase 5C+ 調整後 Roadmap

```
Phase 5C: Pharmacy Station Extension
├── 擴展 /station/ 加入處方掃描
├── 整合 xirs-pharmacy-db.js
└── 實作調劑流程 UI

Phase 5D: Hub Integration (調整)
├── 新增 prescribers 表格 + API
├── 新增 rx_orders 表格 + API (Rx 同步)
├── 新增 dispense_records 表格 + API
└── 新增 tasks 表格 + API (任務指派)

Phase 5E: CIRS/MIRS UI Integration (新增)
├── 加入 Mode Switcher 導覽
├── Dashboard 加入 xIRS 快捷入口
└── 整合 Ops/Tasking 頁面

Phase 5F: Task Domain Implementation (新增)
├── LOGISTICS vs CLINICAL 任務分流
├── 優先權規則實作
└── 任務佇列 UI
```

---

## 4. 待確認決策

| # | 問題 | 選項 | 建議 |
|---|------|------|------|
| 1 | Ops/Tasking 獨立頁面或整合？ | A) /admin/tasking<br>B) CIRS Dashboard 內 | A) 獨立較清楚 |
| 2 | tasks 表格放哪？ | A) xirs_hub.db<br>B) 獨立 tasks.db | A) 同一 DB |
| 3 | patient_ref 格式？ | A) rx_id 直接引用<br>B) 匿名 token | B) token 較安全 |
| 4 | Mode Switcher 樣式？ | A) Header dropdown<br>B) Sidebar 選單 | A) Header |

---

## 5. 檔案變更清單

### 新增檔案

| 檔案 | 用途 |
|------|------|
| `/frontend/admin/tasking.html` | 任務指派頁面 |
| `/backend/routes/tasks.py` | 任務 API |
| `/backend/routes/prescriber.py` | 醫師憑證 API |

### 修改檔案

| 檔案 | 變更 |
|------|------|
| `/backend/database.py` | 新增 tasks, prescribers, rx_orders, dispense_records 表格 |
| `/frontend/index.html` | 加入 Mode Switcher |
| `/docs/xIRS_ARCHITECTURE_DISCUSSION_v1.md` | 更新角色定義 |

---

**文件版本**: 1.0
**建立日期**: 2025-12-22
**狀態**: 待確認後實作
