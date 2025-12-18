# CIRS - Community Inventory Resilience System

> 社區韌性物資管理系統 v1.7.1

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

## 概述

CIRS 是社區級災難韌性管理系統，整合物資管理、人員報到、檢傷分類、互助通訊等功能。設計用於 Raspberry Pi 部署，支援離線運作。

### 核心功能

| 功能 | 說明 |
|------|------|
| **物資管理** | 庫存追蹤、發放紀錄、效期管理、入庫/出庫、組套入庫 |
| **設備管理** | 設備檢查、狀態追蹤、設備範本（7種預設組合） |
| **人員報到** | 災民登記、ID 發放、位置追蹤、照片辨識 |
| **檢傷分類** | START Protocol 四級分類 (GREEN/YELLOW/RED/BLACK) |
| **互助留言板** | 尋人、求助、公告、回覆功能 |
| **防災資料庫** | 離線文件下載 |
| **安全備份** | 加密備份、USB 備份、備份驗證、審計記錄 |
| **HIRS 同步** | 發放物資 QR Code 同步到個人 HIRS |
| **MIRS 連結** | RED/YELLOW 傷患可連結至 MIRS 處置記錄 |
| **Satellite PWA** | 志工行動 App，支援離線報到/物資領取 |
| **xIRS 安全交換** | 國防級端對端加密 USB 資料傳輸 (v2.0) |

### v1.7 新功能：xIRS 安全資料交換

xIRS (Cross-IRS) 是專為離線 USB 傳輸設計的安全通訊協議：

- **端對端加密** - Curve25519 + XSalsa20-Poly1305
- **數位簽章** - Ed25519 防竄改驗證
- **防重放攻擊** - UUID + 時間戳 + 已處理清單
- **信任名冊** - 只接收已驗證站點的資料

詳見 [xIRS 技術規格](docs/xIRS_SECURE_EXCHANGE_SPEC_v2.md)

### 系統架構

```
┌─────────────────────────────────────────────────┐
│  Raspberry Pi (192.168.x.x) - Hub              │
├─────────────────────────────────────────────────┤
│  Port 80:   Portal (統一入口)                   │
│  Port 8090: CIRS API (FastAPI)                  │
│  Port 8000: MIRS (醫療庫存，選配)               │
└─────────────────────────────────────────────────┘
              ↑ WiFi / LAN
    ┌─────────┴─────────┐
    │  Satellite PWA    │  ← 志工手機
    │  (離線優先)        │     報到/物資領取
    └───────────────────┘
```

## 技術棧

- **Frontend**: Alpine.js + Tailwind CSS + PWA
- **Backend**: Python 3.11+ / FastAPI + SQLite (WAL mode)
- **Deployment**: Raspberry Pi 4/5 + Nginx
- **i18n**: JSON-based translations (zh-TW, ja)

## 多語系支援 (i18n)

CIRS 支援繁體中文與日文介面，採用 JSON 語言檔架構：

### 支援語言

| 語言 | 代碼 | 檔案 |
|------|------|------|
| 繁體中文 | `zh-TW` | `frontend/lang/zh-TW.json` |
| 日本語 | `ja` | `frontend/lang/ja.json` |

### 切換語言

1. 以管理員登入 (admin001)
2. 點選統計列的「系統」按鈕
3. 選擇「站點設定」
4. 在語言選擇區點選目標語言

語言設定會儲存在瀏覽器 localStorage，下次開啟時自動載入。

### 日文專有名詞對照

日文版採用日本防災領域專有術語：

| 功能 | 繁體中文 | 日本語 | 備註 |
|------|----------|--------|------|
| 人員管理 | 人員 | 避難者 | 日本慣用語 |
| 物資管理 | 物資 | 支援物資 | 更有救援感 |
| 檢傷分類 | 檢傷分類 | トリアージ | 日本醫療慣用片假名 |
| 入庫 | 入庫 | 入庫 | 相同 |
| 退場 | 退場 | 退所 | 日本用語 |
| 在場人數 | 在場人數 | 在所人数 | |
| 志工 | 志工 | ボランティア | 通用 |
| 設備範本 | 設備範本 | 設備テンプレート | |

## 系統需求

- Python 3.11, 3.12, 或 3.13
- 建議使用虛擬環境 (venv)

## 快速開始

### 本地端開發環境 (macOS/Linux)

```bash
# 1. Clone 專案
git clone https://github.com/cutemo0953/CIRS.git
cd CIRS

# 2. 建立虛擬環境
python3 -m venv venv
source venv/bin/activate  # Linux/macOS
# Windows: venv\Scripts\activate

# 3. 安裝 Python 依賴
cd backend
pip install --upgrade pip
pip install -r requirements.txt

# 4. 初始化資料庫
python init_db.py

# 5. 啟動後端 (開發模式，支援熱重載)
uvicorn main:app --host 0.0.0.0 --port 8090 --reload

# 6. 開啟瀏覽器測試
# API 文件: http://localhost:8090/docs
# 前端介面: http://localhost:8090/frontend
# Portal 入口: http://localhost:8090/portal
```

### 本地端測試流程

```bash
# 確認服務運行中
curl http://localhost:8090/api/health
# 預期回應: {"status":"healthy"}

# 查看系統統計
curl http://localhost:8090/api/stats

# 測試登入 (預設帳號 admin001, PIN: 1234)
curl -X POST http://localhost:8090/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"person_id":"admin001","pin":"1234"}'
```

### 本地端更新流程

當 GitHub 有新版本時，依以下步驟更新：

```bash
# 1. 拉取最新程式碼
cd ~/Downloads/CIRS
git pull origin main

# 2. 後端 Python 檔案變更
#    - 若使用 --reload 參數，uvicorn 會自動重載，無需重啟
#    - 若未使用 --reload，需 Ctrl+C 後重新啟動

# 3. 前端 HTML/JS 檔案變更
#    - 瀏覽器強制重新整理：
#      macOS: Cmd + Shift + R
#      Windows/Linux: Ctrl + Shift + R
#    - 或清除瀏覽器快取

# 4. 資料庫 Schema 變更（若有）
cd backend
python init_db.py  # 會自動執行 migration
```

**開發模式 vs 正式環境：**

| 項目 | 開發模式 | 正式環境 |
|------|----------|----------|
| 啟動指令 | `uvicorn main:app --reload` | `uvicorn main:app` |
| Python 變更 | 自動重載 | 需手動重啟 |
| 前端變更 | 強制重整瀏覽器 | 強制重整瀏覽器 |
| 效能 | 較慢（監控檔案） | 較快 |

**常見問題：**

```bash
# Q: uvicorn: command not found
# A: 需要在 backend 目錄安裝依賴
cd ~/CIRS/backend
pip install -r requirements.txt

# Q: Error loading ASGI app. Could not import module "main"
# A: 必須在 backend 目錄執行 uvicorn
cd ~/CIRS/backend   # 關鍵：要在 backend 目錄
uvicorn main:app --host 0.0.0.0 --port 8090 --reload

# Q: 更新後前端沒有變化？
# A: 清除瀏覽器快取或使用無痕模式
#    macOS: Cmd + Shift + R
#    Windows/Linux: Ctrl + Shift + R

# Q: 更新後 API 報錯？
# A: 可能需要更新資料庫
cd backend && python init_db.py

# Q: Port 8090 已被佔用 (Address already in use)
# A: 找出並關閉佔用程序
lsof -ti :8090 | xargs kill -9   # macOS/Linux
# Windows: netstat -ano | findstr :8090 然後 taskkill /PID <PID> /F

# Q: sqlite3.OperationalError: no such column
# A: 資料庫 schema 已更新，需重新初始化
cd backend && python init_db.py  # 輸入 y 確認重建
```

### Windows 開發環境

```powershell
# 1. Clone 專案
git clone https://github.com/cutemo0953/CIRS.git
cd CIRS

# 2. 建立虛擬環境
python -m venv venv
venv\Scripts\activate

# 3. 安裝依賴
cd backend
pip install --upgrade pip
pip install -r requirements.txt

# 4. 初始化資料庫
python init_db.py

# 5. 啟動後端
uvicorn main:app --host 0.0.0.0 --port 8090 --reload

# 6. 開啟瀏覽器: http://localhost:8090/frontend
```

### Raspberry Pi 部署

```bash
# 1. Clone
cd ~
git clone https://github.com/cutemo0953/CIRS.git
cd CIRS

# 2. 建立虛擬環境 (在專案根目錄)
python3 -m venv venv
source venv/bin/activate

# 3. 安裝依賴 (需先升級 pip)
cd backend
pip install --upgrade pip
pip install -r requirements.txt

# 4. 初始化資料庫
python init_db.py

# 5. 測試啟動
uvicorn main:app --host 0.0.0.0 --port 8090

# 6. 設定 systemd 服務 (開機自動啟動)
sudo nano /etc/systemd/system/cirs.service
```

**cirs.service 範例：**
```ini
[Unit]
Description=CIRS Backend API
After=network.target

[Service]
Type=simple
User=dno
WorkingDirectory=/home/dno/CIRS/backend
ExecStart=/home/dno/CIRS/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8090
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
# 啟用服務
sudo systemctl daemon-reload
sudo systemctl enable cirs
sudo systemctl start cirs
sudo systemctl status cirs
```

詳細部署說明請參閱 [CIRS_DEV_SPEC.md](./CIRS_DEV_SPEC.md)。

## 預設帳號

系統預設建立以下帳號供測試使用（**PIN 皆為 `1234`**）：

| ID | 名稱 | 角色 | 權限 |
|---|---|---|---|
| `admin001` | 管理員 | admin | 全部功能 + 站點設定 + 刪除留言 |
| `staff001` | 志工小明 | staff | 入庫/出庫/報到/設備檢查 |
| `medic001` | 醫護小華 | medic | 檢傷分類 + staff 權限 |

### 新增帳號到現有資料庫

如果是現有部署，需手動新增 staff/medic 帳號：

```bash
sqlite3 backend/data/cirs.db "INSERT OR IGNORE INTO person (id, display_name, role, pin_hash) VALUES
  ('staff001', '志工小明', 'staff', '\$2b\$12\$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/X4.V0jlKfM1c4QGPC'),
  ('medic001', '醫護小華', 'medic', '\$2b\$12\$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/X4.V0jlKfM1c4QGPC');"
```

## 專案結構

```
CIRS/
├── backend/
│   ├── main.py              # FastAPI 入口
│   ├── database.py          # SQLite 連線 (WAL mode)
│   ├── models.py            # SQLAlchemy models
│   ├── routes/
│   │   ├── auth.py          # 認證
│   │   ├── inventory.py     # 物資（含組套管理）
│   │   ├── person.py        # 人員（含管理員功能）
│   │   ├── events.py        # 事件
│   │   ├── messages.py      # 留言板
│   │   ├── backup.py        # 備份系統（加密/USB/驗證）
│   │   └── system.py        # 系統 (時間同步等)
│   ├── requirements.txt
│   └── data/
│       └── cirs.db          # SQLite 資料庫
│
├── frontend/
│   ├── index.html           # PWA 主檔案
│   ├── manifest.json
│   ├── sw.js
│   ├── lang/
│   │   ├── zh-TW.json       # 繁體中文
│   │   └── ja.json          # 日本語
│   ├── mobile/              # Satellite PWA (志工手機)
│   │   ├── index.html
│   │   ├── manifest.json
│   │   ├── service-worker.js
│   │   └── icons/
│   └── assets/
│
├── docs/
│   └── volunteer-pwa-guide.md  # 志工 PWA 安裝指南
│
├── portal/
│   └── index.html           # 統一入口頁面
│
├── files/                   # 防災資料庫
│   ├── maps/
│   ├── manuals/
│   └── contacts/
│
├── scripts/
│   ├── backup.sh            # 備份腳本
│   ├── cleanup.sh           # 清理腳本
│   └── check_rtc.sh         # RTC 檢查
│
├── CIRS_DEV_SPEC.md         # 完整開發規格書
└── README.md
```

## 與 HIRS/MIRS 的關係

| 系統 | 用途 | 部署 |
|------|------|------|
| HIRS | 家庭物資管理 | 個人手機 PWA |
| MIRS | 醫療站庫存 | Raspberry Pi |
| CIRS | 社區/收容所 | Raspberry Pi |

CIRS 發放物資時會產生 QR Code，使用者可用 HIRS 掃描同步到個人庫存。

## UI/UX 特色 (v1.4)

### Dual-Track 架構

CIRS v1.4 採用 Dual-Track 設計，明確分離公共資訊與操作功能：

| 介面 | 用途 | 使用者 | URL |
|------|------|--------|-----|
| **Portal** | 公共資訊看板 | 所有人（無需登入） | `/portal` |
| **Frontend** | 操作人員控制台 | Staff/Medic/Admin | `/frontend` |

### Portal (公共看板)
- **交通燈狀態系統**：四大指標（收容人數、飲用水、糧食、設備）
- **燈號邏輯**：>3 天=綠、1-3 天=黃、<1 天=紅
- 公告自動顯示、狀態說明圖例
- 連結防災資料庫、互助留言
- **無需登入**，純唯讀

### Frontend (操作台)
- **即時統計**：灰階統計列顯示在場人數、物資品項、設備正常、待解決
- **系統按鈕**（Admin 專用）：資料備份、站點設定、API 文件
- **物資管理**：入庫/組套/發放按鈕固定在底部
- **組套入庫**：預設 7 種組套（防災包、糧食補給、醫療補給等）
- **設備管理**：檢查/編輯/刪除按鈕，狀態統計圖表
- **留言板**：回覆留言、標記已解決（管理員）、刪除（管理員）
- **檢傷分類**：淺色底+深色字按鈕，選中變深色
- **MIRS 連結**：RED/YELLOW 傷患旁顯示 MIRS 處置記錄連結

### 權限控制

| 功能 | public | staff | medic | admin |
|------|--------|-------|-------|-------|
| 瀏覽物資/人員 | ✓ | ✓ | ✓ | ✓ |
| 入庫/出庫 | - | ✓ | ✓ | ✓ |
| 設備檢查 | - | ✓ | ✓ | ✓ |
| 檢傷分類 | - | - | ✓ | ✓ |
| 刪除設備/留言 | - | - | - | ✓ |
| 編輯站點設定 | - | - | - | ✓ |

## API 端點說明

### 備份系統 API (`/api/backup`)

```bash
# 查看備份狀態
curl http://localhost:8090/api/backup/status

# 建立本地加密備份
curl -X POST http://localhost:8090/api/backup/create \
  -H "Content-Type: application/json" \
  -d '{"operator_id":"admin001","target":"local","encrypt":true,"password":"your_password"}'

# 建立 USB 備份 (需插入 USB)
curl -X POST http://localhost:8090/api/backup/create \
  -H "Content-Type: application/json" \
  -d '{"operator_id":"admin001","target":"usb","encrypt":true,"password":"your_password"}'

# 驗證備份完整性
curl http://localhost:8090/api/backup/verify/1

# 查看備份審計記錄
curl http://localhost:8090/api/backup/audit-log
```

### 人員管理 API (`/api/person`)

```bash
# 報到登記 (含照片)
curl -X POST http://localhost:8090/api/person \
  -H "Content-Type: application/json" \
  -d '{
    "display_name":"測試病患",
    "triage_status":"YELLOW",
    "photo_data":"data:image/jpeg;base64,...",
    "physical_desc":"男性，約40歲，藍色上衣"
  }'

# 查詢待辨識人員
curl http://localhost:8090/api/person/unidentified/list

# 確認身分 (管理員)
curl -X POST http://localhost:8090/api/person/P0001/confirm-identity \
  -H "Content-Type: application/json" \
  -d '{"national_id":"A123456789","operator_id":"admin001"}'

# 查詢人員修改記錄
curl http://localhost:8090/api/person/P0001/audit-log
```

## 開發規格

### 主要文件

| 文件 | 說明 |
|------|------|
| [CIRS_DEV_SPEC.md](./CIRS_DEV_SPEC.md) | CIRS 完整開發規格書 |
| [SATELLITE_PWA_SPEC.md](./docs/SATELLITE_PWA_SPEC.md) | Satellite PWA 架構與開發規格 |
| [volunteer-pwa-guide.md](./docs/volunteer-pwa-guide.md) | 志工 PWA 安裝指南 |

### CIRS_DEV_SPEC.md 包含：

- Database Schema
- API Endpoints
- UI/UX 設計
- 離線同步策略
- 備份機制
- DS3231 RTC 安裝指南

### SATELLITE_PWA_SPEC.md 包含：

- Hub & Spoke 架構說明（指揮官與傳令兵）
- CIRS Satellite PWA 功能規格
- MIRS Satellite PWA 功能規格（Phase 2）
- 離線同步策略
- API Endpoints
- 開發任務清單

## 更新日誌

### v1.7.1 (2025-12-18) - Satellite PWA v1.3.1
- **新增**：角色控制功能
  - Hub 可指定配對碼允許的角色（僅志工/僅管理員/兩者）
  - 配對 Modal 新增角色選擇下拉選單
  - PWA 角色選擇按鈕根據權限顯示禁用狀態
- **新增**：新人登記功能
  - 支援檢傷分類（輕傷/延遲/立即/死亡）
  - 區域選單從 Hub 載入
  - 卡片號碼與備註欄位
- **改進**：直接 API 呼叫
  - 線上時直接呼叫 `/api/satellite/checkin` 與 `/api/satellite/supply`
  - 不經過 Service Worker 佇列，回應更即時
- **修復**：Safari 外部 app 開啟空白頁問題
  - 新增 CDN 載入偵測與 fallback loading 畫面
  - 10 秒逾時保護機制
- **新增 API**：
  - `POST /api/auth/pairing-code` - 指定允許角色
  - `GET /api/satellite/zones` - 取得 Hub 預設區域
  - `POST /api/satellite/checkin` - 直接報到/退場/新人登記
  - `POST /api/satellite/supply` - 直接物資發放

### v1.6 (2024-12) - Satellite PWA
- **新增**：志工行動 App (Satellite PWA)
  - 離線優先架構（可在無網路環境下操作）
  - QR Code 掃描連接 Hub
  - 人員報到/退場功能
  - 物資領取確認功能
  - iOS Safari 相容（無需 Background Sync API）
  - IndexedDB 同步佇列
  - 自動/手動同步機制
- **新增**：[志工 PWA 安裝指南](docs/volunteer-pwa-guide.md)
  - iOS (Safari) 安裝步驟
  - Android (Chrome) 安裝步驟
  - 首次連接設定說明
  - 常見問題排解
- **改進**：組套範本與設備範本 i18n
  - 組套內物品名稱/單位翻譯
  - 設備範本語言切換時自動重新生成

### v1.5.1 (2024-12) - 完整 i18n 翻譯
- **完成**：所有 UI 元件完整翻譯
  - 全部 Modal（公告發佈、人員移動、組套入庫、寄贈接收、物資紀錄等）
  - 設備範本選擇/管理/編輯介面
  - 物資發放 QR Code、寄贈收據介面
  - 動態日期格式（根據語言切換 locale）
- **新增翻譯 Key**：
  - `inventory.historyTitle/unknownItem/noHistory/noMatchingHistory/loadMore`
- **改進**：Header 語言切換器（參考 denovortho-site 設計）

### v1.5 (2024-12) - 多語系支援 (i18n)
- **新增**：國際化架構 (i18n)
  - JSON 語言檔架構 (`frontend/lang/`)
  - 繁體中文 (zh-TW) 預設語言
  - 日本語 (ja) 完整翻譯，含防災專有術語
- **新增**：語言切換功能
  - 站點設定內可切換語言
  - Header 快速語言切換
  - localStorage 持久化語言偏好
  - 即時切換無需重新整理
- **翻譯範圍**：
  - 底部導覽列、統計列、系統選單
  - 登入介面、檢傷分類介面
  - 設備範本管理介面
  - 錯誤訊息、Toast 通知
- **日文術語**：採用日本防災領域專有名詞
  - 「避難者」取代「人員」
  - 「支援物資」取代「物資」
  - 「トリアージ」取代「檢傷分類」

### v1.4.1 (2024-12) - Dual-Track Architecture
- **架構重構**：實施 Dual-Track 策略
  - Portal = 公共資訊看板（唯讀、交通燈系統、無需登入）
  - Frontend = 操作人員控制台（需認證、資料密集、CRUD）
- **Portal 重構**：
  - 移除管理員登入、備份、設定功能
  - 新增交通燈狀態系統（綠/黃/紅）
  - 四大指標：收容人數、飲用水、糧食、設備
  - 公告自動顯示、狀態說明圖例
- **Frontend 強化**：
  - 統計列「收容人數」改為「在場人數」
  - 新增系統按鈕（Admin 專用）：資料備份、站點設定、API 文件
  - 備份管理整合至 Frontend
- **API 新增**：`GET /api/public/status` 輕量公開端點

### v1.4 (2024-12)
- 新增：設備範本功能
  - 7 種預設範本（電力設備組、通訊設備組、醫療設備組、收容基本設備、炊事設備組、衛生設備組、救援工具組）
  - 套用範本可批次建立設備，含預設檢查週期
  - 管理員可新增/編輯/刪除自訂範本
- 改進：物資發放按鈕改用大地色系 (amber-600)
- 改進：人員清單區域/檢傷按鈕改用 primary 色系
- 新增：單人快速移動區域功能
- 新增：物資紀錄查詢（管理員）

### v1.3 (2024-12)
- 新增：安全備份系統
  - 加密備份（密碼保護）
  - USB 外接硬碟備份支援
  - 備份驗證（SHA-256 校驗）
  - 備份記錄與審計日誌
  - 備份排程設定
- 新增：無法辨識身分者拍照功能
  - 昏迷/無法辨識身分時可拍照存檔
  - 外觀特徵描述
  - 待辨識人員列表
- 新增：管理員人員管理功能
  - 修正人員資料（含審計記錄）
  - 原因代碼範本（輸入錯誤/身分確認/重複登記/資料更正）
  - 確認身分功能
  - 修改記錄查詢
- 新增：完整審計日誌系統
  - 所有敏感操作留存記錄
  - 記錄操作者、時間、原因、修改前後值

### v1.2 (2024-12)
- 新增：組套入庫功能 (Bundle Intake)
  - 7 種預設組套：防災包、糧食補給、醫療補給、電力補給、嬰兒用品、日用品、收容所設備
  - 支援倍數入庫（一次入庫多套）
  - 自動合併現有物資或建立新物資
- 新增：組套管理功能（管理員）
  - 新增/編輯/刪除組套
  - 自訂組套圖示、名稱、說明
  - 動態新增/移除組套內物資
- 改進：物資管理底部按鈕改為 3 欄（入庫/組套/發放）
- 改進：人員 ID 系統重新設計
  - 系統序號（P0001, P0002...）作為對外顯示
  - 身分證字號 hash 後儲存（隱私保護）
  - 無法辨識身分時自動產生序號
  - 重複身分證會回傳已登記資訊

### v1.1 (2024-12)
- 新增：設備管理 (檢查/編輯/刪除/狀態統計)
- 新增：留言板回覆功能
- 新增：留言解決/刪除功能 (管理員)
- 新增：MIRS 處置記錄連結
- 新增：多角色帳號 (admin/staff/medic)
- 改進：Portal 站點名稱/公告編輯
- 改進：物資入庫/發放按鈕移至底部
- 改進：即時統計灰階顯示
- 修正：檢傷按鈕樣式 (淺底深字)

### v1.0 (2024-12)
- 初始版本

## 授權

MIT License

---

**Designed for Taiwan Disaster Preparedness**
De Novo Orthopedics Inc. / 谷盺生物科技股份有限公司
