# MIRS 單站/多站 Database 開發歷程總結

**整理日期**: 2024-12-10
**用途**: 作為 CIRS 多站 ID 管理設計參考

---

## 1. 版本演進概覽

```
v1.4.2-plus → v1.4.5 → v1.5 → v2.0 → v2.3
   │            │        │       │       │
   │            │        │       │       └── MVP聚焦：移除網路功能
   │            │        │       └── 靜態配置：修復 Station ID 同步問題
   │            │        └── Setup Wizard：動態配置 + Database Profiles
   │            └── 部署到 Raspberry Pi 發現同步問題
   └── 血袋標籤列印功能
```

---

## 2. 單站架構時期 (v1.4.2-plus ~ v1.4.5)

### 2.1 設計理念
- **單機優先**: 一台 Raspberry Pi = 一個站點
- **離線運作**: 無需網路，WiFi 熱點自成一體
- **簡單部署**: 20 分鐘自動安裝腳本

### 2.2 血袋標籤功能 (v1.4.2-plus)
這是 CIRS 發放記錄 QR Code 的重要參考：

```javascript
// 血袋標籤列印功能
printBloodBagLabel(record) {
    const qrData = {
        id: record.id,
        blood_type: record.blood_type,
        quantity: record.quantity,
        dispensed_at: record.dispensed_at,
        patient_ref: record.patient_ref_id
    };

    // 產生 QR Code 包含完整追蹤資訊
    const qrCode = generateQRCode(JSON.stringify(qrData));

    // 標籤格式：上方文字 + 下方 QR Code
    printLabel({
        header: `${record.blood_type} x ${record.quantity}u`,
        subtext: record.patient_ref_id || '未指定病患',
        qrCode: qrCode,
        timestamp: formatDate(record.dispensed_at)
    });
}
```

### 2.3 Station ID 格式
```
{TYPE}-{ORG}-{NUMBER}

TYPE 站點類型:
- HC     = Health Center (衛生所)
- BORP   = Backup Operating Room Platform (備援手術站)
- LOG-HUB = Logistics Hub (物資中繼站)
- HOSP   = Hospital (醫院)
- SURG   = Surgical Station (手術站)

ORG 組織代碼:
- DNO = De Novo Orthopedics
- VGH = Veterans General Hospital
- NTUH = National Taiwan University Hospital

NUMBER 站點編號:
- 01, 02, 03...

範例:
- BORP-VGH-01  (榮總備援手術站 1 號)
- HC-DNO-01   (DNO 衛生所 1 號)
- SURG-02     (手術站 2 號，簡化格式)
```

---

## 3. Setup Wizard 時期 (v1.5)

### 3.1 設計目標
支援不同類型站點快速部署，首次啟動時選擇站點類型

### 3.2 Database Profiles 系統
```
database/profiles/
├── health_center.sql      # 衛生所 - 15藥品 + 4設備
├── hospital_custom.sql    # 醫院自訂 - 空白
├── surgical_station.sql   # BORP - 15藥品 + 16組手術器械
└── logistics_hub.sql      # 物資中繼站 - 5倍存量
```

### 3.3 遇到的問題：Station ID 不同步

**問題描述**:
部署到 Raspberry Pi 後，Setup Wizard 完成設定，但物品查詢顯示「載入失敗」

**根本原因**:
```
1. 後端啟動 → 載入預設站點 ID (HC-000000)
2. 使用者完成 Setup Wizard → 建立新站點 (SURG-02)
3. 後端記憶體仍使用 HC-000000 過濾資料
4. API 查詢結果 = 0 筆 → 前端顯示「載入失敗」
```

**問題程式碼**:
```python
# main.py - v1.4.5 有問題的版本
class Config:
    STATION_ID = "HC-000000"  # 預設值，被 Setup Wizard 更新後後端不知道
```

```javascript
// setup_wizard.html - 只更新資料庫，未同步後端
async completeSetup() {
    await fetch('/api/setup/complete', {
        method: 'POST',
        body: JSON.stringify({ station_id: this.stationId })
    });
    // 後端 Config.STATION_ID 還是 HC-000000！
}
```

---

## 4. 靜態配置時期 (v2.0)

### 4.1 解決方案：移除 Setup Wizard
從「動態配置」改為「靜態配置」，站點資訊直接寫在程式碼/配置檔

### 4.2 新架構

```
v1.4.5 (動態配置 - 有問題):
┌─────────────┐    ┌──────────────┐    ┌─────────────┐
│ Setup Wizard│ → │ station_config│ → │   main.py   │
│   (前端)    │    │    .json     │    │  (需reload) │
└─────────────┘    └──────────────┘    └─────────────┘
      ↓                                       ↓
   localStorage                         記憶體變數
      ↓                                       ↓
   Index.html  ←─────── 不同步 ───────→  API 過濾


v2.0 (靜態配置 - 解決問題):
┌─────────────┐    ┌─────────────┐
│  config.py  │ → │   main.py   │
│  (站點設定) │    │  (啟動載入) │
└─────────────┘    └─────────────┘
                         ↓
                   /api/station/info
                         ↓
                   Index.html (自動取得)
```

### 4.3 v2.0 Station Info API
前端不再自己存 Station ID，而是從後端 API 取得：

```python
@app.get("/api/station/info")
async def get_station_info():
    return {
        "station_id": config.STATION_ID,
        "station_name": config.STATION_NAME,
        "station_type": config.STATION_TYPE,
        "organization": {
            "code": config.ORG_CODE,
            "name": config.ORG_NAME
        },
        "version": config.VERSION
    }
```

```javascript
// 前端初始化時從 API 取得站點資訊
async loadStationInfo() {
    const response = await fetch('/api/station/info');
    const data = await response.json();
    this.stationId = data.station_id;  // 確保與後端同步
}
```

---

## 5. 多站架構設計 (v2.0 MULTI_STATION_DEV_GUIDE)

### 5.1 Hub-Spoke 三層架構

```
                    ┌─────────────────┐
                    │   Total Hub     │  第三層：總部
                    │  (雲端/安全區)   │
                    └────────┬────────┘
                             │
              ╔══════════════╧══════════════╗
              ║         HTTP/JSON           ║
              ╚══════════════╤══════════════╝
                             │
         ┌───────────────────┼───────────────────┐
         │                   │                   │
    ┌────▼────┐         ┌────▼────┐         ┌────▼────┐
    │ Zone Hub │         │ Zone Hub │         │ Zone Hub │  第二層：區域中樞
    │  (北區)  │         │  (中區)  │         │  (南區)  │
    └────┬────┘         └────┬────┘         └────┬────┘
         │                   │                   │
    ╔════╧════╗         ╔════╧════╗         ╔════╧════╗
    ║  WiFi   ║         ║  WiFi   ║         ║  WiFi   ║
    ╚════╤════╝         ╚════╤════╝         ╚════╤════╝
         │                   │                   │
    ┌────▼────┐         ┌────▼────┐         ┌────▼────┐
    │ Spoke 1 │         │ Spoke 3 │         │ Spoke 5 │  第一層：前線站點
    │ Spoke 2 │         │ Spoke 4 │         │ Spoke 6 │
    └─────────┘         └─────────┘         └─────────┘
```

### 5.2 Transfer Record 跨站轉移記錄

當物資從一站轉移到另一站：

```python
class TransferRecord:
    id: int
    source_station_id: str      # 來源站點
    destination_station_id: str  # 目的站點
    item_id: int
    quantity: int
    transfer_type: str  # 'PUSH' (主動送出) / 'PULL' (請求調撥)
    status: str  # 'PENDING', 'IN_TRANSIT', 'RECEIVED', 'REJECTED'
    created_at: datetime
    received_at: datetime | None
    notes: str | None
```

### 5.3 JSON 同步封包格式

```json
{
  "packet_type": "SYNC_REQUEST",
  "source_station": "BORP-VGH-01",
  "destination_station": "HUB-NORTH",
  "timestamp": "2024-12-10T10:30:00+08:00",
  "payload": {
    "inventory_snapshot": [...],
    "dispense_records": [...],
    "transfer_records": [...],
    "blood_inventory": [...]
  },
  "checksum": "sha256:abc123..."
}
```

### 5.4 Failover 機制

```
正常情況: Spoke → Zone Hub → Total Hub

Zone Hub 斷線時:
Spoke → (本地暫存) → Zone Hub 恢復後自動同步

Total Hub 斷線時:
Zone Hub → (本地暫存) → Total Hub 恢復後自動同步

完全離線時:
Spoke 獨立運作，USB 匯出 JSON 人工搬運
```

---

## 6. 給 CIRS 的建議

### 6.1 ID 命名規則建議

```
CIRS Station ID 格式建議：
{SHELTER_TYPE}-{DISTRICT}-{NUMBER}

SHELTER_TYPE:
- MAIN = 主要收容所
- SUB  = 次要收容點
- MED  = 醫療站
- LOG  = 物資集散點

DISTRICT 區域代碼:
- 使用行政區代碼 (例如台中南屯 = TC-NT)

範例:
- MAIN-TC-NT-01  (台中南屯主收容所 1 號)
- MED-TC-NT-01   (台中南屯醫療站 1 號)
- LOG-TC-01      (台中物資集散點 1 號)
```

### 6.2 CIRS-HIRS QR Code 同步建議

參考 MIRS 血袋標籤功能，發放記錄 QR Code 應包含：

```javascript
// CIRS 發放記錄 QR Code 內容建議
const distributionQRData = {
    type: 'CIRS_DISTRIBUTION',
    version: '1.0',
    station_id: 'MAIN-TC-NT-01',  // 發放站點
    record_id: 123,
    recipient_id: 456,
    recipient_name: '王小明',
    items: [
        { name: '礦泉水', quantity: 2, unit: '瓶' },
        { name: '餅乾', quantity: 1, unit: '包' }
    ],
    distributed_at: '2024-12-10T14:30:00+08:00',
    distributed_by: 'admin001'
};
```

HIRS 掃描後應能解析此格式並顯示記錄詳情。

### 6.3 多站 Schema 建議

```sql
-- 站點配置表
CREATE TABLE IF NOT EXISTS station_config (
    id INTEGER PRIMARY KEY,
    station_id TEXT UNIQUE NOT NULL,
    station_name TEXT NOT NULL,
    station_type TEXT NOT NULL,  -- MAIN, SUB, MED, LOG
    parent_hub_id TEXT,          -- 上層 Hub 站點 ID
    is_hub INTEGER DEFAULT 0,    -- 是否為 Hub
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 跨站轉移記錄
CREATE TABLE IF NOT EXISTS transfer_record (
    id INTEGER PRIMARY KEY,
    source_station_id TEXT NOT NULL,
    dest_station_id TEXT NOT NULL,
    item_id INTEGER NOT NULL,
    quantity REAL NOT NULL,
    status TEXT DEFAULT 'PENDING',  -- PENDING, IN_TRANSIT, RECEIVED
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    received_at DATETIME,
    FOREIGN KEY (item_id) REFERENCES inventory(id)
);

-- 記錄來源站點
ALTER TABLE inventory ADD COLUMN origin_station_id TEXT;
ALTER TABLE distribution_record ADD COLUMN station_id TEXT;
```

---

## 7. 關鍵教訓總結

| 問題 | MIRS 經歷 | CIRS 應避免 |
|------|----------|-------------|
| Station ID 不同步 | v1.4.5 → v2.0 花費大量時間修復 | 從一開始就用 API 取得站點資訊 |
| Setup Wizard 複雜 | 最終移除，改用靜態配置 | 用環境變數或配置檔，不用精靈 |
| 多站 ID 衝突 | 嚴格格式: TYPE-ORG-NUMBER | 定義清楚的 ID 命名規則 |
| 前後端狀態不一致 | localStorage vs 後端記憶體 | 以後端 API 為單一真相來源 |
| 離線同步 | JSON 封包 + Checksum | 採用相同機制 |

---

## 8. 下一步

1. **修復 CIRS-HIRS QR Code 同步問題**
   - 確認發放記錄 QR Code 包含完整資訊
   - HIRS 端實作 QR Code 解析邏輯

2. **新增發放記錄 QR Code 按鈕**
   - 參考 MIRS 血袋標籤列印功能
   - 在記錄列表加入 QR Code 圖示按鈕

3. **撰寫 CIRS Single-to-Multi Station Dev Spec**
   - 基於本文件和 MIRS 經驗
   - 定義 CIRS 專屬的站點 ID 格式
   - 設計跨站同步機制

---

**文件版本**: v1.0
**作者**: Claude Code
**參考來源**:
- MIRS_v2.0_MULTI_STATION_DEV_GUIDE.md
- MIRS_MIGRATION_GUIDE_v1.1.md
- MIRS_MIGRATION_GUIDE_v1.4.5_to_v2.0.md
- MIRS_v1.4.2-plus_DEV_SPEC.md
- MIRS_v2.3_SPEC.md
