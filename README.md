# CIRS - Community Inventory Resilience System

> 社區韌性物資管理系統 v1.1

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

## 概述

CIRS 是社區級災難韌性管理系統，整合物資管理、人員報到、檢傷分類、互助通訊等功能。設計用於 Raspberry Pi 部署，支援離線運作。

### 核心功能

| 功能 | 說明 |
|------|------|
| **物資管理** | 庫存追蹤、發放紀錄、效期管理、入庫/出庫 |
| **設備管理** | 設備檢查、狀態追蹤（正常/待修/停用） |
| **人員報到** | 災民登記、ID 發放、位置追蹤 |
| **檢傷分類** | START Protocol 四級分類 (GREEN/YELLOW/RED/BLACK) |
| **互助留言板** | 尋人、求助、公告、回覆功能 |
| **防災資料庫** | 離線文件下載 |
| **HIRS 同步** | 發放物資 QR Code 同步到個人 HIRS |
| **MIRS 連結** | RED/YELLOW 傷患可連結至 MIRS 處置記錄 |

### 系統架構

```
┌─────────────────────────────────────────────────┐
│  Raspberry Pi (192.168.x.x)                     │
├─────────────────────────────────────────────────┤
│  Port 80:   Portal (統一入口)                   │
│  Port 8090: CIRS API (FastAPI)                  │
│  Port 8000: MIRS (醫療庫存，選配)               │
└─────────────────────────────────────────────────┘
```

## 技術棧

- **Frontend**: Alpine.js + Tailwind CSS + PWA
- **Backend**: Python 3.11+ / FastAPI + SQLite (WAL mode)
- **Deployment**: Raspberry Pi 4/5 + Nginx

## 系統需求

- Python 3.11, 3.12, 或 3.13
- 建議使用虛擬環境 (venv)

## 快速開始

### 開發環境 (macOS/Linux)

```bash
# 1. Clone
git clone https://github.com/cutemo0953/CIRS.git
cd CIRS

# 2. 建立虛擬環境
python3 -m venv venv
source venv/bin/activate  # Linux/macOS
# Windows: venv\Scripts\activate

# 3. 安裝 Python 依賴 (需先升級 pip)
cd backend
pip install --upgrade pip
pip install -r requirements.txt

# 4. 初始化資料庫
python init_db.py

# 5. 啟動後端
uvicorn main:app --host 0.0.0.0 --port 8090 --reload

# 6. 開啟瀏覽器
open http://localhost:8090
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
│   │   ├── inventory.py     # 物資
│   │   ├── person.py        # 人員
│   │   ├── events.py        # 事件
│   │   ├── messages.py      # 留言板
│   │   └── system.py        # 系統 (時間同步等)
│   ├── requirements.txt
│   └── data/
│       └── cirs.db          # SQLite 資料庫
│
├── frontend/
│   ├── index.html           # PWA 主檔案
│   ├── manifest.json
│   ├── sw.js
│   └── assets/
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

## UI/UX 特色 (v1.1)

### Portal 管理
- 管理員可編輯站點名稱
- 管理員可發布/編輯廣播公告

### Frontend 功能
- **即時統計**：灰階統計列顯示收容人數、物資品項、設備正常、今日留言
- **物資管理**：入庫/發放按鈕固定在底部，配色 (#4c826b / #fee39a)
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

## 開發規格

完整規格書請參閱 [CIRS_DEV_SPEC.md](./CIRS_DEV_SPEC.md)，包含：

- Database Schema
- API Endpoints
- UI/UX 設計
- 離線同步策略
- 備份機制
- DS3231 RTC 安裝指南

## 更新日誌

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
