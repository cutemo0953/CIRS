"""
CIRS - Medication Status API for Doctor PWA (xIRS v1.1)
Provides medication list and stock status for prescribing.
"""
from fastapi import APIRouter, HTTPException
from typing import Optional
from datetime import datetime
import time

from database import get_db, dict_from_row

router = APIRouter()


# Demo medication list (in production, sync from MIRS)
DEMO_MEDICATIONS = [
    {"code": "ACETAMINOPHEN_500_TAB", "name": "Acetaminophen 500mg 錠", "category": "解熱鎮痛", "form": "TAB", "is_controlled": False, "substitution_group": "APAP"},
    {"code": "IBUPROFEN_400_TAB", "name": "Ibuprofen 400mg 錠", "category": "解熱鎮痛", "form": "TAB", "is_controlled": False, "substitution_group": "NSAID"},
    {"code": "AMOXICILLIN_500_CAP", "name": "Amoxicillin 500mg 膠囊", "category": "抗生素", "form": "CAP", "is_controlled": False, "substitution_group": "AMOX"},
    {"code": "AZITHROMYCIN_250_TAB", "name": "Azithromycin 250mg 錠", "category": "抗生素", "form": "TAB", "is_controlled": False, "substitution_group": "MACROLIDE"},
    {"code": "CETIRIZINE_10_TAB", "name": "Cetirizine 10mg 錠", "category": "抗組織胺", "form": "TAB", "is_controlled": False, "substitution_group": "ANTIHISTAMINE"},
    {"code": "OMEPRAZOLE_20_CAP", "name": "Omeprazole 20mg 膠囊", "category": "消化系統", "form": "CAP", "is_controlled": False, "substitution_group": "PPI"},
    {"code": "METFORMIN_500_TAB", "name": "Metformin 500mg 錠", "category": "降血糖", "form": "TAB", "is_controlled": False, "substitution_group": "METFORMIN"},
    {"code": "AMLODIPINE_5_TAB", "name": "Amlodipine 5mg 錠", "category": "降血壓", "form": "TAB", "is_controlled": False, "substitution_group": "CCB"},
    {"code": "SALBUTAMOL_100_INH", "name": "Salbutamol 100mcg 吸入劑", "category": "呼吸系統", "form": "INH", "is_controlled": False, "substitution_group": "SABA"},
    {"code": "DEXTROMETHORPHAN_15_SYR", "name": "Dextromethorphan 15mg/5ml 糖漿", "category": "止咳", "form": "SYR", "is_controlled": False, "substitution_group": "COUGH"},
    {"code": "LOPERAMIDE_2_CAP", "name": "Loperamide 2mg 膠囊", "category": "止瀉", "form": "CAP", "is_controlled": False, "substitution_group": "ANTIDIARRHEAL"},
    {"code": "DIAZEPAM_5_TAB", "name": "Diazepam 5mg 錠", "category": "鎮靜安眠", "form": "TAB", "is_controlled": True, "substitution_group": "BENZO"},
    {"code": "MORPHINE_10_TAB", "name": "Morphine 10mg 錠", "category": "止痛", "form": "TAB", "is_controlled": True, "substitution_group": "OPIOID"},
    {"code": "TRAMADOL_50_CAP", "name": "Tramadol 50mg 膠囊", "category": "止痛", "form": "CAP", "is_controlled": True, "substitution_group": "OPIOID"},
    {"code": "GLUCOSE_5_IV", "name": "Glucose 5% 500ml 注射液", "category": "輸液", "form": "IV", "is_controlled": False, "substitution_group": "IV_FLUID"},
    {"code": "NACL_09_IV", "name": "Normal Saline 0.9% 500ml", "category": "輸液", "form": "IV", "is_controlled": False, "substitution_group": "IV_FLUID"},
]

# Demo stock status (simulated)
DEMO_STOCK = {
    "ACETAMINOPHEN_500_TAB": {"qty": 500, "min": 100, "status": "OK"},
    "IBUPROFEN_400_TAB": {"qty": 200, "min": 50, "status": "OK"},
    "AMOXICILLIN_500_CAP": {"qty": 80, "min": 100, "status": "LOW"},
    "AZITHROMYCIN_250_TAB": {"qty": 150, "min": 50, "status": "OK"},
    "CETIRIZINE_10_TAB": {"qty": 300, "min": 50, "status": "OK"},
    "OMEPRAZOLE_20_CAP": {"qty": 0, "min": 50, "status": "OUT"},
    "METFORMIN_500_TAB": {"qty": 400, "min": 100, "status": "OK"},
    "AMLODIPINE_5_TAB": {"qty": 250, "min": 50, "status": "OK"},
    "SALBUTAMOL_100_INH": {"qty": 20, "min": 30, "status": "LOW"},
    "DEXTROMETHORPHAN_15_SYR": {"qty": 45, "min": 20, "status": "OK"},
    "LOPERAMIDE_2_CAP": {"qty": 0, "min": 30, "status": "OUT"},
    "DIAZEPAM_5_TAB": {"qty": 50, "min": 20, "status": "OK"},
    "MORPHINE_10_TAB": {"qty": 10, "min": 10, "status": "LOW"},
    "TRAMADOL_50_CAP": {"qty": 30, "min": 20, "status": "OK"},
    "GLUCOSE_5_IV": {"qty": 100, "min": 50, "status": "OK"},
    "NACL_09_IV": {"qty": 120, "min": 50, "status": "OK"},
}


@router.get("/list")
async def get_medication_list():
    """
    Get full medication list for Doctor PWA.
    In production, this would sync from MIRS.
    """
    return {
        "count": len(DEMO_MEDICATIONS),
        "medications": DEMO_MEDICATIONS,
        "source": "DEMO",
        "updated_at": datetime.now().isoformat()
    }


@router.get("/status")
async def get_medication_status(station_id: Optional[str] = None):
    """
    Get medication stock status for Doctor PWA.
    Returns status (OK/LOW/OUT) without exact quantities.

    Per v1.1 spec:
    - as_of: timestamp of last sync
    - ttl_seconds: cache validity period (30 min default)
    - items: list of {code, status}
    """
    # In demo mode, return simulated stock status
    now = int(time.time())

    medications_with_status = []
    for med in DEMO_MEDICATIONS:
        stock = DEMO_STOCK.get(med['code'], {"status": "UNKNOWN"})
        medications_with_status.append({
            "code": med['code'],
            "name": med['name'],
            "stock_status": stock['status'],
            "is_controlled": med.get('is_controlled', False)
        })

    return {
        "as_of": now,
        "ttl_seconds": 1800,  # 30 minutes
        "station_id": station_id or "PHARM-01",
        "source": "DEMO",
        "medications": medications_with_status
    }


@router.get("/{code}")
async def get_medication_detail(code: str):
    """Get detailed information about a specific medication."""
    for med in DEMO_MEDICATIONS:
        if med['code'] == code:
            stock = DEMO_STOCK.get(code, {"qty": 0, "min": 0, "status": "UNKNOWN"})
            return {
                **med,
                "stock_status": stock['status'],
                "in_stock": stock['status'] != 'OUT'
            }

    raise HTTPException(status_code=404, detail="Medication not found")
