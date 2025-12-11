#!/bin/bash
# ============================================================================
# IRS 系統統一部署腳本
# 在樹莓派上部署 MIRS, CIRS, HIRS 三合一系統
# ============================================================================

set -e

# 顏色定義
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# 部署路徑
HOME_DIR="/home/pi"
MIRS_DIR="${HOME_DIR}/MIRS"
CIRS_DIR="${HOME_DIR}/CIRS"
HIRS_DIR="${HOME_DIR}/HIRS"

echo -e "${BLUE}"
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║          IRS 三合一系統部署腳本                              ║"
echo "║          MIRS / CIRS / HIRS                                  ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# 顯示選單
show_menu() {
    echo ""
    echo -e "${GREEN}請選擇要部署的系統：${NC}"
    echo "  1) 部署全部 (MIRS + CIRS + HIRS)"
    echo "  2) 只部署 MIRS (醫療站)"
    echo "  3) 只部署 CIRS (社區物資站)"
    echo "  4) 只部署 HIRS (家庭物資)"
    echo "  5) 設定 WiFi 熱點"
    echo "  6) 查看服務狀態"
    echo "  7) 重新啟動所有服務"
    echo "  0) 離開"
    echo ""
    read -p "請輸入選項 [0-7]: " choice
}

# 安裝 Python 依賴
install_python_deps() {
    echo -e "${GREEN}[*] 安裝系統依賴...${NC}"
    sudo apt update
    sudo apt install -y python3-pip python3-venv git
}

# 部署 MIRS
deploy_mirs() {
    echo -e "${BLUE}========== 部署 MIRS ===========${NC}"

    if [ ! -d "$MIRS_DIR" ]; then
        echo -e "${YELLOW}請先將 MIRS 程式碼複製到 ${MIRS_DIR}${NC}"
        return 1
    fi

    cd "$MIRS_DIR"

    # 建立虛擬環境
    if [ ! -d "venv" ]; then
        echo -e "${GREEN}[*] 建立 Python 虛擬環境...${NC}"
        python3 -m venv venv
    fi

    # 安裝依賴
    echo -e "${GREEN}[*] 安裝 Python 依賴...${NC}"
    source venv/bin/activate
    pip install --upgrade pip
    pip install fastapi uvicorn[standard] qrcode pillow python-multipart aiofiles
    deactivate

    # 複製 systemd 服務檔
    echo -e "${GREEN}[*] 設定 systemd 服務...${NC}"
    sudo cp "${CIRS_DIR}/deploy/mirs.service" /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable mirs
    sudo systemctl start mirs

    echo -e "${GREEN}[✓] MIRS 部署完成！${NC}"
    echo -e "    網址: http://$(hostname -I | awk '{print $1}'):8000"
}

# 部署 CIRS
deploy_cirs() {
    echo -e "${BLUE}========== 部署 CIRS ===========${NC}"

    if [ ! -d "$CIRS_DIR" ]; then
        echo -e "${YELLOW}請先將 CIRS 程式碼複製到 ${CIRS_DIR}${NC}"
        return 1
    fi

    cd "${CIRS_DIR}/backend"

    # 建立虛擬環境
    if [ ! -d "venv" ]; then
        echo -e "${GREEN}[*] 建立 Python 虛擬環境...${NC}"
        python3 -m venv ../venv
    fi

    # 安裝依賴
    echo -e "${GREEN}[*] 安裝 Python 依賴...${NC}"
    source ../venv/bin/activate
    pip install --upgrade pip
    pip install fastapi uvicorn[standard] qrcode pillow python-multipart aiofiles
    deactivate

    # 初始化資料庫
    if [ ! -f "data/cirs.db" ]; then
        echo -e "${GREEN}[*] 初始化資料庫...${NC}"
        mkdir -p data
        source ../venv/bin/activate
        python3 -c "from main import init_db; init_db()"
        deactivate
    fi

    # 複製 systemd 服務檔
    echo -e "${GREEN}[*] 設定 systemd 服務...${NC}"
    sudo cp "${CIRS_DIR}/deploy/cirs.service" /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable cirs
    sudo systemctl start cirs

    echo -e "${GREEN}[✓] CIRS 部署完成！${NC}"
    echo -e "    網址: http://$(hostname -I | awk '{print $1}'):8001"
}

# 部署 HIRS
deploy_hirs() {
    echo -e "${BLUE}========== 部署 HIRS ===========${NC}"

    if [ ! -d "$HIRS_DIR" ]; then
        echo -e "${YELLOW}請先將 HIRS 程式碼複製到 ${HIRS_DIR}${NC}"
        return 1
    fi

    # HIRS 是純靜態檔案，不需要 venv
    # 複製 systemd 服務檔
    echo -e "${GREEN}[*] 設定 systemd 服務...${NC}"
    sudo cp "${CIRS_DIR}/deploy/hirs.service" /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable hirs
    sudo systemctl start hirs

    echo -e "${GREEN}[✓] HIRS 部署完成！${NC}"
    echo -e "    網址: http://$(hostname -I | awk '{print $1}'):8082"
}

# 設定 WiFi 熱點
setup_wifi() {
    echo -e "${BLUE}========== 設定 WiFi 熱點 ===========${NC}"
    read -p "WiFi 名稱 [IRS-Station]: " ssid
    ssid=${ssid:-IRS-Station}
    read -p "WiFi 密碼 [irs12345678]: " password
    password=${password:-irs12345678}

    bash "${CIRS_DIR}/deploy/setup-wifi-ap.sh" "$ssid" "$password"
}

# 查看服務狀態
show_status() {
    echo -e "${BLUE}========== 服務狀態 ===========${NC}"
    echo ""
    echo -e "${GREEN}MIRS:${NC}"
    systemctl status mirs --no-pager -l 2>/dev/null || echo "  未安裝"
    echo ""
    echo -e "${GREEN}CIRS:${NC}"
    systemctl status cirs --no-pager -l 2>/dev/null || echo "  未安裝"
    echo ""
    echo -e "${GREEN}HIRS:${NC}"
    systemctl status hirs --no-pager -l 2>/dev/null || echo "  未安裝"
    echo ""

    # 顯示 IP 和 Port
    IP=$(hostname -I | awk '{print $1}')
    echo -e "${YELLOW}服務網址：${NC}"
    echo "  MIRS: http://${IP}:8000"
    echo "  CIRS: http://${IP}:8001"
    echo "  HIRS: http://${IP}:8082"
}

# 重啟服務
restart_services() {
    echo -e "${GREEN}[*] 重新啟動所有服務...${NC}"
    sudo systemctl restart mirs 2>/dev/null || true
    sudo systemctl restart cirs 2>/dev/null || true
    sudo systemctl restart hirs 2>/dev/null || true
    echo -e "${GREEN}[✓] 完成${NC}"
    show_status
}

# 部署全部
deploy_all() {
    install_python_deps
    deploy_mirs
    deploy_cirs
    deploy_hirs
    echo ""
    echo -e "${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║                    全部部署完成！                            ║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}"
    show_status
}

# 主程式
main() {
    while true; do
        show_menu
        case $choice in
            1) deploy_all ;;
            2) install_python_deps && deploy_mirs ;;
            3) install_python_deps && deploy_cirs ;;
            4) deploy_hirs ;;
            5) setup_wifi ;;
            6) show_status ;;
            7) restart_services ;;
            0) echo "再見！"; exit 0 ;;
            *) echo -e "${RED}無效選項${NC}" ;;
        esac
        echo ""
        read -p "按 Enter 繼續..."
    done
}

# 如果有參數，直接執行
if [ "$1" == "--all" ]; then
    deploy_all
elif [ "$1" == "--mirs" ]; then
    install_python_deps && deploy_mirs
elif [ "$1" == "--cirs" ]; then
    install_python_deps && deploy_cirs
elif [ "$1" == "--hirs" ]; then
    deploy_hirs
elif [ "$1" == "--wifi" ]; then
    setup_wifi
elif [ "$1" == "--status" ]; then
    show_status
else
    main
fi
