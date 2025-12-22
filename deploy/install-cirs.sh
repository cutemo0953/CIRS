#!/bin/bash
# ============================================================================
# CIRS 社區物資站 - 單獨安裝腳本
# ============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

CIRS_DIR="/home/pi/CIRS"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  CIRS 社區物資站安裝${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# 檢查目錄
if [ ! -d "$CIRS_DIR" ]; then
    echo -e "${RED}錯誤: 請先將 CIRS 程式碼複製到 ${CIRS_DIR}${NC}"
    exit 1
fi

# 1. 安裝系統依賴
echo -e "${GREEN}[1/5] 安裝系統依賴...${NC}"
sudo apt update
sudo apt install -y python3-pip python3-venv

# 2. 建立虛擬環境
echo -e "${GREEN}[2/5] 建立 Python 虛擬環境...${NC}"
cd "$CIRS_DIR"
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

# 3. 安裝 Python 依賴
echo -e "${GREEN}[3/5] 安裝 Python 依賴...${NC}"
source venv/bin/activate
pip install --upgrade pip
pip install fastapi uvicorn[standard] qrcode pillow python-multipart aiofiles
deactivate

# 4. 初始化資料庫
echo -e "${GREEN}[4/5] 初始化資料庫...${NC}"
cd "$CIRS_DIR/backend"
# Check for either xirs_hub.db (new) or cirs.db (old, will be migrated)
if [ ! -f "data/xirs_hub.db" ] && [ ! -f "data/cirs.db" ]; then
    mkdir -p data
    source ../venv/bin/activate
    python3 -c "from main import init_db; init_db()" 2>/dev/null || echo "  (資料庫將在首次啟動時建立)"
    deactivate
fi

# 5. 設定 systemd 服務
echo -e "${GREEN}[5/5] 設定 systemd 服務...${NC}"
sudo cp "${SCRIPT_DIR}/cirs.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable cirs
sudo systemctl start cirs

# 完成
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  CIRS 安裝完成！${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
IP=$(hostname -I | awk '{print $1}')
echo -e "服務狀態: $(systemctl is-active cirs)"
echo -e "網址: ${YELLOW}http://${IP}:8001${NC}"
echo ""
echo -e "常用指令："
echo -e "  查看狀態: ${YELLOW}sudo systemctl status cirs${NC}"
echo -e "  重新啟動: ${YELLOW}sudo systemctl restart cirs${NC}"
echo -e "  查看 log: ${YELLOW}sudo journalctl -u cirs -f${NC}"
