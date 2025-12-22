# xIRS Integration Specification v1.1
## CIRS ↔ MIRS Data Interoperability

**Status**: Reviewed Draft
**Date**: 2024-12-23
**Contributors**: Claude, Gemini, ChatGPT
**Revision**: v1.1 - Incorporated privacy/identity boundary fixes

---

## 1. Executive Summary

This specification defines how CIRS (Community Inventory Resilience System) and MIRS (Medical Inventory Resilience System) share data, focusing on:
- Medication inventory sync (MIRS → CIRS)
- Procedure records (MIRS domain, accessible via Doctor PWA)
- Prescription flow across systems

### Key Principle
> **MIRS is the source of truth for all medical data.**
> CIRS caches medication data for offline resilience.

---

## 2. System Architecture

### 2.1 High-Level Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        MIRS (醫療系統)                           │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐             │
│  │ 藥品主檔     │  │ 庫存管理     │  │ 處置模組     │             │
│  │ Medication  │  │ Inventory   │  │ Procedures  │             │
│  │ Master      │  │ Management  │  │ Module      │             │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘             │
│         │                │                │                     │
│         └────────────────┼────────────────┘                     │
│                          │                                      │
│                    MIRS API                                     │
│                    /api/mirs/*                                  │
└──────────────────────────┼──────────────────────────────────────┘
                           │
                    ┌──────▼──────┐
                    │   Cache     │
                    │   Layer     │
                    └──────┬──────┘
                           │
┌──────────────────────────┼──────────────────────────────────────┐
│                          │                                      │
│                    CIRS API                                     │
│                    /api/*                                       │
│                          │                                      │
│  ┌─────────────┐  ┌──────▼──────┐  ┌─────────────┐             │
│  │ 人員管理     │  │ 藥品快取     │  │ 物資管理     │             │
│  │ Person      │  │ Med Cache   │  │ Inventory   │             │
│  │ Management  │  │ (from MIRS) │  │ (非藥品)     │             │
│  └─────────────┘  └─────────────┘  └─────────────┘             │
│                                                                 │
│                        CIRS (避難所系統)                         │
└─────────────────────────────────────────────────────────────────┘
                           │
           ┌───────────────┼───────────────┐
           │               │               │
    ┌──────▼──────┐ ┌──────▼──────┐ ┌──────▼──────┐
    │ Doctor PWA  │ │ Pharmacy   │ │ Admin       │
    │             │ │ PWA        │ │ Console     │
    └─────────────┘ └─────────────┘ └─────────────┘
```

### 2.2 Data Ownership

| Data Type | Owner | Consumers | Sync Method |
|-----------|-------|-----------|-------------|
| 藥品主檔 (Medication Master) | MIRS | CIRS, Doctor PWA | Cache + TTL |
| 藥品庫存 (Med Inventory) | MIRS | CIRS Pharmacy | Cache + TTL |
| 處置記錄 (Procedures) | MIRS | Doctor PWA | Direct API |
| 處方 (Prescriptions) | MIRS | Doctor PWA, Pharmacy | Event-based |
| 人員/掛號 (Registration) | CIRS | Doctor PWA | Direct API |
| 非藥品物資 (Non-med Inventory) | CIRS | Admin | Local |

---

## 3. Medication Data Sync

### 3.0 Core Principle: Master-Slave Cache Model

> **MIRS is the single source of truth for all medication data.**
> **CIRS caches medication data for offline resilience but NEVER creates or modifies medications.**

```
┌────────────────────────────────────────────────────────────────┐
│                     Data Flow Direction                         │
│                                                                 │
│   MIRS (Master)                                                 │
│   ├── Medication Master File                                    │
│   ├── Stock Management                                          │
│   └── Formulary Updates                                         │
│            │                                                    │
│            │  EXPORT (push/pull)                                │
│            ▼                                                    │
│   CIRS (Slave Cache)                                            │
│   ├── medication_cache table                                    │
│   ├── TTL-based staleness                                       │
│   └── Read-only consumers                                       │
│            │                                                    │
│            │  STATUS QUERIES (read-only)                        │
│            ▼                                                    │
│   PWAs (Consumers)                                              │
│   ├── Doctor PWA (view stock, prescribe)                        │
│   ├── Pharmacy PWA (view stock, dispense)                       │
│   └── Admin Console (view reports)                              │
│                                                                 │
└────────────────────────────────────────────────────────────────┘

⚠️  CIRS Admin Console should NOT have "新增藥品" button.
    Medications are IMPORTED from MIRS, never created locally.
```

### 3.1 Cache Strategy

```
┌─────────────────────────────────────────────────────────┐
│                    Cache Architecture                    │
├─────────────────────────────────────────────────────────┤
│                                                         │
│   MIRS Database                                         │
│   └── medications table (source of truth)               │
│            │                                            │
│            │ (1) Periodic sync or on-demand             │
│            ▼                                            │
│   CIRS Cache (in SQLite)                                │
│   └── medication_cache table                            │
│       ├── code (PK)                                     │
│       ├── name                                          │
│       ├── category                                      │
│       ├── form                                          │
│       ├── is_controlled                                 │
│       ├── stock_status (OK/LOW/OUT)                     │
│       ├── cached_at (timestamp)                         │
│       └── ttl_seconds (default: 1800)                   │
│            │                                            │
│            │ (2) API response with staleness indicator  │
│            ▼                                            │
│   Doctor PWA (IndexedDB)                                │
│   └── medications store                                 │
│       └── includes as_of, ttl_seconds for UI warning    │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### 3.2 Sync Modes

#### Mode 1: Scheduled Sync (Background)
```python
# CIRS backend cron job (every 30 min)
async def sync_medications_from_mirs():
    try:
        response = await mirs_client.get("/api/medications/list")
        for med in response["medications"]:
            upsert_medication_cache(med)
        log.info(f"Synced {len(response['medications'])} medications")
    except MIRSConnectionError:
        log.warning("MIRS unreachable, using cached data")
```

#### Mode 2: On-Demand Sync (User Action)
```javascript
// Doctor PWA - when user clicks "更新"
async function refreshStockStatus() {
    const response = await fetch('/api/medications/status');
    const data = await response.json();

    // Check if data is stale
    const now = Math.floor(Date.now() / 1000);
    const isStale = (now - data.as_of) > data.ttl_seconds;

    if (isStale) {
        showWarning("庫存資訊已過期，請連線更新");
    }
}
```

#### Mode 3: Offline Fallback
```python
# CIRS API endpoint
@router.get("/api/medications/status")
async def get_medication_status():
    # Try to get fresh data from MIRS
    try:
        fresh_data = await mirs_client.get_stock_status()
        update_cache(fresh_data)
        return fresh_data
    except:
        # Fallback to cache
        cached = get_cached_medications()
        return {
            "as_of": cached.cached_at,
            "ttl_seconds": 1800,
            "is_cached": True,
            "medications": cached.items
        }
```

### 3.3 API Contract: MIRS → CIRS

#### Request
```http
GET /api/mirs/medications/stock-status
Authorization: Bearer <service_token>
X-Station-ID: CIRS-HUB-001
```

#### Response
```json
{
    "as_of": 1703318400,
    "ttl_seconds": 1800,
    "station_id": "PHARM-01",
    "medications": [
        {
            "code": "ACETAMINOPHEN_500_TAB",
            "name": "Acetaminophen 500mg 錠",
            "stock_status": "OK",
            "category": "解熱鎮痛",
            "is_controlled": false
        },
        {
            "code": "MORPHINE_10_TAB",
            "name": "Morphine 10mg 錠",
            "stock_status": "LOW",
            "category": "止痛",
            "is_controlled": true
        }
    ]
}
```

### 3.4 MIRS Export Packet Schema

For bulk import/sync operations, MIRS provides an export packet with complete medication data:

```json
{
    "$schema": "MIRS_EXPORT_PACKET_v1.0",
    "export_info": {
        "exported_at": "2024-12-23T10:00:00Z",
        "exported_by": "MIRS-HUB-001",
        "export_type": "FULL",
        "record_count": 150,
        "signature": "<ed25519_signature_of_payload>"
    },
    "medications": [
        {
            "code": "ACETAMINOPHEN_500_TAB",
            "name": "Acetaminophen 500mg 錠",
            "name_en": "Acetaminophen 500mg Tablet",
            "category": "解熱鎮痛",
            "form": "TAB",
            "unit": "TAB",
            "is_controlled": false,
            "atc_code": "N02BE01",
            "dosage_forms": ["PO"],
            "common_dosages": ["500mg TID", "500mg PRN"],
            "max_daily_dose": "4000mg",
            "stock": {
                "quantity": 500,
                "min_quantity": 100,
                "status": "OK"
            }
        }
    ],
    "categories": [
        { "code": "ANTIPYRETIC", "label": "解熱鎮痛", "order": 1 },
        { "code": "ANTIBIOTIC", "label": "抗生素", "order": 2 },
        { "code": "GI", "label": "腸胃", "order": 3 },
        { "code": "RESPIRATORY", "label": "呼吸道", "order": 4 },
        { "code": "CONTROLLED", "label": "管制藥品", "order": 99 }
    ]
}
```

#### Import Flow

```
┌──────────────────────────────────────────────────────────────┐
│  CIRS Admin Console - 藥品匯入                                │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  📥 從 MIRS 匯入藥品清單                                 │ │
│  │                                                        │ │
│  │  ○ 線上同步 (需連接 MIRS)                               │ │
│  │  ● 匯入檔案 (離線模式)                                   │ │
│  │                                                        │ │
│  │  ┌──────────────────────────────────────────────────┐ │ │
│  │  │  選擇匯出檔案 (.json)                              │ │ │
│  │  └──────────────────────────────────────────────────┘ │ │
│  │                                                        │ │
│  │  ⚠️ 匯入將覆蓋現有快取資料                              │ │
│  │                                                        │ │
│  │  [取消]                              [確認匯入]        │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

---

## 4. Procedure Module

### 4.1 Overview

處置記錄 (Procedure Records) 是簡化版的手術/處置記錄，用於：
- 災難現場的緊急處置
- 避難所內的簡易醫療處置
- 不需追蹤耗材庫存

### 4.2 Data Model

> **Privacy Principle**: 病患姓名 (Class-A PII) 只存在 CIRS，不進入 MIRS/Clinical 系統。
> 使用 `patient_ref` (遮蔽 ID) + `display_label` (非識別資訊) 替代。

```sql
-- MIRS/Clinical Database (或 Doctor PWA IndexedDB)
CREATE TABLE procedure_record (
    id TEXT PRIMARY KEY,                    -- PROC-YYYYMMDD-XXX

    -- Patient Reference (NOT name - privacy boundary)
    patient_ref TEXT NOT NULL,              -- CIRS reg_id or masked reference
    display_label TEXT,                     -- Non-identifying: "TRIAGE-GREEN / M~40"
    encounter_id TEXT,                      -- Links Rx + Procedure for same visit

    -- Procedure Details
    procedure_type TEXT NOT NULL,           -- Enum code: WOUND_SUTURE, DEBRIDEMENT...
    procedure_type_other TEXT,              -- Free text if type = OTHER
    anesthesia_type TEXT DEFAULT 'NONE',    -- NONE, LOCAL, TOPICAL, SEDATION

    -- Surgeon (auto-filled from logged-in doctor)
    surgeon_id TEXT NOT NULL,               -- Prescriber ID
    surgeon_name TEXT NOT NULL,             -- For display/audit

    -- Timing
    start_time TEXT,                        -- ISO8601
    end_time TEXT,
    duration_minutes INTEGER,

    -- Clinical Notes
    indication TEXT,                        -- 處置原因/適應症
    procedure_note TEXT,                    -- 處置內容/步驟
    findings TEXT,                          -- 術中發現
    complications TEXT,                     -- 併發症

    -- Metadata
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    created_by TEXT NOT NULL,
    signature TEXT NOT NULL,                -- Ed25519 signature (mandatory)

    -- Soft link to related prescription (optional)
    related_rx_id TEXT
);

-- Index for encounter-based queries
CREATE INDEX idx_procedure_encounter ON procedure_record(encounter_id);
CREATE INDEX idx_procedure_patient ON procedure_record(patient_ref);
```

### 4.2.1 Privacy Boundary Design

```
┌─────────────────────────────────────────────────────────────┐
│  CIRS (Identity Boundary)                                   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ person table                                         │   │
│  │ ├── person_id: "P-001"                              │   │
│  │ ├── name: "王大明" ← Class-A PII, stays here        │   │
│  │ ├── id_number: "A123..." ← Never leaves CIRS        │   │
│  │ └── ...                                              │   │
│  └─────────────────────────────────────────────────────┘   │
│                          │                                  │
│                          ▼ (generates)                      │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ registration table                                   │   │
│  │ ├── reg_id: "REG-20241223-001" ← Encounter Key      │   │
│  │ ├── patient_ref: "P-001-A7B3" ← Masked reference    │   │
│  │ └── display_label: "TRIAGE-GREEN / M~40"            │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼ (only ref + label cross boundary)
┌─────────────────────────────────────────────────────────────┐
│  MIRS / Doctor PWA (Clinical Boundary)                      │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ procedure_record                                     │   │
│  │ ├── patient_ref: "P-001-A7B3"                       │   │
│  │ ├── display_label: "TRIAGE-GREEN / M~40"            │   │
│  │ └── (NO patient_name, NO id_number)                 │   │
│  └─────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ prescription (rx_order)                              │   │
│  │ ├── patient_ref: "P-001-A7B3" (same key)            │   │
│  │ └── encounter_id: "REG-20241223-001"                │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 4.3 Procedure Types (處置類型)

| Code | Label | Description |
|------|-------|-------------|
| WOUND_SUTURE | 傷口縫合 | Wound closure with sutures |
| WOUND_DEBRIDEMENT | 清創術 | Wound debridement |
| FRACTURE_SPLINT | 骨折固定 | Splinting/immobilization |
| BURN_DRESSING | 燒燙傷換藥 | Burn wound dressing |
| FOREIGN_BODY | 異物移除 | Foreign body removal |
| INCISION_DRAINAGE | 切開引流 | I&D for abscess |
| IV_ACCESS | 靜脈注射 | IV line placement |
| CATHETER | 導尿管置入 | Urinary catheterization |
| NG_TUBE | 鼻胃管置入 | NG tube insertion |
| CPR | 心肺復甦 | Cardiopulmonary resuscitation |
| OTHER | 其他 | Other procedures |

### 4.4 Anesthesia Types (麻醉方式)

| Code | Label |
|------|-------|
| NONE | 無麻醉 |
| LOCAL | 局部麻醉 |
| TOPICAL | 表面麻醉 |
| SEDATION | 鎮靜 |
| REGIONAL | 區域麻醉 |

### 4.5 Doctor PWA Integration

#### UI: 處置 Tab (新增至 Bottom Nav)

```
┌─────────────────────────────────────────┐
│  處置記錄                          [+]  │
├─────────────────────────────────────────┤
│                                         │
│  今日處置 (2)                           │
│  ┌─────────────────────────────────┐   │
│  │ 🩹 王○明 - 傷口縫合              │   │
│  │    10:30 | 李醫師 | 15 分鐘      │   │
│  └─────────────────────────────────┘   │
│  ┌─────────────────────────────────┐   │
│  │ 🦴 陳○華 - 骨折固定              │   │
│  │    11:45 | 李醫師 | 25 分鐘      │   │
│  └─────────────────────────────────┘   │
│                                         │
└─────────────────────────────────────────┘

Bottom Nav:
[等候室] [病患] [📷] [處置] [藥品]
```

#### New Procedure Form

```
┌─────────────────────────────────────────┐
│  新增處置記錄                      [×]  │
├─────────────────────────────────────────┤
│                                         │
│  病患 *                                 │
│  ┌─────────────────────────────────┐   │
│  │ 選擇病患 (從我的病患/今日看診)    ▼│   │
│  └─────────────────────────────────┘   │
│                                         │
│  處置類型 *                             │
│  ┌─────────────────────────────────┐   │
│  │ 傷口縫合                        ▼│   │
│  └─────────────────────────────────┘   │
│                                         │
│  麻醉方式                               │
│  ○ 無  ● 局部麻醉  ○ 表面麻醉  ○ 鎮靜  │
│                                         │
│  處置時長 (分鐘)                        │
│  ┌─────────────────────────────────┐   │
│  │ 15                               │   │
│  └─────────────────────────────────┘   │
│                                         │
│  處置備註                               │
│  ┌─────────────────────────────────┐   │
│  │ 右手臂撕裂傷 5cm，縫合 8 針      │   │
│  │                                  │   │
│  └─────────────────────────────────┘   │
│                                         │
│  ┌─────────────────────────────────┐   │
│  │         簽章並儲存               │   │
│  └─────────────────────────────────┘   │
│                                         │
└─────────────────────────────────────────┘
```

### 4.6 API Endpoints

#### Create Procedure (Doctor PWA → MIRS)
```http
POST /api/mirs/procedures
Authorization: Bearer <doctor_token>
Content-Type: application/json

{
    "patient_ref": "P-001-A7B3",
    "display_label": "TRIAGE-GREEN / M~40",
    "encounter_id": "REG-20241223-001",
    "procedure_type": "WOUND_SUTURE",
    "anesthesia_type": "LOCAL",
    "surgeon_id": "DOC-001",
    "surgeon_name": "李醫師",
    "duration_minutes": 15,
    "procedure_note": "右手臂撕裂傷 5cm，縫合 8 針",
    "signature": "<ed25519_signature>"
}
```

> **Note**: `patient_ref` is a masked reference, NOT the patient's real name.
> The `display_label` contains non-identifying info (triage status, approximate age/gender).
> Full patient identity remains in CIRS only.

#### List Today's Procedures
```http
GET /api/mirs/procedures/today?surgeon_id=DOC-001
Authorization: Bearer <doctor_token>
```

---

## 5. Implementation Plan

### Phase 1: Foundation (Week 1-2)
1. Define MIRS ↔ CIRS service authentication (JWT/API Key)
2. Create `medication_cache` table in CIRS
3. Implement cache sync endpoint
4. Add staleness indicator to Doctor PWA

### Phase 2: Procedure Module (Week 3-4)
1. Create `procedure_record` table in MIRS
2. Add 處置 tab to Doctor PWA
3. Implement procedure form and list
4. Add Ed25519 signature for procedures

### Phase 3: Integration Testing (Week 5)
1. Test offline scenarios
2. Test cache invalidation
3. Test cross-system patient lookup
4. End-to-end prescription + procedure flow

---

## 6. Design Decisions (Resolved)

Based on collaborative review (Claude, Gemini, ChatGPT - 2024-12-23):

| # | Question | Decision | Rationale |
|---|----------|----------|-----------|
| 1 | **Authentication** | Service-level JWT | CIRS→MIRS uses service token; per-doctor JWT for Doctor PWA actions |
| 2 | **Patient Identity** | CIRS `reg_id` as Encounter Key | Option A selected. `patient_ref` is masked, `display_label` is non-identifying |
| 3 | **Offline Procedures** | Yes, store in IndexedDB | Sync to MIRS when online; Ed25519 signature ensures tamper-evidence |
| 4 | **Signature Verification** | Trust with Verify | CIRS should verify MIRS signatures for critical data (export packets) |
| 5 | **Controlled Substances** | Separate audit trail | 管制藥品 require additional logging and dual-signature (future) |

### 6.1 Remaining Open Questions

1. **Cache Invalidation**: Push notification from MIRS vs polling interval?
   - Current: 30-min polling (simple)
   - Future: WebSocket push for real-time updates

2. **Conflict Resolution**: If Doctor PWA and MIRS both have procedures for same encounter?
   - Proposed: Last-write-wins with timestamp, but preserve both in audit log

3. **Multi-Hub Sync**: How to handle disaster scenarios with multiple CIRS hubs?
   - Future scope: Federation protocol

---

## 7. Appendix

### A. Glossary

| Term | Definition |
|------|------------|
| CIRS | Community Inventory Resilience System (避難所系統) |
| MIRS | Medical Inventory Resilience System (醫療系統) |
| Hub | Central server (中央伺服器) |
| Sub-Hub | Satellite station (衛星站) |
| TTL | Time-To-Live (快取有效期) |
| Stale | Data older than TTL (過期資料) |

### B. Related Documents

- `xIRS_REGISTRATION_SPEC_v1.2.md` - Patient registration flow
- `xIRS_RX_SPEC_v1.1.md` - Prescription QR format
- `TEST_MEDICATION_FLOW.md` - Testing guide

---

*This specification is open for discussion. Please provide feedback via GitHub Issues or direct discussion.*
