# IRS Satellite PWA Interoperability Specification v1.4

> CIRS 與 MIRS Satellite PWA 統一規格

**版本:** 1.4.1
**日期:** 2025-12-20
**狀態:** Implemented

---

## 1. 概述

本文件定義 IRS 系統（CIRS、MIRS）的 Satellite PWA 配對與裝置管理規格，確保跨系統一致性。

### 1.1 設計理念

```
Static QR + Dynamic 6-digit Code = Device Flow

┌─────────────┐     掃描 QR      ┌─────────────┐
│  Hub Portal │  ─────────────►  │  Satellite  │
│  (顯示配對碼) │                 │  PWA 開啟   │
└─────────────┘                  └──────┬──────┘
                                        │
                                        │ 輸入 6 位數配對碼
                                        ▼
                                 ┌─────────────┐
                                 │  交換 JWT   │
                                 │  完成配對   │
                                 └─────────────┘
```

### 1.2 系統對照

| 系統 | API 前綴 | 配對碼表 | 裝置表 |
|------|---------|---------|--------|
| CIRS | `/api/auth/` | satellite_pairing_codes | satellite_devices |
| MIRS | `/api/mirs-mobile/v1/` | mirs_mobile_pairing_codes | mirs_mobile_devices |

---

## 2. API 端點對照表

### 2.1 認證端點

| 功能 | CIRS | MIRS |
|------|------|------|
| 產生配對碼 | `GET /api/auth/pairing-code` | `POST /api/mirs-mobile/v1/auth/pairing` |
| 產生配對 QR | `GET /api/auth/pairing-qr` | `GET /api/mirs-mobile/v1/auth/pairing-qr` |
| 配對資訊 | `GET /api/auth/pairing-info` | `GET /api/mirs-mobile/v1/auth/pairing-info` |
| 交換配對碼 | `POST /api/auth/satellite/exchange` | `POST /api/mirs-mobile/v1/auth/exchange` |
| 驗證 Token | `POST /api/auth/satellite/verify` | `GET /api/mirs-mobile/v1/auth/verify` |

### 2.2 裝置管理端點 (v1.4)

| 功能 | CIRS | MIRS |
|------|------|------|
| 列出裝置 | `GET /api/auth/satellite/devices` | `GET /api/mirs-mobile/v1/devices` |
| 撤銷裝置 | `POST /api/auth/satellite/devices/revoke` | `POST /api/mirs-mobile/v1/devices/{id}/revoke` |
| 恢復裝置 | `POST /api/auth/satellite/devices/unrevoke` | `POST /api/mirs-mobile/v1/devices/{id}/unrevoke` |
| 黑名單 | `POST /api/auth/satellite/devices/blacklist` | `POST /api/mirs-mobile/v1/devices/{id}/blacklist` |
| 解除黑名單 | `POST /api/auth/satellite/devices/unblacklist` | `POST /api/mirs-mobile/v1/devices/{id}/unblacklist` |

### 2.3 操作端點 (v1.4.1)

| 功能 | CIRS | MIRS |
|------|------|------|
| 報到/登記 | `POST /api/satellite/checkin` | - |
| 物資發放 | `POST /api/satellite/supply` | - |
| 庫存盤點 | `POST /api/satellite/stocktake` | `POST /api/mirs-mobile/v1/stocktake` |
| 庫存查詢 | `GET /api/satellite/inventory` | `GET /api/mirs-mobile/v1/inventory` |

---

## 3. 資料結構

### 3.1 配對碼規格

| 項目 | CIRS | MIRS |
|------|------|------|
| 格式 | 6 位數字 | 6 位數字 |
| 有效期 | 5 分鐘 | 5 分鐘 |
| 使用次數 | 單次 | 單次 |
| Rate Limit | 5 次/分鐘/IP | 5 次/分鐘/IP |

### 3.2 JWT Token 結構

```json
// CIRS Token
{
  "sub": "satellite",
  "type": "satellite_pairing",
  "hub_name": "烏日社區避難中心",
  "device_id": "uuid-xxx",
  "allowed_roles": "volunteer",
  "iat": "2025-12-20T08:00:00",
  "exp": 1766000000
}

// MIRS Token
{
  "device_id": "uuid-xxx",
  "staff_id": "STAFF-001",
  "staff_name": "護理師A",
  "role": "nurse",
  "scopes": ["mirs:equipment:read", "mirs:equipment:write"],
  "station_id": "BORP-DNO-01",
  "iat": 1734700000,
  "exp": 1734743200
}
```

### 3.3 裝置表結構對照

| 欄位 | CIRS | MIRS | 說明 |
|------|------|------|------|
| 主鍵 | device_id | device_id | 裝置 UUID |
| 名稱 | device_name | device_name | 可選 |
| 角色 | allowed_roles | role | 權限角色 |
| 權限 | - | scopes | MIRS 有細粒度權限 |
| 人員 | - | staff_id, staff_name | MIRS 追蹤操作人員 |
| 站點 | - | station_id | MIRS 多站點支援 |
| 撤銷 | is_revoked | revoked | 0/1 |
| 黑名單 | is_blacklisted | blacklisted | 0/1 (v1.4) |
| 活動時間 | last_activity_at | last_seen | 最後活動 |
| 配對時間 | paired_at | paired_at | 首次配對 |
| IP | ip_address | ip_address | v1.4 |
| UA | user_agent | user_agent | v1.4 |

---

## 4. 安全機制

### 4.1 Rate Limiting

兩系統均採用相同的限速機制：
- 限制：5 次/分鐘/IP
- 錯誤碼：429 Too Many Requests
- 等待時間：60 秒

### 4.2 裝置狀態機

```
                    ┌──────────────┐
                    │   新裝置     │
                    └──────┬───────┘
                           │ exchange
                           ▼
                    ┌──────────────┐
          ┌────────│   Active     │────────┐
          │        └──────────────┘        │
          │ revoke                         │ blacklist
          ▼                                ▼
   ┌──────────────┐                 ┌──────────────┐
   │   Revoked    │                 │  Blacklisted │
   └──────┬───────┘                 └──────┬───────┘
          │                                │
          │ unrevoke                       │ unblacklist
          │                                │
          ▼                                ▼
   ┌──────────────┐                 ┌──────────────┐
   │   Active     │                 │   Active     │
   │ (可重新配對)  │                 │ (可重新配對)  │
   └──────────────┘                 └──────────────┘
```

### 4.3 黑名單 vs 撤銷

| 操作 | 撤銷 (Revoke) | 黑名單 (Blacklist) |
|------|--------------|-------------------|
| 效果 | Token 失效 | Token 失效 + 無法重新配對 |
| 用途 | 裝置遺失、人員離職 | 惡意裝置、安全事件 |
| 恢復 | unrevoke 或重新配對 | 僅 unblacklist 可解除 |

---

## 5. 實作差異

### 5.1 CIRS 特點

- 簡化模型：僅追蹤 device_id 和 allowed_roles
- 志工導向：預設角色為 volunteer
- 整合於 auth.py router

### 5.2 MIRS 特點

- 醫療級追蹤：記錄 staff_id、staff_name
- 細粒度權限：使用 scopes 控制 API 存取
- 多站點支援：station_id 區分站點
- 獨立 Mobile 模組：services/mobile/

### 5.3 角色權限對照 (v1.4.1)

| 功能 | CIRS 志工 | CIRS 管理員 | MIRS 護理師 |
|------|----------|------------|------------|
| 報到/登記 | ✓ | ✓ | - |
| 新人登記（基本欄位） | ✓ | ✓ | - |
| 新人登記（身分證/電話） | ✗ | ✓ | - |
| 物資發放 | ✓ | ✓ | - |
| 庫存查詢 | ✓（唯讀） | ✓ | ✓ |
| 庫存盤點調整 | ✗ | ✓ | ✓ |
| 設備巡檢 | - | - | ✓ |
| 血袋入庫 | - | - | ✓ |

### 5.4 人員登記欄位對照 (v1.4.1)

| 欄位 | CIRS Hub | CIRS PWA 志工 | CIRS PWA 管理員 |
|------|----------|--------------|----------------|
| 姓名 | ✓ | ✓ | ✓ |
| 身分證 | ✓ (hash) | ✗ | ✓ (hash) |
| 電話 | ✓ (hash) | ✗ | ✓ (hash) |
| 檢傷分類 | ✓ | ✓ | ✓ |
| 區域 | ✓ | ✓ | ✓ |
| 系統編號 | 自動 (P0001) | 自動 (P0001) | 自動 (P0001) |

---

## 6. 變更記錄

| 版本 | 日期 | 變更內容 |
|------|------|---------|
| 1.0 | 2025-12-12 | 初版：6 位數配對碼 + Rate Limiting |
| 1.3 | 2025-12-18 | 角色控制、Rate Limiting 5 次/分鐘 |
| 1.4 | 2025-12-20 | 裝置管理（撤銷/黑名單）、IP/UA 追蹤、MIRS 整合 |
| 1.4.1 | 2025-12-20 | CIRS: 盤點端點、管理員專屬欄位（身分證/電話）、角色 UI 區分 |

---

## 7. 相關文件

- [SATELLITE_PWA_SPEC.md](./SATELLITE_PWA_SPEC.md) - CIRS Satellite PWA 完整規格
- [IRS_INTEROP_SPEC.md](./IRS_INTEROP_SPEC.md) - IRS 跨系統資料交換規格
- [xIRS_SECURE_EXCHANGE_SPEC_v2.md](./xIRS_SECURE_EXCHANGE_SPEC_v2.md) - Hub-to-Hub 安全交換

---

*Document generated for IRS Ecosystem*
*CIRS v1.7.1 + MIRS v1.4.8*
