#!/bin/bash
# ============================================================================
# 樹莓派 WiFi 熱點設定腳本
# 讓樹莓派在離線時自動開啟 WiFi AP，供使用者連線存取 MIRS/CIRS/HIRS
# ============================================================================

set -e

# 顏色定義
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  樹莓派 WiFi 熱點設定${NC}"
echo -e "${GREEN}========================================${NC}"

# 預設設定
AP_SSID="${1:-IRS-Station}"
AP_PASSWORD="${2:-irs12345678}"
AP_IP="192.168.4.1"
DHCP_RANGE_START="192.168.4.2"
DHCP_RANGE_END="192.168.4.20"

echo ""
echo -e "${YELLOW}設定參數：${NC}"
echo "  SSID: $AP_SSID"
echo "  密碼: $AP_PASSWORD"
echo "  IP: $AP_IP"
echo ""

# 1. 安裝必要套件
echo -e "${GREEN}[1/5] 安裝必要套件...${NC}"
sudo apt update
sudo apt install -y hostapd dnsmasq

# 2. 停止服務以便設定
echo -e "${GREEN}[2/5] 停止服務...${NC}"
sudo systemctl stop hostapd 2>/dev/null || true
sudo systemctl stop dnsmasq 2>/dev/null || true

# 3. 設定靜態 IP (dhcpcd.conf)
echo -e "${GREEN}[3/5] 設定靜態 IP...${NC}"
sudo tee -a /etc/dhcpcd.conf > /dev/null << EOF

# WiFi AP 設定 - IRS Station
interface wlan0
    static ip_address=${AP_IP}/24
    nohook wpa_supplicant
EOF

# 4. 設定 DHCP 伺服器 (dnsmasq)
echo -e "${GREEN}[4/5] 設定 DHCP 伺服器...${NC}"
sudo mv /etc/dnsmasq.conf /etc/dnsmasq.conf.orig 2>/dev/null || true
sudo tee /etc/dnsmasq.conf > /dev/null << EOF
# IRS Station DHCP 設定
interface=wlan0
dhcp-range=${DHCP_RANGE_START},${DHCP_RANGE_END},255.255.255.0,24h

# DNS 設定 (自己當 DNS)
address=/irs.local/${AP_IP}
address=/mirs.local/${AP_IP}
address=/cirs.local/${AP_IP}
address=/hirs.local/${AP_IP}
EOF

# 5. 設定 WiFi 熱點 (hostapd)
echo -e "${GREEN}[5/5] 設定 WiFi 熱點...${NC}"
sudo tee /etc/hostapd/hostapd.conf > /dev/null << EOF
# IRS Station WiFi AP 設定
interface=wlan0
driver=nl80211
ssid=${AP_SSID}
hw_mode=g
channel=7
wmm_enabled=0
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
wpa=2
wpa_passphrase=${AP_PASSWORD}
wpa_key_mgmt=WPA-PSK
wpa_pairwise=TKIP
rsn_pairwise=CCMP
EOF

# 設定 hostapd 使用此設定檔
sudo sed -i 's|#DAEMON_CONF=""|DAEMON_CONF="/etc/hostapd/hostapd.conf"|' /etc/default/hostapd

# 啟用服務
echo -e "${GREEN}啟用服務...${NC}"
sudo systemctl unmask hostapd
sudo systemctl enable hostapd
sudo systemctl enable dnsmasq

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  WiFi 熱點設定完成！${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "請重新啟動樹莓派: ${YELLOW}sudo reboot${NC}"
echo ""
echo -e "重啟後可連線至："
echo -e "  WiFi: ${YELLOW}${AP_SSID}${NC}"
echo -e "  密碼: ${YELLOW}${AP_PASSWORD}${NC}"
echo ""
echo -e "服務網址："
echo -e "  MIRS: ${YELLOW}http://${AP_IP}:8000${NC} 或 ${YELLOW}http://mirs.local:8000${NC}"
echo -e "  CIRS: ${YELLOW}http://${AP_IP}:8001${NC} 或 ${YELLOW}http://cirs.local:8001${NC}"
echo -e "  HIRS: ${YELLOW}http://${AP_IP}:8082${NC} 或 ${YELLOW}http://hirs.local:8082${NC}"
echo ""
