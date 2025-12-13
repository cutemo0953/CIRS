# IRS Donation Flow Specification

**Version:** 1.0
**Date:** 2025-12-12
**Status:** Draft
**Scope:** CIRS (Inbound) & HIRS (Outbound)

---

## Why We Need This (為什麼做這件事)

### 問題背景

在災難救援情境中，除了「避難所發放物資給民眾」(DISTRIBUTION)，還有一個重要的反向流程：**民眾捐贈物資給避難所**。

目前的痛點：
1. **CIRS 沒有正式的捐贈入庫流程** - 志工只能用一般的「新增庫存」，無法追蹤捐贈來源
2. **HIRS 使用者無法同步更新** - 捐贈後，HIRS 庫存仍顯示舊數量
3. **缺乏捐贈紀錄** - 捐贈者沒有「數位收據」證明自己捐過什麼

### 設計哲學：實體優先，數位為輔

**核心原則：Human Inspection First (No HIRS-to-CIRS scanning)**

為什麼不讓 CIRS 直接掃描 HIRS 的 QR Code 來入庫？

1. **品質控管** - 志工必須親眼檢查物資（過期？損壞？數量對嗎？）
2. **防止詐騙** - 如果可以「掃一下就入庫」，有人可能拿假 QR Code 騙取捐贈證明
3. **實際情況** - 捐贈者帶來的物資可能與 HIRS 庫存不符（臨時多帶、少帶）

因此，流程是：
```
[實體物資] → [志工清點] → [CIRS 入庫] → [產生收據 QR] → [HIRS 掃描] → [選擇性扣庫存]
```

---

## 1. User Journey (使用者旅程)

```
┌─────────────────────────────────────────────────────────────────────┐
│                        捐贈流程 (Donation Flow)                       │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  民眾 (HIRS)                              志工 (CIRS)                │
│  ──────────                              ──────────                 │
│                                                                     │
│  1. 帶物資到避難所 ──────────────────────>                           │
│                                                                     │
│                                          2. 人工清點                 │
│                                             - 檢查品質               │
│                                             - 確認數量               │
│                                             - 剔除不合格             │
│                                                                     │
│                                          3. 系統入庫                 │
│                                             - 輸入品項               │
│                                             - 選擇「來源：捐贈」     │
│                                             - 填寫捐贈者姓名(選填)   │
│                                                                     │
│                                          4. 產生收據 QR Code         │
│                        <─────────────────────────────────────────── │
│                                                                     │
│  5. 用 HIRS 掃描收據                                                 │
│     - 看到捐贈明細                                                   │
│     - 選擇是否扣除庫存                                               │
│     - 保存捐贈紀錄                                                   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. Data Protocol (資料協定)

### 2.1 Message Type

新增 `DONATION_RECEIPT` 到 IRS Interop Spec 的 MESSAGE_TYPES。

| Type | Direction | Description |
|------|-----------|-------------|
| `DISTRIBUTION` | CIRS → HIRS | 物資發放 |
| `DONATION_RECEIPT` | CIRS → HIRS | 捐贈收據 |
| `TEMPLATE` | Any → Any | 物資包範本 |

### 2.2 Envelope Format

```json
{
  "schema_version": "1.0",
  "message_type": "DONATION_RECEIPT",
  "issuer": {
    "system": "CIRS",
    "site_id": "CIRS-TPE-001",
    "site_name": "台北社區物資站"
  },
  "timestamp": "2025-12-12T15:00:00+08:00",
  "message_id": "uuid-v4",
  "payload": {
    "receipt_id": "DON-CIRS-TPE-001-20251212-001",
    "donor_name": "王先生",
    "items": [
      {
        "item_code": "WATER-500ML",
        "name": "礦泉水 500ml",
        "qty": 10,
        "unit": "瓶",
        "category": "water"
      },
      {
        "item_code": "FOOD-INSTANT-NOODLE",
        "name": "泡麵",
        "qty": 5,
        "unit": "包",
        "category": "food"
      }
    ],
    "thank_you_note": "感謝您的愛心捐贈！",
    "notes": ""
  }
}
```

### 2.3 Receipt ID Format

```
DON-{SITE_ID}-{YYYYMMDD}-{SEQ}
```

範例：`DON-CIRS-TPE-001-20251212-001`

---

## 3. CIRS Specification (接收端)

### 3.1 UI/UX: 捐贈入庫

**位置**: 庫存管理 → 新增庫存 (或獨立的「接收捐贈」按鈕)

**流程**:

1. **選擇入庫來源**
   - `[ ] 採購`
   - `[x] 捐贈` ← 選擇此項
   - `[ ] 調撥`
   - `[ ] 其他`

2. **填寫捐贈者資訊** (選填)
   - 捐贈者姓名：`[王先生_________]`
   - 備註：`[________________]`

3. **輸入物資明細**
   - 使用現有的物品選擇器
   - 可新增多個品項

4. **確認入庫**
   - 按下「確認」後：
     - 庫存 +N
     - 記錄 EventLog (event_type: RESOURCE_IN, reason: DONATION)
     - **顯示捐贈收據 QR Code**

### 3.2 Backend API

**Endpoint**: `POST /api/inventory/inbound`

**Request**:
```json
{
  "items": [
    { "item_id": 1, "quantity": 10 },
    { "item_id": 2, "quantity": 5 }
  ],
  "source": "donation",
  "donor_name": "王先生",
  "notes": ""
}
```

**Response**:
```json
{
  "success": true,
  "message": "入庫成功",
  "receipt": {
    "schema_version": "1.0",
    "message_type": "DONATION_RECEIPT",
    ...
  }
}
```

### 3.3 Database Schema

**EventLog 擴充**:
```sql
-- 新增 reason 欄位的可能值
-- reason: 'DONATION' | 'PURCHASE' | 'TRANSFER' | 'ADJUSTMENT' | 'OTHER'

-- 新增 metadata 欄位 (JSON)
-- metadata: { "donor_name": "王先生", "receipt_id": "DON-..." }
```

---

## 4. HIRS Specification (捐贈端)

### 4.1 Feature: 掃描收據 & Smart Deduct

**觸發**: 掃描到 `message_type: DONATION_RECEIPT` 時

**流程**:

1. **解析收據**
   - 顯示來源站點
   - 顯示捐贈明細

2. **Smart Match**
   - 比對 `item_code` 或 `name`
   - 找出使用者庫存中對應的品項

3. **詢問扣除**
   ```
   ┌────────────────────────────────────────┐
   │  收到來自「台北社區物資站」的捐贈收據    │
   │                                        │
   │  📦 礦泉水 500ml × 10 瓶               │
   │     └ 您的庫存: 12 瓶 → 剩 2 瓶        │
   │                                        │
   │  📦 泡麵 × 5 包                         │
   │     └ 您的庫存: 3 包 → 全部扣除         │
   │                                        │
   │  ─────────────────────────────────────  │
   │  是否從您的庫存中扣除這些項目？          │
   │                                        │
   │  [ 是，扣除庫存 ]  [ 否，僅記錄 ]       │
   └────────────────────────────────────────┘
   ```

4. **邊界情況處理**

   | 情況 | 處理方式 |
   |------|----------|
   | 庫存 ≥ 收據數量 | 正常扣除 |
   | 庫存 < 收據數量 | 扣除現有庫存，提示「已扣除 N 個」 |
   | 庫存中無此品項 | 僅記錄，不扣除 |
   | 重複掃描同一收據 | 提示「此收據已記錄於 YYYY-MM-DD」 |

### 4.2 Feature: 捐贈歷史

**位置**: 設定 → 捐贈紀錄 (或與「社區領取記錄」合併為「物資往來記錄」)

**資料結構**:
```javascript
donationHistory: [
  {
    id: "uuid",
    receiptId: "DON-CIRS-TPE-001-20251212-001",
    destination: "台北社區物資站",
    destinationSystem: "CIRS",
    items: [
      { name: "礦泉水", qty: 10, unit: "瓶", deducted: true },
      { name: "泡麵", qty: 5, unit: "包", deducted: true }
    ],
    timestamp: "2025-12-12T15:00:00+08:00",
    scannedAt: "2025-12-12T15:05:00+08:00"
  }
]
```

### 4.3 Feature: 手動捐贈 (無收據)

**位置**: 物品詳情 → 移除/消耗

**更新**: 在「移除原因」中加入「捐贈」選項

```
移除原因：
[ ] 已使用
[ ] 已過期
[x] 捐贈
[ ] 遺失
[ ] 其他
```

選擇「捐贈」後，記錄到本地捐贈歷史（無 receiptId）。

---

## 5. Security Considerations

### 5.1 收據不可偽造

- `message_id` 使用 UUID v4
- `receipt_id` 包含站點 ID + 日期 + 序號
- Phase 2 可加入 HMAC 簽章

### 5.2 防重複掃描

HIRS 本地儲存已掃描的 `receipt_id`，避免重複入帳。

### 5.3 隱私保護

- `donor_name` 是選填的
- 收據不包含捐贈者的 HIRS 識別碼

---

## 6. Implementation Checklist

### CIRS

- [ ] 更新 `irs-schema.js` 加入 `DONATION_RECEIPT`
- [ ] API: `POST /api/inventory/inbound` 支援 `source=donation`
- [ ] API: 回傳 `DONATION_RECEIPT` envelope
- [ ] Frontend: 新增庫存時可選擇「來源：捐贈」
- [ ] Frontend: 入庫後顯示收據 QR Code
- [ ] Database: EventLog 加入 `reason` 和 `metadata`

### HIRS

- [ ] Scanner: 處理 `DONATION_RECEIPT` 類型
- [ ] Logic: Smart Deduct (比對品項 → 建議扣除)
- [ ] Logic: 防重複掃描 (儲存已掃描的 receipt_id)
- [ ] UI: 捐贈確認對話框
- [ ] UI: 捐贈歷史頁面
- [ ] Feature: 手動捐贈（移除原因加入「捐贈」）

---

## 7. Future Enhancements (Phase 2)

1. **電子感謝狀** - 捐贈達一定數量，自動產生感謝狀 PDF
2. **捐贈統計** - CIRS 後台顯示捐贈總量、排行榜
3. **HMAC 簽章** - 防止收據偽造
4. **捐贈預約** - HIRS 使用者可預告要捐什麼，CIRS 看到通知

---

## Appendix: Architecture Decision Record (ADR)

### ADR-003: 為什麼不讓 CIRS 掃描 HIRS QR Code？

**Context**: 最初設計考慮讓 CIRS 直接掃描 HIRS 的庫存 QR Code 來自動入庫。

**Decision**: 拒絕此方案，改用「人工清點 → 數位收據」流程。

**Rationale**:
1. **品質無法保證** - QR Code 說有 10 瓶水，實際可能只有 8 瓶或已過期
2. **安全風險** - 有人可能偽造 QR Code 騙取捐贈證明
3. **責任歸屬** - 入庫後發現問題，難以追究是捐贈者還是志工的責任
4. **實際操作** - 志工本來就要檢查物資，多掃一個 QR Code 沒有減輕工作量

**Consequences**:
- 流程稍微繁瑣（志工要手動輸入）
- 但保證了物資品質和系統安全性
- 捐贈者仍可獲得數位收據

### ADR-004: Receipt ID 格式設計

**Context**: 需要一個可識別、可追蹤的收據編號。

**Decision**: 使用 `DON-{SITE_ID}-{YYYYMMDD}-{SEQ}` 格式。

**Rationale**:
1. **可讀性** - 一眼看出是捐贈收據、哪個站點、哪天
2. **唯一性** - SITE_ID + 日期 + 序號組合不會重複
3. **可排序** - 按日期自然排序
4. **可查詢** - 捐贈者可用收據 ID 向站點查詢

**Example**: `DON-CIRS-TPE-001-20251212-003` = 台北站 2025/12/12 第 3 張捐贈收據
