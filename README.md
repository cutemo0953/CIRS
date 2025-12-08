# CIRS - Community Inventory Resilience System

> 社區韌性物資管理系統 v1.0

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

## 概述

CIRS 是社區級災難韌性管理系統，整合物資管理、人員報到、檢傷分類、互助通訊等功能。設計用於 Raspberry Pi 部署，支援離線運作。

### 核心功能

| 功能 | 說明 |
|------|------|
| **物資管理** | 庫存追蹤、發放紀錄、效期管理 |
| **人員報到** | 災民登記、ID 發放 |
| **檢傷分類** | START Protocol 四級分類 |
| **互助留言板** | 尋人、求助、公告 |
| **防災資料庫** | 離線文件下載 |
| **HIRS 同步** | 發放物資同步到個人 HIRS |

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
- **Backend**: Python FastAPI + SQLite (WAL mode)
- **Deployment**: Raspberry Pi 4/5 + Nginx

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

# 3. 安裝 Python 依賴
cd backend
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

# 2. 建立虛擬環境
python3 -m venv venv
source venv/bin/activate

# 3. 安裝依賴
cd backend
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

## 開發規格

完整規格書請參閱 [CIRS_DEV_SPEC.md](./CIRS_DEV_SPEC.md)，包含：

- Database Schema
- API Endpoints
- UI/UX 設計
- 離線同步策略
- 備份機制
- DS3231 RTC 安裝指南

## 授權

MIT License

---

**Designed for Taiwan Disaster Preparedness**
De Novo Orthopedics Inc. / 谷盺生物科技股份有限公司
