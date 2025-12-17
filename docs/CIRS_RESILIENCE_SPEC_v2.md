# CIRS Resilience Estimation Specification v2.0

**Version:** 2.0
**Status:** Draft
**Last Updated:** 2024-12
**Aligned With:** MIRS Resilience Framework v1.0

---

## 1. Overview

### 1.1 Purpose

CIRS 韌性估算系統為社區避難所提供「可撐多久」的量化評估，協助指揮官在災難期間做出資源配置決策。

### 1.2 Design Principles

1. **Weighted Weakest Link**: 最短板決定存亡，但全面發展仍受鼓勵
2. **Explicit Logic**: 所有計算規則數據化，不允許 NULL 邏輯
3. **Auditability**: 每次計算產生可追溯的快照
4. **MIRS Alignment**: API 結構與 MIRS Lifelines 對齊，支援未來聯邦整合
5. **Offline-First**: 所有計算可在無網路環境下完成

### 1.3 Three Laws of Resilience

```
Law 1: Law of Capacity
  Total_Usable = Σ(quantity × capacity_per_unit)

Law 2: Law of Dependency
  Endurance(A) = MIN(Endurance(A), Endurance(Dependency))

Law 3: Law of Weakest Link
  Effective_Days = MIN(all_category_days)
```

---

## 2. Scoring Formula (P0: Hardened Logic)

### 2.1 Weighted Weakest Link Model

```
Score = 0.6 × (WeakestHours / TargetHours × 100) + 0.4 × AvgCategoryScore

Where:
  - WeakestHours = MIN(WaterHours, FoodHours, MedicalHours, PowerHours, StaffHours)
  - TargetHours = isolation_target_days × 24
  - AvgCategoryScore = AVG(all non-zero category scores)
  - Score is capped at 0-100
```

**Rationale:**
- 60% weight to weakest link (木桶效應): If water runs out, food abundance is meaningless
- 40% weight to average: Encourages balanced preparedness
- If WeakestHours < 0, treat as 0

### 2.2 Category Score Calculation

Each category (WATER, FOOD, MEDICAL, POWER, STAFF) calculates:

```python
def calculate_category_score(hours_remaining: float, target_hours: float) -> float:
    if target_hours <= 0:
        return 0
    ratio = hours_remaining / target_hours
    # Cap at 100 (don't reward excessive stockpiling beyond target)
    return min(100, ratio * 100)
```

### 2.3 Status Thresholds

| Status | Condition | UI Color |
|--------|-----------|----------|
| SAFE | Score >= 80 | Green |
| WARNING | 60 <= Score < 80 | Yellow |
| CRITICAL | Score < 60 | Red |
| UNKNOWN | Cannot calculate | Gray |

---

## 3. Database Schema

### 3.1 Inventory Standards Table (Explicit Model)

```sql
-- 移除模糊的 NULL 邏輯，採用顯式計算模式
CREATE TABLE inventory_standards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,              -- 'WATER', 'FOOD', 'MEDICAL', 'POWER', 'DAILY'
    item_name TEXT NOT NULL,
    item_code TEXT UNIQUE,               -- 標準化代碼

    -- 計算模式 (P0: 不允許 NULL)
    calc_mode TEXT NOT NULL DEFAULT 'PER_PERSON_DAY',
    -- ENUM: 'PER_PERSON_DAY', 'PER_N_PEOPLE', 'FIXED_MIN', 'CUSTOM_FORMULA'

    calc_params JSON NOT NULL DEFAULT '{}',
    -- 範例:
    -- PER_PERSON_DAY: {"rate": 3.0, "unit": "L"}           -> 每人每天 3L 水
    -- PER_N_PEOPLE:   {"n": 50, "qty": 1, "unit": "組"}    -> 每 50 人 1 組急救包
    -- FIXED_MIN:      {"min_qty": 1, "unit": "台"}         -> 最少 1 台發電機
    -- CUSTOM_FORMULA: {"formula": "ceil(population / 100) * 2"} -> 自訂公式

    -- 韌性類別 (用於 Lifeline 分組)
    resilience_category TEXT,            -- 'WATER', 'FOOD', 'POWER', 'OXYGEN', 'STAFF'

    -- 容量/消耗設定
    capacity_per_unit REAL,              -- 每單位容量 (如 600ml/瓶)
    capacity_unit TEXT,                  -- 'ml', 'L', 'kcal', 'Wh'
    consumption_rate REAL,               -- 每人每天消耗率
    consumption_unit TEXT,               -- 'L/day', 'kcal/day'

    -- 描述 (用於 UI 顯示和審核)
    description TEXT,
    description_en TEXT,

    -- 元資料
    is_essential BOOLEAN DEFAULT FALSE,  -- 是否為必需品
    sort_order INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 預設標準
INSERT INTO inventory_standards (category, item_name, item_code, calc_mode, calc_params, resilience_category, capacity_per_unit, capacity_unit, consumption_rate, consumption_unit, description, is_essential) VALUES
-- 飲水
('WATER', '飲用水', 'WATER-DRINK', 'PER_PERSON_DAY', '{"rate": 3.0, "unit": "L"}', 'WATER', 0.6, 'L', 3.0, 'L/day', '內政部標準: 每人每天 3 公升', TRUE),
('WATER', '生活用水', 'WATER-DAILY', 'PER_PERSON_DAY', '{"rate": 10.0, "unit": "L"}', 'WATER', 1.0, 'L', 10.0, 'L/day', '洗漱、沖廁等生活用水', FALSE),

-- 食物
('FOOD', '主食熱量', 'FOOD-MAIN', 'PER_PERSON_DAY', '{"rate": 1800, "unit": "kcal"}', 'FOOD', NULL, 'kcal', 1800, 'kcal/day', '成人每日基本熱量需求', TRUE),
('FOOD', '嬰兒奶粉', 'FOOD-BABY', 'CUSTOM_FORMULA', '{"formula": "baby_count * 6", "unit": "罐"}', 'FOOD', NULL, '罐', NULL, NULL, '每嬰兒每天約需 150-200ml 奶 6 次', FALSE),

-- 醫療
('MEDICAL', '急救包', 'MED-FIRSTAID', 'PER_N_PEOPLE', '{"n": 50, "qty": 1, "unit": "組"}', 'MEDICAL', NULL, '組', NULL, NULL, '每 50 人配置 1 組急救包', TRUE),
('MEDICAL', 'N95 口罩', 'MED-MASK-N95', 'PER_PERSON_DAY', '{"rate": 1, "unit": "個"}', 'MEDICAL', NULL, '個', 1.0, '個/day', '傳染病防護用', FALSE),

-- 電力
('POWER', '行動電源站', 'PWR-STATION', 'FIXED_MIN', '{"min_qty": 1, "unit": "台"}', 'POWER', NULL, 'Wh', NULL, NULL, '至少需要 1 台備用電源', TRUE),
('POWER', '發電機', 'PWR-GENERATOR', 'FIXED_MIN', '{"min_qty": 1, "unit": "台"}', 'POWER', NULL, 'L', NULL, NULL, '至少需要 1 台發電機', TRUE),

-- 日用品
('DAILY', '毛毯', 'DAILY-BLANKET', 'PER_N_PEOPLE', '{"n": 1, "qty": 1, "unit": "件"}', NULL, NULL, '件', NULL, NULL, '每人 1 件', FALSE),
('DAILY', '睡袋', 'DAILY-SLEEPBAG', 'PER_N_PEOPLE', '{"n": 2, "qty": 1, "unit": "個"}', NULL, NULL, '個', NULL, NULL, '每 2 人 1 個', FALSE);
```

### 3.2 Resilience Configuration Table

```sql
CREATE TABLE resilience_config (
    station_id TEXT PRIMARY KEY,

    -- 目標設定
    isolation_target_days INTEGER DEFAULT 3,
    isolation_source TEXT DEFAULT 'manual',    -- 'manual', 'cdc', 'custom'

    -- 人口設定
    population_count INTEGER DEFAULT 0,
    population_label TEXT DEFAULT '收容人數',
    special_needs JSON DEFAULT '{}',           -- {"elderly": 10, "infant": 5, "disabled": 3}

    -- 閾值設定
    threshold_safe REAL DEFAULT 1.2,           -- >= 120% 為安全
    threshold_warning REAL DEFAULT 1.0,        -- >= 100% 為警告

    -- 計算權重 (可自訂)
    weight_weakest REAL DEFAULT 0.6,           -- 最短板權重
    weight_average REAL DEFAULT 0.4,           -- 平均權重

    -- 規則版本 (用於審計)
    rules_version TEXT DEFAULT 'v2.0',

    -- Profile 連結
    water_profile_id INTEGER,
    food_profile_id INTEGER,
    power_profile_id INTEGER,
    staff_profile_id INTEGER,

    -- 元資料
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_by TEXT
);
```

### 3.3 Staffing Rules Table (Externalized Logic)

```sql
-- 人力計算規則外部化，從程式碼移至資料庫
CREATE TABLE staffing_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role_code TEXT NOT NULL UNIQUE,          -- 'MEDIC', 'VOLUNTEER', 'ADMIN', 'SECURITY'
    role_name TEXT NOT NULL,
    role_name_en TEXT,

    -- 計算規則
    calc_mode TEXT NOT NULL DEFAULT 'PER_N_PEOPLE',
    -- 'PER_N_PEOPLE': n 人需要 qty 位
    -- 'FIXED_MIN': 最少需要 qty 位
    -- 'PER_SHIFT': 每班需要 qty 位

    calc_params JSON NOT NULL,
    -- PER_N_PEOPLE: {"n": 100, "qty": 1, "rounding": "CEILING"}
    -- FIXED_MIN: {"min_qty": 2}
    -- PER_SHIFT: {"qty_per_shift": 2, "shifts_per_day": 3}

    rounding_mode TEXT DEFAULT 'CEILING',    -- 'CEILING', 'FLOOR', 'ROUND'

    -- 依賴設定 (某些角色可能依賴其他角色)
    depends_on_role TEXT,                    -- 如 'MEDIC_ASSISTANT' 依賴 'MEDIC'

    -- UI 設定
    icon TEXT,
    color TEXT,
    sort_order INTEGER DEFAULT 0,

    -- 元資料
    is_essential BOOLEAN DEFAULT TRUE,
    description TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 預設人力配置規則
INSERT INTO staffing_rules (role_code, role_name, role_name_en, calc_mode, calc_params, rounding_mode, description, is_essential) VALUES
('MEDIC', '醫護人員', 'Medical Staff', 'PER_N_PEOPLE', '{"n": 100, "qty": 1, "rounding": "CEILING"}', 'CEILING', '每 100 人至少需要 1 位醫護', TRUE),
('VOLUNTEER', '志工', 'Volunteer', 'PER_N_PEOPLE', '{"n": 30, "qty": 1, "rounding": "CEILING"}', 'CEILING', '每 30 人需要 1 位志工', TRUE),
('ADMIN', '行政人員', 'Admin Staff', 'FIXED_MIN', '{"min_qty": 2}', 'CEILING', '至少需要 2 位行政人員', TRUE),
('SECURITY', '保全人員', 'Security', 'PER_SHIFT', '{"qty_per_shift": 1, "shifts_per_day": 3}', 'CEILING', '24 小時輪班，每班 1 人', FALSE),
('COOK', '廚房人員', 'Kitchen Staff', 'PER_N_PEOPLE', '{"n": 50, "qty": 1, "rounding": "CEILING"}', 'CEILING', '每 50 人需要 1 位廚房人員', FALSE);
```

### 3.4 Resilience History Table (Auditability)

```sql
-- 計算快照，用於離線同步、災後檢討、機器學習
CREATE TABLE resilience_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    station_id TEXT NOT NULL,

    -- 計算時間
    calc_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,

    -- 輸入快照 (當時的環境狀態)
    input_snapshot JSON NOT NULL,
    -- {
    --   "population": 150,
    --   "target_days": 3,
    --   "special_needs": {"elderly": 10, "infant": 5},
    --   "inventory_hash": "sha256:abc123...",
    --   "staff_on_duty": {"MEDIC": 2, "VOLUNTEER": 5}
    -- }

    -- 結果快照 (完整的 dashboard JSON)
    result_snapshot JSON NOT NULL,
    -- {
    --   "score": 72,
    --   "status": "WARNING",
    --   "weakest_link": {"category": "WATER", "hours": 48},
    --   "lifelines": [...],
    --   "recommendations": [...]
    -- }

    -- 規則版本 (用於版本比對)
    rules_version TEXT NOT NULL,              -- 'v2.0'

    -- 驗證用 hash
    input_hash TEXT,                          -- SHA256(input_snapshot)
    result_hash TEXT,                         -- SHA256(result_snapshot)

    -- 計算性能
    calc_duration_ms INTEGER,                 -- 計算耗時

    -- 觸發來源
    triggered_by TEXT DEFAULT 'MANUAL',       -- 'MANUAL', 'SCHEDULE', 'INVENTORY_CHANGE', 'POPULATION_CHANGE'

    -- 索引優化
    FOREIGN KEY (station_id) REFERENCES config(key)
);

CREATE INDEX idx_resilience_history_station ON resilience_history(station_id);
CREATE INDEX idx_resilience_history_timestamp ON resilience_history(calc_timestamp);
CREATE INDEX idx_resilience_history_version ON resilience_history(rules_version);
```

### 3.5 Shelter Network Table (Federation Ready)

```sql
-- 避難所網路連結 (支援聯邦同步)
CREATE TABLE shelter_network (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 本站資訊
    local_station_id TEXT NOT NULL,

    -- 遠端站點資訊
    remote_station_id TEXT NOT NULL,
    remote_station_name TEXT,
    remote_ip TEXT,
    remote_port INTEGER DEFAULT 8090,

    -- 連接狀態
    connection_status TEXT DEFAULT 'UNKNOWN',  -- 'ONLINE', 'OFFLINE', 'UNKNOWN'
    last_sync_at DATETIME,
    last_heartbeat DATETIME,

    -- 資料信賴度 (v2.0 新增)
    data_confidence_score INTEGER DEFAULT 100, -- 0-100，基於數據新鮮度
    -- 計算公式: 100 - (hours_since_last_sync * 4)，最低 0

    -- 容量資訊 (用於分流決策)
    remote_population INTEGER DEFAULT 0,
    remote_capacity INTEGER DEFAULT 0,
    remote_score INTEGER DEFAULT 0,

    -- 同步設定
    sync_enabled BOOLEAN DEFAULT TRUE,
    sync_interval_minutes INTEGER DEFAULT 30,

    -- 元資料
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(local_station_id, remote_station_id)
);

CREATE INDEX idx_shelter_network_status ON shelter_network(connection_status);
CREATE INDEX idx_shelter_network_confidence ON shelter_network(data_confidence_score);
```

---

## 4. API Specification

### 4.1 Dashboard Endpoint

```
GET /api/resilience/dashboard
```

**Response (aligned with MIRS Lifelines format):**

```json
{
  "system": "CIRS",
  "version": "2.0",
  "station_id": "shelter_001",
  "calculated_at": "2024-12-15T14:30:00+08:00",
  "rules_version": "v2.0",

  "context": {
    "isolation_target_days": 3,
    "isolation_target_hours": 72,
    "population": {
      "total": 150,
      "label": "收容人數",
      "special_needs": {
        "elderly": 10,
        "infant": 5,
        "disabled": 3
      }
    }
  },

  "score": {
    "overall": 72,
    "status": "WARNING",
    "weakest_link": {
      "category": "WATER",
      "hours_remaining": 48,
      "limiting_factor": "STORED_WATER",
      "score": 67
    },
    "category_scores": {
      "WATER": 67,
      "FOOD": 85,
      "POWER": 78,
      "MEDICAL": 90,
      "STAFF": 60
    },
    "formula_applied": "0.6 × 60 + 0.4 × 76 = 66.4 → 72"
  },

  "lifelines": [
    {
      "category": "WATER",
      "name": "飲用水供應",
      "status": "WARNING",
      "hours_remaining": 48,
      "target_hours": 72,
      "limiting_factor": "STORED_WATER",
      "inventory": {
        "items": [
          {
            "name": "礦泉水 600ml",
            "quantity": 200,
            "unit": "瓶",
            "capacity_total": 120,
            "capacity_unit": "L"
          },
          {
            "name": "桶裝水 20L",
            "quantity": 15,
            "unit": "桶",
            "capacity_total": 300,
            "capacity_unit": "L"
          }
        ],
        "total_capacity": 420,
        "capacity_unit": "L"
      },
      "consumption": {
        "profile_name": "標準收容",
        "rate": 450,
        "rate_unit": "L/day",
        "rate_display": "150人 × 3L/人/天 = 450L/天"
      },
      "recommendation": "建議啟動限水模式或申請外部補給"
    },
    {
      "category": "FOOD",
      "name": "糧食供應",
      "status": "SAFE",
      "hours_remaining": 96,
      "target_hours": 72,
      "limiting_factor": null,
      "inventory": {
        "items": [
          {
            "name": "泡麵",
            "quantity": 500,
            "unit": "包",
            "calories_total": 200000,
            "calories_unit": "kcal"
          }
        ],
        "total_calories": 400000,
        "calories_unit": "kcal"
      },
      "consumption": {
        "profile_name": "標準收容",
        "rate": 270000,
        "rate_unit": "kcal/day",
        "rate_display": "150人 × 1800kcal/人/天"
      },
      "recommendation": null
    },
    {
      "category": "POWER",
      "name": "電力供應",
      "status": "WARNING",
      "hours_remaining": 56,
      "target_hours": 72,
      "limiting_factor": "GENERATOR_FUEL",
      "inventory": {
        "sources": [
          {
            "name": "行動電源站 (85%)",
            "type": "BATTERY",
            "capacity": "2000 Wh",
            "available": "1700 Wh",
            "hours": 17
          },
          {
            "name": "發電機 (燃油 80L)",
            "type": "GENERATOR",
            "capacity": "3000W",
            "fuel_rate": "2 L/hr",
            "hours": 40
          }
        ],
        "total_hours": 57
      },
      "consumption": {
        "profile_name": "基本運作",
        "load_watts": 100,
        "load_display": "100W (照明 + 通訊)"
      },
      "recommendation": "建議補充發電機燃油"
    },
    {
      "category": "STAFF",
      "name": "人力配置",
      "status": "CRITICAL",
      "hours_remaining": 36,
      "target_hours": 72,
      "limiting_factor": "MEDIC_SHORTAGE",
      "staffing": {
        "required": {
          "MEDIC": 2,
          "VOLUNTEER": 5,
          "ADMIN": 2
        },
        "on_duty": {
          "MEDIC": 1,
          "VOLUNTEER": 6,
          "ADMIN": 2
        },
        "gap": {
          "MEDIC": -1
        }
      },
      "recommendation": "緊急需要增派 1 名醫護人員"
    }
  ],

  "recommendations": [
    {
      "priority": "HIGH",
      "category": "STAFF",
      "action": "REQUEST_MEDIC",
      "message": "緊急需要增派 1 名醫護人員",
      "impact": "可將 STAFF 評分從 60 提升至 100"
    },
    {
      "priority": "MEDIUM",
      "category": "WATER",
      "action": "ENABLE_RATIONING",
      "message": "建議啟動限水模式（每人每天 2L）",
      "impact": "可將維持時數從 48 提升至 72 小時"
    },
    {
      "priority": "LOW",
      "category": "POWER",
      "action": "REFUEL_GENERATOR",
      "message": "建議補充發電機燃油 40L",
      "impact": "可額外增加 20 小時運轉時間"
    }
  ],

  "audit": {
    "calc_duration_ms": 45,
    "history_id": 12345,
    "input_hash": "sha256:abc123...",
    "result_hash": "sha256:def456..."
  }
}
```

### 4.2 Configuration Endpoints

```
GET  /api/resilience/config
PUT  /api/resilience/config

GET  /api/resilience/standards          # 物資標準列表
POST /api/resilience/standards          # 新增自訂標準
PUT  /api/resilience/standards/:id      # 更新標準

GET  /api/resilience/staffing-rules     # 人力規則列表
PUT  /api/resilience/staffing-rules/:id # 更新人力規則
```

### 4.3 History Endpoints

```
GET /api/resilience/history
Query Parameters:
  - station_id: string (required)
  - from: ISO datetime
  - to: ISO datetime
  - limit: number (default 100)

Response:
{
  "history": [
    {
      "id": 12345,
      "calc_timestamp": "2024-12-15T14:30:00+08:00",
      "score": 72,
      "status": "WARNING",
      "rules_version": "v2.0",
      "population": 150,
      "triggered_by": "INVENTORY_CHANGE"
    }
  ],
  "total": 500
}

GET /api/resilience/history/:id         # 取得完整快照
```

### 4.4 Simulation Endpoint

```
POST /api/resilience/simulate
Body:
{
  "population": 200,
  "inventory_adjustments": [
    {"item_code": "WATER-DRINK", "quantity_change": +100}
  ],
  "staff_adjustments": {
    "MEDIC": 2
  }
}

Response: (same format as dashboard, but with "simulated": true flag)
```

---

## 5. Calculation Engine

### 5.1 Core Algorithm (Python)

```python
from dataclasses import dataclass
from typing import Dict, List, Optional
from enum import Enum
import math
import json
import hashlib
from datetime import datetime


class StatusLevel(str, Enum):
    SAFE = "SAFE"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    UNKNOWN = "UNKNOWN"


@dataclass
class CategoryResult:
    category: str
    name: str
    hours_remaining: float
    target_hours: float
    score: float
    status: StatusLevel
    limiting_factor: Optional[str]
    inventory: Dict
    consumption: Dict
    recommendation: Optional[str]


class CIRSResilienceEngine:
    """
    CIRS 韌性計算引擎 v2.0

    實作 Weighted Weakest Link 評分模型
    """

    def __init__(self, db_connection):
        self.conn = db_connection
        self.rules_version = "v2.0"

    def calculate(self, station_id: str) -> Dict:
        """計算完整韌性狀態"""
        start_time = datetime.now()

        # 1. Load configuration
        config = self._load_config(station_id)
        target_hours = config['isolation_target_days'] * 24
        population = config['population_count']

        # 2. Calculate each category
        lifelines = []
        category_scores = {}

        # Water
        water_result = self._calculate_water(station_id, population, target_hours)
        lifelines.append(water_result)
        category_scores['WATER'] = water_result.score

        # Food
        food_result = self._calculate_food(station_id, population, target_hours)
        lifelines.append(food_result)
        category_scores['FOOD'] = food_result.score

        # Power
        power_result = self._calculate_power(station_id, target_hours)
        lifelines.append(power_result)
        category_scores['POWER'] = power_result.score

        # Medical
        medical_result = self._calculate_medical(station_id, population, target_hours)
        lifelines.append(medical_result)
        category_scores['MEDICAL'] = medical_result.score

        # Staff
        staff_result = self._calculate_staff(station_id, population, target_hours)
        lifelines.append(staff_result)
        category_scores['STAFF'] = staff_result.score

        # 3. Calculate overall score using Weighted Weakest Link
        weakest_score = min(s for s in category_scores.values() if s > 0) if category_scores else 0
        avg_score = sum(category_scores.values()) / len(category_scores) if category_scores else 0

        weight_weakest = config.get('weight_weakest', 0.6)
        weight_average = config.get('weight_average', 0.4)

        overall_score = weight_weakest * weakest_score + weight_average * avg_score
        overall_score = max(0, min(100, overall_score))  # Clamp to 0-100

        # 4. Determine overall status
        if overall_score >= 80:
            overall_status = StatusLevel.SAFE
        elif overall_score >= 60:
            overall_status = StatusLevel.WARNING
        else:
            overall_status = StatusLevel.CRITICAL

        # 5. Find weakest link
        weakest_category = min(category_scores, key=category_scores.get)
        weakest_lifeline = next(l for l in lifelines if l.category == weakest_category)

        # 6. Generate recommendations
        recommendations = self._generate_recommendations(lifelines, config)

        # 7. Build result
        calc_duration = (datetime.now() - start_time).total_seconds() * 1000

        result = {
            'system': 'CIRS',
            'version': '2.0',
            'station_id': station_id,
            'calculated_at': datetime.now().isoformat(),
            'rules_version': self.rules_version,
            'context': {
                'isolation_target_days': config['isolation_target_days'],
                'isolation_target_hours': target_hours,
                'population': {
                    'total': population,
                    'label': config.get('population_label', '收容人數'),
                    'special_needs': config.get('special_needs', {})
                }
            },
            'score': {
                'overall': round(overall_score, 1),
                'status': overall_status.value,
                'weakest_link': {
                    'category': weakest_category,
                    'hours_remaining': weakest_lifeline.hours_remaining,
                    'limiting_factor': weakest_lifeline.limiting_factor,
                    'score': weakest_lifeline.score
                },
                'category_scores': {k: round(v, 1) for k, v in category_scores.items()},
                'formula_applied': f"{weight_weakest} × {weakest_score:.1f} + {weight_average} × {avg_score:.1f} = {overall_score:.1f}"
            },
            'lifelines': [self._lifeline_to_dict(l) for l in lifelines],
            'recommendations': recommendations,
            'audit': {
                'calc_duration_ms': round(calc_duration, 1)
            }
        }

        # 8. Save to history
        history_id = self._save_history(station_id, config, result, calc_duration)
        result['audit']['history_id'] = history_id

        return result

    def _calculate_water(self, station_id: str, population: int, target_hours: float) -> CategoryResult:
        """計算飲水韌性"""
        # Load inventory
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT name, quantity, unit, specification
            FROM inventory
            WHERE category = 'water' AND quantity > 0
        """)
        items = cursor.fetchall()

        # Calculate total capacity (liters)
        total_liters = 0
        inventory_items = []
        for item in items:
            # Parse specification for volume (e.g., "600ml")
            spec = item['specification'] or ''
            volume_per_unit = self._parse_volume(spec) or 0.6  # Default 600ml
            item_total = item['quantity'] * volume_per_unit
            total_liters += item_total
            inventory_items.append({
                'name': item['name'],
                'quantity': item['quantity'],
                'unit': item['unit'],
                'capacity_total': round(item_total, 1),
                'capacity_unit': 'L'
            })

        # Consumption: 3L per person per day
        daily_consumption = population * 3.0
        hourly_consumption = daily_consumption / 24

        # Calculate hours remaining
        hours_remaining = total_liters / hourly_consumption if hourly_consumption > 0 else float('inf')

        # Calculate score
        score = min(100, (hours_remaining / target_hours) * 100) if target_hours > 0 else 0

        # Determine status
        if score >= 80:
            status = StatusLevel.SAFE
        elif score >= 60:
            status = StatusLevel.WARNING
        else:
            status = StatusLevel.CRITICAL

        # Recommendation
        recommendation = None
        if hours_remaining < target_hours:
            gap_liters = (target_hours - hours_remaining) * hourly_consumption
            recommendation = f"需補充約 {gap_liters:.0f}L 飲用水，或啟動限水模式"

        return CategoryResult(
            category='WATER',
            name='飲用水供應',
            hours_remaining=round(hours_remaining, 1),
            target_hours=target_hours,
            score=round(score, 1),
            status=status,
            limiting_factor='STORED_WATER' if hours_remaining < target_hours else None,
            inventory={
                'items': inventory_items,
                'total_capacity': round(total_liters, 1),
                'capacity_unit': 'L'
            },
            consumption={
                'profile_name': '標準收容',
                'rate': round(daily_consumption, 1),
                'rate_unit': 'L/day',
                'rate_display': f"{population}人 × 3L/人/天 = {daily_consumption:.0f}L/天"
            },
            recommendation=recommendation
        )

    def _calculate_staff(self, station_id: str, population: int, target_hours: float) -> CategoryResult:
        """計算人力韌性 (使用外部化規則)"""
        cursor = self.conn.cursor()

        # Load staffing rules
        cursor.execute("SELECT * FROM staffing_rules WHERE is_essential = 1")
        rules = cursor.fetchall()

        # Load current staff
        cursor.execute("""
            SELECT role, COUNT(*) as count
            FROM person
            WHERE role IN ('medic', 'staff', 'admin') AND checked_in_at IS NOT NULL
            GROUP BY role
        """)
        current_staff = {row['role'].upper(): row['count'] for row in cursor.fetchall()}

        required = {}
        on_duty = {}
        gap = {}
        limiting_role = None
        worst_ratio = float('inf')

        for rule in rules:
            role_code = rule['role_code']
            params = json.loads(rule['calc_params'])
            rounding = rule['rounding_mode']

            # Calculate required count
            if rule['calc_mode'] == 'PER_N_PEOPLE':
                n = params['n']
                qty_per_n = params['qty']
                raw_required = (population / n) * qty_per_n
            elif rule['calc_mode'] == 'FIXED_MIN':
                raw_required = params['min_qty']
            elif rule['calc_mode'] == 'PER_SHIFT':
                raw_required = params['qty_per_shift'] * params['shifts_per_day']
            else:
                raw_required = 1

            # Apply rounding
            if rounding == 'CEILING':
                required_count = math.ceil(raw_required)
            elif rounding == 'FLOOR':
                required_count = math.floor(raw_required)
            else:
                required_count = round(raw_required)

            required[role_code] = required_count
            on_duty[role_code] = current_staff.get(role_code, 0)

            if on_duty[role_code] < required_count:
                gap[role_code] = on_duty[role_code] - required_count
                ratio = on_duty[role_code] / required_count if required_count > 0 else 0
                if ratio < worst_ratio:
                    worst_ratio = ratio
                    limiting_role = role_code

        # Calculate hours based on worst staff ratio
        if worst_ratio == float('inf'):
            hours_remaining = target_hours  # Fully staffed
            score = 100
        else:
            hours_remaining = target_hours * worst_ratio
            score = min(100, worst_ratio * 100)

        # Status
        if score >= 80:
            status = StatusLevel.SAFE
        elif score >= 60:
            status = StatusLevel.WARNING
        else:
            status = StatusLevel.CRITICAL

        # Recommendation
        recommendation = None
        if gap:
            shortage_msgs = [f"{abs(v)} 名{k}" for k, v in gap.items() if v < 0]
            if shortage_msgs:
                recommendation = f"需增派: {', '.join(shortage_msgs)}"

        return CategoryResult(
            category='STAFF',
            name='人力配置',
            hours_remaining=round(hours_remaining, 1),
            target_hours=target_hours,
            score=round(score, 1),
            status=status,
            limiting_factor=f"{limiting_role}_SHORTAGE" if limiting_role else None,
            inventory={
                'required': required,
                'on_duty': on_duty,
                'gap': gap
            },
            consumption={
                'profile_name': '標準配置',
                'rate': sum(required.values()),
                'rate_unit': '人',
                'rate_display': f"總需求 {sum(required.values())} 人"
            },
            recommendation=recommendation
        )

    def _save_history(self, station_id: str, config: Dict, result: Dict, duration_ms: float) -> int:
        """儲存計算快照"""
        cursor = self.conn.cursor()

        input_snapshot = {
            'population': config['population_count'],
            'target_days': config['isolation_target_days'],
            'special_needs': config.get('special_needs', {}),
            'timestamp': datetime.now().isoformat()
        }

        input_json = json.dumps(input_snapshot, ensure_ascii=False)
        result_json = json.dumps(result, ensure_ascii=False)

        input_hash = hashlib.sha256(input_json.encode()).hexdigest()
        result_hash = hashlib.sha256(result_json.encode()).hexdigest()

        cursor.execute("""
            INSERT INTO resilience_history (
                station_id, input_snapshot, result_snapshot, rules_version,
                input_hash, result_hash, calc_duration_ms, triggered_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            station_id, input_json, result_json, self.rules_version,
            input_hash, result_hash, round(duration_ms), 'MANUAL'
        ))

        self.conn.commit()
        return cursor.lastrowid

    # ... (additional helper methods)
```

---

## 6. Implementation Phases

### Phase 1: Calculation Engine (Week 1-2)
- [ ] Implement `CIRSResilienceEngine` class
- [ ] Create `inventory_standards` table and seed data
- [ ] Create `staffing_rules` table and seed data
- [ ] Implement Weighted Weakest Link scoring formula
- [ ] Unit tests for all calculation methods
- [ ] Edge case tests (population=0, empty inventory, etc.)

### Phase 2: Database & History (Week 2-3)
- [ ] Create `resilience_config` table
- [ ] Create `resilience_history` table
- [ ] Implement history save/query APIs
- [ ] Add input/result hash validation
- [ ] Migration scripts for existing CIRS databases

### Phase 3: API & Integration (Week 3-4)
- [ ] Implement `/api/resilience/dashboard` endpoint
- [ ] Implement `/api/resilience/config` CRUD
- [ ] Implement `/api/resilience/simulate` endpoint
- [ ] Implement `/api/resilience/history` query
- [ ] Align response format with MIRS Lifelines

### Phase 4: UI Dashboard (Week 4-5)
- [ ] Resilience score gauge component
- [ ] Lifelines bar chart (per category)
- [ ] Weakest link highlight
- [ ] Recommendations panel
- [ ] History timeline view
- [ ] Simulation mode (what-if scenarios)

### Phase 5: Federation Preparation (Future)
- [ ] Create `shelter_network` table
- [ ] Implement `data_confidence_score` calculation
- [ ] Heartbeat mechanism
- [ ] Cross-shelter routing algorithm
- [ ] P2P sync protocol design

---

## 7. Testing Strategy

### 7.1 Unit Tests

```python
def test_weighted_weakest_link_formula():
    """Test the core scoring formula"""
    engine = CIRSResilienceEngine(mock_db)

    # Case 1: All categories at 100%
    scores = {'WATER': 100, 'FOOD': 100, 'POWER': 100, 'STAFF': 100}
    result = engine._calculate_overall_score(scores)
    assert result == 100

    # Case 2: One category at 0%
    scores = {'WATER': 0, 'FOOD': 100, 'POWER': 100, 'STAFF': 100}
    result = engine._calculate_overall_score(scores)
    assert result == 30  # 0.6 * 0 + 0.4 * 75 = 30

    # Case 3: Mixed scores
    scores = {'WATER': 50, 'FOOD': 80, 'POWER': 90, 'STAFF': 70}
    result = engine._calculate_overall_score(scores)
    # weakest = 50, avg = 72.5
    # 0.6 * 50 + 0.4 * 72.5 = 30 + 29 = 59
    assert abs(result - 59) < 1


def test_staffing_rules_rounding():
    """Test staffing calculation with different rounding modes"""
    engine = CIRSResilienceEngine(mock_db)

    # 150 people, 1 medic per 100 people
    # CEILING: ceil(150/100) = 2
    result = engine._calculate_staff('test', 150, 72)
    assert result.inventory['required']['MEDIC'] == 2

    # 99 people
    # CEILING: ceil(99/100) = 1
    result = engine._calculate_staff('test', 99, 72)
    assert result.inventory['required']['MEDIC'] == 1


def test_population_zero():
    """Test edge case: population = 0"""
    engine = CIRSResilienceEngine(mock_db)
    result = engine.calculate('test')

    # Should not crash, should return valid structure
    assert result['score']['overall'] >= 0
    assert result['lifelines'] is not None
```

### 7.2 Integration Tests

```python
def test_full_dashboard_calculation():
    """Integration test for complete dashboard"""
    # Setup test database with sample data
    db = setup_test_db()
    seed_test_inventory(db)
    seed_test_staff(db)

    engine = CIRSResilienceEngine(db)
    result = engine.calculate('shelter_001')

    # Verify structure
    assert 'score' in result
    assert 'lifelines' in result
    assert len(result['lifelines']) == 5

    # Verify MIRS alignment
    for lifeline in result['lifelines']:
        assert 'category' in lifeline
        assert 'status' in lifeline
        assert 'hours_remaining' in lifeline
        assert 'limiting_factor' in lifeline
        assert 'recommendation' in lifeline


def test_history_snapshot_integrity():
    """Test that history snapshots are correctly saved and retrievable"""
    db = setup_test_db()
    engine = CIRSResilienceEngine(db)

    # Calculate twice
    result1 = engine.calculate('shelter_001')
    result2 = engine.calculate('shelter_001')

    # Query history
    cursor = db.cursor()
    cursor.execute("SELECT COUNT(*) FROM resilience_history WHERE station_id = ?", ('shelter_001',))
    count = cursor.fetchone()[0]

    assert count == 2

    # Verify hash integrity
    cursor.execute("SELECT input_hash, result_hash FROM resilience_history ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()
    assert row['input_hash'] is not None
    assert len(row['input_hash']) == 64  # SHA256 hex length
```

---

## 8. Security Considerations

### 8.1 Data Privacy
- Population counts and special needs data are sensitive
- History snapshots should be encrypted at rest for federation
- Consider zero-knowledge proofs for cross-shelter queries

### 8.2 Input Validation
- All API inputs must be validated against schema
- Prevent SQL injection via parameterized queries
- Rate limit simulation endpoint to prevent abuse

### 8.3 Audit Trail
- All configuration changes logged
- History snapshots immutable (no UPDATE/DELETE)
- Hash validation for tampering detection

---

## 9. Changelog

### v2.0 (2024-12)
- **NEW**: Weighted Weakest Link scoring formula
- **NEW**: Explicit `calc_mode` / `calc_params` for standards (no NULL logic)
- **NEW**: `staffing_rules` table (externalized human resource calculation)
- **NEW**: `resilience_history` table (auditability snapshots)
- **NEW**: `shelter_network.data_confidence_score` for federation
- **CHANGED**: API response aligned with MIRS Lifelines format
- **CHANGED**: Phase-based implementation plan (Engine → UI → Federation)

### v1.0 (Initial Draft)
- Basic resilience concept proposal
- Category-based evaluation framework

---

**Document Status:** Draft for Review
**Next Review:** After Phase 1 Implementation
**Maintainer:** De Novo Orthopedics Inc. / 谷盺生物科技股份有限公司
