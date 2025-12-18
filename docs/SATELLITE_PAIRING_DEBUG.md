# Satellite PWA 配對問題除錯文件

> 建立時間：2025-12-18
> 狀態：待解決

---

## 問題摘要

Satellite PWA 配對流程無法正常運作。使用者無法從手機成功配對到 CIRS Hub。

---

## 預期流程 vs 實際行為

### 預期流程（應該只需一步）

```
1. 管理員在 CIRS Portal 開啟「設定 → Satellite 配對」
2. 畫面顯示 QR Code（內含 URL: http://172.20.10.2:8090/mobile/?pairing_code=ABC123）
3. 志工用手機相機 App 掃描 QR Code
4. 手機自動開啟瀏覽器，載入 Satellite PWA
5. PWA 自動解析 URL 中的 pairing_code
6. PWA 自動呼叫 /api/auth/satellite/exchange API
7. 配對成功，顯示角色選擇（志工/管理員）
8. 完成，可開始使用
```

### 實際行為（問題）

```
1-4. 同上，正常
5. PWA 載入後，URL 中有 pairing_code，但...
6. 呼叫 exchange API 失敗，顯示「連接時發生錯誤」
7. 使用者被要求「手動輸入連結」或「再掃一次 QR Code」← 這不合理
```

---

## 技術細節

### 環境配置

- **Hub**: MacBook 執行 CIRS Backend (localhost:8090)
- **網路**: 手機開熱點，MacBook 連接手機熱點
- **Hub IP**: 172.20.10.2 (或 10.101.1.150，視熱點分配)
- **手機**: iPhone，使用 Safari

### 相關程式碼位置

| 檔案 | 說明 |
|------|------|
| `/frontend/mobile/index.html` | Satellite PWA 主程式 |
| `/backend/routes/auth.py` | 配對 API (`/api/auth/satellite/exchange`) |
| `/frontend/index.html` | CIRS Portal（產生 QR Code） |

### 配對 API

**Endpoint**: `POST /api/auth/satellite/exchange`

**Request**:
```json
{
  "pairing_code": "ABC123",
  "device_id": "DEV-xxxx-xxxx-xxxx"
}
```

**Response (成功)**:
```json
{
  "access_token": "eyJhbG...",
  "token_type": "bearer",
  "hub_name": "烏日社區避難中心"
}
```

**Response (失敗)**:
```json
{
  "detail": "Pairing code not found or expired"
}
```

### PWA 配對邏輯 (簡化)

```javascript
// /frontend/mobile/index.html 中的 checkUrlToken()

async checkUrlToken() {
    const urlParams = new URLSearchParams(window.location.search);
    const pairingCode = urlParams.get('pairing_code');
    const hubUrl = `${window.location.protocol}//${window.location.host}`;

    if (pairingCode) {
        // 應該自動執行這段
        const response = await fetch(`${hubUrl}/api/auth/satellite/exchange`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                pairing_code: pairingCode,
                device_id: deviceId
            })
        });
        // ... 處理回應
    }
}
```

---

## 已確認可排除的問題

### ✅ Backend API 正常運作

從 localhost 測試 exchange API：
```bash
$ curl -X POST http://localhost:8090/api/auth/satellite/exchange \
  -H "Content-Type: application/json" \
  -d '{"pairing_code":"ABC123","device_id":"TEST-001"}'

# 回應 200 OK，返回 access_token
```

### ✅ QR Code URL 格式正確

```
http://172.20.10.2:8090/mobile/?pairing_code=ABC123
                 ↑              ↑
           正確包含 /mobile/    正確包含 pairing_code
```

### ✅ Pairing Code 有效期設定正確

- 配對碼有效期：5 分鐘
- Token 有效期：12 小時

---

## 🔴 根本原因：iPhone 熱點網路架構限制

### 問題確認

**當 iPhone 作為熱點提供者時，iPhone 自己無法訪問連接到熱點的其他裝置！**

```
┌─────────────────────────────────────────────────────┐
│                  iPhone (熱點提供者)                  │
│                  172.20.10.1 (Gateway)               │
│                       │                              │
│    ┌─────────────────┴─────────────────┐            │
│    │                                    │            │
│    ▼                                    ▼            │
│ MacBook                            iPhone 自己       │
│ 10.101.1.150                       ❌ 無法連到       │
│ (CIRS Backend)                     10.101.1.150     │
└─────────────────────────────────────────────────────┘

原因：iPhone 是 NAT Gateway，不是網路上的 peer
      路由器無法「訪問」連接到自己的裝置
```

### 這就是為什麼配對失敗

1. QR Code 指向 `http://10.101.1.150:8090/mobile/?pairing_code=XXX`
2. iPhone 掃描後開啟 Safari
3. Safari 嘗試連線 `10.101.1.150:8090`
4. **連線失敗** - iPhone 無法路由到自己熱點下的裝置
5. 顯示「連接時發生錯誤」

### 驗證方式

在 iPhone Safari 輸入 `http://10.101.1.150:8090/api/health`
- 預期結果：**無法連線** (確認此問題)

---

## 可能的解決方案

### 方案 A：使用真正的 WiFi 路由器（推薦）

```
┌─────────────┐
│ WiFi Router │
│ 192.168.1.1 │
└──────┬──────┘
       │
   ┌───┴───┐
   │       │
   ▼       ▼
MacBook  iPhone
   ↔ 可以互連 ↔
```

### 方案 B：MacBook 開熱點給 iPhone（角色互換）

```
MacBook 開熱點 → iPhone 連接
MacBook IP: 192.168.2.1 (Gateway)
iPhone 可以訪問 MacBook 的服務
```

### 方案 C：使用 ngrok/cloudflared 暴露本地服務

```bash
# 在 MacBook 執行
ngrok http 8090

# 得到公開 URL 如: https://abc123.ngrok.io
# 更新 QR Code 使用這個 URL
```

### 方案 D：USB 連接 + 網路共享

透過 USB 線連接 iPhone 和 MacBook，使用「網際網路共享」

---

## 舊的可能原因（已排除）

### 2. CORS 問題

手機瀏覽器可能因為 CORS 政策阻擋 API 請求。

**Backend CORS 設定** (`/backend/main.py`):
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

理論上已允許所有來源，但可能有遺漏。

### 3. HTTPS vs HTTP 問題

- QR Code URL 是 `http://` (非加密)
- 現代瀏覽器可能阻擋非 HTTPS 的 fetch 請求
- 或阻擋 mixed content

### 4. JavaScript 執行錯誤

PWA 的 JavaScript 可能在某處拋出錯誤，導致 `checkUrlToken()` 未正確執行。

**需要檢查**：手機 Safari 的 Console 錯誤訊息

---

## 除錯用 Console Log

已在程式碼中加入以下 log（需開啟 Safari Web Inspector）：

```javascript
[Satellite] checkUrlToken called { pairingCode, hubUrl, pathname }
[Satellite] exchangePairingCode called { hubUrl, pairingCode }
[Satellite] Using device_id: DEV-xxxx
[Satellite] Fetching: http://172.20.10.2:8090/api/auth/satellite/exchange
[Satellite] Response status: 200 (或錯誤碼)
```

---

## 錯誤訊息

使用者看到的錯誤：
```
連接時發生錯誤
```

對應程式碼：
```javascript
// exchangePairingCode() 的 catch block
catch (error) {
    console.error('[Satellite] Pairing code exchange error:', error);
    this.showToast('無法連接到 Hub，請確認在同一個 WiFi 網路', 'error');
}
```

這表示 `fetch()` 拋出了異常（網路層錯誤），而非 API 回傳錯誤。

---

## 需要的資訊

請提供以下資訊以協助除錯：

1. **手機 Safari Console 完整 log**
   - 連接 Mac，Safari > 開發 > [iPhone 名稱] > 選擇頁面
   - 截圖或複製所有 `[Satellite]` 開頭的訊息

2. **手機能否直接訪問 Hub**
   - 在手機 Safari 輸入 `http://[Hub IP]:8090/api/health`
   - 截圖結果

3. **Hub IP 確認**
   - 在 Mac 終端機執行 `ipconfig getifaddr en0` 或查看網路設定
   - 確認 QR Code 中的 IP 與實際 IP 相符

4. **網路拓撲**
   - 手機開熱點？還是連到同一個 WiFi？
   - 有無防火牆或 VPN？

---

## 暫時解決方案

如果自動配對持續失敗，可用以下方式手動配對：

1. 在 Mac 瀏覽器開啟 CIRS Portal
2. 設定 → Satellite 配對 → 複製連結
3. 透過 AirDrop / iMessage 傳送連結給手機
4. 手機點擊連結開啟

---

## 相關檔案清單

```
CIRS/
├── frontend/
│   ├── index.html              # CIRS Portal（產生 QR）
│   ├── mobile/
│   │   ├── index.html          # Satellite PWA
│   │   ├── manifest.json
│   │   └── service-worker.js
│   └── lang/
│       └── zh-TW.json          # 翻譯檔
├── backend/
│   ├── main.py                 # FastAPI 主程式 (CORS 設定)
│   └── routes/
│       └── auth.py             # 配對 API
└── docs/
    ├── SATELLITE_PWA_SPEC.md   # 規格書
    └── SATELLITE_PAIRING_DEBUG.md  # 本文件
```
