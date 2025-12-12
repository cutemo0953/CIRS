#!/bin/bash
# ============================================================================
# MIRS 醫療站庫存系統 - 單獨安裝腳本
# ============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

MIRS_DIR="/home/pi/MIRS"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  MIRS 醫療站庫存系統安裝${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# 檢查目錄
if [ ! -d "$MIRS_DIR" ]; then
    echo -e "${RED}錯誤: 請先將 MIRS 程式碼複製到 ${MIRS_DIR}${NC}"
    exit 1
fi

# 1. 安裝系統依賴
echo -e "${GREEN}[1/4] 安裝系統依賴...${NC}"
sudo apt update
sudo apt install -y python3-pip python3-venv

# 2. 建立虛擬環境
echo -e "${GREEN}[2/4] 建立 Python 虛擬環境...${NC}"
cd "$MIRS_DIR"
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

# 3. 安裝 Python 依賴
echo -e "${GREEN}[3/4] 安裝 Python 依賴...${NC}"
source venv/bin/activate
pip install --upgrade pip
pip install fastapi uvicorn[standard] qrcode pillow python-multipart aiofiles
deactivate

# 4. 設定 systemd 服務
echo -e "${GREEN}[4/4] 設定 systemd 服務...${NC}"
sudo cp "${SCRIPT_DIR}/mirs.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable mirs
sudo systemctl start mirs

# 完成
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  MIRS 安裝完成！${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
IP=$(hostname -I | awk '{print $1}')
echo -e "服務狀態: $(systemctl is-active mirs)"
echo -e "網址: ${YELLOW}http://${IP}:8000${NC}"
echo ""
echo -e "常用指令："
echo -e "  查看狀態: ${YELLOW}sudo systemctl status mirs${NC}"
echo -e "  重新啟動: ${YELLOW}sudo systemctl restart mirs${NC}"
echo -e "  查看 log: ${YELLOW}sudo journalctl -u mirs -f${NC}"
