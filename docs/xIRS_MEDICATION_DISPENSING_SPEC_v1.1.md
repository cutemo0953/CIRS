# xIRS 藥品發放系統規格 v1.1

**Version**: 1.1
**Date**: 2025-12-22
**Status**: Draft
**Author**: Claude
**Reviewers**: Gemini, ChatGPT

---

## 0. Non-Negotiables (不可妥協原則)

1. **No private-key transit**: Doctor 裝置本地生成私鑰，Hub 永遠不發送 private key
2. **Privacy-first identifiers**: 下游只用 `patient_ref`，QR 不含病患姓名/身分證
3. **Dispensing = inventory deduction**: 發藥確認才是庫存扣減的權威事件，不是開立處方
4. **Staleness is always visible**: 任何顯示庫存狀態的 UI 必須顯示 `as_of` 和 TTL 狀態

---

## Changelog (v1.0 → v1.1)

| Issue | v1.0 問題 | v1.1 修正 |
|-------|----------|----------|
| **私鑰傳輸** | Hub 發送 private_key 給 Doctor | Doctor 本地生成 keypair，Hub 只發 certificate |
| **病患隱私** | patient_name 出現在下游 | 強制 patient_ref-only |
| **匯入完整性** | MEDICATION_EXPORT 無簽章 | 必須使用 XSDEP 簽章封套 |
| **庫存過期** | 無 staleness 語意 | 強制 as_of + TTL，背景刷新 |
| **多站點庫存** | 單一 current_stock | per-station stock 分區 |
| **閉環回饋** | 無發藥結果回饋 | 新增 DISPENSE_RESULT |
| **重放保護** | 未強制 | 強制 rx_id + nonce 防重放 |

---

## 1. 系統架構總覽 (v1.1)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    xIRS MEDICATION DISPENSING v1.1                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────┐                                                            │
│  │    MIRS     │  ← 藥品主檔 (Master)                                        │
│  └──────┬──────┘                                                            │
│         │                                                                    │
│         │ ① XSDEP-Signed MEDICATION_EXPORT (防竄改)                         │
│         ↓                                                                    │
│  ┌─────────────┐                                                            │
│  │  CIRS Hub   │  ← 災難現場快取                                             │
│  │             │     - per-station stock (多站點庫存)                        │
│  │             │     - prescriber_certs (Hub 簽發的憑證)                     │
│  └──────┬──────┘                                                            │
│         │                                                                    │
│    ┌────┴─────┬──────────────────┐                                          │
│    │          │                   │                                          │
│    │ ②        │ ③                │ ④                                        │
│    │ Cert     │ Meds+Stock       │ Rx QR                                    │
│    │ (no key!)│ (status+TTL)     │                                          │
│    ↓          ↓                   ↓                                          │
│  ┌─────────┐ ┌─────────┐    ┌─────────┐                                     │
│  │ Doctor  │ │Pharmacy │←───│ Patient │                                     │
│  │  PWA    │ │  PWA    │    │  QR     │                                     │
│  │         │ │         │────┼─────────┼─→ ⑤ DISPENSE_RESULT                │
│  │ ←───────┼─┼─────────┼────┘         │   (閉環回饋)                        │
│  └─────────┘ └─────────┘              │                                     │
│                                                                              │
│  ※ Doctor 只看 patient_ref，不看 patient_name (Class A 隱私)                │
│  ※ Doctor 私鑰永遠只在本地生成，Hub 只發 certificate                        │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 關鍵修正詳解

### 2.1 醫師金鑰管理 (Critical Security Fix)

**v1.0 問題:** Hub 產生 keypair 並發送 private_key 給 Doctor
**風險:** 破壞不可否認性 (non-repudiation)，Hub 洩漏 = 所有簽章失效

**v1.1 修正:**

```
┌─────────────────────────────────────────────────────────────────┐
│  DOCTOR KEYPAIR GENERATION (v1.1)                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  [Doctor PWA]                                                    │
│       │                                                          │
│       ├─ 1. 首次啟動 → 本地生成 Ed25519 keypair                  │
│       │      private_key → 儲存 IndexedDB (PIN 加密)             │
│       │      public_key → 準備上傳                               │
│       │                                                          │
│       ├─ 2. 掃描配對 QR → 開啟 PWA                               │
│       │                                                          │
│       └─ 3. 呼叫 /api/prescribers/register-key                   │
│              ↓                                                   │
│              Request: { pairing_code, public_key, device_info }  │
│              ↓                                                   │
│  [CIRS Hub]                                                      │
│       │                                                          │
│       ├─ 4. 驗證 pairing_code                                    │
│       ├─ 5. 簽發 prescriber_certificate                          │
│       │      (Hub 用自己的私鑰簽署)                              │
│       │                                                          │
│       └─ 6. 回傳:                                                │
│              {                                                   │
│                prescriber_id,                                    │
│                name, title, license_no,                          │
│                certificate: {                                    │
│                  public_key,                                     │
│                  issued_at, expires_at,                          │
│                  hub_signature  ← Hub 簽章                       │
│                },                                                │
│                medication_catalog (with stock_status)            │
│              }                                                   │
│                                                                  │
│  ※ private_key 永遠不離開 Doctor 裝置！                          │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**API 變更:**

```
# v1.0 (DEPRECATED)
POST /api/prescribers/pair
Response: { private_key, public_key, ... }  ← 危險！

# v1.1 (NEW)
POST /api/prescribers/register-key
Request:  { pairing_code, public_key, device_info }
Response: { prescriber_id, certificate, medication_catalog }
          ↑ 不含 private_key
```

**離線憑證分發 (CERT_UPDATE):**

```json
{
  "type": "CERT_UPDATE",
  "ver": 1,
  "as_of": "2025-12-22T10:00:00Z",
  "prescriber_certs": [
    {
      "prescriber_id": "DR-001",
      "name": "王大明",
      "public_key": "...",
      "status": "ACTIVE",
      "issued_at": "2025-12-22T08:00:00Z",
      "expires_at": "2025-12-31T23:59:59Z"
    }
  ],
  "revocations": [
    { "prescriber_id": "DR-099", "revoked_at": "2025-12-21T15:00:00Z", "reason": "離職" }
  ],
  "hub_signature": "..."
}
```

**分發方式:**
1. QR Code (分塊傳輸)
2. XSDEP USB `.xirs` 檔案
3. 內網 API (配對時下載)

### 2.2 病患隱私 (Class A Protection)

**強制規則:** Doctor/Pharmacy 端只能使用 `patient_ref`

| 欄位 | CIRS Admin | Doctor PWA | Pharmacy PWA | Hub Sync |
|------|------------|------------|--------------|----------|
| patient_name | ✓ | ✗ | ✗ | ✗ |
| patient_id (full) | ✓ | ✗ | ✗ | ✗ |
| patient_ref (***0042) | ✓ | ✓ | ✓ | ✓ |
| age_group | ✓ | ✓ | ✓ | ✓ |
| gender | ✓ | ✓ | ✓ | ✓ |
| triage | ✓ | ✓ | ✓ | ✓ |
| chief_complaint | ✓ | ✓ | ✓ | ✓ |

**IndexedDB Schema 修正:**

```javascript
// Doctor PWA - patients store
{
  patient_ref: "***0042",      // Primary key (NOT patient_id)
  age_group: "adult",
  gender: "M",
  triage: "YELLOW",
  chief_complaint: "頭痛、發燒",
  last_seen: "2025-12-22T10:30:00Z"
  // NO patient_name, NO patient_id
}

// Pharmacy PWA - dispense_history store
{
  dispense_id: "DISP-...",
  rx_id: "RX-...",
  patient_ref: "***0042",      // NOT patient_name
  items: [...],
  dispensed_at: "..."
  // NO patient_name
}
```

### 2.3 藥品匯入完整性 (XSDEP Signed)

**v1.1 格式:**

```json
{
  "type": "XSDEP_ENVELOPE",
  "ver": 1,
  "payload_type": "MEDICATION_EXPORT",
  "payload": {
    "source": "MIRS",
    "source_station": "HC-000000",
    "exported_at": "2025-12-22T08:00:00Z",
    "medications": [
      {
        "code": "ACE001",
        "generic_name": "Acetaminophen",
        "brand_name": "普拿疼",
        "substitution_group": "ACETAMINOPHEN_ORAL",
        "unit": "顆",
        "default_dose": "500mg",
        "category": "止痛藥",
        "is_controlled": false
      }
    ]
  },
  "sender_id": "MIRS-HC-000000",
  "signature": "...",           // Ed25519 簽章
  "signed_at": "2025-12-22T08:00:00Z"
}
```

**匯入驗證:**
1. CIRS Hub 必須驗證 `signature`
2. 必須檢查 `sender_id` 在信任清單中
3. 匯入成功後記錄 `imported_at` 和來源

### 2.4 庫存狀態 + Staleness (TTL)

**API Response 格式:**

```json
// GET /api/medications/status
{
  "as_of": "2025-12-22T14:30:00Z",
  "ttl_seconds": 1800,
  "station_id": "PHARMACY-001",
  "medications": [
    {
      "code": "ACE001",
      "stock_status": "OK",
      "stock_label": "✓ 有庫存"
    },
    {
      "code": "IBU001",
      "stock_status": "LOW",
      "stock_label": "⚠ 低庫存"
    },
    {
      "code": "AMX001",
      "stock_status": "OUT",
      "stock_label": "✗ 缺貨"
    }
  ]
}
```

**Doctor PWA 行為:**

```javascript
// 開藥選單打開時
async function refreshMedicationStatus() {
  const cached = await DoctorDB.getSetting('medication_status');
  const now = Date.now();

  // 檢查 TTL
  if (cached && cached.expires_at > now) {
    return cached.medications; // 使用快取
  }

  // 嘗試背景刷新
  try {
    const response = await fetch('/api/medications/status');
    if (response.ok) {
      const data = await response.json();
      await DoctorDB.setSetting('medication_status', {
        medications: data.medications,
        as_of: data.as_of,
        expires_at: now + (data.ttl_seconds * 1000)
      });
      return data.medications;
    }
  } catch (e) {
    // 離線 - 使用過期快取但顯示警告
    if (cached) {
      showStaleWarning(cached.as_of);
      return cached.medications;
    }
  }

  return []; // 無資料
}
```

**UI 顯示:**

```
┌──────────────────────────────────────────┐
│  藥品選擇                                 │
│  ⚠ 庫存資訊更新於: 4 小時前              │  ← staleness 警告
├──────────────────────────────────────────┤
│  Acetaminophen 500mg                      │
│  普拿疼  [✓ 有庫存]                       │
├──────────────────────────────────────────┤
│  Ibuprofen 400mg                          │
│  布洛芬  [⚠ 低庫存]                       │
└──────────────────────────────────────────┘
```

### 2.5 Per-Station 庫存 (Multi-Pharmacy)

**Database Schema:**

```sql
-- 取代單一 current_stock
CREATE TABLE pharmacy_stock (
    station_id TEXT NOT NULL,
    med_code TEXT NOT NULL,
    quantity INTEGER DEFAULT 0,
    min_stock INTEGER DEFAULT 10,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (station_id, med_code),
    FOREIGN KEY (med_code) REFERENCES medications(code)
);

-- 例如:
-- PHARMACY-001, ACE001, 500
-- PHARMACY-002, ACE001, 200
```

**Doctor PWA 選擇領藥站點:**

```
掛號時指定:
┌────────────────────────────────────────┐
│  掛號資訊                               │
│  ────────────────────────────────────  │
│  領藥站點:                              │
│  ○ PHARMACY-001 (A區藥局)              │
│  ● PHARMACY-002 (B區藥局) ← 已選        │
│  ○ 不指定 (任一藥局)                    │
└────────────────────────────────────────┘
```

### 2.6 發藥結果閉環 (DISPENSE_RESULT)

**新增 QR 類型:**

```json
{
  "type": "DISPENSE_RESULT",
  "ver": 1,
  "rx_id": "RX-20251222-001",
  "result": "PARTIAL",           // FILLED | PARTIAL | REJECTED
  "items": [
    {
      "code": "ACE001",
      "prescribed_qty": 20,
      "dispensed_qty": 20,
      "status": "FILLED"
    },
    {
      "code": "IBU001",
      "prescribed_qty": 10,
      "dispensed_qty": 0,
      "status": "REJECTED",
      "reason": "OUT_OF_STOCK",
      "substitution_offered": "NAPROXEN_250MG"
    }
  ],
  "dispensed_by": "PH-001",
  "dispensed_at": "2025-12-22T15:00:00Z",
  "pharmacy_station": "PHARMACY-001",
  "hmac": "..."
}
```

**流程:**

```
Doctor 開 Rx → Patient 拿 Rx QR 到 Pharmacy
                        ↓
              Pharmacy 發藥 (或部分發藥)
                        ↓
              產生 DISPENSE_RESULT QR
                        ↓
              Patient 帶回給 Doctor 掃描
                        ↓
              Doctor PWA 記錄發藥結果
              (可看到哪些藥沒發、為什麼)
```

### 2.7 重放保護 (Mandatory)

**Pharmacy PWA 必須執行:**

```javascript
async function processRxQR(rxOrder) {
  // 1. 檢查是否已處理過
  const existing = await PharmacyDB.checkProcessedRx(rxOrder.rx_id);
  if (existing) {
    if (existing.nonce === rxOrder.nonce) {
      return { error: 'DUPLICATE', message: '此處方已處理過' };
    } else {
      return { error: 'REPLAY_ATTACK', message: '偵測到重放攻擊！' };
    }
  }

  // 2. 驗證簽章
  const verification = await RxVerifier.verify(rxOrder);
  if (!verification.valid) {
    return { error: verification.error };
  }

  // 3. 記錄為已處理
  await PharmacyDB.recordProcessedRx(rxOrder, 'PENDING', pharmacistId);

  // 4. 進入發藥流程
  return { success: true };
}
```

---

## 3. 額外改進

### 3.1 Generic-First 開藥 (藥師替代權)

**Doctor PWA UI:**

```
┌──────────────────────────────────────────┐
│  藥品選擇                                 │
├──────────────────────────────────────────┤
│  Acetaminophen (乙醯胺酚)                 │  ← 成分名為主
│  └ 普拿疼 / 泰諾 / 百服寧               │  ← 商品名為輔
│  [✓ 有庫存]                              │
├──────────────────────────────────────────┤
│  Ibuprofen (布洛芬)                       │
│  └ 安舒疼 / 伊普                         │
│  [⚠ 低庫存]                              │
└──────────────────────────────────────────┘
```

**Rx Payload:**

```json
{
  "items": [
    {
      "generic_code": "ACETAMINOPHEN_500MG",
      "generic_name": "Acetaminophen 500mg",
      "substitution_group": "ACETAMINOPHEN_ORAL",
      "qty": 20,
      "allow_substitution": true   // 授權藥師替代
    }
  ]
}
```

### 3.2 緊急開立 (無掛號單)

**Doctor PWA 首頁:**

```
┌────────────────────────────────────┐
│  xIRS Doctor                        │
├────────────────────────────────────┤
│                                     │
│  ┌────────────────────────────┐    │
│  │  📷 掃描掛號單              │    │  ← 標準流程
│  │     (Scan Registration)     │    │
│  └────────────────────────────┘    │
│                                     │
│  ┌────────────────────────────┐    │
│  │  🚨 緊急開立                │    │  ← 無掛號單
│  │     (Emergency Prescribe)   │    │     先處置後補資料
│  └────────────────────────────┘    │
│                                     │
└────────────────────────────────────┘
```

**緊急開立流程:**
1. 醫師手動輸入 patient_ref (或使用臂帶編號)
2. 輸入 age_group, gender, chief_complaint
3. 開立處方
4. 後續可與 CIRS 掛號單補關聯

---

## 4. 更新後的 API 設計

### 4.1 醫師配對 (v1.1)

```
POST /api/prescribers/register-key
Content-Type: application/json

Request:
{
  "pairing_code": "ABC123",
  "public_key": "base64-encoded-ed25519-public-key",
  "device_info": {
    "user_agent": "...",
    "platform": "..."
  }
}

Response:
{
  "prescriber_id": "DR-001",
  "name": "王大明",
  "title": "醫師",
  "license_no": "醫字第12345號",
  "certificate": {
    "public_key": "...",
    "issued_at": "2025-12-22T10:00:00Z",
    "expires_at": "2025-12-31T23:59:59Z",
    "hub_signature": "..."
  },
  "medication_catalog": [
    {
      "code": "ACE001",
      "generic_name": "Acetaminophen",
      "brand_name": "普拿疼",
      "stock_status": "OK",
      "stock_label": "✓ 有庫存"
    }
  ],
  "catalog_as_of": "2025-12-22T10:00:00Z",
  "catalog_ttl_seconds": 1800
}
```

### 4.2 庫存狀態 (輕量級)

```
GET /api/medications/status?station_id=PHARMACY-001
Authorization: Bearer <prescriber_token>

Response:
{
  "as_of": "2025-12-22T14:30:00Z",
  "ttl_seconds": 1800,
  "station_id": "PHARMACY-001",
  "medications": [
    { "code": "ACE001", "stock_status": "OK", "stock_label": "✓ 有庫存" },
    { "code": "IBU001", "stock_status": "LOW", "stock_label": "⚠ 低庫存" }
  ]
}
```

### 4.3 發藥結果上傳

```
POST /api/satellite/dispense-results
Authorization: Bearer <pharmacy_token>

Request:
{
  "results": [
    {
      "rx_id": "RX-20251222-001",
      "result": "PARTIAL",
      "items": [...],
      "dispensed_by": "PH-001",
      "dispensed_at": "2025-12-22T15:00:00Z"
    }
  ]
}
```

---

## 5. 實作優先順序 (v1.1)

### Phase 1: 安全修正 (Critical)
- [ ] Doctor PWA: 本地 keypair 生成
- [ ] Hub: `/api/prescribers/register-key` (不發私鑰)
- [ ] Hub: 簽發 prescriber_certificate
- [ ] 移除所有 patient_name 從 Doctor/Pharmacy 端

### Phase 2: 庫存改進
- [ ] Hub: per-station pharmacy_stock 表
- [ ] API: `/api/medications/status` with as_of + TTL
- [ ] Doctor PWA: 背景刷新 + staleness 警告

### Phase 3: 閉環回饋
- [ ] Pharmacy PWA: 產生 DISPENSE_RESULT QR
- [ ] Doctor PWA: 掃描並記錄發藥結果
- [ ] UI: 顯示未完成發藥的處方

### Phase 4: 資料完整性
- [ ] MIRS: 匯出 XSDEP 簽章封套
- [ ] Hub: 驗證簽章後匯入
- [ ] Pharmacy: 強制 nonce 防重放

---

## 6. 決策記錄 (ADR)

### ADR-001: 私鑰永遠不離開 Doctor 裝置
- **狀態:** 已採納 (v1.1)
- **原因:** 維護不可否認性，Hub 洩漏不影響簽章可信度
- **影響:** 需要重新設計配對流程

### ADR-002: patient_ref-only 原則
- **狀態:** 已採納 (v1.1)
- **原因:** 維護 Class A 隱私分級
- **影響:** Doctor/Pharmacy PWA 不能顯示病患姓名

### ADR-003: 庫存狀態而非精確數量
- **狀態:** 維持 (v1.0)
- **原因:** 降低醫師認知負擔，避免敏感營運資料外洩
- **影響:** 醫師可能開出「低庫存」藥品，需藥師確認

### ADR-004: 強制 DISPENSE_RESULT 閉環
- **狀態:** 已採納 (v1.1)
- **原因:** 避免醫師反覆開出不可執行處方
- **影響:** 需要額外 QR 掃描流程

---

## 7. UI 需求

### 7.1 Doctor PWA

**主要按鈕:**
- 掃描掛號單 (Scan Registration QR)
- 緊急開立 (Emergency Prescribe - 無掛號單)

**藥品選擇器:**
- 顯示成分名 (Generic name)、劑量、劑型
- 顯示 R/Y/G 庫存狀態 + `as_of` 時間
- 當 TTL 超過時顯示 "離線/過期" 警示

**等候室 (Waiting Room):**
- 依 priority 排序 (STAT > URGENT > ROUTINE)
- 顯示等待時間
- 點擊進入處方開立

### 7.2 Pharmacy PWA

**主要流程:**
- 快速掃描 → 驗證 → 發藥
- 替代藥品 UI 限制在同一 substitution group

**管制藥品模式 (Controlled Drug Mode):**

```
┌─────────────────────────────────────────────────┐
│  ⚠️ 管制藥品警示                                │
│  ─────────────────────────────────────────────  │
│                                                  │
│  藥品: Morphine 10mg                            │
│  數量: 5 顆                                      │
│                                                  │
│  本藥品為管制藥品，發藥需要:                     │
│  ✓ 藥師確認簽核                                 │
│  ✓ 詳細審核備註                                 │
│                                                  │
│  審核備註 (必填):                               │
│  ┌─────────────────────────────────────────┐   │
│  │ 已確認病患身份，疼痛評估 NRS 8/10       │   │
│  │ 符合管制藥品處方規範                     │   │
│  └─────────────────────────────────────────┘   │
│                                                  │
│  [取消]                    [確認發藥並簽核]     │
└─────────────────────────────────────────────────┘
```

**管制藥品規則:**
1. `is_controlled: true` 的藥品觸發此模式
2. 強制藥師輸入 PIN/指紋確認身份
3. 審核備註為必填欄位
4. 所有操作記錄完整審計軌跡

---

## 8. 安全需求

### 8.1 簽章要求

| 類型 | 簽章方式 | 簽章者 |
|------|----------|--------|
| Registration QR | Ed25519 | Hub 私鑰 |
| Prescriber Certificate | Ed25519 | Hub 私鑰 |
| MEDICATION_EXPORT | Ed25519 (XSDEP) | MIRS Station 私鑰 |
| RX_ORDER | Ed25519 | Doctor 私鑰 |
| DISPENSE_RECORD | HMAC-SHA256 | Station Secret |

### 8.2 重放保護

**RX 重放防護:**
```javascript
// Pharmacy PWA 必須檢查
const processed = await db.get('processed_rx', rx_id);
if (processed) {
  if (processed.nonce === rx.nonce) {
    throw new Error('DUPLICATE: 此處方已處理');
  } else {
    throw new Error('REPLAY_ATTACK: nonce 不符');
  }
}
```

**Packet 重放防護:**
- Hub 維護 `packet_id` 去重表
- 已處理的 packet_id 拒絕重複處理

### 8.3 Service Worker 快取規則

**禁止快取的端點:**
```javascript
// sw.js - Clinical endpoints must not be cached
const NO_CACHE_PATTERNS = [
  '/api/medications/status',
  '/api/registrations/',
  '/api/prescribers/',
  '/api/satellite/dispense'
];

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // Check if this is a no-cache endpoint
  if (NO_CACHE_PATTERNS.some(p => url.pathname.includes(p))) {
    // Pass through to network, no cache
    event.respondWith(fetch(event.request));
    return;
  }

  // Other requests can use cache strategy
  // ...
});
```

**後端 Header 設定:**
```python
# FastAPI middleware for clinical endpoints
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)

    # Clinical/sensitive endpoints
    if any(p in request.url.path for p in ['/medications/', '/dispense', '/registrations/']):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"

    return response
```

### 8.4 資料加密

| 儲存位置 | 加密方式 |
|----------|----------|
| Doctor IndexedDB | AES-256 (PIN-derived key) |
| Pharmacy IndexedDB | AES-256 (Station secret) |
| XSDEP Packet | ChaCha20-Poly1305 |
| Hub Database | SQLite + filesystem encryption |

---

## 9. 實作檢查清單 (Minimal Viable)

### Phase 1: 安全基礎 (Week 1)
- [ ] 移除 Hub 發送 private_key 的邏輯
- [ ] Doctor PWA: 本地 Ed25519 keypair 生成
- [ ] Hub: `/api/prescribers/register-key` API
- [ ] Hub: 簽發 prescriber_certificate

### Phase 2: 藥品庫存 (Week 2)
- [ ] Hub: per-station `pharmacy_stock` 表
- [ ] API: `/api/medications/status` (as_of + TTL)
- [ ] Doctor PWA: 背景刷新 + staleness 警告 UI
- [ ] MIRS: XSDEP 簽章匯出

### Phase 3: 發藥流程 (Week 3)
- [ ] Pharmacy PWA: Rx QR 掃描驗證
- [ ] Pharmacy PWA: nonce 防重放檢查
- [ ] Pharmacy PWA: DISPENSE_RECORD 產生
- [ ] Pharmacy PWA: DISPENSE_RESULT_TICKET QR

### Phase 4: 閉環與管制 (Week 4)
- [ ] Doctor PWA: 掃描 DISPENSE_RESULT
- [ ] Doctor PWA: 未完成處方顯示
- [ ] Pharmacy PWA: 管制藥品模式
- [ ] 全流程 patient_ref-only 驗證

---

## 10. 附錄

### 10.1 Stock Status 定義

| Status | 條件 | UI 顯示 |
|--------|------|---------|
| GREEN / OK | qty >= min_stock | ✓ 有庫存 |
| YELLOW / LOW | 0 < qty < min_stock | ⚠ 低庫存 |
| RED / OUT | qty == 0 OR disabled | ✗ 缺貨 |

### 10.2 處方優先級

| Priority | 含義 | 建議處理時間 |
|----------|------|--------------|
| STAT | 緊急 | 立即 |
| URGENT | 急件 | 30 分鐘內 |
| ROUTINE | 一般 | 依序處理 |

### 10.3 相關規格文件

- `xIRS_REGISTRATION_SPEC_v1.0.md` - 掛號系統
- `xIRS_DATA_DOMAINS_v1.0.md` - 資料分類與隱私
- `xIRS_XSDEP_SPEC_v1.0.md` - 跨系統資料交換協定
