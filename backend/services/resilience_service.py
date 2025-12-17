"""
CIRS Resilience Calculation Service v2.0
Based on: CIRS_RESILIENCE_SPEC_v2.md

Implements:
- Weighted Weakest Link scoring formula
- Explicit calc_mode standards
- Externalized staffing rules
- Calculation history snapshots
"""

import sqlite3
import json
import math
import hashlib
import re
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum


class StatusLevel(str, Enum):
    """韌性警戒狀態"""
    SAFE = "SAFE"           # Score >= 80
    WARNING = "WARNING"     # 60 <= Score < 80
    CRITICAL = "CRITICAL"   # Score < 60
    UNKNOWN = "UNKNOWN"     # Cannot calculate


@dataclass
class CategoryResult:
    """單一類別韌性計算結果"""
    category: str
    name: str
    hours_remaining: float
    target_hours: float
    score: float
    status: str
    limiting_factor: Optional[str]
    inventory: Dict
    consumption: Dict
    recommendation: Optional[str]

    def to_dict(self) -> Dict:
        return asdict(self)


class CIRSResilienceEngine:
    """
    CIRS 韌性計算引擎 v2.0

    實作 Weighted Weakest Link 評分模型:
    Score = 0.6 × WeakestScore + 0.4 × AvgScore
    """

    RULES_VERSION = "v2.0"

    # Volume parsing patterns
    VOLUME_PATTERNS = [
        (r'(\d+(?:\.\d+)?)\s*[mM][lL]', 0.001),      # ml -> L
        (r'(\d+(?:\.\d+)?)\s*[lL]', 1.0),             # L
        (r'(\d+(?:\.\d+)?)\s*公升', 1.0),             # 公升
        (r'(\d+(?:\.\d+)?)\s*[cC][cC]', 0.001),       # cc -> L
    ]

    # Calorie parsing patterns
    CALORIE_PATTERNS = [
        (r'(\d+(?:\.\d+)?)\s*[kK]?[cC]al', 1.0),     # kcal
        (r'(\d+(?:\.\d+)?)\s*大卡', 1.0),             # 大卡
    ]

    def __init__(self, db_connection_or_path):
        """
        初始化引擎

        Args:
            db_connection_or_path: SQLite connection or database path
        """
        if isinstance(db_connection_or_path, str):
            self.db_path = db_connection_or_path
            self._conn = None
        else:
            self.db_path = None
            self._conn = db_connection_or_path

    def _get_connection(self) -> sqlite3.Connection:
        """取得資料庫連接"""
        if self._conn:
            return self._conn
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _close_connection(self, conn):
        """關閉非持久連接"""
        if not self._conn and conn:
            conn.close()

    # =========================================================================
    # Main Calculation Method
    # =========================================================================

    def calculate(self, station_id: str = "default") -> Dict:
        """
        計算完整韌性狀態

        Args:
            station_id: 站點 ID

        Returns:
            完整韌性狀態 JSON (對齊 MIRS Lifelines 格式)
        """
        start_time = datetime.now()
        conn = self._get_connection()

        try:
            # 1. Load configuration
            config = self._load_config(conn, station_id)
            target_hours = config['isolation_target_days'] * 24
            population = config['population_count']

            # 2. Calculate each category
            lifelines = []
            category_scores = {}

            # Water
            water_result = self._calculate_water(conn, population, target_hours)
            if water_result:
                lifelines.append(water_result)
                category_scores['WATER'] = water_result.score

            # Food
            food_result = self._calculate_food(conn, population, target_hours)
            if food_result:
                lifelines.append(food_result)
                category_scores['FOOD'] = food_result.score

            # Power
            power_result = self._calculate_power(conn, target_hours)
            if power_result:
                lifelines.append(power_result)
                category_scores['POWER'] = power_result.score

            # Medical
            medical_result = self._calculate_medical(conn, population, target_hours)
            if medical_result:
                lifelines.append(medical_result)
                category_scores['MEDICAL'] = medical_result.score

            # Staff
            staff_result = self._calculate_staff(conn, population, target_hours)
            if staff_result:
                lifelines.append(staff_result)
                category_scores['STAFF'] = staff_result.score

            # 3. Calculate overall score using Weighted Weakest Link
            if category_scores:
                valid_scores = [s for s in category_scores.values() if s >= 0]
                if valid_scores:
                    weakest_score = min(valid_scores)
                    avg_score = sum(valid_scores) / len(valid_scores)
                else:
                    weakest_score = 0
                    avg_score = 0
            else:
                weakest_score = 0
                avg_score = 0

            weight_weakest = config.get('weight_weakest', 0.6)
            weight_average = config.get('weight_average', 0.4)

            overall_score = weight_weakest * weakest_score + weight_average * avg_score
            overall_score = max(0, min(100, overall_score))  # Clamp to 0-100

            # 4. Determine overall status
            if not category_scores:
                overall_status = StatusLevel.UNKNOWN
            elif overall_score >= 80:
                overall_status = StatusLevel.SAFE
            elif overall_score >= 60:
                overall_status = StatusLevel.WARNING
            else:
                overall_status = StatusLevel.CRITICAL

            # 5. Find weakest link
            weakest_link = None
            if category_scores:
                weakest_category = min(category_scores, key=category_scores.get)
                weakest_lifeline = next((l for l in lifelines if l.category == weakest_category), None)
                if weakest_lifeline:
                    weakest_link = {
                        'category': weakest_category,
                        'hours_remaining': weakest_lifeline.hours_remaining,
                        'limiting_factor': weakest_lifeline.limiting_factor,
                        'score': weakest_lifeline.score
                    }

            # 6. Generate recommendations
            recommendations = self._generate_recommendations(lifelines, config)

            # 7. Build result
            calc_duration = (datetime.now() - start_time).total_seconds() * 1000

            result = {
                'system': 'CIRS',
                'version': '2.0',
                'station_id': station_id,
                'calculated_at': datetime.now().isoformat(),
                'rules_version': self.RULES_VERSION,
                'context': {
                    'isolation_target_days': config['isolation_target_days'],
                    'isolation_target_hours': target_hours,
                    'population': {
                        'total': population,
                        'label': config.get('population_label', '收容人數'),
                        'special_needs': json.loads(config.get('special_needs', '{}'))
                    }
                },
                'score': {
                    'overall': round(overall_score, 1),
                    'status': overall_status.value,
                    'weakest_link': weakest_link,
                    'category_scores': {k: round(v, 1) for k, v in category_scores.items()},
                    'formula_applied': f"{weight_weakest} × {weakest_score:.1f} + {weight_average} × {avg_score:.1f} = {overall_score:.1f}"
                },
                'lifelines': [l.to_dict() for l in lifelines],
                'recommendations': recommendations,
                'audit': {
                    'calc_duration_ms': round(calc_duration, 1)
                }
            }

            # 8. Save to history
            history_id = self._save_history(conn, station_id, config, result, calc_duration)
            result['audit']['history_id'] = history_id

            return result

        finally:
            self._close_connection(conn)

    # =========================================================================
    # Category Calculation Methods
    # =========================================================================

    def _calculate_water(self, conn, population: int, target_hours: float) -> Optional[CategoryResult]:
        """計算飲水韌性"""
        cursor = conn.cursor()

        # Load inventory
        cursor.execute("""
            SELECT name, quantity, unit, specification
            FROM inventory
            WHERE category = 'water' AND quantity > 0
        """)
        items = list(cursor.fetchall())

        if not items and population == 0:
            return None

        # Calculate total capacity (liters)
        total_liters = 0.0
        inventory_items = []
        for item in items:
            spec = item['specification'] or ''
            volume_per_unit = self._parse_volume(spec) or 0.6  # Default 600ml
            item_total = (item['quantity'] or 0) * volume_per_unit
            total_liters += item_total
            inventory_items.append({
                'name': item['name'],
                'quantity': item['quantity'],
                'unit': item['unit'],
                'capacity_total': round(item_total, 1),
                'capacity_unit': 'L'
            })

        # Consumption: 3L per person per day
        daily_consumption = population * 3.0 if population > 0 else 0
        hourly_consumption = daily_consumption / 24 if daily_consumption > 0 else 0

        # Calculate hours remaining
        if hourly_consumption > 0:
            hours_remaining = total_liters / hourly_consumption
        else:
            hours_remaining = float('inf') if total_liters > 0 else 0

        # Calculate score
        if target_hours > 0 and hours_remaining != float('inf'):
            score = min(100, (hours_remaining / target_hours) * 100)
        elif hours_remaining == float('inf'):
            score = 100
        else:
            score = 0

        # Determine status
        status = self._get_status(score)

        # Recommendation
        recommendation = None
        if hours_remaining < target_hours and hours_remaining != float('inf'):
            gap_liters = (target_hours - hours_remaining) * hourly_consumption
            recommendation = f"需補充約 {gap_liters:.0f}L 飲用水，或啟動限水模式"

        return CategoryResult(
            category='WATER',
            name='飲用水供應',
            hours_remaining=round(hours_remaining, 1) if hours_remaining != float('inf') else 9999,
            target_hours=target_hours,
            score=round(score, 1),
            status=status.value,
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
                'rate_display': f"{population}人 × 3L/人/天 = {daily_consumption:.0f}L/天" if population > 0 else "無收容人數"
            },
            recommendation=recommendation
        )

    def _calculate_food(self, conn, population: int, target_hours: float) -> Optional[CategoryResult]:
        """計算糧食韌性"""
        cursor = conn.cursor()

        # Load inventory
        cursor.execute("""
            SELECT name, quantity, unit, specification
            FROM inventory
            WHERE category = 'food' AND quantity > 0
        """)
        items = list(cursor.fetchall())

        if not items and population == 0:
            return None

        # Estimate total calories (simplified)
        total_calories = 0.0
        inventory_items = []
        for item in items:
            spec = item['specification'] or ''
            name = item['name'] or ''

            # Try to parse calories from spec
            calories_per_unit = self._parse_calories(spec)
            if not calories_per_unit:
                # Default estimates
                if '泡麵' in name or '麵' in name:
                    calories_per_unit = 400
                elif '餅乾' in name:
                    calories_per_unit = 200
                elif '罐頭' in name:
                    calories_per_unit = 300
                elif '米' in name:
                    calories_per_unit = 350  # per 100g
                else:
                    calories_per_unit = 300  # default

            item_total = (item['quantity'] or 0) * calories_per_unit
            total_calories += item_total
            inventory_items.append({
                'name': item['name'],
                'quantity': item['quantity'],
                'unit': item['unit'],
                'calories_total': round(item_total, 0),
                'calories_unit': 'kcal'
            })

        # Consumption: 1800 kcal per person per day
        daily_consumption = population * 1800 if population > 0 else 0
        hourly_consumption = daily_consumption / 24 if daily_consumption > 0 else 0

        # Calculate hours remaining
        if hourly_consumption > 0:
            hours_remaining = total_calories / hourly_consumption
        else:
            hours_remaining = float('inf') if total_calories > 0 else 0

        # Calculate score
        if target_hours > 0 and hours_remaining != float('inf'):
            score = min(100, (hours_remaining / target_hours) * 100)
        elif hours_remaining == float('inf'):
            score = 100
        else:
            score = 0

        status = self._get_status(score)

        recommendation = None
        if hours_remaining < target_hours and hours_remaining != float('inf'):
            gap_kcal = (target_hours - hours_remaining) * hourly_consumption
            recommendation = f"需補充約 {gap_kcal/1000:.0f} 千大卡糧食"

        return CategoryResult(
            category='FOOD',
            name='糧食供應',
            hours_remaining=round(hours_remaining, 1) if hours_remaining != float('inf') else 9999,
            target_hours=target_hours,
            score=round(score, 1),
            status=status.value,
            limiting_factor='STORED_FOOD' if hours_remaining < target_hours else None,
            inventory={
                'items': inventory_items,
                'total_calories': round(total_calories, 0),
                'calories_unit': 'kcal'
            },
            consumption={
                'profile_name': '標準收容',
                'rate': round(daily_consumption, 0),
                'rate_unit': 'kcal/day',
                'rate_display': f"{population}人 × 1800kcal/人/天" if population > 0 else "無收容人數"
            },
            recommendation=recommendation
        )

    def _calculate_power(self, conn, target_hours: float) -> Optional[CategoryResult]:
        """計算電力韌性"""
        cursor = conn.cursor()

        # Load power equipment
        cursor.execute("""
            SELECT name, quantity, unit, specification, check_status
            FROM inventory
            WHERE (category = 'power' OR category = 'equipment')
              AND (LOWER(name) LIKE '%電%' OR LOWER(name) LIKE '%發電%' OR LOWER(name) LIKE '%電源%')
              AND quantity > 0
        """)
        items = list(cursor.fetchall())

        if not items:
            return None

        # Simplified power calculation
        sources = []
        total_hours = 0.0

        for item in items:
            name = item['name'] or ''
            qty = item['quantity'] or 0
            spec = item['specification'] or ''

            if '電源站' in name or '行動電源' in name:
                # Assume 2000Wh capacity, 100W load
                capacity_wh = 2000 * qty
                load_watts = 100
                hours = capacity_wh / load_watts if load_watts > 0 else 0
                sources.append({
                    'name': f"{name} ×{qty}" if qty > 1 else name,
                    'type': 'BATTERY',
                    'capacity': f"{capacity_wh} Wh",
                    'hours': round(hours, 1)
                })
                total_hours += hours

            elif '發電機' in name:
                # Assume 50L tank, 2L/hr consumption
                fuel_liters = 50 * qty
                fuel_rate = 2.0
                hours = fuel_liters / fuel_rate if fuel_rate > 0 else 0
                sources.append({
                    'name': f"{name} ×{qty}" if qty > 1 else name,
                    'type': 'GENERATOR',
                    'capacity': f"{fuel_liters}L 燃油",
                    'hours': round(hours, 1)
                })
                total_hours += hours

        # Calculate score
        if target_hours > 0:
            score = min(100, (total_hours / target_hours) * 100)
        else:
            score = 100 if total_hours > 0 else 0

        status = self._get_status(score)

        recommendation = None
        if total_hours < target_hours:
            gap = target_hours - total_hours
            recommendation = f"電力缺口 {gap:.0f} 小時，建議補充燃油或增加備用電源"

        return CategoryResult(
            category='POWER',
            name='電力供應',
            hours_remaining=round(total_hours, 1),
            target_hours=target_hours,
            score=round(score, 1),
            status=status.value,
            limiting_factor='POWER_SHORTAGE' if total_hours < target_hours else None,
            inventory={
                'sources': sources,
                'total_hours': round(total_hours, 1)
            },
            consumption={
                'profile_name': '基本運作',
                'load_watts': 100,
                'load_display': '約 100W (照明+通訊)'
            },
            recommendation=recommendation
        )

    def _calculate_medical(self, conn, population: int, target_hours: float) -> Optional[CategoryResult]:
        """計算醫療物資韌性"""
        cursor = conn.cursor()

        # Load medical inventory
        cursor.execute("""
            SELECT name, quantity, unit, specification
            FROM inventory
            WHERE category = 'medical' AND quantity > 0
        """)
        items = list(cursor.fetchall())

        if not items:
            return None

        # Check essential items
        inventory_items = []
        has_firstaid = False
        has_masks = False

        for item in items:
            name = item['name'] or ''
            qty = item['quantity'] or 0

            if '急救' in name or 'firstaid' in name.lower():
                has_firstaid = True
            if '口罩' in name:
                has_masks = True

            inventory_items.append({
                'name': name,
                'quantity': qty,
                'unit': item['unit']
            })

        # Score based on having essential items
        base_score = 50
        if has_firstaid:
            base_score += 25
        if has_masks:
            base_score += 25

        # Assume 72 hours if we have basics
        hours_remaining = target_hours if base_score >= 75 else target_hours * (base_score / 100)

        status = self._get_status(base_score)

        recommendation = None
        if not has_firstaid:
            recommendation = "缺少急救包，建議立即補充"
        elif not has_masks:
            recommendation = "缺少口罩，建議補充防疫物資"

        return CategoryResult(
            category='MEDICAL',
            name='醫療物資',
            hours_remaining=round(hours_remaining, 1),
            target_hours=target_hours,
            score=round(base_score, 1),
            status=status.value,
            limiting_factor='MEDICAL_SHORTAGE' if base_score < 75 else None,
            inventory={
                'items': inventory_items,
                'has_essentials': {
                    'firstaid': has_firstaid,
                    'masks': has_masks
                }
            },
            consumption={
                'profile_name': '標準配置',
                'rate': population,
                'rate_unit': '人',
                'rate_display': f"供應 {population} 人"
            },
            recommendation=recommendation
        )

    def _calculate_staff(self, conn, population: int, target_hours: float) -> Optional[CategoryResult]:
        """計算人力韌性 (使用外部化規則)"""
        cursor = conn.cursor()

        # Load staffing rules
        cursor.execute("SELECT * FROM staffing_rules WHERE is_essential = 1")
        rules = list(cursor.fetchall())

        if not rules:
            return None

        # Load current staff
        cursor.execute("""
            SELECT role, COUNT(*) as count
            FROM person
            WHERE role IN ('medic', 'staff', 'admin')
              AND checked_in_at IS NOT NULL
            GROUP BY role
        """)
        current_staff = {}
        for row in cursor.fetchall():
            role = row['role'].upper() if row['role'] else 'UNKNOWN'
            # Map role names
            if role == 'STAFF':
                role = 'VOLUNTEER'
            current_staff[role] = row['count']

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
                n = params.get('n', 100)
                qty_per_n = params.get('qty', 1)
                raw_required = (population / n) * qty_per_n if n > 0 else 0
            elif rule['calc_mode'] == 'FIXED_MIN':
                raw_required = params.get('min_qty', 1)
            elif rule['calc_mode'] == 'PER_SHIFT':
                qty_per_shift = params.get('qty_per_shift', 1)
                shifts = params.get('shifts_per_day', 3)
                raw_required = qty_per_shift * shifts
            else:
                raw_required = 1

            # Apply rounding
            if rounding == 'CEILING':
                required_count = math.ceil(raw_required)
            elif rounding == 'FLOOR':
                required_count = math.floor(raw_required)
            else:
                required_count = round(raw_required)

            required_count = max(1, required_count)  # At least 1 for essential roles
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
            hours_remaining = target_hours
            score = 100
        else:
            hours_remaining = target_hours * worst_ratio
            score = min(100, worst_ratio * 100)

        status = self._get_status(score)

        recommendation = None
        if gap:
            shortage_msgs = []
            for k, v in gap.items():
                if v < 0:
                    rule = next((r for r in rules if r['role_code'] == k), None)
                    role_name = rule['role_name'] if rule else k
                    shortage_msgs.append(f"{abs(v)} 名{role_name}")
            if shortage_msgs:
                recommendation = f"需增派: {', '.join(shortage_msgs)}"

        return CategoryResult(
            category='STAFF',
            name='人力配置',
            hours_remaining=round(hours_remaining, 1),
            target_hours=target_hours,
            score=round(score, 1),
            status=status.value,
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

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _load_config(self, conn, station_id: str) -> Dict:
        """載入站點韌性設定"""
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM resilience_config WHERE station_id = ?
        """, (station_id,))
        row = cursor.fetchone()

        if row:
            return dict(row)

        # Try default config
        cursor.execute("""
            SELECT * FROM resilience_config WHERE station_id = 'default'
        """)
        row = cursor.fetchone()

        if row:
            result = dict(row)
            result['station_id'] = station_id
            return result

        # Fallback defaults
        return {
            'station_id': station_id,
            'isolation_target_days': 3,
            'population_count': 0,
            'population_label': '收容人數',
            'special_needs': '{}',
            'threshold_safe': 1.2,
            'threshold_warning': 1.0,
            'weight_weakest': 0.6,
            'weight_average': 0.4,
            'rules_version': self.RULES_VERSION
        }

    def _get_status(self, score: float) -> StatusLevel:
        """根據分數判斷狀態"""
        if score >= 80:
            return StatusLevel.SAFE
        elif score >= 60:
            return StatusLevel.WARNING
        else:
            return StatusLevel.CRITICAL

    def _parse_volume(self, spec: str) -> Optional[float]:
        """解析容量規格 (返回公升)"""
        for pattern, multiplier in self.VOLUME_PATTERNS:
            match = re.search(pattern, spec)
            if match:
                return float(match.group(1)) * multiplier
        return None

    def _parse_calories(self, spec: str) -> Optional[float]:
        """解析熱量規格 (返回 kcal)"""
        for pattern, multiplier in self.CALORIE_PATTERNS:
            match = re.search(pattern, spec)
            if match:
                return float(match.group(1)) * multiplier
        return None

    def _generate_recommendations(self, lifelines: List[CategoryResult], config: Dict) -> List[Dict]:
        """生成建議列表"""
        recommendations = []

        for lifeline in lifelines:
            if lifeline.recommendation:
                priority = 'HIGH' if lifeline.status == StatusLevel.CRITICAL.value else 'MEDIUM'
                recommendations.append({
                    'priority': priority,
                    'category': lifeline.category,
                    'action': f"FIX_{lifeline.limiting_factor}" if lifeline.limiting_factor else "REVIEW",
                    'message': lifeline.recommendation,
                    'impact': f"可將 {lifeline.category} 評分從 {lifeline.score:.0f} 提升"
                })

        # Sort by priority
        priority_order = {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2}
        recommendations.sort(key=lambda x: priority_order.get(x['priority'], 99))

        return recommendations

    def _save_history(self, conn, station_id: str, config: Dict, result: Dict, duration_ms: float) -> int:
        """儲存計算快照"""
        cursor = conn.cursor()

        input_snapshot = {
            'population': config.get('population_count', 0),
            'target_days': config.get('isolation_target_days', 3),
            'special_needs': json.loads(config.get('special_needs', '{}')),
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
            station_id, input_json, result_json, self.RULES_VERSION,
            input_hash, result_hash, round(duration_ms), 'MANUAL'
        ))

        conn.commit()
        return cursor.lastrowid

    # =========================================================================
    # Configuration API Methods
    # =========================================================================

    def get_config(self, station_id: str = "default") -> Dict:
        """取得站點韌性設定"""
        conn = self._get_connection()
        try:
            return self._load_config(conn, station_id)
        finally:
            self._close_connection(conn)

    def update_config(self, station_id: str, updates: Dict) -> bool:
        """更新站點韌性設定"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            # Get current config or create default
            current = self._load_config(conn, station_id)
            current.update(updates)
            current['updated_at'] = datetime.now().isoformat()

            # Ensure special_needs is JSON string
            if 'special_needs' in current and isinstance(current['special_needs'], dict):
                current['special_needs'] = json.dumps(current['special_needs'], ensure_ascii=False)

            cursor.execute("""
                INSERT OR REPLACE INTO resilience_config (
                    station_id, isolation_target_days, population_count,
                    population_label, special_needs, threshold_safe, threshold_warning,
                    weight_weakest, weight_average, rules_version, updated_at, updated_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                station_id,
                current.get('isolation_target_days', 3),
                current.get('population_count', 0),
                current.get('population_label', '收容人數'),
                current.get('special_needs', '{}'),
                current.get('threshold_safe', 1.2),
                current.get('threshold_warning', 1.0),
                current.get('weight_weakest', 0.6),
                current.get('weight_average', 0.4),
                self.RULES_VERSION,
                current.get('updated_at'),
                updates.get('updated_by', 'SYSTEM')
            ))

            conn.commit()
            return True
        finally:
            self._close_connection(conn)

    def get_history(self, station_id: str = "default", limit: int = 100) -> List[Dict]:
        """取得計算歷史"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, station_id, calc_timestamp, rules_version,
                       calc_duration_ms, triggered_by,
                       json_extract(result_snapshot, '$.score.overall') as score,
                       json_extract(result_snapshot, '$.score.status') as status
                FROM resilience_history
                WHERE station_id = ?
                ORDER BY calc_timestamp DESC
                LIMIT ?
            """, (station_id, limit))

            return [dict(row) for row in cursor.fetchall()]
        finally:
            self._close_connection(conn)

    def get_history_detail(self, history_id: int) -> Optional[Dict]:
        """取得計算歷史詳情"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM resilience_history WHERE id = ?
            """, (history_id,))

            row = cursor.fetchone()
            if row:
                result = dict(row)
                result['input_snapshot'] = json.loads(result['input_snapshot'])
                result['result_snapshot'] = json.loads(result['result_snapshot'])
                return result
            return None
        finally:
            self._close_connection(conn)


# Export
__all__ = ['CIRSResilienceEngine', 'StatusLevel', 'CategoryResult']
