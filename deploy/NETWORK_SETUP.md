# IRS 網路設定指南

樹莓派離線部署的兩種網路模式。

## 模式比較

| 模式 | 設備需求 | 連線範圍 | 同時連線數 | 適用場景 |
|------|---------|---------|-----------|---------|
| A. 純 AP 模式 | 只有樹莓派 | 約 10-15 公尺 | 5-10 人 | 小型據點、快速部署 |
| B. 外接 Router | 樹莓派 + Router | 取決於 Router | 20+ 人 | 大型據點、多人同時使用 |

---

## 模式 A：純 AP 模式（預設）

樹莓派自己當 WiFi 熱點，最簡單的部署方式。

```
┌─────────────┐
│   手機/平板  │
└──────┬──────┘
       │ WiFi
       ▼
┌─────────────────────┐
│     樹莓派          │
│  WiFi AP: IRS-Station │
│  IP: 192.168.4.1    │
│                     │
│  MIRS → :8000       │
│  CIRS → :8001       │
│  HIRS → :8082       │
└─────────────────────┘
```

### 安裝步驟

```bash
cd /home/pi/CIRS/deploy
./setup-wifi-ap.sh IRS-Station mypassword
sudo reboot
```

### 連線方式

1. 手機搜尋 WiFi：`IRS-Station`
2. 輸入密碼：`mypassword`（或你設定的密碼）
3. 開啟瀏覽器：`http://192.168.4.1:8001`

---

## 模式 B：外接 Router 模式

用外接 Router 擴大 WiFi 範圍，樹莓派用網路線連接。

```
┌─────────────┐     ┌─────────────┐
│   手機/平板  │     │   手機/平板  │
└──────┬──────┘     └──────┬──────┘
       │ WiFi              │ WiFi
       └────────┬──────────┘
                ▼
       ┌─────────────────┐
       │  外接 Router    │
       │  (WiFi AP 模式)  │
       │  DHCP: 關閉     │
       └────────┬────────┘
                │ 網路線
                ▼
       ┌─────────────────────┐
       │      樹莓派          │
       │  eth0: 192.168.4.1  │
       │  DHCP Server: 開啟  │
       │                     │
       │  MIRS → :8000       │
       │  CIRS → :8001       │
       │  HIRS → :8082       │
       └─────────────────────┘
```

### 安裝步驟

#### 1. 設定樹莓派（有線網路 DHCP）

```bash
cd /home/pi/CIRS/deploy
./setup-eth-dhcp.sh
sudo reboot
```

#### 2. 設定外接 Router

不同品牌設定方式略有不同，但基本步驟相同：

**通用設定原則：**
- 模式：AP 模式 / 橋接模式 / Access Point
- DHCP：**關閉**（由樹莓派提供）
- WiFi 名稱：自訂（如 `IRS-Station`）
- WiFi 密碼：自訂

**常見 Router 設定：**

<details>
<summary>Google WiFi / Nest WiFi</summary>

1. 開啟 Google Home App
2. 選擇 WiFi 裝置 → 設定
3. 無法直接設為純 AP 模式
4. **替代方案**：讓 Google WiFi 當主路由，樹莓派接在其下
   - Google WiFi 會自動分配 IP
   - 需查看樹莓派取得的 IP（見下方說明）

</details>

<details>
<summary>TP-Link Router</summary>

1. 連線到 Router（預設 192.168.0.1）
2. 進入「操作模式」或「Working Mode」
3. 選擇「Access Point 模式」
4. 關閉 DHCP
5. 設定 WiFi 名稱和密碼
6. 儲存並重啟

</details>

<details>
<summary>ASUS Router</summary>

1. 連線到 Router（預設 192.168.1.1）
2. 進入「系統管理」→「操作模式」
3. 選擇「Access Point (AP) 模式」
4. DHCP 會自動關閉
5. 設定無線網路名稱和密碼
6. 套用設定

</details>

<details>
<summary>小米路由器</summary>

1. 開啟小米 WiFi App 或 192.168.31.1
2. 進入「常用設定」→「上網設定」
3. 選擇「有線中繼（交換機模式）」
4. 設定 WiFi 名稱和密碼
5. 儲存

</details>

<details>
<summary>一般 Router（通用）</summary>

1. 查閱說明書找到管理介面 IP（常見：192.168.0.1 或 192.168.1.1）
2. 登入管理介面
3. 尋找以下關鍵字：
   - 「操作模式」/ Operation Mode
   - 「AP 模式」/ Access Point
   - 「橋接模式」/ Bridge Mode
4. 關閉 DHCP 伺服器
5. 設定 WiFi 名稱密碼
6. 儲存重啟

</details>

#### 3. 連接設備

1. 用網路線連接：Router LAN 孔 → 樹莓派網路孔
2. Router 接上電源
3. 手機連線到 Router 的 WiFi
4. 開啟瀏覽器：`http://192.168.4.1:8001`

### 連線方式

| 服務 | 網址 |
|------|------|
| MIRS | `http://192.168.4.1:8000` |
| CIRS | `http://192.168.4.1:8001` |
| HIRS | `http://192.168.4.1:8082` |

---

## 特殊情況：Router 不支援 AP 模式

如果你的 Router 無法關閉 DHCP（如 Google WiFi），可以讓 Router 當主路由：

```
┌─────────────┐
│   手機/平板  │
└──────┬──────┘
       │ WiFi
       ▼
┌─────────────────┐
│  Router         │
│  DHCP: 開啟     │
│  192.168.1.1    │
└────────┬────────┘
         │ 網路線
         ▼
┌─────────────────────┐
│      樹莓派          │
│  eth0: DHCP 取得 IP │
│  (例如 192.168.1.50)│
└─────────────────────┘
```

### 查看樹莓派 IP

```bash
# 方法 1：在樹莓派上執行
hostname -I

# 方法 2：查看 Router 管理介面的「已連接裝置」清單
```

### 連線方式

用 Router 分配給樹莓派的 IP：
- MIRS: `http://192.168.1.50:8000`（IP 依實際情況）
- CIRS: `http://192.168.1.50:8001`
- HIRS: `http://192.168.1.50:8082`

---

## 故障排除

### 手機連上 WiFi 但無法開啟網頁

```bash
# 檢查樹莓派服務是否運作
sudo systemctl status cirs

# 檢查 IP 設定
ip addr show

# 檢查 DHCP 服務
sudo systemctl status dnsmasq
```

### 連線速度很慢

- 純 AP 模式：樹莓派 WiFi 晶片效能有限，屬正常現象
- 外接 Router：檢查網路線是否為 Cat5e 以上

### 多人同時使用會斷線

- 純 AP 模式建議 5-10 人以下
- 超過 10 人建議使用外接 Router 模式

---

## 建議配置

| 場景 | 建議模式 | 原因 |
|------|---------|------|
| 緊急部署、人少 | 純 AP | 快速、無需額外設備 |
| 固定據點、人多 | 外接 Router | 穩定、範圍大 |
| 戶外活動 | 純 AP + 行動電源 | 機動性高 |
| 室內大空間 | 外接 Router | 訊號覆蓋完整 |
