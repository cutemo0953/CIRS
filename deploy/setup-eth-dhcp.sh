#!/bin/bash
# ============================================================================
# 樹莓派有線網路 DHCP 伺服器設定
# 用於外接 Router 模式：Router 當 AP，樹莓派提供 DHCP
# ============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  有線網路 DHCP 伺服器設定${NC}"
echo -e "${GREEN}  (外接 Router 模式)${NC}"
echo -e "${GREEN}========================================${NC}"

ETH_IP="192.168.4.1"
DHCP_START="192.168.4.10"
DHCP_END="192.168.4.100"

echo ""
echo -e "${YELLOW}設定參數：${NC}"
echo "  樹莓派 IP: $ETH_IP"
echo "  DHCP 範圍: $DHCP_START - $DHCP_END"
echo ""

# 1. 安裝 dnsmasq
echo -e "${GREEN}[1/3] 安裝 dnsmasq...${NC}"
sudo apt update
sudo apt install -y dnsmasq

# 2. 設定靜態 IP
echo -e "${GREEN}[2/3] 設定有線網路靜態 IP...${NC}"

# 備份原設定
sudo cp /etc/dhcpcd.conf /etc/dhcpcd.conf.backup.$(date +%Y%m%d) 2>/dev/null || true

# 移除舊的 eth0 設定（如果有）
sudo sed -i '/# IRS eth0 設定/,/^$/d' /etc/dhcpcd.conf

# 新增 eth0 設定
sudo tee -a /etc/dhcpcd.conf > /dev/null << EOF

# IRS eth0 設定 - 外接 Router 模式
interface eth0
    static ip_address=${ETH_IP}/24
    static routers=${ETH_IP}
    static domain_name_servers=${ETH_IP}

EOF

# 3. 設定 DHCP 伺服器
echo -e "${GREEN}[3/3] 設定 DHCP 伺服器...${NC}"

# 備份原設定
sudo mv /etc/dnsmasq.conf /etc/dnsmasq.conf.backup.$(date +%Y%m%d) 2>/dev/null || true

sudo tee /etc/dnsmasq.conf > /dev/null << EOF
# IRS DHCP 伺服器設定 - 外接 Router 模式

# 只在 eth0 上提供 DHCP
interface=eth0

# DHCP 範圍
dhcp-range=${DHCP_START},${DHCP_END},255.255.255.0,24h

# 自訂域名解析（方便記憶）
address=/irs.local/${ETH_IP}
address=/mirs.local/${ETH_IP}
address=/cirs.local/${ETH_IP}
address=/hirs.local/${ETH_IP}

# 禁用 DNS 轉發（離線環境）
no-resolv
no-poll

# 本地 DNS
local=/local/
domain=local
expand-hosts

EOF

# 啟用服務
sudo systemctl enable dnsmasq
sudo systemctl restart dnsmasq

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  設定完成！${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "請重新啟動樹莓派: ${YELLOW}sudo reboot${NC}"
echo ""
echo -e "${YELLOW}接線方式：${NC}"
echo "  1. 用網路線連接：外接 Router → 樹莓派網路孔"
echo "  2. 外接 Router 設為 AP 模式（關閉 DHCP）"
echo "  3. 手機連線到 Router 的 WiFi"
echo ""
echo -e "${YELLOW}連線網址：${NC}"
echo "  MIRS: http://${ETH_IP}:8000  或  http://mirs.local:8000"
echo "  CIRS: http://${ETH_IP}:8001  或  http://cirs.local:8001"
echo "  HIRS: http://${ETH_IP}:8082  或  http://hirs.local:8082"
echo ""
