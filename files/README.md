# CIRS 防災資料庫

本目錄存放可離線存取的防災參考資料。所有檔案應為 PDF 格式，以便在無網路環境下直接開啟使用。

---

## 目錄結構

```
files/
├── maps/          # 地圖類（災害潛勢、避難路線）
├── manuals/       # 手冊類（操作指南、急救教材）
├── contacts/      # 聯絡資訊（緊急電話、應變中心）
└── templates/     # 表單範本（登記表、紀錄表）
```

---

## 建議下載清單

### maps/ 地圖類

| 檔案名稱建議 | 來源 | 連結 |
|-------------|------|------|
| `ncdr_disaster_potential_map.pdf` | 國家災害防救科技中心 3D災害潛勢地圖 | https://dmap.ncdr.nat.gov.tw |
| `flood_potential_map.pdf` | 經濟部水利署淹水潛勢圖 | https://www.wra.gov.tw/cp.aspx?n=6244 |
| `debris_flow_map.pdf` | 水土保持局土石流潛勢圖 | https://maps.nlsc.gov.tw/pro/009_layer.html |
| `local_evacuation_map.pdf` | 各縣市政府消防局防災地圖 | 各縣市災防專區 |

**操作方式**：進入 NCDR 網站，選擇縣市與災害類型，使用「資料分析與下載」匯出，或截圖製成 PDF。

---

### manuals/ 手冊類

| 檔案名稱建議 | 來源 | 連結 |
|-------------|------|------|
| `resilient_community_manual.pdf` | 韌性社區操作手冊（消防署 2025 版） | https://rtp.nfa.gov.tw/dc/download |
| `family_disaster_card.pdf` | 家庭防災卡（消防署 109 版） | https://syes.chc.edu.tw/posts/710 |
| `mohw_emergency_response.pdf` | 衛福部災害緊急應變小組作業要點 | https://dep.mohw.gov.tw/DOPL/cp-242-1171-101.html |
| `emergency_response_guide.pdf` | 緊急應變措施技術指引（勞動部） | https://www.osha.gov.tw |
| `cpr_first_aid.pdf` | CPR 急救教材（紅十字會） | https://www.redcross.org.tw |

**重點手冊**：「韌性社區操作手冊」包含避難所管理、物資管理、防災地圖繪製等核心內容，建議優先下載。

---

### contacts/ 聯絡資訊類

| 檔案名稱建議 | 來源 | 連結 |
|-------------|------|------|
| `emergency_centers_national.pdf` | 中央及各縣市災害應變中心聯絡方式 | https://www.nfa.gov.tw/cht/index.php?act=article&code=print&ids=1533&article_id=10314 |
| `emergency_centers_local.pdf` | 本地區災害應變中心聯絡電話 | 各區公所網站 |
| `emergency_phone_card.pdf` | 緊急電話卡（自製） | 見下方範本 |

**緊急電話速查**：
- `110` - 警察報案（治安、交通事故）
- `119` - 消防報案（火災、救護、救災）
- `1999` - 市民服務專線（可轉接災害應變中心）
- `1911` - 台電停電報修（24 小時）
- `1910` - 台水停水報修（24 小時）

---

### templates/ 表單範本類

| 檔案名稱建議 | 用途 | 建議欄位 |
|-------------|------|---------|
| `evacuee_registration.pdf` | 災民登記表 | 姓名、身分證、年齡、性別、電話、原住址、安置位置、特殊需求、緊急聯絡人 |
| `supply_distribution_log.pdf` | 物資發放紀錄表 | 日期、物資名稱、數量、領用人簽名、發放人、餘量 |
| `triage_record.pdf` | 檢傷分類紀錄單 | 序號、姓名、性別、年齡、主訴、意識/呼吸/心跳、分類等級（紅黃綠黑）、送醫資訊 |
| `shelter_roster.pdf` | 避難所人員名冊 | 姓名、身分證、性別、年齡、家庭人數、床位區域、特殊照護需求 |
| `supply_request.pdf` | 物資需求申請單 | 申請單位、日期、物資名稱/數量、需求理由、緊急程度、核准欄 |

**參考來源**：韌性社區操作手冊附錄表單

---

## 檔案命名規則

- 使用英文檔名（避免路徑編碼問題）
- 格式：`{類別}_{描述}_{版本或年份}.pdf`
- 範例：
  - `manual_resilient_community_2025.pdf`
  - `map_taichung_nantun_flood.pdf`
  - `contact_emergency_centers_2024.pdf`

---

## 法定必備說明

目前台灣對「社區避難中心」並無明文規定必備哪些固定格式文件，但以下為**強烈建議配置**：

1. **災害潛勢地圖** - 中央防災計畫要求參採
2. **韌性社區操作手冊** - 申請韌性社區標章必備
3. **家庭防災卡** - 教育部要求學校填寫，社區建議配置
4. **災害應變中心聯絡表** - 實務上必要

---

## 更新日誌

| 日期 | 說明 |
|------|------|
| 2024-12-10 | 初始建立，整理官方資料來源 |
