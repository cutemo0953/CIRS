# IRS 三合一系統部署指南

在樹莓派上部署 MIRS、CIRS、HIRS 三合一離線庫存管理系統。

## 系統概覽

| 系統 | 用途 | Port | 說明 |
|------|------|------|------|
| MIRS | 醫療站庫存 | 8000 | 藥品、醫療器材管理 |
| CIRS | 社區物資站 | 8001 | 社區發放物資管理 |
| HIRS | 家庭物資 | 8082 | 家庭防災物資管理 (PWA) |

## 快速部署

### 1. 準備樹莓派

```bash
# 更新系統
sudo apt update && sudo apt upgrade -y

# 建立專案目錄
mkdir -p /home/pi/{MIRS,CIRS,HIRS}
```

### 2. 複製程式碼

將三個系統的程式碼分別複製到：
- `/home/pi/MIRS/`
- `/home/pi/CIRS/`
- `/home/pi/HIRS/`

可以用 USB 隨身碟、SCP 或 Git clone。

### 3. 執行部署腳本

```bash
cd /home/pi/CIRS/deploy
chmod +x deploy.sh setup-wifi-ap.sh
./deploy.sh
```

部署腳本提供互動式選單：
- 部署全部系統
- 只部署單一系統
- 設定 WiFi 熱點
- 查看服務狀態

### 4. 設定 WiFi 熱點（離線使用）

```bash
./deploy.sh --wifi

# 或手動執行
./setup-wifi-ap.sh IRS-Station mypassword
```

設定完成後重新啟動：
```bash
sudo reboot
```

## 手動部署

### 安裝 systemd 服務

```bash
# 複製服務檔
sudo cp /home/pi/CIRS/deploy/mirs.service /etc/systemd/system/
sudo cp /home/pi/CIRS/deploy/cirs.service /etc/systemd/system/
sudo cp /home/pi/CIRS/deploy/hirs.service /etc/systemd/system/

# 重新載入 systemd
sudo systemctl daemon-reload

# 啟用服務（開機自動啟動）
sudo systemctl enable mirs cirs hirs

# 立即啟動
sudo systemctl start mirs cirs hirs
```

### 檢查服務狀態

```bash
# 查看所有 IRS 服務
sudo systemctl status mirs cirs hirs

# 查看即時 log
sudo journalctl -u cirs -f
```

## 連線方式

### 有網路環境

使用樹莓派的 IP 位址：
```
MIRS: http://192.168.x.x:8000
CIRS: http://192.168.x.x:8001
HIRS: http://192.168.x.x:8082
```

### 離線環境（WiFi 熱點）

1. 用手機/平板連線 WiFi：`IRS-Station`（預設密碼：`irs12345678`）
2. 開啟瀏覽器：

```
MIRS: http://192.168.4.1:8000  或  http://mirs.local:8000
CIRS: http://192.168.4.1:8001  或  http://cirs.local:8001
HIRS: http://192.168.4.1:8082  或  http://hirs.local:8082
```

## 給不同使用者的網址

| 使用者 | 系統 | 網址 |
|--------|------|------|
| 醫療站人員 | MIRS | `http://192.168.4.1:8000` |
| 社區發放站 | CIRS | `http://192.168.4.1:8001` |
| 一般民眾 | HIRS | `http://192.168.4.1:8082` |

## 常用指令

```bash
# 重啟服務
sudo systemctl restart mirs cirs hirs

# 停止服務
sudo systemctl stop mirs cirs hirs

# 查看 log
sudo journalctl -u cirs -n 50

# 即時追蹤 log
sudo journalctl -u cirs -f
```

## 目錄結構

```
/home/pi/
├── MIRS/                 # 醫療站系統
│   ├── main.py
│   ├── venv/
│   └── data/
├── CIRS/                 # 社區物資站
│   ├── backend/
│   │   ├── main.py
│   │   └── data/
│   ├── frontend/
│   └── deploy/           # 部署腳本 (本目錄)
│       ├── deploy.sh
│       ├── setup-wifi-ap.sh
│       ├── cirs.service
│       ├── mirs.service
│       └── hirs.service
└── HIRS/                 # 家庭物資 (純靜態)
    ├── index.html
    ├── sw.js
    └── assets/
```

## 故障排除

### 服務無法啟動

```bash
# 查看詳細錯誤
sudo journalctl -u cirs -n 100

# 確認路徑正確
ls -la /home/pi/CIRS/backend/main.py

# 確認 venv 存在
ls -la /home/pi/CIRS/venv/bin/uvicorn
```

### WiFi 熱點無法連線

```bash
# 檢查 hostapd 狀態
sudo systemctl status hostapd

# 檢查 dnsmasq 狀態
sudo systemctl status dnsmasq

# 重新啟動網路服務
sudo systemctl restart hostapd dnsmasq
```

### Port 被佔用

```bash
# 查看 port 使用狀況
sudo lsof -i :8000
sudo lsof -i :8001
sudo lsof -i :8082

# 強制終止佔用程序
sudo kill -9 <PID>
```

## 備份與還原

### 備份資料

```bash
# CIRS 資料庫
cp /home/pi/CIRS/backend/data/cirs.db ~/backup/

# MIRS 資料庫
cp /home/pi/MIRS/data/*.db ~/backup/
```

### 還原資料

```bash
# 停止服務
sudo systemctl stop cirs mirs

# 還原
cp ~/backup/cirs.db /home/pi/CIRS/backend/data/

# 重啟服務
sudo systemctl start cirs mirs
```
