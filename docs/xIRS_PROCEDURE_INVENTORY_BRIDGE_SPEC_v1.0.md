# xIRS Procedure-Inventory Bridge Spec v1.0

**Version**: 1.0
**Theme**: Low-Coupling Bridge Between Clinical Procedures and Inventory Deduction
**Supplements**: xIRS_LITE_CPOE_SPEC_v1.0.md, STATION_PWA_DEV_SPEC_v2.3.md
**Date**: 2025-12-22
**Status**: Draft
**Contributors**: Claude, Gemini, ChatGPT

---

## 1. Executive Summary

### 1.1 The Variance Problem

In disaster medical response, **Order ≠ Execution**:

```
醫囑 (Order)              實際執行 (Actual)
────────────              ──────────────────
插管 x1                   第一次 7.5mm 失敗
                          第二次 7.0mm 成功
                          消耗：2 支 ET tube

輸液 1000mL               病患躁動撕掉 IV
                          重新建立 IV
                          消耗：2 套 IV set
```

**結論**：自動扣庫 = 假資料。必須由執行者確認實際消耗。

### 1.2 Solution: Low-Coupling Bridge

```
┌─────────────────┐                      ┌─────────────────┐
│  Clinical PWA   │                      │  Station PWA    │
│  (Class B)      │                      │  (Class C)      │
│                 │                      │                 │
│  患者資訊       │    event_ref         │  庫存異動       │
│  處置記錄       │◄───────────────────► │  無患者資訊     │
│  Ed25519 簽章   │                      │  HMAC 驗證      │
└────────┬────────┘                      └────────┬────────┘
         │                                        │
         │              ┌──────────┐              │
         └──────────────►   Hub    ◄──────────────┘
                        │ 對帳合併 │
                        └──────────┘
```

**核心原則**：
- Station **永遠不處理** 患者可識別資訊
- Clinical 和 Inventory 透過 `event_ref` (UUID) 鬆耦合連結
- 只有 Hub 能完整對帳

---

## 2. Architecture Overview

### 2.1 Data Classification Alignment

| Class | Content | Storage | Example |
|-------|---------|---------|---------|
| **Class A** | 完全加密，Hub-only | Hub DB (encrypted) | 身分證、完整病歷 |
| **Class B** | 臨床資料，加密傳輸 | Clinical PWA → Hub | 處置記錄、用藥記錄 |
| **Class C** | 物流資料，明文可讀 | Station PWA → Hub | 庫存異動、進出貨 |

### 2.2 The Bridge Pattern

```
┌─────────────────────────────────────────────────────────────────────┐
│                    PROCEDURE → INVENTORY BRIDGE                      │
│                                                                      │
│  ┌──────────────┐         ┌──────────────┐         ┌──────────────┐ │
│  │  PROCEDURE   │         │ CONSUMPTION  │         │ CONSUMPTION  │ │
│  │    ORDER     │────────►│    TICKET    │────────►│   RECORD     │ │
│  │  (Clinical)  │         │  (QR Bridge) │         │  (Station)   │ │
│  └──────────────┘         └──────────────┘         └──────────────┘ │
│        │                        │                        │          │
│        │ Contains:              │ Contains:              │ Contains:│
│        │ - patient_ref          │ - event_ref            │ - event_ │
│        │ - performer_id         │ - items[]              │   ref    │
│        │ - procedure_code       │ - hmac                 │ - items  │
│        │ - suggested_items      │ - NO patient info      │ - ts     │
│        │ - Ed25519 sig          │                        │ - hmac   │
│        │                        │                        │          │
│        ▼                        ▼                        ▼          │
│   Clinical DB              QR Code / NFC            Station DB      │
│   (Encrypted)              (Transport)              (Plain Text)    │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Data Structures

### 3.1 PROCEDURE_ORDER (Clinical Side)

Created by Doctor/Nurse when ordering a procedure.

```json
{
  "type": "PROCEDURE_ORDER",
  "version": "1.0",

  "order_id": "ORD-DOC001-20251222-0015",
  "event_ref": "evt_a1b2c3d4e5f6",

  "performer_id": "DOC-001",
  "performer_name": "王大明醫師",

  "patient_ref": "***0042",

  "procedure": {
    "code": "INTUBATION",
    "name": "氣管內管插管",
    "category": "AIRWAY"
  },

  "suggested_items": [
    {
      "code": "DEV-ETTUBE-7.5",
      "name": "氣管內管 7.5mm",
      "qty": 1,
      "required": true
    },
    {
      "code": "DEV-LARYNGO-MAC3",
      "name": "喉頭鏡 Mac #3",
      "qty": 1,
      "required": true
    },
    {
      "code": "DEV-STYLET",
      "name": "導引鋼絲",
      "qty": 1,
      "required": false
    },
    {
      "code": "MED-XYLOCAINE-SPRAY",
      "name": "Xylocaine Spray",
      "qty": 1,
      "required": false
    }
  ],

  "priority": "STAT",
  "notes": "預期困難插管，備妥 Video Laryngoscope",

  "ts": 1734858600,
  "signature": "Ed25519-Base64..."
}
```

**Storage**: Clinical PWA IndexedDB (encrypted) → Hub Clinical DB

### 3.2 CONSUMPTION_TICKET (QR Bridge)

Generated by executor (Nurse/Tech) after procedure completion. **NO patient identifiable information**.

```json
{
  "type": "CONSUMPTION_TICKET",
  "version": "1.0",

  "ticket_id": "TKT-20251222-0042",
  "event_ref": "evt_a1b2c3d4e5f6",

  "source": "CLINICAL",
  "source_station": "NURSE-STATION-A",

  "items": [
    { "code": "DEV-ETTUBE-7.5", "qty": 1 },
    { "code": "DEV-ETTUBE-7.0", "qty": 1 },
    { "code": "DEV-LARYNGO-MAC3", "qty": 1 },
    { "code": "DEV-STYLET", "qty": 1 }
  ],

  "executor_id": "NURSE-001",
  "ts": 1734859200,

  "hmac": "HMAC-SHA256(station_secret, canonical_payload)"
}
```

**Transport**: QR Code (xIRS format) or NFC

**Privacy Guarantee**:
- ❌ No `patient_ref`
- ❌ No `patient_name`
- ❌ No `procedure_code` (only `event_ref`)
- ✅ Only item codes and quantities

### 3.3 TASK (Logistics-Safe Wrapper)

Optional transformation to create an assignable task without leaking patient details.

```json
{
  "type": "TASK",
  "version": "1.0",

  "task_id": "TASK-20251222-1102",
  "task_kind": "PROCEDURE_EXECUTION",
  "event_ref": "evt_a1b2c3d4e5f6",

  "procedure_code": "INTUBATION",
  "priority": "STAT",
  "assigned_to_role": "NURSE",
  "due_window_min": 30,

  "ts": 1734858605
}
```

**Note**: No `patient_ref` - this can be shown to any station without privacy concerns.

### 3.4 CONSUMPTION_RECORD (Station Side)

Created by Station when scanning CONSUMPTION_TICKET. This is the **authoritative deduction trigger**.

```json
{
  "type": "CONSUMPTION_RECORD",
  "version": "1.0",

  "record_id": "CON-SUPPLY01-20251222-0089",
  "ticket_id": "TKT-20251222-0042",
  "event_ref": "evt_a1b2c3d4e5f6",

  "station_id": "STATION-SUPPLY-A",
  "operator_id": "VOL-015",

  "items_used": [
    {
      "code": "DEV-ETTUBE-7.5",
      "qty": 1,
      "lot": "LOT2024A",
      "expiry": "2025-06"
    },
    {
      "code": "DEV-ETTUBE-7.0",
      "qty": 1,
      "lot": "LOT2024A",
      "expiry": "2025-06"
    },
    {
      "code": "DEV-LARYNGO-MAC3",
      "qty": 1,
      "lot": null,
      "expiry": null
    },
    {
      "code": "DEV-STYLET",
      "qty": 1,
      "lot": null,
      "expiry": null
    }
  ],

  "variance": {
    "added": [
      { "code": "DEV-ETTUBE-7.0", "qty": 1, "reason": "REATTEMPT" }
    ],
    "removed": [
      { "code": "MED-XYLOCAINE-SPRAY", "qty": 1, "reason": "NOT_NEEDED" }
    ]
  },

  "variance_reason": "REATTEMPT",

  "deducted_at": 1734859500,
  "ts": 1734859500,
  "nonce": "f6e5d4c3b2a1",
  "packet_id": "PKT-SUPPLY01-20251222-8888",

  "hmac": "HMAC-SHA256(station_secret, canonical_payload)"
}
```

**Variance Reason Codes**:
| Code | Meaning | 中文 |
|------|---------|------|
| `EXACT` | Matched suggestion exactly | 完全符合 |
| `REATTEMPT` | Procedure reattempted | 重新嘗試 |
| `EXTRA_BLEEDING` | Extra supplies for bleeding | 額外止血 |
| `CONTAMINATION` | Supplies contaminated | 污染更換 |
| `SUBSTITUTION` | Item substituted | 藥品替換 |
| `NOT_NEEDED` | Item not needed | 未使用 |

**Storage**: Station PWA IndexedDB → Hub Logistics DB

---

## 4. Procedure Bundle Templates

### 4.1 Template Structure

Pre-defined bundles to speed up consumption recording.

```json
{
  "type": "PROCEDURE_BUNDLE",
  "version": "1.0",

  "bundles": [
    {
      "procedure_code": "INTUBATION",
      "name": "插管包",
      "category": "AIRWAY",
      "items": [
        { "code": "DEV-ETTUBE-7.5", "qty": 1, "required": true },
        { "code": "DEV-ETTUBE-7.0", "qty": 1, "required": false },
        { "code": "DEV-LARYNGO-MAC3", "qty": 1, "required": true },
        { "code": "DEV-STYLET", "qty": 1, "required": false },
        { "code": "MED-XYLOCAINE-SPRAY", "qty": 1, "required": false },
        { "code": "DEV-TAPE-SILK", "qty": 1, "required": true }
      ]
    },
    {
      "procedure_code": "IV_ACCESS",
      "name": "靜脈通路包",
      "category": "VASCULAR",
      "items": [
        { "code": "DEV-IVCATH-20G", "qty": 1, "required": true },
        { "code": "DEV-IVSET", "qty": 1, "required": true },
        { "code": "DEV-TEGADERM", "qty": 1, "required": true },
        { "code": "DEV-TOURNIQUET", "qty": 1, "required": false },
        { "code": "MED-ALCOHOL-SWAB", "qty": 3, "required": true }
      ]
    },
    {
      "procedure_code": "WOUND_SUTURE",
      "name": "縫合包",
      "category": "WOUND",
      "items": [
        { "code": "DEV-SUTURE-NYLON-4-0", "qty": 1, "required": true },
        { "code": "DEV-NEEDLE-HOLDER", "qty": 1, "required": true },
        { "code": "DEV-FORCEPS-ADSON", "qty": 1, "required": true },
        { "code": "DEV-SCISSORS-SUTURE", "qty": 1, "required": true },
        { "code": "MED-LIDOCAINE-2", "qty": 1, "required": true },
        { "code": "DEV-SYRINGE-10ML", "qty": 1, "required": true }
      ]
    },
    {
      "procedure_code": "CHEST_TUBE",
      "name": "胸管置放包",
      "category": "THORACIC",
      "items": [
        { "code": "DEV-CHESTTUBE-28FR", "qty": 1, "required": true },
        { "code": "DEV-CHEST-DRAINAGE", "qty": 1, "required": true },
        { "code": "DEV-SCALPEL-11", "qty": 1, "required": true },
        { "code": "DEV-CLAMP-KELLY", "qty": 1, "required": true },
        { "code": "DEV-SUTURE-SILK-0", "qty": 1, "required": true },
        { "code": "MED-LIDOCAINE-2", "qty": 2, "required": true }
      ]
    },
    {
      "procedure_code": "FOLEY_CATH",
      "name": "導尿包",
      "category": "URINARY",
      "items": [
        { "code": "DEV-FOLEY-16FR", "qty": 1, "required": true },
        { "code": "DEV-UROBAG", "qty": 1, "required": true },
        { "code": "DEV-SYRINGE-10ML", "qty": 1, "required": true },
        { "code": "MED-XYLOCAINE-JELLY", "qty": 1, "required": true },
        { "code": "MED-NS-10ML", "qty": 1, "required": true }
      ]
    },
    {
      "procedure_code": "NG_TUBE",
      "name": "鼻胃管包",
      "category": "GI",
      "items": [
        { "code": "DEV-NGTUBE-16FR", "qty": 1, "required": true },
        { "code": "DEV-SYRINGE-50ML", "qty": 1, "required": true },
        { "code": "MED-XYLOCAINE-JELLY", "qty": 1, "required": false },
        { "code": "DEV-TAPE-SILK", "qty": 1, "required": true }
      ]
    },
    {
      "procedure_code": "CPR",
      "name": "急救包 (CPR)",
      "category": "RESUSCITATION",
      "items": [
        { "code": "MED-EPI-1MG", "qty": 3, "required": true },
        { "code": "MED-ATROPINE-0.5MG", "qty": 2, "required": false },
        { "code": "MED-AMIODARONE-150MG", "qty": 1, "required": false },
        { "code": "DEV-IVCATH-18G", "qty": 2, "required": true },
        { "code": "DEV-IVSET", "qty": 1, "required": true },
        { "code": "MED-NS-500ML", "qty": 1, "required": true }
      ]
    }
  ]
}
```

### 4.2 Bundle Selection UI (Clinical PWA)

```
┌─────────────────────────────────────────┐
│  處置記錄 - 選擇處置類型               │
├─────────────────────────────────────────┤
│                                         │
│  呼吸道 (Airway)                        │
│  ┌─────────────────────────────────┐   │
│  │ 🫁 插管 (Intubation)            │   │
│  │ 🫁 LMA 置放                      │   │
│  │ 🫁 氣切 (Tracheostomy)          │   │
│  └─────────────────────────────────┘   │
│                                         │
│  血管通路 (Vascular)                    │
│  ┌─────────────────────────────────┐   │
│  │ 💉 周邊靜脈 (Peripheral IV)     │   │
│  │ 💉 中心靜脈 (Central Line)      │   │
│  │ 💉 動脈導管 (Arterial Line)     │   │
│  └─────────────────────────────────┘   │
│                                         │
│  傷口處置 (Wound)                       │
│  ┌─────────────────────────────────┐   │
│  │ 🩹 傷口縫合                      │   │
│  │ 🩹 清創                          │   │
│  │ 🩹 燒傷處理                      │   │
│  └─────────────────────────────────┘   │
│                                         │
└─────────────────────────────────────────┘
```

---

## 5. Workflows

### 5.1 Standard Flow: Order → Execute → Consume

```
┌─────────────────────────────────────────────────────────────────────┐
│                    STANDARD CONSUMPTION FLOW                         │
│                                                                      │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐      │
│  │ 1.DOCTOR │    │ 2.NURSE  │    │ 3.NURSE  │    │ 4.STATION│      │
│  │ 開醫囑   │───►│ 執行處置 │───►│ 產生票券 │───►│ 掃描扣庫 │      │
│  └──────────┘    └──────────┘    └──────────┘    └──────────┘      │
│       │               │               │               │             │
│       ▼               ▼               ▼               ▼             │
│  PROCEDURE       PROCEDURE       CONSUMPTION     CONSUMPTION        │
│    ORDER        EXECUTION         TICKET          RECORD            │
│  (Clinical)     (Clinical)       (QR Code)       (Station)         │
│                                                                      │
│  Contains:       Contains:       Contains:       Contains:          │
│  - patient_ref   - actual items  - event_ref     - event_ref        │
│  - suggested     - complications - items[]       - items[]          │
│    items         - notes         - NO PHI        - lot/expiry       │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### 5.2 Emergency Flow: Execute First, Document Later

```
┌─────────────────────────────────────────────────────────────────────┐
│                    EMERGENCY CONSUMPTION FLOW                        │
│                                                                      │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐      │
│  │ 1.NURSE  │    │ 2.NURSE  │    │ 3.STATION│    │ 4.DOCTOR │      │
│  │ 緊急處置 │───►│ 拿耗材   │───►│ 事後扣庫 │───►│ 補開醫囑 │      │
│  │ (先做)   │    │ (先用)   │    │ (掃票券) │    │ (後補)   │      │
│  └──────────┘    └──────────┘    └──────────┘    └──────────┘      │
│       │               │               │               │             │
│       ▼               ▼               ▼               ▼             │
│  EMERGENCY       CONSUMPTION      CONSUMPTION     RETRO            │
│  PROCEDURE        TICKET           RECORD        ORDER             │
│   (Draft)        (HMAC)          (Confirmed)    (Approved)         │
│                                                                      │
│  ⏰ 2小時內必須完成補單                                             │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### 5.3 EMERGENCY_CONSUMPTION Structure

```json
{
  "type": "EMERGENCY_CONSUMPTION",
  "version": "1.0",

  "emergency_id": "EMRG-CON-20251222-0005",
  "event_ref": "evt_emergency_xyz",

  "executor_id": "NURSE-001",
  "executor_name": "王護理師",

  "reason": "MASS_CASUALTY",
  "reason_text": "多重傷患湧入，緊急取用止血帶",

  "items": [
    { "code": "DEV-TOURNIQUET-CAT", "qty": 5 },
    { "code": "DEV-GAUZE-4X4", "qty": 20 },
    { "code": "DEV-BANDAGE-ELASTIC", "qty": 5 }
  ],

  "consumed_at": 1734860000,

  "requires_retro_order": true,
  "retro_order_deadline": 1734867200,

  "witness_id": "NURSE-002",
  "witness_name": "林護理師",

  "ts": 1734860300,
  "hmac": "HMAC-SHA256..."
}
```

### 5.4 Return/Credit Flow

When items are opened but not used, or wrong items were picked:

```json
{
  "type": "CONSUMPTION_RETURN",
  "version": "1.0",

  "return_id": "RET-20251222-0003",
  "original_ticket_id": "TKT-20251222-0042",
  "event_ref": "evt_a1b2c3d4e5f6",

  "items": [
    {
      "code": "DEV-ETTUBE-7.0",
      "qty": 1,
      "reason": "UNOPENED",
      "condition": "RESTORABLE"
    }
  ],

  "returned_by": "NURSE-001",
  "received_by": "VOL-015",
  "station_id": "STATION-SUPPLY-A",

  "ts": 1734862000,
  "hmac": "HMAC-SHA256..."
}
```

**Return Reasons**:
| Code | Meaning | Restock? |
|------|---------|----------|
| `UNOPENED` | 未開封 | Yes |
| `WRONG_ITEM` | 拿錯 | Yes (if unopened) |
| `CANCELLED` | 處置取消 | Yes (if unopened) |
| `DAMAGED` | 損壞 | No (write-off) |
| `EXPIRED` | 過期 | No (write-off) |

---

## 6. Hub Reconciliation

### 6.1 Data Merge Query

When both Clinical and Station reports arrive at Hub:

```sql
-- Get complete picture of a procedure
SELECT
  p.procedure_code,
  p.performer_name,
  p.patient_ref,      -- Only visible at Hub
  c.items,
  c.deducted_at,
  c.station_id
FROM procedure_orders p
JOIN consumption_records c ON p.event_ref = c.event_ref
WHERE p.event_ref = 'evt_a1b2c3d4e5f6';
```

### 6.2 Reconciliation Report

```json
{
  "type": "RECONCILIATION_REPORT",
  "period": "2025-12-22",

  "matched": [
    {
      "event_ref": "evt_a1b2c3d4e5f6",
      "procedure": "INTUBATION",
      "patient_ref": "***0042",
      "performer": "DOC-001",
      "items_consumed": 4,
      "items_returned": 0,
      "status": "COMPLETE"
    }
  ],

  "unmatched_orders": [
    {
      "order_id": "ORD-DOC001-20251222-0020",
      "event_ref": "evt_pending123",
      "status": "PENDING_CONSUMPTION",
      "age_hours": 2.5
    }
  ],

  "unmatched_consumptions": [
    {
      "ticket_id": "TKT-20251222-0099",
      "event_ref": "evt_orphan456",
      "status": "ORPHAN_CONSUMPTION",
      "note": "Emergency consumption, pending retro order"
    }
  ]
}
```

---

## 7. UI Specifications

### 7.1 Clinical PWA - Consumption Ticket Generation

```
┌─────────────────────────────────────────┐
│  ← 返回      產生領用單                 │
├─────────────────────────────────────────┤
│                                         │
│  處置: 插管 (INTUBATION)                │
│  Event Ref: evt_a1b2***                 │
│                                         │
│  ─────────────────────────────────────  │
│                                         │
│  實際消耗品項:                          │
│  ┌─────────────────────────────────┐   │
│  │ ☑ 氣管內管 7.5mm           x 1  │ ✕ │
│  │ ☑ 氣管內管 7.0mm           x 1  │ ✕ │
│  │   (新增：第一次失敗)             │   │
│  ├─────────────────────────────────┤   │
│  │ ☑ 喉頭鏡 Mac #3            x 1  │   │
│  ├─────────────────────────────────┤   │
│  │ ☑ 導引鋼絲                 x 1  │   │
│  ├─────────────────────────────────┤   │
│  │ ☐ Xylocaine Spray          x 0  │   │
│  │   (未使用，取消勾選)             │   │
│  └─────────────────────────────────┘   │
│                                         │
│  ┌─────────────────────────────────┐   │
│  │    ➕ 新增其他消耗品             │   │
│  └─────────────────────────────────┘   │
│                                         │
│  ─────────────────────────────────────  │
│                                         │
│  ┌─────────────────────────────────┐   │
│  │      📱 產生領用單 QR Code       │   │
│  └─────────────────────────────────┘   │
│                                         │
└─────────────────────────────────────────┘
```

### 7.2 Station PWA - Consumption Ticket Scan

```
┌─────────────────────────────────────────┐
│  收貨                      STATION-A    │
├─────────────────────────────────────────┤
│                                         │
│  ┌─────────────────────────────────┐   │
│  │                                 │   │
│  │         📷 掃描區域             │   │
│  │                                 │   │
│  └─────────────────────────────────┘   │
│                                         │
│  掃描類型:                              │
│  ○ 進貨清單 (MANIFEST)                  │
│  ● 領用單 (CONSUMPTION_TICKET)          │
│  ○ 退還單 (RETURN)                      │
│                                         │
└─────────────────────────────────────────┘
```

### 7.3 Station PWA - Consumption Confirmation

```
┌─────────────────────────────────────────┐
│  ← 取消        確認扣庫                 │
├─────────────────────────────────────────┤
│                                         │
│  ✅ 領用單驗證通過                      │
│  Event: evt_a1b2***                     │
│  來源: NURSE-STATION-A                  │
│                                         │
│  ─────────────────────────────────────  │
│                                         │
│  扣除品項:                              │
│  ┌─────────────────────────────────┐   │
│  │ ☑ DEV-ETTUBE-7.5           x 1  │   │
│  │   庫存: 45 → 44 ✓               │   │
│  ├─────────────────────────────────┤   │
│  │ ☑ DEV-ETTUBE-7.0           x 1  │   │
│  │   庫存: 38 → 37 ✓               │   │
│  ├─────────────────────────────────┤   │
│  │ ☑ DEV-LARYNGO-MAC3         x 1  │   │
│  │   庫存: 12 → 11 ✓               │   │
│  ├─────────────────────────────────┤   │
│  │ ☑ DEV-STYLET               x 1  │   │
│  │   庫存: 28 → 27 ✓               │   │
│  └─────────────────────────────────┘   │
│                                         │
│  ⚠️ 注意：此操作將直接扣除庫存          │
│                                         │
│  ┌─────────────────────────────────┐   │
│  │        ✅ 確認扣庫               │   │
│  └─────────────────────────────────┘   │
│                                         │
│  ┌─────────────────────────────────┐   │
│  │        ❌ 取消                   │   │
│  └─────────────────────────────────┘   │
│                                         │
└─────────────────────────────────────────┘
```

---

## 8. Security Specifications

### 8.1 HMAC Verification

All tickets and records are authenticated with HMAC-SHA256 using `station_secret`:

```javascript
function generateHMAC(payload, stationSecret) {
  // 1. Remove hmac field if present
  const signable = { ...payload };
  delete signable.hmac;

  // 2. Canonical JSON
  const message = JSON.stringify(signable, Object.keys(signable).sort());

  // 3. HMAC-SHA256
  return crypto.createHmac('sha256', stationSecret)
    .update(message)
    .digest('base64');
}

function verifyHMAC(payload, stationSecret) {
  const expected = generateHMAC(payload, stationSecret);
  return crypto.timingSafeEqual(
    Buffer.from(payload.hmac, 'base64'),
    Buffer.from(expected, 'base64')
  );
}
```

### 8.2 Replay Prevention

Station maintains `processed_tickets` store:

```javascript
// IndexedDB: processed_tickets
{
  ticket_id: "TKT-20251222-0042",  // Primary key
  event_ref: "evt_a1b2c3d4e5f6",
  processed_at: "2025-12-22T14:45:00Z",
  operator_id: "VOL-015"
}
```

### 8.3 Privacy Boundaries

| Field | CONSUMPTION_TICKET | Station Display | Hub Storage |
|-------|-------------------|-----------------|-------------|
| `patient_ref` | ❌ Never | ❌ Never | ✅ Via JOIN |
| `patient_name` | ❌ Never | ❌ Never | ✅ Via JOIN |
| `performer_id` | ❌ Never | ❌ Never | ✅ Via JOIN |
| `event_ref` | ✅ Yes | ✅ Yes | ✅ Yes |
| `items[]` | ✅ Yes | ✅ Yes | ✅ Yes |

---

## 9. QR Code Format

Same as existing xIRS protocol:

```
Format: xIRS|{seq}/{total}|{chunk_data_base64}

Example (single QR):
xIRS|1/1|eyJ0eXBlIjoiQ09OU1VNUFRJT05fVElDS0VUIi...
```

Payload after base64 decode:
```json
{
  "type": "CONSUMPTION_TICKET",
  "version": "1.0",
  "ticket_id": "TKT-20251222-0042",
  "event_ref": "evt_a1b2c3d4e5f6",
  "source": "CLINICAL",
  "items": [...],
  "ts": 1734859200,
  "hmac": "..."
}
```

---

## 10. Implementation Status

| Component | Status | Location |
|-----------|--------|----------|
| CONSUMPTION_TICKET schema | ✅ Defined | This spec |
| CONSUMPTION_RECORD schema | ✅ Defined | This spec |
| Procedure Bundle Templates | ✅ Defined | This spec |
| Clinical PWA - Ticket Generation | ⏳ Pending | `/frontend/doctor/` or `/frontend/nurse/` |
| Station PWA - Ticket Scan | ⏳ Pending | `/frontend/station/` |
| Hub Reconciliation API | ⏳ Pending | `/backend/routes/` |
| Emergency Consumption Flow | ⏳ Pending | - |
| Return/Credit Flow | ⏳ Pending | - |

---

## 11. Migration Notes

### 11.1 Updating Lite CPOE Spec

Remove patient identifiable information from QR payloads:

```diff
// RX_ORDER - Before
{
  "patient": {
-   "id": "P0042",
-   "name": "陳小華",
-   "age_group": "adult",
-   "weight_kg": 65
+   "ref": "***0042"
  }
}
```

### 11.2 Updating Station PWA

Add CONSUMPTION_TICKET to scan types:

```javascript
const SCAN_TYPES = [
  'MANIFEST',           // Existing
  'REPORT',             // Existing
  'CONSUMPTION_TICKET', // NEW
  'CONSUMPTION_RETURN'  // NEW
];
```

---

*Document Version: 1.0*
*Created: 2025-12-22*
*Status: Draft - Pending Implementation*
*Contributors: Claude, Gemini, ChatGPT*
