# IRS 跨系統互通規格 (Interoperability Specification)

> 版本: 1.0.0
> 日期: 2025-12-12
> 狀態: Approved

---

## 1. 概述

### 1.1 系統架構

```
┌─────────────────────────────────────────────────────────────────┐
│                        IRS 生態系統                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────┐    QR Sync     ┌─────────────┐                │
│  │    CIRS     │ ─────────────► │    HIRS     │                │
│  │  社區物資站  │                │  家庭物資    │                │
│  │  (Backend)  │                │  (PWA)      │                │
│  └──────┬──────┘                └─────────────┘                │
│         │                                                       │
│         │ Triage Link                                          │
│         ▼                                                       │
│  ┌─────────────┐                                               │
│  │    MIRS     │                                               │
│  │  醫療站庫存  │                                               │
│  │  (Backend)  │                                               │
│  └─────────────┘                                               │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 系統職責

| 系統 | 職責 | 資料儲存 | 連線需求 |
|------|------|---------|---------|
| HIRS | 家庭防災物資管理 | LocalStorage (PWA) | 離線優先 |
| CIRS | 社區物資站營運 | SQLite (Raspberry Pi) | 區域網路 |
| MIRS | 醫療站庫存管理 | SQLite (Raspberry Pi) | 區域網路 |
| CoreIRS | 商業庫存管理 | SQLite (Raspberry Pi) | 區域網路 |

### 1.3 互通場景

| 場景 | 來源 | 目標 | 傳輸方式 |
|------|------|------|---------|
| 社區發放 → 家庭接收 | CIRS | HIRS | QR Code |
| 傷患分流連結 | CIRS | MIRS | Triage Tag ID |
| 範本分享 | HIRS | HIRS | QR Code / JSON |

---

## 2. 資料交換格式

### 2.1 通用信封格式 (Envelope)

所有跨系統資料交換必須使用此信封格式：

```json
{
  "$schema": "https://irs.local/schemas/envelope/v1.json",
  "schema_version": "1.0",
  "message_type": "DISTRIBUTION | TEMPLATE | INVENTORY_SYNC",
  "issuer": {
    "system": "CIRS | HIRS | MIRS",
    "site_id": "string",
    "site_name": "string"
  },
  "timestamp": "ISO 8601 datetime",
  "message_id": "uuid v4",
  "payload": { },
  "signature": "optional HMAC-SHA256"
}
```

#### 欄位說明

| 欄位 | 必填 | 說明 |
|------|------|------|
| schema_version | Y | 固定 "1.0"，未來升級時遞增 |
| message_type | Y | 訊息類型，決定 payload 結構 |
| issuer.system | Y | 來源系統 |
| issuer.site_id | Y | 站點代碼 (如 CIRS-TPE-001) |
| issuer.site_name | N | 站點顯示名稱 |
| timestamp | Y | ISO 8601 格式 |
| message_id | Y | UUID v4，用於去重 |
| payload | Y | 依 message_type 不同結構 |
| signature | N | HMAC-SHA256，Phase 2 實作 |

---

### 2.2 DISTRIBUTION - 發放記錄

CIRS 發放物資給民眾，產生 QR Code 供 HIRS 掃描接收。

```json
{
  "schema_version": "1.0",
  "message_type": "DISTRIBUTION",
  "issuer": {
    "system": "CIRS",
    "site_id": "CIRS-TPE-001",
    "site_name": "台北社區物資站"
  },
  "timestamp": "2025-12-12T10:30:00+08:00",
  "message_id": "550e8400-e29b-41d4-a716-446655440000",
  "payload": {
    "distribution_id": "DIST-20251212-001",
    "recipient": {
      "display_name": "王小明",
      "household_size": 4
    },
    "items": [
      {
        "item_code": "WATER-500ML",
        "name": "礦泉水 500ml",
        "qty": 12,
        "unit": "瓶",
        "category": "water",
        "expiry_date": "2026-06-30"
      },
      {
        "item_code": "RICE-1KG",
        "name": "白米",
        "qty": 2,
        "unit": "公斤",
        "category": "food"
      }
    ],
    "notes": "第一批發放"
  }
}
```

#### payload.items[] 欄位

| 欄位 | 必填 | 說明 |
|------|------|------|
| item_code | Y | 品項代碼 (參考 §3 品項分類) |
| name | Y | 顯示名稱 |
| qty | Y | 數量 (正數) |
| unit | Y | 單位 (參考 §3.2 標準單位) |
| category | Y | 分類代碼 |
| expiry_date | N | 效期 (YYYY-MM-DD) |
| lot_number | N | 批號 |

---

### 2.3 TEMPLATE - 物資包範本

HIRS 分享物資包範本給其他 HIRS 使用者。

```json
{
  "schema_version": "1.0",
  "message_type": "TEMPLATE",
  "issuer": {
    "system": "HIRS",
    "site_id": "HIRS-USER-abc123",
    "site_name": "小明的防災包"
  },
  "timestamp": "2025-12-12T10:30:00+08:00",
  "message_id": "550e8400-e29b-41d4-a716-446655440001",
  "payload": {
    "template_id": "TPL-20251212-001",
    "template_name": "四口之家三日份",
    "description": "適合 4 人家庭的基本防災物資",
    "household_size": 4,
    "target_days": 3,
    "items": [
      {
        "item_code": "WATER-2L",
        "name": "飲用水",
        "qty": 24,
        "unit": "公升",
        "category": "water",
        "is_required": true,
        "purchase_url": "https://example.com/water"
      }
    ],
    "tags": ["基礎", "四人家庭", "三日份"],
    "author": "防災達人"
  }
}
```

#### 購買連結安全規範

| 規則 | 說明 |
|------|------|
| 白名單網域 | 僅允許已知安全的電商網域 |
| 顯示警告 | 非白名單網域顯示「外部連結」警告 |
| 可選關閉 | 使用者可選擇不匯入購買連結 |

**白名單網域 (Phase 1)：**
- `shopee.tw`
- `momoshop.com.tw`
- `pcone.com.tw`
- `amazon.com`
- `books.com.tw`

---

### 2.4 INVENTORY_SYNC - 庫存同步 (未來)

預留給未來 CIRS ↔ CIRS 或 MIRS ↔ MIRS 同步使用。

```json
{
  "schema_version": "1.0",
  "message_type": "INVENTORY_SYNC",
  "issuer": { ... },
  "timestamp": "...",
  "message_id": "...",
  "payload": {
    "sync_type": "FULL | DELTA",
    "as_of": "2025-12-12T10:30:00+08:00",
    "items": [
      {
        "item_code": "...",
        "qty_on_hand": 100,
        "qty_reserved": 10,
        "last_updated": "..."
      }
    ]
  }
}
```

---

## 3. 品項分類系統 (Item Taxonomy)

### 3.1 分類代碼

| 代碼 | 名稱 | 說明 | 適用系統 |
|------|------|------|---------|
| water | 飲用水 | 水、飲料 | HIRS, CIRS |
| food | 食物 | 乾糧、罐頭、即食品 | HIRS, CIRS |
| medical | 醫療 | 藥品、急救用品 | HIRS, CIRS, MIRS |
| hygiene | 衛生 | 清潔、衛生用品 | HIRS, CIRS |
| tools | 工具 | 手電筒、工具、繩索 | HIRS, CIRS |
| documents | 證件 | 證件、現金、存摺 | HIRS |
| clothing | 衣物 | 衣服、保暖用品 | HIRS, CIRS |
| power | 電力 | 電池、行動電源 | HIRS, CIRS |
| communication | 通訊 | 收音機、充電器 | HIRS, CIRS |
| shelter | 避難 | 帳篷、睡袋、地墊 | HIRS, CIRS |
| baby | 嬰幼兒 | 奶粉、尿布、嬰兒用品 | HIRS, CIRS |
| elderly | 長者 | 長者專用物品 | HIRS, CIRS |
| pet | 寵物 | 寵物用品 | HIRS, CIRS |
| blood | 血液 | 血袋 | MIRS |
| equipment | 設備 | 醫療設備 | MIRS |
| surgical | 手術 | 手術器械、耗材 | MIRS |

### 3.2 標準單位

| 單位代碼 | 顯示名稱 | 說明 |
|---------|---------|------|
| 個 | 個 | 預設單位 |
| 瓶 | 瓶 | 瓶裝液體 |
| 罐 | 罐 | 罐頭 |
| 包 | 包 | 袋裝 |
| 盒 | 盒 | 盒裝 |
| 箱 | 箱 | 整箱 |
| 公斤 | 公斤 | 重量 |
| 公升 | 公升 | 容量 |
| 組 | 組 | 組合包 |
| 套 | 套 | 套裝 |
| 打 | 打 | 12 個 |
| 元 | 元 | 現金 |
| 袋 | 袋 | 血袋 (MIRS) |
| 支 | 支 | 針劑 (MIRS) |
| 顆 | 顆 | 藥錠 (MIRS) |

### 3.3 品項代碼命名規則

#### 標準品項格式

格式：`{CATEGORY}-{IDENTIFIER}`

| 範例 | 說明 |
|------|------|
| WATER-500ML | 500ml 瓶裝水 |
| WATER-2L | 2L 瓶裝水 |
| FOOD-RICE-1KG | 白米 1kg |
| FOOD-CAN-TUNA | 鮪魚罐頭 |
| MED-PAINKILLER | 止痛藥 |
| TOOL-FLASHLIGHT | 手電筒 |

#### 自訂品項格式 (CoreIRS / 動態新增)

格式：`CUSTOM-{UUID}`

| 範例 | 說明 |
|------|------|
| CUSTOM-a1b2c3d4 | CoreIRS 動態新增的品項 |
| CUSTOM-factory-001 | 工廠自訂品項 |

**處理規則：**
- 接收端遇到未知的 `CUSTOM-*` 代碼時，使用 `name` 欄位顯示
- 分類歸入「其他/未分類」
- 不報錯，允許匯入

**規則：**
- 全大寫
- 使用連字號分隔
- 避免特殊字元
- 長度 <= 32 字元

---

## 4. QR Code 規範

### 4.1 編碼格式

| 參數 | 值 |
|------|---|
| 編碼 | UTF-8 |
| QR 模式 | Byte Mode |
| 錯誤更正 | Level L (7%) |
| 版本 | 自動 (依資料量) |

### 4.2 資料壓縮

當 JSON 長度 > 500 字元時，建議壓縮：

1. JSON → UTF-8 bytes
2. gzip 壓縮
3. Base64 編碼
4. 加上前綴 `GZ:`

```
GZ:H4sIAAAAAAAAA6tWKkktLlGyUlAqS8wpTtVRSs7PS0nNK...
```

接收端判斷：
- 以 `GZ:` 開頭 → Base64 解碼 → gzip 解壓
- 否則 → 直接 JSON parse

### 4.3 大小限制

| 類型 | 建議上限 | 說明 |
|------|---------|------|
| DISTRIBUTION | 10 items | 超過分多張 QR |
| TEMPLATE | 20 items | 考慮手機掃描能力 |

---

## 5. 安全機制

### 5.1 Phase 1 - Trust on Scan (現行)

**設計理念：** 災難現場無法預先交換密鑰，採用「信任即掃描」模式，由使用者人工確認。

**驗證項目：**
- schema_version 檢查
- message_type 檢查
- 必填欄位驗證
- 資料型別驗證

**使用者確認流程：**
```
┌─────────────────────────────────────────┐
│  ⚠️ 匯入確認                            │
├─────────────────────────────────────────┤
│                                         │
│  此資料來自：                           │
│  📍 台北社區物資站 (CIRS-TPE-001)       │
│                                         │
│  包含 3 項物資：                        │
│  • 礦泉水 x 6 瓶                        │
│  • 白米 x 2 公斤                        │
│  • 罐頭 x 4 罐                          │
│                                         │
│  ┌─────────┐  ┌─────────┐              │
│  │  取消   │  │  匯入   │              │
│  └─────────┘  └─────────┘              │
└─────────────────────────────────────────┘
```

### 5.2 Phase 2 - Public Key 驗證 (規劃中)

**問題：** HMAC-SHA256 需要預先共享密鑰，災難現場做不到 (Key Exchange Problem)。

**解決方案：** 非對稱加密

```
┌─────────────────┐
│  CIRS 站點      │
│  生成 Key Pair  │
│  - Public Key   │
│  - Private Key  │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│  印製「站點驗證卡」                      │
│  ┌─────────┐                            │
│  │ QR Code │  台北社區物資站             │
│  │(PubKey) │  CIRS-TPE-001              │
│  └─────────┘  掃描此碼以驗證發放單       │
└─────────────────────────────────────────┘
```

**流程：**
1. CIRS 站點生成 Public/Private Key Pair
2. Public Key 印成 QR Code 貼在站點門口
3. HIRS 使用者先掃「站點驗證卡」，儲存 Public Key
4. 之後掃發放單時，用 Public Key 驗證簽章
5. 驗證通過顯示 ✅，失敗顯示 ⚠️

**簽章格式：**
```
signature = Ed25519.sign(
  private_key,
  JSON.stringify(payload, sorted_keys)
)
```

### 5.3 Phase 3 - 不可信匯入模式 (規劃中)

HIRS 接收不可信來源時：
1. 顯示差異比對（新增/修改/刪除）
2. 標記來源為「未驗證」
3. 分開儲存，不混入主庫存
4. 使用者確認後才合併
5. 保留來源追溯記錄

---

## 6. HIRS 接收處理流程

### 6.1 掃描 QR Code

```
┌─────────────┐
│  掃描 QR    │
└──────┬──────┘
       │
       ▼
┌─────────────────┐
│ 判斷格式        │
│ - GZ: 開頭?    │
│ - JSON 開頭?   │
└──────┬──────────┘
       │
       ▼
┌─────────────────┐
│ 解析 JSON       │
│ - schema_version │
│ - message_type  │
└──────┬──────────┘
       │
       ▼
┌─────────────────┐
│ 驗證必填欄位    │
└──────┬──────────┘
       │
       ▼
┌─────────────────┐         ┌─────────────────┐
│ 檢查簽章        │─ 無效 ─►│ 顯示警告        │
│ (Phase 2)       │         │ 確認是否繼續    │
└──────┬──────────┘         └──────┬──────────┘
       │ 有效                      │ 確認
       ▼                           ▼
┌─────────────────────────────────────────────┐
│ 依 message_type 處理                         │
│ - DISTRIBUTION: 新增到庫存 + 記錄領取歷史    │
│ - TEMPLATE: 新增到範本庫                     │
└─────────────────────────────────────────────┘
```

### 6.2 去重機制

- 依 `message_id` 去重
- 同一 `message_id` 不重複匯入
- 儲存已匯入的 `message_id` 清單 (最近 1000 筆)

### 6.3 品項合併策略

當 DISTRIBUTION 的品項與現有庫存有相同 `item_code` 時：

| 情況 | 處理方式 |
|------|---------|
| item_code 相同 | 數量相加 |
| item_code 不存在 | 新增品項 |
| 單位不同 | 顯示警告，讓使用者選擇 |

---

## 7. CIRS 發放處理流程

### 7.1 產生發放 QR

```
┌─────────────────┐
│ 選擇發放對象    │
│ (人員 / 匿名)   │
└──────┬──────────┘
       │
       ▼
┌─────────────────┐
│ 選擇發放品項    │
│ - 品項代碼      │
│ - 數量          │
└──────┬──────────┘
       │
       ▼
┌─────────────────┐
│ 扣除庫存        │
│ 記錄 event_log  │
└──────┬──────────┘
       │
       ▼
┌─────────────────┐
│ 產生 JSON       │
│ - 填入 issuer   │
│ - 填入 items    │
│ - 產生 message_id │
└──────┬──────────┘
       │
       ▼
┌─────────────────┐
│ (Phase 2)       │
│ 計算簽章        │
└──────┬──────────┘
       │
       ▼
┌─────────────────┐
│ 編碼 QR Code    │
│ - UTF-8 Byte    │
│ - 顯示給民眾掃描 │
└─────────────────┘
```

### 7.2 發放記錄保存

CIRS 端保存完整發放記錄：

```sql
-- event_log 表
INSERT INTO event_log (
  event_type,      -- 'DISTRIBUTE'
  item_id,
  quantity,
  person_id,
  operator_id,
  metadata,        -- JSON: { message_id, recipient, ... }
  created_at
) VALUES (...);
```

---

## 8. 錯誤處理

### 8.1 錯誤代碼

| 代碼 | 說明 | 處理建議 |
|------|------|---------|
| ERR_INVALID_SCHEMA | schema_version 不支援 | 提示升級應用 |
| ERR_MISSING_FIELD | 必填欄位缺失 | 顯示缺失欄位 |
| ERR_INVALID_TYPE | message_type 不支援 | 忽略或顯示錯誤 |
| ERR_SIGNATURE_INVALID | 簽章驗證失敗 | 顯示警告 |
| ERR_DUPLICATE | message_id 已存在 | 靜默忽略 |
| ERR_QR_PARSE | QR 無法解析 | 重新掃描 |

### 8.2 使用者提示

| 情況 | 提示訊息 |
|------|---------|
| 成功匯入 | ✅ 已接收 {n} 項物資 |
| 簽章無效 | ⚠️ 此 QR 來源未驗證，確定要匯入嗎？ |
| 重複匯入 | ℹ️ 此發放記錄已匯入過 |
| 格式錯誤 | ❌ 無法識別的 QR Code 格式 |

---

## 9. 版本相容性

### 9.1 版本策略

| schema_version | 狀態 | 支援期限 |
|----------------|------|---------|
| 1.0 | 現行版本 | 長期支援 |
| 1.x | 向下相容 | 新增欄位為選填 |
| 2.0 | 未來 | 可能不相容 |

### 9.2 升級路徑

- 1.0 → 1.1：新增選填欄位，舊版可忽略
- 1.x → 2.0：需要轉換器，提供遷移工具

---

## 10. 實作檢查清單

### 10.1 HIRS 實作項目

- [ ] 解析 schema_version 1.0
- [ ] 處理 DISTRIBUTION message_type
- [ ] 處理 TEMPLATE message_type
- [ ] message_id 去重
- [ ] 品項合併邏輯
- [ ] 領取歷史記錄
- [ ] GZ: 壓縮格式支援
- [ ] 購買連結白名單檢查
- [ ] (Phase 2) 簽章驗證
- [ ] (Phase 3) 不可信匯入模式

### 10.2 CIRS 實作項目

- [ ] 產生 DISTRIBUTION message
- [ ] 填入 issuer 資訊
- [ ] 產生 message_id (UUID v4)
- [ ] UTF-8 Byte Mode QR 編碼
- [ ] 發放記錄保存 metadata
- [ ] (Phase 2) HMAC 簽章
- [ ] (Phase 2) 站點密鑰管理

### 10.3 共用元件

- [ ] item_taxonomy.json 品項對照表
- [ ] JSON Schema 驗證檔
- [ ] 單位轉換函式庫

---

## 11. 附錄

### A. JSON Schema 檔案

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "$id": "https://irs.local/schemas/envelope/v1.json",
  "type": "object",
  "required": ["schema_version", "message_type", "issuer", "timestamp", "message_id", "payload"],
  "properties": {
    "schema_version": {
      "type": "string",
      "enum": ["1.0"]
    },
    "message_type": {
      "type": "string",
      "enum": ["DISTRIBUTION", "TEMPLATE", "INVENTORY_SYNC"]
    },
    "issuer": {
      "type": "object",
      "required": ["system", "site_id"],
      "properties": {
        "system": { "type": "string", "enum": ["CIRS", "HIRS", "MIRS"] },
        "site_id": { "type": "string", "maxLength": 64 },
        "site_name": { "type": "string", "maxLength": 128 }
      }
    },
    "timestamp": {
      "type": "string",
      "format": "date-time"
    },
    "message_id": {
      "type": "string",
      "format": "uuid"
    },
    "payload": {
      "type": "object"
    },
    "signature": {
      "type": "string"
    }
  }
}
```

### B. 範例：完整 DISTRIBUTION QR 內容

```json
{"schema_version":"1.0","message_type":"DISTRIBUTION","issuer":{"system":"CIRS","site_id":"CIRS-TPE-001","site_name":"台北社區物資站"},"timestamp":"2025-12-12T10:30:00+08:00","message_id":"550e8400-e29b-41d4-a716-446655440000","payload":{"distribution_id":"DIST-20251212-001","recipient":{"display_name":"王小明"},"items":[{"item_code":"WATER-500ML","name":"礦泉水","qty":6,"unit":"瓶","category":"water"}]}}
```

### C. 變更記錄

| 版本 | 日期 | 變更內容 |
|------|------|---------|
| 1.0.0-draft | 2025-12-12 | 初版草案 |
| 1.0.0 | 2025-12-12 | 納入 Gemini Review：CUSTOM 品項、Trust on Scan、Public Key 驗證 |

---

## 12. 設計決策記錄 (ADR)

### ADR-001: Trust on Scan vs HMAC

**問題**：如何在災難現場驗證 QR Code 來源？

**選項**：
1. HMAC-SHA256 - 需要預先共享密鑰
2. Trust on Scan - 使用者人工確認
3. Public Key - 非對稱加密

**決策**：Phase 1 採用 Trust on Scan，Phase 2 導入 Public Key

**理由**：
- 災難現場無法預先交換密鑰
- 使用者確認流程簡單直覺
- Public Key 方案可後續升級，不影響現有流程

### ADR-002: 自訂品項 (CUSTOM) 支援

**問題**：CoreIRS 需要動態新增品項，但 HIRS 不認識這些品項代碼

**決策**：允許 `CUSTOM-{UUID}` 格式，接收端以 `name` 顯示

**理由**：
- 商業場景品項千變萬化，無法預先定義
- 使用 `name` 欄位保證人類可讀
- 分類歸入「其他」不影響核心功能

### ADR-003: QR 壓縮 (GZ:)

**問題**：QR Code 容量有限，JSON 文字佔空間

**決策**：JSON > 500 字元時使用 gzip + Base64，前綴 `GZ:`

**理由**：
- 10 個品項的 JSON 約 800-1000 字元
- gzip 可壓縮 60-70%
- pako.js 約 20-30KB，可接受

---

## 13. 待辦事項 (Roadmap)

### Phase 1 (現行) - 2025 Q4
- [x] 定義 JSON Envelope 格式
- [x] 定義 Item Taxonomy
- [ ] 實作 CIRS QR 產生器
- [ ] 實作 HIRS QR 掃描器
- [ ] Trust on Scan 確認流程

### Phase 2 (規劃中) - 2026 Q1
- [ ] Public Key 產生與管理
- [ ] 站點驗證卡 QR
- [ ] Ed25519 簽章驗證
- [ ] gzip 壓縮支援

### Phase 3 (未來)
- [ ] 不可信匯入模式
- [ ] 差異比對 UI
- [ ] 來源追溯記錄

---

*Document generated for IRS Ecosystem*
*HIRS / CIRS / MIRS / CoreIRS Interoperability*
*Reviewed by: Claude, ChatGPT, Gemini*
