"""
CIRS Resilience API Routes v2.0
Provides resilience calculation, configuration, and history endpoints.
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime

from database import get_db
from services.resilience_service import CIRSResilienceEngine, StatusLevel

router = APIRouter()


# ============================================================================
# Pydantic Models
# ============================================================================

class ResilienceConfigUpdate(BaseModel):
    """韌性設定更新模型"""
    isolation_target_days: Optional[int] = Field(None, ge=1, le=30)
    population_count: Optional[int] = Field(None, ge=0)
    population_label: Optional[str] = Field(None, max_length=50)
    special_needs: Optional[Dict[str, int]] = None
    threshold_safe: Optional[float] = Field(None, ge=0.5, le=3.0)
    threshold_warning: Optional[float] = Field(None, ge=0.5, le=3.0)
    weight_weakest: Optional[float] = Field(None, ge=0.0, le=1.0)
    weight_average: Optional[float] = Field(None, ge=0.0, le=1.0)
    updated_by: Optional[str] = None


class SimulationRequest(BaseModel):
    """模擬計算請求模型"""
    population: Optional[int] = Field(None, ge=0)
    target_days: Optional[int] = Field(None, ge=1, le=30)
    inventory_adjustments: Optional[list] = None
    staff_adjustments: Optional[Dict[str, int]] = None


# ============================================================================
# Dashboard Endpoint
# ============================================================================

@router.get("/dashboard")
async def get_resilience_dashboard(station_id: str = Query("default")):
    """
    取得完整韌性儀表板數據

    實作 Weighted Weakest Link 評分模型:
    Score = 0.6 × WeakestScore + 0.4 × AvgScore

    Returns:
        完整韌性狀態 JSON (對齊 MIRS Lifelines 格式)
    """
    try:
        with get_db() as conn:
            engine = CIRSResilienceEngine(conn)
            result = engine.calculate(station_id)
            return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"計算失敗: {str(e)}")


@router.get("/summary")
async def get_resilience_summary(station_id: str = Query("default")):
    """
    取得韌性摘要 (簡化版，用於 Portal 顯示)
    """
    try:
        with get_db() as conn:
            engine = CIRSResilienceEngine(conn)
            full_result = engine.calculate(station_id)

            # Return simplified summary
            return {
                "score": full_result['score']['overall'],
                "status": full_result['score']['status'],
                "weakest_link": full_result['score']['weakest_link'],
                "category_scores": full_result['score']['category_scores'],
                "lifeline_count": len(full_result['lifelines']),
                "critical_count": sum(1 for l in full_result['lifelines'] if l['status'] == 'CRITICAL'),
                "warning_count": sum(1 for l in full_result['lifelines'] if l['status'] == 'WARNING'),
                "recommendations": full_result['recommendations'][:3],  # Top 3
                "calculated_at": full_result['calculated_at']
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"計算失敗: {str(e)}")


# ============================================================================
# Configuration Endpoints
# ============================================================================

@router.get("/config")
async def get_resilience_config(station_id: str = Query("default")):
    """取得韌性設定"""
    try:
        with get_db() as conn:
            engine = CIRSResilienceEngine(conn)
            config = engine.get_config(station_id)
            return config
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"取得設定失敗: {str(e)}")


@router.put("/config")
async def update_resilience_config(
    updates: ResilienceConfigUpdate,
    station_id: str = Query("default")
):
    """更新韌性設定"""
    try:
        with get_db() as conn:
            engine = CIRSResilienceEngine(conn)

            # Convert Pydantic model to dict, excluding None values
            update_dict = updates.dict(exclude_none=True)

            if not update_dict:
                raise HTTPException(status_code=400, detail="沒有提供更新內容")

            # Validate weights sum to 1
            if 'weight_weakest' in update_dict or 'weight_average' in update_dict:
                current = engine.get_config(station_id)
                new_weakest = update_dict.get('weight_weakest', current.get('weight_weakest', 0.6))
                new_average = update_dict.get('weight_average', current.get('weight_average', 0.4))
                if abs(new_weakest + new_average - 1.0) > 0.01:
                    raise HTTPException(
                        status_code=400,
                        detail=f"權重總和必須為 1.0 (目前: {new_weakest + new_average})"
                    )

            success = engine.update_config(station_id, update_dict)
            if success:
                return {
                    "success": True,
                    "message": "設定已更新",
                    "updated_fields": list(update_dict.keys())
                }
            else:
                raise HTTPException(status_code=500, detail="更新失敗")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新設定失敗: {str(e)}")


# ============================================================================
# Standards & Rules Endpoints
# ============================================================================

@router.get("/standards")
async def get_inventory_standards():
    """取得物資標準列表"""
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT * FROM inventory_standards ORDER BY category, sort_order
        """)
        standards = [dict(row) for row in cursor.fetchall()]
        return {"standards": standards}


@router.get("/staffing-rules")
async def get_staffing_rules():
    """取得人力配置規則列表"""
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT * FROM staffing_rules ORDER BY sort_order
        """)
        rules = [dict(row) for row in cursor.fetchall()]
        return {"rules": rules}


# ============================================================================
# History Endpoints
# ============================================================================

@router.get("/history")
async def get_resilience_history(
    station_id: str = Query("default"),
    limit: int = Query(100, ge=1, le=1000)
):
    """取得韌性計算歷史"""
    try:
        with get_db() as conn:
            engine = CIRSResilienceEngine(conn)
            history = engine.get_history(station_id, limit)
            return {
                "station_id": station_id,
                "history": history,
                "total": len(history)
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"取得歷史失敗: {str(e)}")


@router.get("/history/{history_id}")
async def get_resilience_history_detail(history_id: int):
    """取得計算歷史詳情 (完整快照)"""
    try:
        with get_db() as conn:
            engine = CIRSResilienceEngine(conn)
            detail = engine.get_history_detail(history_id)
            if not detail:
                raise HTTPException(status_code=404, detail="歷史記錄不存在")
            return detail
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"取得詳情失敗: {str(e)}")


# ============================================================================
# Simulation Endpoint
# ============================================================================

@router.post("/simulate")
async def simulate_resilience(
    request: SimulationRequest,
    station_id: str = Query("default")
):
    """
    模擬韌性計算 (What-If 場景)

    允許用戶調整人口、物資等參數，查看對韌性分數的影響。
    注意：此端點不會修改實際數據。
    """
    try:
        with get_db() as conn:
            engine = CIRSResilienceEngine(conn)

            # Get current config
            current_config = engine.get_config(station_id)

            # Apply simulation adjustments
            sim_config = current_config.copy()
            if request.population is not None:
                sim_config['population_count'] = request.population
            if request.target_days is not None:
                sim_config['isolation_target_days'] = request.target_days

            # Temporarily update config for simulation
            engine.update_config(station_id, sim_config)

            try:
                # Calculate with simulated config
                result = engine.calculate(station_id)
                result['simulated'] = True
                result['simulation_params'] = {
                    'population': request.population,
                    'target_days': request.target_days,
                    'inventory_adjustments': request.inventory_adjustments,
                    'staff_adjustments': request.staff_adjustments
                }
                return result
            finally:
                # Restore original config
                engine.update_config(station_id, current_config)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"模擬失敗: {str(e)}")
