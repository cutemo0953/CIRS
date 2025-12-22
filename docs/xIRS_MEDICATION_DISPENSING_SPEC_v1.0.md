# xIRS 藥品發放系統規格 v1.0

**Version**: 1.0
**Date**: 2025-12-22
**Status**: Draft
**Author**: Claude

---

## 1. 系統架構總覽

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        xIRS MEDICATION DISPENSING ARCHITECTURE               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────┐                                                            │
│  │    MIRS     │  ← 醫院藥品主檔 (Master Database)                           │
│  │   (醫院)    │    - medicines table                                        │
│  └──────┬──────┘    - current_stock, is_controlled_drug                     │
│         │                                                                    │
│         │ ① Pre-deployment Sync (災前準備)                                   │
│         │    - Export medications JSON                                       │
│         │    - Upload to CIRS Hub                                           │
│         ↓                                                                    │
│  ┌─────────────┐                                                            │
│  │  CIRS Hub   │  ← 災難現場藥品快取 (Disaster Site Cache)                   │
│  │  (災難現場)  │    - medications table (NEW)                               │
│  └──────┬──────┘    - prescriber_certs table (NEW)                          │
│         │                                                                    │
│    ┌────┴─────┬──────────────────┐                                          │
│    │          │                   │                                          │
│    │ ②        │ ③                │ ④                                        │
│    │ Pairing  │ Pairing          │ QR Rx                                    │
│    │ +Certs   │ +Meds            │                                          │
│    ↓          ↓                   ↓                                          │
│  ┌─────────┐ ┌─────────┐    ┌─────────┐                                     │
│  │ Doctor  │ │Pharmacy │←───│ Patient │ (掃描處方)                           │
│  │  PWA    │ │  PWA    │    │  QR     │                                     │
│  └────┬────┘ └────┬────┘    └─────────┘                                     │
│       │           │                                                          │
│       │ ⑤ Writes  │ ⑥ Dispenses                                             │
│       │ Rx QR     │ & Records                                               │
│       ↓           ↓                                                          │
│  ┌─────────────────────┐                                                    │
│  │   DISPENSE_RECORD   │ → ⑦ Sync back to Hub                               │
│  │   (發藥紀錄)         │ → ⑧ Post-event sync to MIRS                        │
│  └─────────────────────┘                                                    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 資料流程詳解

### 2.1 災前準備 (Pre-deployment)

**從 MIRS 匯出藥品清單到 CIRS Hub:**

```
MIRS 管理員 → 匯出藥品 JSON → 匯入 CIRS Hub
```

MIRS 匯出格式:
```json
{
  "type": "MEDICATION_EXPORT",
  "version": 1,
  "source": "MIRS",
  "source_station": "HC-000000",
  "exported_at": "2025-12-22T08:00:00Z",
  "medications": [
    {
      "code": "ACE001",
      "generic_name": "Acetaminophen",
      "brand_name": "普拿疼",
      "unit": "顆",
      "default_dose": "500mg",
      "category": "止痛藥",
      "is_controlled": false,
      "allocation_qty": 500
    }
  ]
}
```

### 2.2 醫師憑證流程 (URL-based Pairing)

```
┌─────────────────────────────────────────────────────────────────┐
│  DOCTOR QR PAIRING FLOW (與 Station/Pharmacy 一致)              │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  [CIRS Admin]                                                    │
│       │                                                          │
│       ├─ 1. 點擊「新增醫師」                                     │
│       ├─ 2. 輸入姓名、執照號碼                                   │
│       ├─ 3. 系統產生 Keypair + 6-digit pairing code              │
│       └─ 4. 顯示 QR Code (URL 格式)                              │
│              ↓                                                   │
│         QR = http://192.168.1.100:8090/doctor/?pair=ABC123       │
│                                                                  │
│  [醫師手機]                                                      │
│       │                                                          │
│       ├─ 5. 掃描 QR → Safari 直接開啟 Doctor PWA                 │
│       ├─ 6. PWA 偵測 URL 參數 → 自動呼叫配對 API                 │
│       ├─ 7. 收到 credentials + medication_catalog                │
│       └─ 8. 儲存至 IndexedDB → 配對完成                          │
│                                                                  │
│  ※ 無需手動輸入 Hub URL 或配對碼！                               │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**Doctor 配對 QR 格式:**
```
http://{hub_ip}:{port}/doctor/?pair={6-digit-code}&id={prescriber_id}
```

**Doctor 配對時收到:**
- prescriber_id
- private_key (用於簽署處方)
- public_key
- name, title, license_no

**Pharmacy 配對時收到:**
- prescriber_certs[] (所有有效醫師的 public key)

### 2.3 藥品清單同步

| PWA | 資料來源 | 同步時機 | 資料內容 |
|-----|---------|---------|----------|
| Pharmacy | CIRS Hub | 配對時 + 手動同步 | 完整藥品清單 + **精確庫存數量** |
| Doctor | CIRS Hub | 配對時 + 手動同步 | 藥品清單 + **庫存狀態指標** |

### 2.4 醫師端庫存可見性 (Disaster Mode)

**設計考量:**
- 平時：醫師不需要知道庫存，專注於臨床判斷
- 災時：讓醫師知道庫存狀況是**好事**，避免開立缺貨藥品

**Doctor PWA 顯示庫存狀態 (非精確數量):**

```
┌──────────────────────────────────────────┐
│  藥品選擇                                 │
├──────────────────────────────────────────┤
│  Acetaminophen 500mg                      │
│  普拿疼  [✓ 有庫存]                       │
├──────────────────────────────────────────┤
│  Ibuprofen 400mg                          │
│  布洛芬  [⚠ 低庫存]                       │
├──────────────────────────────────────────┤
│  Amoxicillin 500mg                        │
│  安莫西林  [✗ 缺貨]                       │
└──────────────────────────────────────────┘
```

**庫存狀態計算:**
```javascript
function getStockStatus(current_stock, min_stock) {
  if (current_stock === 0) return { status: 'OUT', label: '✗ 缺貨', class: 'text-red-600' };
  if (current_stock <= min_stock) return { status: 'LOW', label: '⚠ 低庫存', class: 'text-yellow-600' };
  return { status: 'OK', label: '✓ 有庫存', class: 'text-green-600' };
}
```

**API Response 差異:**
```json
// Pharmacy PWA 收到 (精確數量)
{ "code": "ACE001", "current_stock": 487, "min_stock": 50 }

// Doctor PWA 收到 (狀態指標)
{ "code": "ACE001", "stock_status": "OK", "stock_label": "✓ 有庫存" }
```

---

## 3. 新增資料庫結構

### 3.1 CIRS Hub 新增 Tables

```sql
-- 藥品主檔 (從 MIRS 同步)
CREATE TABLE medications (
    code TEXT PRIMARY KEY,
    generic_name TEXT NOT NULL,
    brand_name TEXT,
    unit TEXT DEFAULT '顆',
    default_dose TEXT,
    category TEXT,
    is_controlled INTEGER DEFAULT 0,
    controlled_schedule TEXT,          -- 如: 第一級、第二級
    current_stock INTEGER DEFAULT 0,   -- Hub 現場庫存
    allocated_stock INTEGER DEFAULT 0, -- 已調撥數量
    min_stock INTEGER DEFAULT 10,
    source_station TEXT,               -- MIRS station ID
    imported_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 醫師憑證
CREATE TABLE prescriber_certs (
    prescriber_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    title TEXT DEFAULT '醫師',
    license_no TEXT,
    public_key TEXT NOT NULL,
    certificate TEXT,                  -- Optional: Hub 簽發的憑證
    issued_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME,
    revoked INTEGER DEFAULT 0,
    revoked_at DATETIME,
    revoked_reason TEXT
);

-- 發藥紀錄 (從 Pharmacy PWA 同步)
CREATE TABLE dispense_records (
    dispense_id TEXT PRIMARY KEY,
    rx_id TEXT NOT NULL,
    patient_ref TEXT,
    patient_name TEXT,
    items TEXT NOT NULL,               -- JSON array
    dispensed_by TEXT,                 -- pharmacist_id
    pharmacy_station TEXT,             -- station_id
    priority TEXT DEFAULT 'ROUTINE',
    dispensed_at DATETIME,
    synced_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    notes TEXT
);

-- 藥品異動紀錄
CREATE TABLE medication_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    medication_code TEXT NOT NULL,
    event_type TEXT NOT NULL,          -- IMPORT/DISPENSE/ADJUST/RETURN
    quantity_change INTEGER NOT NULL,
    quantity_before INTEGER,
    quantity_after INTEGER,
    reference_id TEXT,                 -- dispense_id or import_id
    operator_id TEXT,
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (medication_code) REFERENCES medications(code)
);
```

---

## 4. API 設計

### 4.1 藥品管理 API

```
# 匯入藥品 (從 MIRS JSON)
POST /api/medications/import
Authorization: Bearer <admin_token>
Content-Type: application/json

Request: { MEDICATION_EXPORT JSON }
Response: { imported: 45, updated: 3, errors: [] }
```

```
# 取得藥品清單
GET /api/medications
GET /api/medications?category=止痛藥
GET /api/medications?controlled_only=true
Authorization: Bearer <token>

Response: {
  "medications": [
    { "code": "ACE001", "generic_name": "Acetaminophen", ... }
  ]
}
```

```
# 調整庫存
POST /api/medications/{code}/adjust
Authorization: Bearer <admin_token>

Request: { "quantity_change": -10, "reason": "盤點調整" }
```

### 4.2 醫師憑證 API

```
# 建立醫師 (產生 Keypair)
POST /api/prescribers
Authorization: Bearer <admin_token>

Request: {
  "name": "王大明",
  "title": "醫師",
  "license_no": "醫字第12345號"
}

Response: {
  "prescriber_id": "DR-001",
  "name": "王大明",
  "public_key": "...",
  "private_key": "...",     ← 只在建立時返回一次！
  "certificate": "...",
  "pairing_code": "ABCD12"  ← 醫師 PWA 配對碼
}
```

```
# 取得所有有效憑證 (給 Pharmacy 配對用)
GET /api/prescribers/certs
Authorization: Bearer <station_token>

Response: {
  "prescriber_certs": [
    {
      "prescriber_id": "DR-001",
      "name": "王大明",
      "public_key": "...",
      "valid_until": "2025-12-31T23:59:59Z"
    }
  ]
}
```

### 4.3 Station 配對 API (擴充)

更新 `/api/satellite/stations/pair` Response:

```json
{
  "station_id": "PHARMACY-001",
  "station_type": "PHARMACY",
  "display_name": "藥局站",
  "hub_url": "http://192.168.1.100:8090",
  "config": {
    "station_secret": "...",
    "hub_public_key": "...",
    "hub_encryption_key": "..."
  },
  "prescriber_certs": [           // NEW: 醫師公鑰清單
    {
      "prescriber_id": "DR-001",
      "name": "王大明",
      "public_key": "..."
    }
  ],
  "medications": [                 // NEW: 藥品清單
    {
      "code": "ACE001",
      "generic_name": "Acetaminophen",
      "brand_name": "普拿疼",
      "unit": "顆",
      "default_dose": "500mg",
      "current_stock": 500,
      "is_controlled": false
    }
  ]
}
```

### 4.4 發藥紀錄同步 API

```
# Pharmacy PWA 上傳發藥紀錄
POST /api/satellite/dispense-records
Authorization: Bearer <station_token>

Request: {
  "records": [
    {
      "dispense_id": "DISP-20251222-001",
      "rx_id": "RX-...",
      "patient_ref": "***0042",
      "items": [
        { "code": "ACE001", "qty": 10, "dispensed_qty": 10 }
      ],
      "dispensed_by": "PH-001",
      "dispensed_at": "2025-12-22T14:30:00Z"
    }
  ]
}

Response: { synced: 1, errors: [] }
```

---

## 5. PWA 配對流程更新

### 5.1 Doctor PWA 配對

```
┌─────────────────────────────────────────┐
│  Doctor PWA 配對流程                     │
├─────────────────────────────────────────┤
│                                          │
│  1. Admin 建立醫師帳號                   │
│     → 產生 prescriber_id + keypair       │
│     → 產生 6-digit pairing code          │
│                                          │
│  2. 醫師開啟 Doctor PWA                  │
│     → 輸入 Hub URL + pairing code        │
│                                          │
│  3. PWA 呼叫 /api/prescribers/pair       │
│     → 收到 credentials + medication list │
│                                          │
│  4. 儲存至 IndexedDB:                    │
│     - credentials (private key)          │
│     - medication_catalog                 │
│                                          │
└─────────────────────────────────────────┘
```

### 5.2 Pharmacy PWA 配對 (已完成)

```
┌─────────────────────────────────────────┐
│  Pharmacy PWA 配對流程                   │
├─────────────────────────────────────────┤
│                                          │
│  1. Admin 建立藥局站點                   │
│     → 產生 station_id + pairing code     │
│                                          │
│  2. 藥師開啟 Pharmacy PWA                │
│     → 輸入 6-digit pairing code          │
│                                          │
│  3. PWA 呼叫 /api/satellite/stations/pair│
│     → 收到:                              │
│       - station config                   │
│       - prescriber_certs[] ← 醫師公鑰    │
│       - medications[] ← 藥品清單         │
│                                          │
│  4. 儲存至 IndexedDB:                    │
│     - prescriber_certs                   │
│     - medication_inventory               │
│                                          │
└─────────────────────────────────────────┘
```

---

## 6. 與 MIRS 的整合

### 6.1 現有 MIRS 結構

MIRS 已有 `medicines` table:
```sql
CREATE TABLE medicines (
    medicine_code TEXT PRIMARY KEY,
    generic_name TEXT NOT NULL,
    brand_name TEXT,
    unit TEXT DEFAULT '顆',
    min_stock INTEGER DEFAULT 100,
    current_stock INTEGER DEFAULT 0,
    is_controlled_drug INTEGER DEFAULT 0,
    controlled_level TEXT,
    station_id TEXT NOT NULL DEFAULT 'HC-000000'
);
```

### 6.2 整合方案

**推薦: 在 MIRS 新增「災難部署」功能頁面**

```
MIRS → 一般消耗/調撥 → 災難部署 (NEW)
                         ├─ 選擇藥品清單
                         ├─ 設定調撥數量
                         └─ 匯出 JSON → 匯入 CIRS Hub
```

**不建議: 把藥品發放做在 MIRS 一般消耗頁面**
- MIRS 設計用於醫院固定環境
- 災難現場需要離線優先的 PWA
- 兩者資料模型不同 (MIRS 是站點導向，xIRS 是病患導向)

### 6.3 災後回傳

```
災難結束後:
  CIRS Hub 發藥紀錄 → 匯出 JSON → 匯入 MIRS
  → MIRS 一般消耗 記錄 (with 災難標記)
```

---

## 7. 完整處方發藥流程

```
┌─────────────────────────────────────────────────────────────────────┐
│  COMPLETE RX → DISPENSE WORKFLOW                                    │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  [CIRS Admin]                                                        │
│       │                                                              │
│       ├─ 1. 建立醫師帳號 (Doctor credentials)                        │
│       ├─ 2. 建立藥局站點 (Pharmacy station)                          │
│       └─ 3. 匯入藥品清單 (from MIRS)                                 │
│                                                                      │
│  [Doctor PWA]                                                        │
│       │                                                              │
│       ├─ 4. 配對 Hub → 收到 credentials + medication_catalog        │
│       ├─ 5. 掃描掛號 QR (from CIRS registration)                     │
│       ├─ 6. 選擇藥品 + 劑量                                          │
│       ├─ 7. 簽署處方 (private key)                                   │
│       └─ 8. 產生 RX QR Code                                          │
│                                                                      │
│  [Patient 病患]                                                      │
│       │                                                              │
│       └─ 9. 攜帶 RX QR 到藥局                                        │
│                                                                      │
│  [Pharmacy PWA]                                                      │
│       │                                                              │
│       ├─ 10. 掃描 RX QR                                              │
│       ├─ 11. 驗證簽章 (prescriber public key)                        │
│       ├─ 12. 檢查庫存                                                │
│       ├─ 13. 發藥 + 更新庫存                                         │
│       ├─ 14. 產生 DISPENSE_RECORD                                    │
│       └─ 15. 有網路時同步至 Hub                                      │
│                                                                      │
│  [CIRS Hub]                                                          │
│       │                                                              │
│       ├─ 16. 儲存發藥紀錄                                            │
│       ├─ 17. 更新庫存統計                                            │
│       └─ 18. 災後匯出至 MIRS                                         │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 8. 實作優先順序

### Phase 1: 基礎設施 (Hub)
- [ ] CIRS Hub: 新增 `medications` table
- [ ] CIRS Hub: 新增 `prescriber_certs` table
- [ ] CIRS Hub: 新增 `dispense_records` table
- [ ] API: `/api/medications` CRUD
- [ ] API: `/api/prescribers` CRUD
- [ ] Admin UI: 藥品管理頁面
- [ ] Admin UI: 醫師管理頁面

### Phase 2: Doctor PWA 配對
- [ ] API: `/api/prescribers/pair`
- [ ] Doctor PWA: 配對流程 (輸入 pairing code)
- [ ] Doctor PWA: 下載 credentials + medication list
- [ ] Doctor PWA: 本地儲存 + 離線可用

### Phase 3: Pharmacy PWA 增強
- [ ] API: 擴充 `/api/satellite/stations/pair` 回傳 medications + certs
- [ ] Pharmacy PWA: 配對時儲存 medications 到 IndexedDB
- [ ] Pharmacy PWA: 配對時儲存 prescriber_certs 到 IndexedDB
- [ ] Pharmacy PWA: 發藥時驗證處方簽章

### Phase 4: 同步機制
- [ ] Pharmacy PWA: 發藥紀錄上傳
- [ ] API: `/api/satellite/dispense-records`
- [ ] Hub: 接收並儲存發藥紀錄
- [ ] Hub: 更新藥品庫存

### Phase 5: MIRS 整合
- [ ] MIRS: 新增「災難部署」匯出功能
- [ ] MIRS: 匯出藥品 JSON 格式
- [ ] CIRS Hub: 匯入 MIRS 藥品
- [ ] CIRS Hub: 匯出發藥紀錄給 MIRS

---

## 9. 安全考量

### 9.1 資料分級

| 資料項目 | 分級 | 處理方式 |
|---------|------|----------|
| 醫師 Private Key | Class A | 僅存 Doctor PWA 本地，PIN 加密 |
| 醫師 Public Key | Class C | 可公開分發給所有 Pharmacy |
| 病患完整姓名 | Class A | 僅 CIRS Admin，不傳至 PWA |
| 病患 Masked ID | Class C | 可出現在 QR Code |
| 處方內容 | Class B | 加密傳輸，本地儲存 |
| 藥品庫存 | Class C | 非敏感資料 |

### 9.2 處方簽章驗證

```javascript
// Pharmacy PWA 驗證處方
async function verifyRx(rxOrder) {
  // 1. 取得醫師公鑰
  const cert = await PharmacyDB.getCertificate(rxOrder.prescriber_id);
  if (!cert) {
    return { valid: false, error: 'UNKNOWN_PRESCRIBER' };
  }

  // 2. 檢查憑證有效期
  if (cert.valid_until && new Date(cert.valid_until) < new Date()) {
    return { valid: false, error: 'EXPIRED_CERTIFICATE' };
  }

  // 3. 驗證簽章
  const signable = RxBuilder.getSignableContent(rxOrder);
  const valid = await Ed25519.verify(
    signable,
    rxOrder.signature,
    cert.public_key
  );

  if (!valid) {
    return { valid: false, error: 'INVALID_SIGNATURE' };
  }

  return { valid: true, prescriber: cert };
}
```

---

## 10. Q&A 回答

### Q1: 醫師憑證如何給藥局？

**Answer:**
- CIRS Admin 建立醫師時產生 keypair
- Public key 存入 `prescriber_certs` table
- Pharmacy PWA 配對時，Hub 回傳所有有效醫師的 public key
- Pharmacy 儲存到 IndexedDB，用於驗證處方簽章

### Q2: 藥局如何匯入 Hub 藥品庫存？

**Answer:**
- 藥品清單來源: MIRS 匯出 → CIRS Hub 匯入
- Pharmacy PWA 配對時，Hub 回傳完整藥品清單 (含庫存)
- 後續同步: 手動觸發「同步藥品」或重新配對

### Q3: 醫師 PWA 如何獲得藥品清單？

**Answer:**
- Doctor PWA 配對時，Hub 回傳 `medication_catalog`
- 只包含藥品名稱、劑量建議，**不含庫存數量**
- 醫師開處方時從 catalog 選擇，不需要知道實際庫存

### Q4: 藥品庫存用 CIRS 調撥還是 MIRS？

**Answer:**
- **來源**: MIRS 是藥品主檔 (醫院環境)
- **運作**: CIRS Hub 維護災難現場的獨立庫存
- **關係**: 災前從 MIRS 匯入，災後回傳消耗記錄給 MIRS
- **不建議**: 直接使用 MIRS 的一般消耗功能 (設計目的不同)

### Q5: 需要在 MIRS 做什麼？

**Answer:**
新增「災難部署」功能頁面:
- 選擇要部署的藥品清單
- 設定每項藥品的調撥數量
- 匯出 JSON 檔案
- (可選) 直接 API 同步到 CIRS Hub

---

## 11. 未來擴展

- [ ] 管制藥品特別追蹤流程
- [ ] 藥品批號/效期管理
- [ ] 多藥局站點間調撥
- [ ] 藥品用量預測與補貨建議
- [ ] 與 HIRS (家庭健康紀錄) 整合用藥歷史
