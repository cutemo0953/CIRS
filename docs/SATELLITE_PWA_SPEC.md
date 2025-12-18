# Satellite PWA 開發規格書 v1.3.1

> Hub & Spoke 架構：讓志工手機成為「傳令兵」

**v1.3.1 更新 (2025-12-18):**
- 角色控制：Hub 可指定配對碼允許的角色（僅志工/僅管理員/兩者）
- 新人登記：支援檢傷分類（輕傷/延遲/立即/死亡）+ 區域選單
- 直接 API 呼叫：線上時直接呼叫 API，不經過 Service Worker 佇列
- Safari 空白頁修復：新增 CDN 載入偵測與 fallback loading 畫面
- 區域 API：新增 `/api/satellite/zones` 取得 Hub 預設區域

**v1.3 更新 (2025-12):**
- 配對流程簡化：QR Code 僅開啟 PWA，配對碼改為手動輸入 6 位數字
- 報到/退場：新增手動輸入 ID 選項（解決相機問題）
- 物資發放：新增手動選擇領取人+物資選項
- 新增 API 限速防護（防暴力破解）
- 參考 GitHub Device Flow 設計理念

**v1.2 更新 (2025-12):**
- 相機錯誤處理：iOS Safari 權限引導 + 手動輸入 fallback
- 智慧貼上：自動解析 pairing_code URL、分離 Hub URL 與配對碼
- 配對後角色選擇：志工/管理員 選項
- 設定頁角色顯示與切換功能

**v1.1 更新 (2025-12):**
- 認證流程改為 Pairing Code Pattern（5分鐘有效 + device_id 綁定）
- 同步協議改為 Action Envelope Pattern（action_id 確保冪等性）
- 新增 iOS Fallback Strategy（Pending Actions UI 指示器）
- 新增 action_logs 資料表 schema

---

## 📖 架構概念：指揮官與傳令兵

### 故事版說明

想像災區搭起了一個**救災中心**：

| 角色 | 技術對應 | 職責 |
|------|----------|------|
| **指揮帳篷 / 大白板** | Raspberry Pi (Hub) | 大腦。存資料、發 WiFi。固定不動。 |
| **指揮官監控螢幕** | Admin Dashboard | 眼睛。看報表、做設定。 |
| **傳令兵小筆記本** | 手機 PWA (Satellite) | 手腳。到處跑、掃 QR、點選發放。 |
| **無線電** | WiFi (Intranet) | 神經。連結大腦與手腳。 |

### 設計原則

1. **手機不存資料** - Satellite 只是遙控器，資料都在 Hub
2. **WiFi 自動同步** - 0.1 秒自動同步，不需手動操作
3. **離線暫存** - 斷網時先記在手機，恢復後自動補傳
4. **手機壞了沒關係** - 換一支登入即可繼續

### 為什麼這樣設計？

- **省錢**：志工用自己手機，不用買平板
- **效率**：誰在現場誰輸入，不用跑回櫃台
- **安全**：手機掉了資料還在 Hub 裡

---

## 🏗️ 系統架構圖

```
                    ┌─────────────────────────────────┐
                    │     Raspberry Pi (Hub)          │
                    │  ┌───────────┬───────────────┐  │
                    │  │ CIRS:8090 │ MIRS:8000     │  │
                    │  │ 社區物資   │ 醫療庫存      │  │
                    │  └───────────┴───────────────┘  │
                    │         SQLite Database         │
                    │       (Single Source of Truth)  │
                    └───────────────┬─────────────────┘
                                    │ WiFi / LAN
                    ┌───────────────┼───────────────┐
                    │               │               │
              ┌─────▼─────┐   ┌─────▼─────┐   ┌─────▼─────┐
              │ Satellite │   │ Satellite │   │ Satellite │
              │  (志工A)   │   │  (志工B)   │   │  (醫護C)   │
              │           │   │           │   │           │
              │ 📱 CIRS   │   │ 📱 CIRS   │   │ 📱 MIRS   │
              │  Mobile   │   │  Mobile   │   │  Mobile   │
              └───────────┘   └───────────┘   └───────────┘
                  門口報到        物資發放        醫療巡房
```

---

## 📱 CIRS Satellite PWA

### 目標用戶
- 收容所志工
- 物資發放人員
- 報到登記人員

### 核心功能

| 功能 | 說明 | 優先級 |
|------|------|--------|
| QR Code 開啟 PWA | 掃描 QR Code 開啟 Satellite 網頁（靜態網址） | ✅ Done |
| 6 位數配對碼 | 手動輸入配對碼完成認證 | ✅ v1.3 |
| 人員報到 | 掃描災民 QR 或手動輸入 ID | ✅ v1.3 |
| 人員退場 | 掃描災民 QR 或手動輸入 ID | ✅ v1.3 |
| 物資發放 | 掃描 QR 或手動選擇（領取人+物資+數量） | ✅ v1.3 |
| 離線暫存 | 斷網時暫存操作 | ✅ Done |
| 自動同步 | 恢復連線自動上傳 | ✅ Done |
| 庫存查詢 | 查看目前物資庫存（唯讀） | ✅ Done |
| 人員查詢 | 查看在場人員名單（唯讀） | P2 |

### API Endpoints

#### 認證 (6 位數配對碼) - v1.3.1

```
# Hub 端 (Admin Portal)
GET  /api/auth/pairing-code       # 產生 6 位數配對碼 (5分鐘有效，預設僅志工)
     Response: { "code": "847291", "allowed_roles": "volunteer", "expires_at": "..." }

POST /api/auth/pairing-code       # 產生配對碼並指定允許角色 (v1.3.1)
     Body: { "allowed_roles": "volunteer,admin" }
     Response: { "code": "847291", "allowed_roles": "volunteer,admin", "expires_at": "..." }

GET  /api/auth/pairing-qr         # 產生 QR Code（僅含 PWA 網址，不含配對碼）
     Response: PNG image of QR code pointing to /mobile/

# Satellite 端
POST /api/auth/satellite/exchange # 交換配對碼取得 JWT
     Body: { "pairing_code": "847291", "device_id": "client-uuid" }
     Response: {
       "access_token": "JWT...",
       "expires_in": 43200,
       "hub_name": "...",
       "allowed_roles": "volunteer,admin"  // v1.3.1: 角色控制
     }

     Rate Limit: 5 次/分鐘/IP（防暴力破解）
     Error 429: { "detail": "Too many attempts. Please wait 60 seconds." }
```

#### 配對碼規格 (v1.3)

| 項目 | 規格 |
|------|------|
| 格式 | 6 位純數字 (000000-999999) |
| 有效期 | 5 分鐘 |
| 使用次數 | 單次使用，成功後立即失效 |
| 組合數 | 1,000,000 種 |
| 防護 | API 限速 5 次/分鐘/IP |

#### 操作 API

```
# 人員操作 (v1.3.1: 直接 API + 新人登記)
POST /api/satellite/checkin     # 人員報到/退場/新人登記
     Body: {
       "person_id": "P0001",
       "name": "王小明",              // 新人登記用
       "action": "register",          // register | checkin | checkout
       "triage_status": "green",      // green | yellow | red | black
       "zone_id": "zone_1",           // 區域 ID
       "card_number": "A123456"       // 卡片號碼（可選）
     }
GET  /api/satellite/persons     # 查詢在場人員
GET  /api/satellite/zones       # 查詢 Hub 預設區域 (v1.3.1)

# 物資操作
POST /api/satellite/supply      # 確認領取物資 (v1.3.1: 直接 API)
     Body: { "person_id": "P0001", "item_id": 1, "quantity": 2 }
GET  /api/satellite/inventory   # 查詢庫存摘要

# 同步 (Action Envelope Pattern - 離線時使用)
POST /api/satellite/sync        # 批次同步離線操作 (見下方 Sync Protocol)
GET  /api/satellite/status      # 取得 Hub 狀態
```

### Sync Protocol v1.1 (Action Envelope Pattern)

所有變更操作 (Check-in, Dispense) 必須使用 Action Envelope 格式，通過 `POST /api/satellite/sync` 發送。

#### Request Schema

```json
{
  "batch_id": "uuid-v4",
  "actions": [
    {
      "action_id": "uuid-v4",    // 關鍵：用於冪等性檢查
      "type": "DISPENSE",        // DISPENSE | CHECK_IN | CHECK_OUT
      "timestamp": 1700000000,   // Unix timestamp
      "payload": {
        "item_id": 101,
        "quantity": 1
      }
    }
  ]
}
```

#### Hub 處理邏輯 (Server-Side)

```
對於每個 action:
1. 檢查: action_id 是否已存在於 action_logs 表？
   - 是: 跳過處理 (冪等)，回傳成功
   - 否: 執行業務邏輯 (如 Inventory - 1)
2. 記錄: 將 action_id 存入 action_logs
3. 回應: 回傳已處理的 action_id 列表
```

#### Response Schema

```json
{
  "processed": ["action-id-1", "action-id-2"],
  "failed": [],
  "server_time": 1700000100
}
```

Client 收到回應後，從 IndexedDB 移除已處理的 actions。

#### 離線同步流程圖

```
┌──────────────────────────────────────────────────────────┐
│                    Satellite PWA                          │
├──────────────────────────────────────────────────────────┤
│  User Action                                              │
│       │                                                   │
│       ▼                                                   │
│  ┌─────────────┐                                         │
│  │ Create      │  action_id = uuid()                     │
│  │ Action      │  timestamp = Date.now()                 │
│  │ Envelope    │                                         │
│  └──────┬──────┘                                         │
│         │                                                 │
│         ▼                                                 │
│  ┌─────────────┐    Online?    ┌─────────────┐          │
│  │ Save to     │──── Yes ─────▶│ POST to Hub │          │
│  │ IndexedDB   │               │ /sync       │          │
│  └──────┬──────┘               └──────┬──────┘          │
│         │                             │                  │
│         │ No (Offline)                │ Response         │
│         │                             ▼                  │
│         │                      ┌─────────────┐          │
│         │                      │ Clear from  │          │
│         │                      │ IndexedDB   │          │
│         │                      └─────────────┘          │
│         ▼                                                │
│  ┌─────────────┐                                        │
│  │ Queue for   │  Navbar: "Pending: N"                  │
│  │ Later Sync  │                                        │
│  └─────────────┘                                        │
│                                                          │
│  Network Restored:                                       │
│  ├─ Android: Background Sync API auto-triggers          │
│  └─ iOS: window.online → flush() or manual "Sync Now"   │
└──────────────────────────────────────────────────────────┘
```

### iOS Fallback Strategy

iOS Safari 不支援 Background Sync API，需要特殊處理：

| 策略 | 實作 |
|------|------|
| **UI 指示器** | Navbar 必須顯示 "Pending Actions: N" |
| **自動嘗試** | 優先嘗試 Background Sync |
| **偵測失敗** | 若 iOS 或 sync 失敗，顯示 "Sync Now" 按鈕 |
| **Online 事件** | 監聽 `window.online`，立即觸發 flush |

```javascript
// iOS 偵測與 fallback
const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent);

window.addEventListener('online', async () => {
  if (isIOS || !('serviceWorker' in navigator)) {
    await flushPendingActions();
  }
});

function updatePendingIndicator(count) {
  document.getElementById('pending-badge').textContent =
    count > 0 ? `Pending: ${count}` : '';
}
```

### v1.3 配對流程（GitHub Device Flow 風格）

#### 設計理念

參考 GitHub 的 Device Flow 設計，將 QR Code 與配對碼**分離**：
- **QR Code**：僅用於開啟 PWA 網頁（靜態網址，可印出貼在牆上）
- **配對碼**：6 位數字，口述或螢幕顯示，手動輸入

#### 流程圖

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           v1.3 配對流程                                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   ┌──────────────────────┐         ┌──────────────────────┐            │
│   │   CIRS Portal        │         │   Satellite PWA      │            │
│   │   (管理員電腦)         │         │   (志工手機)          │            │
│   └──────────┬───────────┘         └──────────┬───────────┘            │
│              │                                 │                        │
│   ┌──────────▼───────────┐                    │                        │
│   │ 1. 顯示 QR Code       │                    │                        │
│   │    (僅含 /mobile/ URL) │  ──── 掃描 ────▶  │                        │
│   │                       │                    │                        │
│   │    ┌─────────────┐   │         ┌──────────▼───────────┐            │
│   │    │ ▓▓▓▓▓▓▓▓▓▓▓ │   │         │ 2. 開啟 PWA          │            │
│   │    │ ▓▓▓▓▓▓▓▓▓▓▓ │   │         │    顯示配對碼輸入畫面  │            │
│   │    │ ▓▓▓▓▓▓▓▓▓▓▓ │   │         │                      │            │
│   │    └─────────────┘   │         │    請輸入配對碼：      │            │
│   │                       │         │    ┌─┬─┬─┬─┬─┬─┐     │            │
│   │    配對碼：            │         │    │ │ │ │ │ │ │     │            │
│   │    ┌───────────────┐ │         │    └─┴─┴─┴─┴─┴─┘     │            │
│   │    │   847291      │ │ 口述/   │                      │            │
│   │    │               │ │ 顯示 ─▶ │                      │            │
│   │    └───────────────┘ │         └──────────┬───────────┘            │
│   │    (5 分鐘有效)       │                    │                        │
│   └──────────────────────┘                    │                        │
│                                    ┌──────────▼───────────┐            │
│                                    │ 3. 輸入配對碼         │            │
│                                    │    [8][4][7][2][9][1] │            │
│                                    │                      │            │
│                                    │    → POST /exchange  │            │
│                                    │    → 取得 JWT Token  │            │
│                                    └──────────┬───────────┘            │
│                                               │                        │
│                                    ┌──────────▼───────────┐            │
│                                    │ 4. 配對成功！         │            │
│                                    │    選擇角色：         │            │
│                                    │    [志工] [管理員]    │            │
│                                    └──────────────────────┘            │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

#### 優點對比

| 項目 | v1.2 (QR 含 Token) | v1.3 (分離式) |
|------|-------------------|---------------|
| QR Code 有效期 | 5 分鐘 | **永久**（可印出貼牆） |
| 網路時機依賴 | 掃描時需連網 | 輸入配對碼時才需連網 |
| 失敗處理 | 需重新掃描 | 重新輸入即可 |
| 口述傳達 | 無法（URL 太長） | **可以**（6 位數字） |
| 相機問題影響 | 直接導致失敗 | 不影響（只需開一次） |
| 安全性 | URL 可被截取 | 配對碼短期有效 + 限速 |

### v1.3 報到/退場 & 物資發放 手動模式

為解決 iOS Safari 相機權限問題，v1.3 新增「手動輸入」選項作為 Fallback：

#### 報到/退場 Modal

```
┌─────────────────────────────────┐
│  報到 / 退場                 ✕  │
├─────────────────────────────────┤
│  ┌──────────┐  ┌──────────┐    │
│  │   報到   │  │   退場   │    │
│  └──────────┘  └──────────┘    │
│                                 │
│  ┌─────────────────────────────┐│
│  │  📷  掃描 QR Code           ▸││
│  │      使用相機掃描人員 QR     ││
│  └─────────────────────────────┘│
│                                 │
│            ── 或 ──             │
│                                 │
│  ┌─────────────────────────────┐│
│  │  手動輸入 ID                ││
│  │  ┌───────────────────────┐  ││
│  │  │ 輸入人員 ID 或姓名     │  ││
│  │  └───────────────────────┘  ││
│  │  [        確認報到        ] ││
│  └─────────────────────────────┘│
└─────────────────────────────────┘
```

#### 物資發放 Modal

```
┌─────────────────────────────────┐
│  物資發放                    ✕  │
├─────────────────────────────────┤
│  ┌─────────────────────────────┐│
│  │  📷  掃描 QR Code           ▸││
│  │      掃描人員或物資 QR Code  ││
│  └─────────────────────────────┘│
│                                 │
│            ── 或 ──             │
│                                 │
│  ┌─────────────────────────────┐│
│  │  手動輸入發放資訊            ││
│  │                             ││
│  │  領取人 ID                  ││
│  │  ┌───────────────────────┐  ││
│  │  │ 輸入人員 ID 或姓名     │  ││
│  │  └───────────────────────┘  ││
│  │                             ││
│  │  發放物資                   ││
│  │  ┌───────────────────────┐  ││
│  │  │ 選擇物資...      ▼    │  ││
│  │  └───────────────────────┘  ││
│  │  (物資清單從庫存快取載入)    ││
│  │                             ││
│  │  數量                       ││
│  │  ┌───┐  ┌─────────┐  ┌───┐ ││
│  │  │ - │  │    1    │  │ + │ ││
│  │  └───┘  └─────────┘  └───┘ ││
│  │                             ││
│  │  [        確認發放        ] ││
│  └─────────────────────────────┘│
└─────────────────────────────────┘
```

### 安全設計 v1.3

| 項目 | 設計 |
|------|------|
| **認證流程** | 6 位數配對碼 (5分鐘有效) → JWT Exchange |
| **暴力破解防護** | API 限速 5 次/分鐘/IP |
| **Token 綁定** | JWT 綁定 `device_id`，防止 Token 盜用 |
| **Token 儲存** | `sessionStorage`（關閉分頁即清除） |
| **Token 有效期** | 12 小時 (43200 秒) |
| **Device ID** | Client 產生的 UUID，首次配對時生成 |
| **連接狀態** | `localStorage`（持久化 hub_url） |
| **權限範圍** | 僅限 `/api/satellite/*` API |
| **冪等性** | `action_id` 確保重複提交不會重複處理 |

### Database Schema (Hub 端新增)

```sql
-- 儲存已處理的 action_id，確保冪等性
CREATE TABLE action_logs (
    action_id TEXT PRIMARY KEY,
    batch_id TEXT,
    action_type TEXT NOT NULL,
    device_id TEXT,
    processed_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_action_logs_batch ON action_logs(batch_id);
CREATE INDEX idx_action_logs_device ON action_logs(device_id);

-- 定期清理 (保留 7 天)
-- DELETE FROM action_logs WHERE processed_at < datetime('now', '-7 days');
```

### 檔案結構

```
frontend/mobile/
├── index.html          # 主 PWA 應用
├── manifest.json       # PWA manifest
├── service-worker.js   # 離線快取 & 同步
└── icons/
    ├── icon.svg
    ├── icon-72x72.png
    ├── icon-96x96.png
    ├── icon-128x128.png
    ├── icon-144x144.png
    ├── icon-152x152.png
    ├── icon-192x192.png
    ├── icon-384x384.png
    └── icon-512x512.png
```

---

## 🏥 MIRS Satellite PWA

### 目標用戶
- 醫護人員
- 藥師
- 醫療志工
- 設備管理人員

### 核心功能

| 功能 | 說明 | 優先級 |
|------|------|--------|
| QR 配對連接 | 掃描 Hub QR Code 自動連接 | P1 |
| 檢傷分類 | 更新傷患 Triage 狀態 | P1 |
| 給藥記錄 | 掃描藥品 QR 記錄給藥 | P1 |
| 生命徵象 | 記錄 BP/HR/SpO2/Temp | P1 |
| **設備狀態更新** | 掃描設備 QR，更新運作狀態 | P1 |
| **設備巡檢** | 記錄巡檢結果、回報故障 | P1 |
| 傷患查詢 | 查看傷患清單與狀態 | P2 |
| 藥品庫存 | 查看藥品庫存（唯讀） | P2 |
| **血庫查詢** | 查看血液庫存（唯讀） | P2 |
| **設備清單** | 查看設備狀態總覽（唯讀） | P2 |
| 離線暫存 | 斷網時暫存操作 | P1 |

### API Endpoints（建議）

```
# 認證
GET  /api/auth/mirs-pairing-qr    # 產生 MIRS 配對 QR
POST /api/auth/mirs-satellite/verify

# 傷患操作
GET  /api/mirs-satellite/patients      # 傷患清單
POST /api/mirs-satellite/triage        # 更新檢傷分類
POST /api/mirs-satellite/vitals        # 記錄生命徵象

# 給藥操作
POST /api/mirs-satellite/medication    # 記錄給藥
GET  /api/mirs-satellite/med-inventory # 藥品庫存

# 設備操作 (新增)
GET  /api/mirs-satellite/equipment           # 設備清單
POST /api/mirs-satellite/equipment/:id/status # 更新設備狀態
POST /api/mirs-satellite/equipment/:id/check  # 記錄巡檢
GET  /api/mirs-satellite/equipment/:id/qr     # 取得設備 QR (供掃描)

# 血庫查詢 (新增)
GET  /api/mirs-satellite/blood-inventory     # 血液庫存

# 同步
POST /api/mirs-satellite/sync          # 批次同步
```

### 建議檔案結構

```
MIRS/
└── frontend/
    └── mobile/
        ├── index.html
        ├── manifest.json
        ├── service-worker.js
        └── icons/
```

### MIRS Satellite 使用場景

**狀態：Phase 2 - 架構設計完成，待實作**

| 場景 | 說明 |
|------|------|
| **設備巡檢** | 技術人員手持手機巡檢發電機、氧氣系統，掃描 QR 更新狀態 |
| **藥品盤點** | 藥師在藥庫掃描藥品 QR，確認庫存與效期 |
| **血庫管理** | 檢驗師在血庫掃描血袋，更新狀態 |
| **病房巡房** | 醫護人員在病房記錄生命徵象、給藥紀錄 |

| 考量 | 說明 |
|------|------|
| 現況 | MIRS v2.0 已有完整設備管理、韌性儀表板 |
| 需求 | 設備巡檢、藥品盤點需要行動支援 |
| 優先級 | CIRS Satellite 架構驗證後，複製到 MIRS |
| 共用性 | 可共用 Service Worker、離線同步、配對機制 |

---

## 🔐 xIRS Secure Exchange 與 Satellite 架構關係

### 兩種同步機制對比

xIRS 生態系統有兩種資料同步機制，服務不同場景：

| 機制 | Satellite Sync | xIRS Secure Exchange |
|------|----------------|----------------------|
| **用途** | Hub ↔ Satellite（手機） | Hub ↔ Hub（站點間） |
| **連線方式** | WiFi Intranet（即時） | USB 離線傳輸（批次） |
| **資料流向** | 雙向即時同步 | 單向加密封包 |
| **安全性** | JWT Token | Ed25519 簽章 + NaCl 加密 |
| **使用者** | 志工、醫護人員 | 站點管理員 |
| **典型延遲** | < 1 秒 | 手動觸發（分鐘級） |

### 架構圖

```
                          xIRS Secure Exchange (USB)
    ┌─────────────────┐  ←──────────────────────────→  ┌─────────────────┐
    │   CIRS Hub A    │      .xirs encrypted file      │   CIRS Hub B    │
    │  (避難所 A)      │                                │  (避難所 B)      │
    └────────┬────────┘                                └────────┬────────┘
             │ WiFi                                             │ WiFi
             │ (Satellite Sync)                                 │ (Satellite Sync)
    ┌────────┴────────┐                                ┌────────┴────────┐
    │   📱 📱 📱      │                                │   📱 📱 📱      │
    │  Satellites     │                                │  Satellites     │
    │  (志工手機)      │                                │  (志工手機)      │
    └─────────────────┘                                └─────────────────┘
```

### 使用時機

| 場景 | 使用機制 |
|------|----------|
| 志工在現場報到人員、發放物資 | **Satellite Sync** (WiFi) |
| 醫護在病房巡檢設備、記錄生命徵象 | **Satellite Sync** (WiFi) |
| 避難所 A 將人員名單傳給避難所 B | **xIRS Secure Exchange** (USB) |
| CIRS 社區站將傷患轉送 MIRS 醫療站 | **xIRS Secure Exchange** (USB) |
| 定期備份站點資料到另一站點 | **xIRS Secure Exchange** (USB) |

### 未來整合：Satellite 觸發 xIRS Export（Phase 3）

未來可讓 Admin 透過 Satellite 遠端觸發 Hub 的 xIRS Export：

```
📱 Admin Satellite
    │
    │ POST /api/exchange/export (via WiFi)
    ▼
┌─────────────────┐
│   CIRS Hub      │ → 產生 .xirs 檔案
│                 │ → 顯示「請插入 USB」
└─────────────────┘
```

詳細規格請參考：[xIRS Secure Exchange Spec v2.0](./xIRS_SECURE_EXCHANGE_SPEC_v2.md)

---

## 📋 開發任務清單

### CIRS Satellite PWA

#### ✅ 已完成

- [x] Task 1: PWA Foundation
  - [x] manifest.json
  - [x] service-worker.js
  - [x] 基本 UI 框架
  - [x] 離線快取機制
  - [x] App icons

- [x] Task 2: Pairing & Auth
  - [x] GET /api/auth/pairing-qr
  - [x] GET /api/auth/pairing-info
  - [x] POST /api/auth/satellite/verify
  - [x] URL token 解析
  - [x] sessionStorage 安全儲存

- [x] Task 3: Hub 端 QR 顯示
  - [x] CIRS Frontend 新增「Satellite 配對」按鈕
  - [x] Modal 顯示 QR Code
  - [x] 顯示連接說明與步驟
  - [x] 多語言支援 (zh-TW, ja)

- [x] Task 4: Pairing Code Pattern v1.1
  - [x] POST /api/auth/satellite/exchange (pairing_code + device_id)
  - [x] satellite_pairing_codes 資料表
  - [x] 5 分鐘有效期
  - [x] device_id 綁定

- [x] Task 5: Action Envelope Sync v1.1
  - [x] POST /api/satellite/sync (Action Envelope Pattern)
  - [x] action_logs 資料表 (冪等性追蹤)
  - [x] DISPENSE, CHECK_IN, CHECK_OUT 處理
  - [x] 批次同步回應

- [x] Task 6: Satellite API
  - [x] GET /api/satellite/status (Hub 狀態)
  - [x] GET /api/satellite/inventory (庫存查詢)
  - [x] GET /api/satellite/persons (在場人員)
  - [x] GET /api/satellite/action-logs (操作紀錄)

- [x] Task 7: Satellite PWA 前端
  - [x] QR 掃描配對 (URL pairing_code 處理)
  - [x] 庫存查詢介面 (分類篩選、快取、離線支援)
  - [x] Portal 綠色主題配色同步 (#4c826b)
  - [x] iOS Fallback (Pending 指示器 + Sync Now 按鈕)

- [x] Task 7.1: v1.2 UX 改進
  - [x] 相機錯誤處理 (iOS Safari 權限引導 + 手動輸入 fallback)
  - [x] 智慧貼上 (自動解析 pairing_code URL)
  - [x] 配對後角色選擇 Modal (志工/管理員)
  - [x] 設定頁角色顯示與切換功能
  - [x] Hub 配對 Modal WiFi 警告與疑難排解
  - [x] 複製配對連結按鈕

- [x] Task 7.2: v1.3 配對流程簡化 (GitHub Device Flow)
  - [x] Backend: 改產生 6 位純數字配對碼
  - [x] Backend: 新增 API 限速 (5 次/分鐘/IP)
  - [x] Portal: QR Code 改為僅含 /mobile/ 網址
  - [x] Portal: 大字顯示 6 位數配對碼 + 刷新按鈕
  - [x] Satellite PWA: 新增 6 格數字輸入介面
  - [x] Satellite PWA: 輸入完成自動提交

- [x] Task 7.3: v1.3 手動輸入 Fallback
  - [x] 報到/退場 Modal：可選擇掃描 QR 或手動輸入 ID
  - [x] 物資發放 Modal：可選擇掃描 QR 或手動選擇（領取人+物資+數量）
  - [x] 解決相機權限問題導致功能無法使用的情況

- [x] Task 7.4: v1.3.1 角色控制與新人登記
  - [x] Backend: 配對碼加入 allowed_roles 欄位
  - [x] Backend: POST /api/auth/pairing-code 可指定允許角色
  - [x] Backend: JWT Token 包含 allowed_roles
  - [x] Portal: 配對 Modal 新增角色選擇下拉選單
  - [x] Satellite PWA: 角色選擇按鈕根據 allowed_roles 禁用
  - [x] Satellite PWA: 新人登記支援檢傷分類（綠/黃/紅/黑）
  - [x] Satellite PWA: 新人登記支援區域選單
  - [x] Backend: 新增 /api/satellite/zones API
  - [x] Backend: 新增 /api/satellite/checkin 直接 API
  - [x] Backend: 新增 /api/satellite/supply 直接 API

- [x] Task 7.5: v1.3.1 Safari 相容性修復
  - [x] 新增初始 Loading 畫面（CDN 載入前顯示）
  - [x] CDN 載入失敗偵測與重試按鈕
  - [x] iOS Safari 外部 app 開啟空白頁修復
  - [x] 10 秒逾時保護機制

#### 🔲 待開發

- [ ] Task 8: i18n 支援
  - [ ] 繁體中文 (目前預設)
  - [ ] 日本語

### MIRS Satellite PWA（Phase 2）

- [ ] 複製 CIRS Satellite 架構
- [ ] 調整 API endpoints
- [ ] 實作醫療專用功能

---

## 🐛 已知問題與除錯紀錄

### Issue #1: 掃描 QR Code 後無法再使用相機

**問題描述**：
- 使用者從 CIRS Portal 掃描 QR Code 後開啟 Satellite PWA
- 預期：自動解析 URL 中的 `pairing_code` 並完成配對
- 實際：需要再次掃描 QR Code，但相機功能可能無法使用

**根本原因**：
1. URL 自動配對邏輯存在但可能因網路問題失敗
2. iOS Safari 相機權限可能被拒絕
3. 用戶可能誤開啟了錯誤的路徑（`/` 而非 `/mobile/`）

**狀態**：修復中

**解決方案**：
- [x] 加入 `isPairing` 全螢幕 loading 狀態
- [x] 加入詳細 console.log 除錯資訊
- [x] 相機失敗時提供「手動輸入連結」fallback
- [x] 主頁面偵測 `pairing_code` 參數並重導向到 `/mobile/`

### Issue #2: 手動連接按鈕沒反應

**問題描述**：
- 使用者貼上配對連結後，解析成功顯示綠色確認區塊
- 點擊「連接」按鈕後沒有任何反應
- Backend log 沒有收到 POST 請求

**除錯步驟**：
1. 開啟瀏覽器 DevTools Console
2. 查看是否有 `[Satellite] connectWithParsedUrl called` 訊息
3. 查看是否有 `[Satellite] exchangePairingCode called` 訊息
4. 查看是否有網路錯誤（CORS、連線失敗等）

**可能原因**：
1. JavaScript 執行錯誤（語法問題）
2. Alpine.js 綁定問題
3. 網路連線問題（手機與 Hub 不在同一網路）
4. CORS 設定問題

**狀態**：除錯中

**已加入的除錯程式碼**：
```javascript
// checkUrlToken()
console.log('[Satellite] checkUrlToken called', { pairingCode, hubUrl, pathname });

// exchangePairingCode()
console.log('[Satellite] exchangePairingCode called', { hubUrl, pairingCode });
console.log('[Satellite] Using device_id:', deviceId);
console.log('[Satellite] Fetching:', apiUrl);
console.log('[Satellite] Response status:', response.status);

// connectWithParsedUrl()
console.log('[Satellite] connectWithParsedUrl called', { parsedHubUrl, parsedPairingCode });
console.log('[Satellite] Starting connection...');
console.log('[Satellite] Exchange result:', success);
```

### Issue #3: 角色選擇功能

**問題描述**：
- 配對成功後應該顯示角色選擇 Modal（志工/管理員）
- 設定頁面應該顯示目前角色並可切換

**狀態**：已實作，待驗證

---

## ⚠️ 重要決策記錄

### 1. QR Code 同步（不實作）

**決定**：不做「Satellite 產生 QR 給 Hub 掃」的同步功能

**原因**：
- WiFi 自動同步比 QR Code 快 100 倍
- 99% 情況下 WiFi 會正常運作
- 如果 WiFi 壞了，通常會重開機或換 Router

**備案**：未來可在「設定」深層選單加入「產生備份 QR」作為最後保險

### 2. Token 儲存位置

**決定**：使用 `sessionStorage` 而非 `localStorage`

**原因**：
- 關閉分頁即清除，更安全
- 防止 token 長期暴露
- 連接狀態用 `localStorage` 保持持久化

### 3. MIRS Satellite 時程

**決定**：Phase 2 再實作

**原因**：
- 先驗證 CIRS Satellite 架構
- 醫護人員使用情境不同
- 可共用已開發的基礎元件

---

## 📚 相關文件

- [志工 PWA 安裝指南](./volunteer-pwa-guide.md)
- [CIRS 開發規格書](../CIRS_DEV_SPEC.md)
- [xIRS Secure Exchange Spec v2.0](./xIRS_SECURE_EXCHANGE_SPEC_v2.md)
- [MIRS README](../../MIRS-v2.0-single-station/README.md)
- [README](../README.md)

---

*Last Updated: 2025-12-18 (v1.3.1)*
