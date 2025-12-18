# CIRS v2.0 社群分享文案

## LinkedIn / Facebook 正式版

---

### 中文版

**CIRS 社區韌性物資系統 v2.0 正式發布**

我們很高興宣布 CIRS (Community Inventory Resilience System) v2.0 已達到「演習就緒」狀態。

**什麼是 CIRS？**

CIRS 是專為台灣災害收容所設計的物資管理與人員追蹤系統。當颱風、地震來襲，社區需要快速建立避難所時，CIRS 能協助：

- 管理收容所物資（食物、飲水、醫療用品）
- 追蹤人員報到與退場
- 進行傷病分類（Triage）
- 區域配置與人員分配

**v2.0 重點功能**

🛰️ **Satellite PWA 志工行動 App**
- 志工用自己的手機即可操作
- 掃描 QR Code 快速報到
- 支援離線操作，網路恢復自動同步
- 無需安裝 App，開啟網頁即可使用

🎛️ **角色控制**
- 管理員 vs 志工權限分離
- 靈活的配對碼權限指定

📍 **區域管理**
- 預設區域配置（報到區、休息區、醫療區等）
- 新收容人員可直接指派區域

🏥 **檢傷分類整合**
- 支援標準 START Triage 分類
- 輕傷/延遲/立即/死亡 四級分類

**技術架構**

採用 Hub & Spoke 設計：
- Hub: Raspberry Pi 本地伺服器（可離線運作）
- Spoke: 志工手機 PWA（行動操作）
- 資料完全存在本地，不需網際網路

**免費開源**

CIRS 是 xIRS 韌性工具系列的一部分，由 De Novo Orthopedics Inc. 開發並免費提供給台灣社區使用。

🔗 線上展示：https://cirs-demo.vercel.app
🔗 了解更多：https://denovortho-site.vercel.app/zh-TW/resilience

#DisasterPreparedness #Taiwan #OpenSource #CommunityResilience #防災準備 #社區韌性 #開源

---

### English Version

**CIRS Community Inventory Resilience System v2.0 Released**

We're excited to announce that CIRS (Community Inventory Resilience System) v2.0 has reached "Exercise Ready" status.

**What is CIRS?**

CIRS is an inventory management and personnel tracking system designed for Taiwan's disaster evacuation shelters. When typhoons or earthquakes strike and communities need to rapidly establish shelters, CIRS helps with:

- Managing shelter supplies (food, water, medical supplies)
- Tracking personnel check-in and checkout
- Conducting triage classification
- Zone configuration and personnel assignment

**Key Features in v2.0**

🛰️ **Satellite PWA - Volunteer Mobile App**
- Volunteers use their own smartphones
- QR code scanning for quick check-in
- Offline operation with automatic sync
- No app installation required - just open the website

🎛️ **Role-Based Access Control**
- Admin vs. Volunteer permission separation
- Flexible pairing code permission assignment

📍 **Zone Management**
- Pre-configured zones (Check-in, Rest Area, Medical, etc.)
- Direct zone assignment for new evacuees

🏥 **Triage Integration**
- Standard START Triage classification support
- Minor/Delayed/Immediate/Deceased four-level classification

**Architecture**

Hub & Spoke design:
- Hub: Raspberry Pi local server (offline capable)
- Spoke: Volunteer smartphone PWA (mobile operations)
- All data stored locally - no internet required

**Free and Open**

CIRS is part of the xIRS resilience tool family, developed by De Novo Orthopedics Inc. and provided free for Taiwan communities.

🔗 Live Demo: https://cirs-demo.vercel.app
🔗 Learn More: https://denovortho-site.vercel.app/en/resilience

#DisasterPreparedness #Taiwan #OpenSource #CommunityResilience

---

## Twitter/X 短版

### 中文

🚀 CIRS v2.0 發布！

台灣社區收容所物資管理系統，新增：
📱 志工手機 PWA（離線可用）
🎯 角色控制 + 區域管理
🏥 檢傷分類整合

免費開源，為台灣防災準備 🇹🇼

展示：cirs-demo.vercel.app

#台灣 #防災 #開源 #社區韌性

### English

🚀 CIRS v2.0 Released!

Community shelter inventory system for Taiwan with:
📱 Volunteer mobile PWA (offline-ready)
🎯 Role control + zone management
🏥 Triage integration

Free & open source for Taiwan disaster preparedness 🇹🇼

Demo: cirs-demo.vercel.app

#Taiwan #DisasterPreparedness #OpenSource

---

## Instagram 圖文版

**主圖建議**：
- 左側：CIRS Portal 截圖
- 右側：手機 Satellite PWA 截圖
- 標題：「CIRS v2.0 - 為台灣社區打造韌性」

**文案**：

當災害來臨，社區收容所需要快速運作。

CIRS v2.0 讓志工用自己的手機就能：
✅ 掃 QR Code 報到
✅ 發放物資
✅ 追蹤收容人數
✅ 即使沒網路也能操作

這是 xIRS 韌性工具系列的一環，由 De Novo Orthopedics 免費提供。

🔗 連結在 bio

#台灣防災 #社區韌性 #開源軟體 #志工 #收容所 #CIRS #xIRS

---

## 新聞稿格式（如需發給媒體）

**標題**：De Novo Orthopedics 發布 CIRS v2.0 社區韌性物資系統

**副標**：開源防災工具新增志工行動 App，支援離線操作

**內文**：

（2025年12月18日，台灣）— De Novo Orthopedics Inc. 今日宣布其社區韌性物資系統 CIRS (Community Inventory Resilience System) v2.0 版本正式達到「演習就緒」狀態，可供台灣各社區進行防災演習使用。

CIRS 是一套專為災害收容所設計的開源物資管理系統，採用 Hub & Spoke 架構，以 Raspberry Pi 作為本地伺服器，搭配志工手機 PWA 進行行動操作。此設計確保系統可在網路中斷的災害情境下持續運作。

v2.0 版本新增多項功能，包括：
- Satellite PWA：志工可用自己的智慧型手機進行報到登記與物資發放
- 角色控制：區分管理員與志工權限
- 區域管理：預設區域配置，快速分配收容人員
- 檢傷分類整合：支援標準 START Triage 四級分類

CIRS 是 xIRS 韌性工具系列的一部分，同系列還包括家庭物資管理的 HIRS 以及醫療站物資管理的 MIRS。所有工具皆免費提供給台灣社區使用。

De Novo Orthopedics Inc. 技術長表示：「台灣位於多種自然災害風險的交匯處，社區的韌性準備至關重要。我們希望透過開源工具，降低社區建立防災能力的門檻。」

有意進行 CIRS 演習的社區或組織，可透過公司網站聯繫。

**關於 De Novo Orthopedics Inc.**

De Novo Orthopedics Inc. (谷盺生物科技股份有限公司) 是一家專注於骨科醫療技術的公司，同時致力於社區韌性工具的開發與推廣。

**媒體聯繫**：tom@denovortho.com
**公司網站**：https://denovortho-site.vercel.app
**CIRS 展示**：https://cirs-demo.vercel.app

---

## 使用建議

1. **LinkedIn/Facebook**：使用正式版，可搭配 2-3 張產品截圖
2. **Twitter/X**：使用短版，搭配 1 張主畫面截圖
3. **Instagram**：製作圖文組合，使用建議的圖片搭配
4. **媒體**：如需發新聞稿，使用最後的格式

## 建議發文時間

- 台灣時間：週二至週四 10:00-12:00 或 14:00-16:00
- 避開週末及國定假日

## Hashtags 建議

中文：#防災準備 #社區韌性 #台灣 #開源 #志工 #收容所 #xIRS
英文：#DisasterPreparedness #CommunityResilience #Taiwan #OpenSource #Volunteer
