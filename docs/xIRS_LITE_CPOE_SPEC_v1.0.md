# xIRS Lite CPOE Spec v1.0

**Version**: 1.0 (Initial Draft)
**Theme**: Offline Prescription & Dispensing for Disaster Medical Response
**System**: MIRS/CIRS Extension
**Security**: Ed25519 Signatures, Offline Trust Chain
**Date**: 2025-12-21
**Status**: Phase 5A-5B Implemented

---

## Implementation Status

| Phase | Component | Status | Location |
|-------|-----------|--------|----------|
| 5A | Core Protocol (JS) | ✅ Done | `/shared/js/xirs-rx.js`, `xirs-dispense.js` |
| 5A | Pharmacy DB Schema | ✅ Done | `/shared/js/xirs-pharmacy-db.js` |
| 5A | Doctor DB Schema | ✅ Done | `/shared/js/xirs-doctor-db.js` |
| 5B | Doctor PWA | ✅ Done | `/frontend/doctor/` |
| 5C | Pharmacy Extension | ⏳ Pending | Extend `/frontend/station/` |
| 5D | Hub Integration | ⏳ Pending | `/backend/routes/prescriber.py` |

---

## 1. Executive Summary

### 1.1 Problem Statement

Current xIRS v1.8 handles **物資 (supplies)** well but lacks support for **藥品調劑 (medication dispensing)** with proper clinical workflow:

| Current State | Gap |
|---------------|-----|
| Anyone at Station can dispense anything | No prescriber authorization |
| No distinction between supplies vs. controlled meds | Controlled substances need audit trail |
| Inventory-focused | No patient-medication linkage |

### 1.2 Solution: Lite CPOE

A **minimal** clinical order layer that adds:

- **Prescription (Rx)** creation by authorized prescribers
- **Verification & Dispensing** by pharmacists
- **Audit trail** for controlled substances
- **Offline-first** operation via QR-based protocol

### 1.3 Explicit Non-Goals (Scope Boundaries)

To prevent scope creep into full HIS, we **explicitly exclude**:

| Excluded | Reason |
|----------|--------|
| Full medical records (EMR) | Out of scope - use paper or external system |
| Diagnosis codes (ICD-10/11) | Not needed for dispensing |
| Lab orders / Imaging | Different workflow |
| Billing / Insurance (NHI) | Post-disaster concern |
| Medication interaction checking | Pharmacist clinical judgment |
| E-prescription regulatory compliance | Emergency use exemption |

---

## 2. Architecture Overview

### 2.1 Role Definitions

| Role | Device | Trust Level | Capabilities |
|------|--------|-------------|--------------|
| **Prescriber (Doctor)** | Phone/Tablet PWA | High (Has signing key) | Create Rx, Sign orders |
| **Pharmacist** | Pharmacy Station iPad | High (Has verification keys) | Verify Rx, Dispense, Sign-off |
| **Patient/Runner** | Phone or Paper | Zero (Blind Carrier) | Transport Rx QR only |
| **Hub Admin** | PC/Laptop | Full | Manage keys, View audit logs |

### 2.2 Trust Chain

```
┌─────────────────────────────────────────────────────────────────────┐
│                         KEY HIERARCHY                                │
│                                                                      │
│  ┌──────────────┐                                                   │
│  │   Hub Root   │  Master authority                                 │
│  │   Keypair    │  Signs: Station keys, Prescriber keys             │
│  └──────┬───────┘                                                   │
│         │                                                            │
│         ├──────────────────┬────────────────────┐                   │
│         ▼                  ▼                    ▼                   │
│  ┌──────────────┐   ┌──────────────┐    ┌──────────────┐           │
│  │   Station    │   │  Prescriber  │    │  Pharmacist  │           │
│  │   Keypair    │   │   Keypair    │    │   Keypair    │           │
│  └──────────────┘   └──────────────┘    └──────────────┘           │
│         │                  │                    │                   │
│         │                  │                    │                   │
│    Signs:              Signs:              Signs:                   │
│    Reports             Rx Orders           Dispense Records         │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.3 Data Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                         PRESCRIPTION FLOW                            │
│                                                                      │
│  ┌──────────┐         ┌──────────┐         ┌──────────────┐         │
│  │  Doctor  │         │ Patient  │         │   Pharmacy   │         │
│  │   PWA    │         │ (Runner) │         │   Station    │         │
│  └────┬─────┘         └────┬─────┘         └──────┬───────┘         │
│       │                    │                      │                  │
│       │  1. Create Rx      │                      │                  │
│       │  2. Sign (Ed25519) │                      │                  │
│       │  3. Display QR     │                      │                  │
│       │ ─────────────────► │                      │                  │
│       │    (Patient sees   │                      │                  │
│       │     or photos QR)  │                      │                  │
│       │                    │                      │                  │
│       │                    │  4. Walk to Pharmacy │                  │
│       │                    │ ────────────────────►│                  │
│       │                    │                      │                  │
│       │                    │                      │  5. Scan Rx QR   │
│       │                    │                      │  6. Verify Sig   │
│       │                    │                      │  7. Check Dup    │
│       │                    │                      │  8. Dispense     │
│       │                    │                      │  9. Log Action   │
│       │                    │                      │                  │
│       │                    │  10. Receive Meds    │                  │
│       │                    │ ◄────────────────────│                  │
│       │                    │                      │                  │
└─────────────────────────────────────────────────────────────────────┘

                              ║
                              ║ Later (via Runner)
                              ▼

┌─────────────────────────────────────────────────────────────────────┐
│                         SYNC TO HUB                                  │
│                                                                      │
│  ┌──────────────┐                              ┌──────────┐         │
│  │   Pharmacy   │    Encrypted Report          │   Hub    │         │
│  │   Station    │  ──────────────────────────► │          │         │
│  └──────────────┘    (Contains Dispense Logs)  └──────────┘         │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Protocol Specifications

### 3.1 Packet Types

| Packet Type | Direction | Security | Purpose |
|-------------|-----------|----------|---------|
| `RX_ORDER` | Doctor → Pharmacy | Signed (Doctor key) | Prescription |
| `DISPENSE_RECORD` | Pharmacy → Hub | Encrypted + HMAC | Dispensing log |
| `PRESCRIBER_CERT` | Hub → Pharmacy | Signed (Hub key) | Doctor's public key |

### 3.2 RX_ORDER Structure

```json
{
  "type": "RX_ORDER",
  "version": "1.0",

  "rx_id": "RX-DOC001-20251221-0042",
  "prescriber_id": "DOC-001",
  "prescriber_name": "王大明醫師",

  "patient": {
    "id": "P0042",
    "name": "陳小華",
    "age_group": "adult",
    "weight_kg": 65
  },

  "items": [
    {
      "code": "MED-PARA-500",
      "name": "Paracetamol 500mg",
      "qty": 6,
      "unit": "tab",
      "freq": "TID",
      "duration_days": 2,
      "route": "PO",
      "instruction": "飯後服用"
    },
    {
      "code": "MED-AMOX-250",
      "name": "Amoxicillin 250mg",
      "qty": 9,
      "unit": "cap",
      "freq": "TID",
      "duration_days": 3,
      "route": "PO",
      "instruction": "飯後服用，需完成療程"
    }
  ],

  "priority": "ROUTINE",
  "diagnosis_text": "上呼吸道感染",
  "note": "對 Penicillin 無過敏史",

  "ts": 1734800000,
  "nonce": "a1b2c3d4e5f6",
  "signature": "Ed25519-Base64-Signature..."
}
```

**Priority Levels**:

| Priority | Meaning | UI Behavior |
|----------|---------|-------------|
| `STAT` | Immediate / Emergency | Red alert, skip queue |
| `URGENT` | Within 1 hour | Orange highlight |
| `ROUTINE` | Normal queue | Default |

**Frequency Codes**:

| Code | Meaning | 中文 |
|------|---------|------|
| `QD` | Once daily | 每日一次 |
| `BID` | Twice daily | 每日兩次 |
| `TID` | Three times daily | 每日三次 |
| `QID` | Four times daily | 每日四次 |
| `Q4H` | Every 4 hours | 每4小時 |
| `Q6H` | Every 6 hours | 每6小時 |
| `Q8H` | Every 8 hours | 每8小時 |
| `PRN` | As needed | 需要時 |
| `STAT` | Immediately | 立即 |
| `HS` | At bedtime | 睡前 |
| `AC` | Before meals | 飯前 |
| `PC` | After meals | 飯後 |

### 3.3 DISPENSE_RECORD Structure

```json
{
  "type": "DISPENSE_RECORD",
  "version": "1.0",

  "dispense_id": "DISP-PHARM01-20251221-0015",
  "rx_id": "RX-DOC001-20251221-0042",

  "pharmacist_id": "PHARM-001",
  "pharmacist_name": "林藥師",

  "patient_id": "P0042",

  "status": "FILLED",

  "dispensed_items": [
    {
      "code": "MED-PARA-500",
      "qty_ordered": 6,
      "qty_dispensed": 6,
      "lot_number": "LOT2024A",
      "expiry_date": "2025-06"
    },
    {
      "code": "MED-AMOX-250",
      "qty_ordered": 9,
      "qty_dispensed": 9,
      "lot_number": "LOT2024B",
      "expiry_date": "2025-08"
    }
  ],

  "substitutions": [],

  "witness_id": null,
  "witness_name": null,

  "counseling_provided": true,
  "patient_signature": false,

  "ts": 1734800300,
  "nonce": "f6e5d4c3b2a1",
  "hmac": "HMAC-SHA256..."
}
```

**Status Values**:

| Status | Meaning |
|--------|---------|
| `FILLED` | Fully dispensed as ordered |
| `PARTIAL` | Partial fill (qty_dispensed < qty_ordered) |
| `SUBSTITUTED` | Different medication substituted |
| `REJECTED` | Pharmacist rejected (reason required) |
| `CANCELLED` | Prescriber cancelled |

### 3.4 PRESCRIBER_CERT Structure

Distributed to Pharmacy Stations so they can verify Rx signatures offline.

```json
{
  "type": "PRESCRIBER_CERT",
  "version": "1.0",

  "prescriber_id": "DOC-001",
  "name": "王大明",
  "title": "醫師",
  "license_no": "醫字第012345號",

  "public_key": "Ed25519-PublicKey-Base64...",
  "key_id": "DOC001-2024",

  "permissions": {
    "can_prescribe_controlled": true,
    "controlled_schedule": ["II", "III", "IV"],
    "max_days_supply": 30
  },

  "valid_from": "2024-01-01",
  "valid_until": "2025-12-31",

  "issued_by": "HUB-001",
  "issued_at": 1704067200,
  "hub_signature": "Ed25519-Hub-Signature..."
}
```

### 3.5 QR Encoding

Same as xIRS v1.8:

```
Format: xIRS|{seq}/{total}|{chunk_data_base64}

Example (single QR):
xIRS|1/1|eyJ0eXBlIjoiUlhfT1JERVIiLC...

Example (multi-QR for large Rx):
xIRS|1/2|eyJ0eXBlIjoiUlhfT1JERVIiLC...
xIRS|2/2|ImRpYWdub3Npc190ZXh0Ijoi...
```

---

## 4. Security Specifications

### 4.1 Signature Requirements

| Packet | Signer | Verification |
|--------|--------|--------------|
| `RX_ORDER` | Prescriber's Ed25519 key | Pharmacy Station verifies against PRESCRIBER_CERT |
| `DISPENSE_RECORD` | HMAC with Station secret | Hub verifies |
| `PRESCRIBER_CERT` | Hub's Ed25519 key | Pharmacy Station verifies against Hub public key |

### 4.2 Rx Signing Process (Doctor Side)

```python
def sign_rx(rx_order: dict, prescriber_private_key: str) -> dict:
    """
    Sign an Rx order with prescriber's private key.
    """
    # 1. Create signable payload (without signature)
    signable = {k: v for k, v in rx_order.items() if k != 'signature'}

    # 2. Canonical JSON serialization
    message = json.dumps(signable, sort_keys=True, separators=(',', ':'))

    # 3. Sign with Ed25519
    signature = ed25519_sign(prescriber_private_key, message)

    # 4. Return with signature
    rx_order['signature'] = base64_encode(signature)
    return rx_order
```

### 4.3 Rx Verification Process (Pharmacy Side)

```python
def verify_rx(rx_order: dict, prescriber_certs: dict) -> VerifyResult:
    """
    Verify an Rx order's signature.
    """
    prescriber_id = rx_order.get('prescriber_id')

    # 1. Find prescriber's certificate
    cert = prescriber_certs.get(prescriber_id)
    if not cert:
        return VerifyResult(valid=False, error="Unknown prescriber")

    # 2. Check certificate validity
    if not is_cert_valid(cert):
        return VerifyResult(valid=False, error="Certificate expired")

    # 3. Extract signable payload
    signable = {k: v for k, v in rx_order.items() if k != 'signature'}
    message = json.dumps(signable, sort_keys=True, separators=(',', ':'))

    # 4. Verify signature
    signature = base64_decode(rx_order['signature'])
    public_key = base64_decode(cert['public_key'])

    if not ed25519_verify(message, signature, public_key):
        return VerifyResult(valid=False, error="Invalid signature")

    return VerifyResult(valid=True, prescriber_name=cert['name'])
```

### 4.4 Replay Prevention

**Pharmacy Station (IndexedDB)**:

```javascript
// Store: processed_rx
{
  rx_id: "RX-DOC001-20251221-0042",  // Primary key
  nonce: "a1b2c3d4e5f6",
  processed_at: "2025-12-21T14:30:00Z",
  status: "FILLED",
  pharmacist_id: "PHARM-001"
}
```

**Verification Logic**:

```javascript
async function checkRxProcessed(rxId, nonce) {
  const existing = await db.processed_rx.get(rxId);

  if (existing) {
    if (existing.nonce === nonce) {
      // Same Rx, already processed
      return { duplicate: true, status: existing.status };
    } else {
      // Same rx_id but different nonce - possible replay attack
      return { duplicate: true, error: "NONCE_MISMATCH" };
    }
  }

  return { duplicate: false };
}
```

### 4.5 Controlled Substance Requirements

For Schedule II-IV medications:

| Requirement | Implementation |
|-------------|----------------|
| Double verification | `witness_id` + `witness_name` required |
| Quantity limits | Check against `cert.permissions.max_days_supply` |
| Audit logging | All actions logged with timestamps |
| Separate storage | Flagged in inventory as `is_controlled: true` |

```json
{
  "type": "DISPENSE_RECORD",
  "rx_id": "RX-DOC001-20251221-0099",

  "dispensed_items": [
    {
      "code": "MED-MORPH-10",
      "name": "Morphine 10mg",
      "is_controlled": true,
      "schedule": "II",
      "qty_ordered": 5,
      "qty_dispensed": 5
    }
  ],

  "witness_id": "PHARM-002",
  "witness_name": "張藥師",
  "witness_signature": "Ed25519-Witness-Sig...",

  "double_count_verified": true
}
```

---

## 5. User Interface Specifications

### 5.1 Doctor PWA Screens

**5.1.1 Patient Selection**

```
┌─────────────────────────────────────────┐
│  👨‍⚕️ Doctor Mode                    ⚙️ │
├─────────────────────────────────────────┤
│                                         │
│  ┌─────────────────────────────────┐   │
│  │ 🔍 搜尋病患 ID 或姓名...         │   │
│  └─────────────────────────────────┘   │
│                                         │
│  最近看診:                              │
│  ┌─────────────────────────────────┐   │
│  │ P0042 陳小華  男 35歲           ▶│   │
│  ├─────────────────────────────────┤   │
│  │ P0038 林美玲  女 28歲           ▶│   │
│  ├─────────────────────────────────┤   │
│  │ P0051 張大偉  男 62歲           ▶│   │
│  └─────────────────────────────────┘   │
│                                         │
│  ┌─────────────────────────────────┐   │
│  │    ➕ 新增病患                   │   │
│  └─────────────────────────────────┘   │
│                                         │
└─────────────────────────────────────────┘
```

**5.1.2 Prescription Entry**

```
┌─────────────────────────────────────────┐
│  ← 返回    開立處方    P0042 陳小華    │
├─────────────────────────────────────────┤
│                                         │
│  診斷/主訴:                             │
│  ┌─────────────────────────────────┐   │
│  │ 上呼吸道感染、發燒              │   │
│  └─────────────────────────────────┘   │
│                                         │
│  處方內容:                              │
│  ┌─────────────────────────────────┐   │
│  │ Paracetamol 500mg               │   │
│  │ 6 顆 | TID | 2天                │ ✕ │
│  ├─────────────────────────────────┤   │
│  │ Amoxicillin 250mg               │   │
│  │ 9 顆 | TID | 3天                │ ✕ │
│  └─────────────────────────────────┘   │
│                                         │
│  ┌─────────────────────────────────┐   │
│  │    ➕ 新增藥品                   │   │
│  └─────────────────────────────────┘   │
│                                         │
│  優先級: ○ 一般  ○ 優先  ○ 緊急        │
│                                         │
│  ┌─────────────────────────────────┐   │
│  │      ✍️ 簽章並開立處方          │   │
│  └─────────────────────────────────┘   │
│                                         │
└─────────────────────────────────────────┘
```

**5.1.3 Rx QR Display**

```
┌─────────────────────────────────────────┐
│            處方已開立                   │
├─────────────────────────────────────────┤
│                                         │
│           ┌───────────────┐             │
│           │               │             │
│           │   [QR CODE]   │             │
│           │               │             │
│           │    (1/1)      │             │
│           └───────────────┘             │
│                                         │
│           RX-DOC001-20251221-0042       │
│                                         │
│  病患: P0042 陳小華                     │
│  藥品: 2 項                             │
│  開立: 2025-12-21 14:30                 │
│                                         │
│  ─────────────────────────────────────  │
│                                         │
│  請病患持此 QR Code 至藥局領藥          │
│                                         │
│  ┌─────────────────────────────────┐   │
│  │         開立下一張處方           │   │
│  └─────────────────────────────────┘   │
│                                         │
└─────────────────────────────────────────┘
```

### 5.2 Pharmacy Station Screens

**5.2.1 Queue View**

```
┌─────────────────────────────────────────┐
│  💊 藥局                   待處理: 5   │
├─────────────────────────────────────────┤
│                                         │
│  ┌─────────────────────────────────┐   │
│  │        📷 掃描處方 QR            │   │
│  └─────────────────────────────────┘   │
│                                         │
│  待調劑:                                │
│  ┌─────────────────────────────────┐   │
│  │ 🔴 RX-0099 王先生 STAT 管制藥   ▶│   │
│  ├─────────────────────────────────┤   │
│  │ 🟠 RX-0098 李小姐 URGENT        ▶│   │
│  ├─────────────────────────────────┤   │
│  │ ⚪ RX-0097 陳太太 ROUTINE       ▶│   │
│  ├─────────────────────────────────┤   │
│  │ ⚪ RX-0096 張先生 ROUTINE       ▶│   │
│  └─────────────────────────────────┘   │
│                                         │
│  今日統計:                              │
│  ├─ 已調劑: 42                          │
│  ├─ 管制藥: 3                           │
│  └─ 拒絕/退回: 1                        │
│                                         │
└─────────────────────────────────────────┘
```

**5.2.2 Dispense Screen**

```
┌─────────────────────────────────────────┐
│  ← 返回        調劑確認                 │
├─────────────────────────────────────────┤
│                                         │
│  ✅ 簽章驗證通過                        │
│  開立醫師: 王大明醫師 (DOC-001)         │
│                                         │
│  病患: P0042 陳小華                     │
│  診斷: 上呼吸道感染                     │
│                                         │
│  ─────────────────────────────────────  │
│                                         │
│  處方內容:                              │
│  ┌─────────────────────────────────┐   │
│  │ ☑ Paracetamol 500mg             │   │
│  │   6 顆 TID x 2天                 │   │
│  │   庫存: 150 ✓                    │   │
│  ├─────────────────────────────────┤   │
│  │ ☑ Amoxicillin 250mg             │   │
│  │   9 顆 TID x 3天                 │   │
│  │   庫存: 89 ✓                     │   │
│  └─────────────────────────────────┘   │
│                                         │
│  ┌─────────────────────────────────┐   │
│  │        ✅ 確認發藥               │   │
│  └─────────────────────────────────┘   │
│                                         │
│  ┌─────────────────────────────────┐   │
│  │        ❌ 拒絕/退回              │   │
│  └─────────────────────────────────┘   │
│                                         │
└─────────────────────────────────────────┘
```

**5.2.3 Controlled Substance Double-Check**

```
┌─────────────────────────────────────────┐
│           ⚠️ 管制藥品確認              │
├─────────────────────────────────────────┤
│                                         │
│  此處方包含管制藥品，需要雙人確認:      │
│                                         │
│  ┌─────────────────────────────────┐   │
│  │ 🔴 Morphine 10mg (Schedule II)  │   │
│  │    數量: 5 顆                    │   │
│  └─────────────────────────────────┘   │
│                                         │
│  第一確認: ✓ 林藥師 (PHARM-001)        │
│                                         │
│  第二確認 (見證人):                     │
│  ┌─────────────────────────────────┐   │
│  │ 見證人 ID: PHARM-002            │   │
│  └─────────────────────────────────┘   │
│  ┌─────────────────────────────────┐   │
│  │ 見證人姓名: 張藥師              │   │
│  └─────────────────────────────────┘   │
│                                         │
│  ☐ 已完成雙人清點確認                   │
│                                         │
│  ┌─────────────────────────────────┐   │
│  │      ✅ 雙重確認後發藥           │   │
│  └─────────────────────────────────┘   │
│                                         │
└─────────────────────────────────────────┘
```

---

## 6. Database Schema

### 6.1 Hub Database Extensions

```sql
-- Prescriber Registry
CREATE TABLE prescribers (
    prescriber_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    title TEXT,
    license_no TEXT,
    public_key TEXT NOT NULL,
    key_id TEXT NOT NULL,
    permissions TEXT,  -- JSON
    valid_from DATE,
    valid_until DATE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    is_active INTEGER DEFAULT 1
);

-- Rx Orders (synced from Pharmacy Stations)
CREATE TABLE rx_orders (
    rx_id TEXT PRIMARY KEY,
    prescriber_id TEXT NOT NULL,
    patient_id TEXT,
    patient_name TEXT,
    items TEXT NOT NULL,  -- JSON
    priority TEXT DEFAULT 'ROUTINE',
    diagnosis_text TEXT,
    note TEXT,
    ts INTEGER NOT NULL,
    nonce TEXT NOT NULL,
    signature TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (prescriber_id) REFERENCES prescribers(prescriber_id)
);

-- Dispense Records (synced from Pharmacy Stations)
CREATE TABLE dispense_records (
    dispense_id TEXT PRIMARY KEY,
    rx_id TEXT NOT NULL,
    pharmacy_station_id TEXT NOT NULL,
    pharmacist_id TEXT NOT NULL,
    pharmacist_name TEXT,
    patient_id TEXT,
    status TEXT NOT NULL,
    dispensed_items TEXT NOT NULL,  -- JSON
    substitutions TEXT,  -- JSON
    witness_id TEXT,
    witness_name TEXT,
    ts INTEGER NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (rx_id) REFERENCES rx_orders(rx_id)
);

CREATE INDEX idx_rx_orders_patient ON rx_orders(patient_id);
CREATE INDEX idx_rx_orders_prescriber ON rx_orders(prescriber_id);
CREATE INDEX idx_dispense_rx ON dispense_records(rx_id);
CREATE INDEX idx_dispense_pharmacist ON dispense_records(pharmacist_id);
```

### 6.2 Pharmacy Station IndexedDB Schema

```javascript
// Store: prescriber_certs
{
  prescriber_id: "DOC-001",       // Primary key
  name: "王大明",
  title: "醫師",
  public_key: "base64...",
  key_id: "DOC001-2024",
  permissions: { ... },
  valid_until: "2025-12-31",
  hub_signature: "base64..."
}

// Store: processed_rx
{
  rx_id: "RX-DOC001-20251221-0042",  // Primary key
  nonce: "a1b2c3d4e5f6",
  patient_id: "P0042",
  patient_name: "陳小華",
  prescriber_id: "DOC-001",
  prescriber_name: "王大明醫師",
  items: [...],
  status: "FILLED",
  pharmacist_id: "PHARM-001",
  processed_at: "2025-12-21T14:30:00Z"
}

// Store: dispense_queue
{
  id: auto,
  rx_id: "RX-DOC001-20251221-0042",
  rx_data: { ... },
  priority: "ROUTINE",
  received_at: "2025-12-21T14:25:00Z",
  status: "PENDING"
}

// Store: medication_inventory (extends existing)
{
  code: "MED-MORPH-10",
  name: "Morphine 10mg",
  quantity: 25,
  unit: "tab",
  is_controlled: true,
  schedule: "II",
  lot_number: "LOT2024C",
  expiry_date: "2025-12"
}
```

### 6.3 Doctor PWA IndexedDB Schema

```javascript
// Store: my_credentials
{
  prescriber_id: "DOC-001",
  name: "王大明",
  private_key: "base64...",  // Encrypted at rest
  public_key: "base64...",
  certificate: { ... }
}

// Store: recent_patients
{
  patient_id: "P0042",
  name: "陳小華",
  age_group: "adult",
  last_seen: "2025-12-21T14:00:00Z"
}

// Store: issued_rx
{
  rx_id: "RX-DOC001-20251221-0042",
  patient_id: "P0042",
  items: [...],
  issued_at: "2025-12-21T14:30:00Z",
  qr_displayed: true
}

// Store: medication_catalog
{
  code: "MED-PARA-500",
  name: "Paracetamol 500mg",
  category: "解熱鎮痛",
  default_dose: "1-2 tab",
  default_freq: "TID",
  is_controlled: false,
  common_instructions: ["飯後服用", "需要時服用"]
}
```

---

## 7. Implementation Roadmap

### Phase 5A: Core Protocol (Week 1-2)

**Deliverables**:
- Rx packet builder (Python + JS)
- Prescriber key management
- Rx signing / verification

**Files**:
```
/shared/
├── crypto/
│   └── prescriber.py     # Prescriber key management
├── protocol/
│   ├── rx.py             # RX_ORDER builder
│   └── dispense.py       # DISPENSE_RECORD builder
└── js/
    ├── xirs-rx.js        # Browser Rx handling
    └── xirs-dispense.js  # Browser dispense handling
```

### Phase 5B: Doctor PWA (Week 2-3)

**Deliverables**:
- Doctor PWA with patient selection
- Medication catalog
- Rx creation and signing
- QR display

**Files**:
```
/frontend/doctor/
├── index.html
├── manifest.json
└── service-worker.js
```

### Phase 5C: Pharmacy Station Extension (Week 3-4)

**Deliverables**:
- Rx scanner and verification
- Dispense queue UI
- Controlled substance workflow
- Inventory integration

**Files**:
```
/frontend/pharmacy/
├── index.html           # Extend from /station/
├── manifest.json
└── service-worker.js
```

### Phase 5D: Hub Integration (Week 4-5)

**Deliverables**:
- Prescriber management API
- Rx/Dispense sync endpoints
- Audit reporting

**Endpoints**:
| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/prescriber/register` | Register new prescriber |
| GET | `/api/prescriber/{id}/cert` | Get prescriber certificate |
| GET | `/api/prescriber/certs` | List all certs (for Pharmacy sync) |
| POST | `/api/rx/ingest` | Receive Rx from report |
| POST | `/api/dispense/ingest` | Receive dispense record |
| GET | `/api/rx/audit` | View Rx audit log |

---

## 8. Migration & Deployment

### 8.1 Prescriber Onboarding

```
1. Hub Admin creates prescriber account
   └── Generates Ed25519 keypair
   └── Creates PRESCRIBER_CERT signed by Hub

2. Prescriber receives credentials
   └── QR code containing private key (one-time display)
   └── Or secure USB transfer

3. Doctor PWA imports credentials
   └── Scan QR or paste key
   └── Store encrypted in IndexedDB

4. Pharmacy Stations sync prescriber certs
   └── Download via Runner or initial pairing
   └── Verify Hub signature
```

### 8.2 Medication Catalog Distribution

```
Hub maintains master medication catalog
  │
  ├─► Doctor PWA (minimal: code, name, common doses)
  │
  └─► Pharmacy Station (full: code, name, stock, controlled flag)
```

### 8.3 Backward Compatibility

- Existing Stations continue to work as supply-only
- Pharmacy mode is opt-in activation
- Doctor PWA is separate app

---

## 9. Appendix

### A. Comparison with Full HIS

| Feature | Lite CPOE (This Spec) | Full HIS |
|---------|----------------------|----------|
| Rx creation | ✓ Simple form | Complex with templates |
| Signature | ✓ Ed25519 | PKI/Certificate |
| Interaction check | ✗ Pharmacist judgment | ✓ Automated |
| Allergy check | ✗ Manual note | ✓ Automated |
| EMR integration | ✗ None | ✓ Full |
| Billing | ✗ None | ✓ Full |
| Regulatory compliance | Emergency use | Full e-Rx compliance |
| Offline capable | ✓ Yes | Usually No |
| Setup complexity | Low | High |

### B. FHIR Mapping (Future)

For future interoperability:

| Lite CPOE | FHIR R4 Resource |
|-----------|------------------|
| RX_ORDER | MedicationRequest |
| DISPENSE_RECORD | MedicationDispense |
| prescriber | Practitioner |
| patient | Patient (minimal) |
| audit log | AuditEvent |

### C. Regulatory Considerations

This system is designed for **災難醫療緊急應變 (Disaster Medical Response)** where normal regulatory requirements may be suspended. In normal operations:

- E-prescription requires 健保署 certification
- Controlled substances require additional reporting
- Full patient consent workflows

These are explicitly out of scope for emergency use.

---

*Document Version: 1.0*
*Created: 2025-12-21*
*Status: Draft - Pending Review*
*Authors: Claude (AI), with input from Gemini & ChatGPT*
