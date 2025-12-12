#!/bin/bash
# ============================================================================
# HIRS 家庭物資管理 - 單獨安裝腳本
# (純靜態 PWA，不需要 Python)
# ============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

HIRS_DIR="/home/pi/HIRS"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  HIRS 家庭物資管理安裝${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# 檢查目錄
if [ ! -d "$HIRS_DIR" ]; then
    echo -e "${RED}錯誤: 請先將 HIRS 程式碼複製到 ${HIRS_DIR}${NC}"
    exit 1
fi

# 檢查 index.html 存在
if [ ! -f "$HIRS_DIR/index.html" ]; then
    echo -e "${RED}錯誤: 找不到 ${HIRS_DIR}/index.html${NC}"
    exit 1
fi

# 設定 systemd 服務
echo -e "${GREEN}[1/1] 設定 systemd 服務...${NC}"
sudo cp "${SCRIPT_DIR}/hirs.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable hirs
sudo systemctl start hirs

# 完成
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  HIRS 安裝完成！${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
IP=$(hostname -I | awk '{print $1}')
echo -e "服務狀態: $(systemctl is-active hirs)"
echo -e "網址: ${YELLOW}http://${IP}:8082${NC}"
echo ""
echo -e "${YELLOW}提示: HIRS 是 PWA 應用，使用者可以：${NC}"
echo -e "  1. 用手機瀏覽器開啟上述網址"
echo -e "  2. 點選「加到主畫面」"
echo -e "  3. 之後可離線使用"
echo ""
echo -e "常用指令："
echo -e "  查看狀態: ${YELLOW}sudo systemctl status hirs${NC}"
echo -e "  重新啟動: ${YELLOW}sudo systemctl restart hirs${NC}"
echo -e "  查看 log: ${YELLOW}sudo journalctl -u hirs -f${NC}"
