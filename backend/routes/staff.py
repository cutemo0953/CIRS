"""
CIRS Staff Management API Routes v1.1
Implements self-service onboarding, clock-in/out, and Fast Pass features.
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, timedelta
import uuid
import json

from database import get_db, write_db, dict_from_row, rows_to_list

router = APIRouter()


# ============================================================================
# Pydantic Models
# ============================================================================

class JoinRequest(BaseModel):
    """自助登錄申請"""
    display_name: str = Field(..., min_length=1, max_length=50)
    phone: Optional[str] = Field(None, max_length=20)
    claimed_role: str = Field(..., pattern="^(MEDIC|NURSE|VOLUNTEER|ADMIN|SECURITY|COORDINATOR)$")
    skills: Optional[List[str]] = None
    expected_hours: float = Field(4, ge=1, le=24)
    notes: Optional[str] = Field(None, max_length=200)


class JoinApproval(BaseModel):
    """核准申請"""
    verified: bool = False
    override_role: Optional[str] = None
    notes: Optional[str] = None
    approver_id: str


class StaffCreate(BaseModel):
    """新增工作人員 (管理員手動)"""
    display_name: str = Field(..., min_length=1, max_length=50)
    phone: Optional[str] = None
    staff_role: str = Field(..., pattern="^(MEDIC|NURSE|VOLUNTEER|ADMIN|SECURITY|COORDINATOR)$")
    verified: bool = False
    expected_hours: float = Field(4, ge=1, le=24)
    skills: Optional[List[str]] = None
    notes: Optional[str] = None


class ClockInRequest(BaseModel):
    """報到請求"""
    expected_hours: float = Field(4, ge=1, le=24)
    notes: Optional[str] = None


class FastPassRequest(BaseModel):
    """快速通關請求"""
    badge_token: str


class StaffVerify(BaseModel):
    """驗證工作人員"""
    verifier_id: str
    notes: Optional[str] = None


# ============================================================================
# Helper Functions
# ============================================================================

def generate_token(prefix: str) -> str:
    """Generate token with prefix (JR- or BT-)"""
    return f"{prefix}{uuid.uuid4().hex[:12]}"


def generate_person_id(conn) -> str:
    """Generate sequential person ID"""
    cursor = conn.execute(
        "SELECT id FROM person WHERE id LIKE 'P%' ORDER BY id DESC LIMIT 1"
    )
    row = cursor.fetchone()
    if row and row['id'].startswith('P'):
        try:
            last_num = int(row['id'][1:])
            return f"P{last_num + 1:04d}"
        except ValueError:
            pass
    return "P0001"


def get_role_config(conn, role_code: str) -> Optional[dict]:
    """Get role configuration"""
    cursor = conn.execute(
        "SELECT * FROM staff_role_config WHERE role_code = ?",
        (role_code,)
    )
    row = cursor.fetchone()
    return dict_from_row(row) if row else None


# ============================================================================
# Self-Service Join API
# ============================================================================

@router.post("/join")
async def submit_join_request(request: JoinRequest):
    """
    提交自助登錄申請
    Returns QR token for admin approval
    """
    qr_token = generate_token("JR-")
    expires_at = datetime.now() + timedelta(minutes=30)

    with write_db() as conn:
        conn.execute("""
            INSERT INTO staff_join_requests
            (qr_token, display_name, phone, claimed_role, skills, expected_hours, notes, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            qr_token,
            request.display_name,
            request.phone,
            request.claimed_role,
            json.dumps(request.skills or [], ensure_ascii=False),
            request.expected_hours,
            request.notes,
            expires_at.isoformat()
        ))

    return {
        "qr_token": qr_token,
        "expires_at": expires_at.isoformat(),
        "qr_url": f"/staff/join/pending?token={qr_token}",
        "message": "請出示此 QR Code 給管理員掃描"
    }


# Static /join routes must come before /join/{token}
@router.get("/join/pending")
async def list_pending_requests():
    """
    列出待處理的申請
    """
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT j.*, r.display_name as role_display, r.color_hex
            FROM staff_join_requests j
            LEFT JOIN staff_role_config r ON j.claimed_role = r.role_code
            WHERE j.status = 'PENDING'
              AND j.expires_at > datetime('now')
            ORDER BY j.created_at ASC
        """)
        requests = rows_to_list(cursor.fetchall())

        for req in requests:
            if req.get('skills'):
                try:
                    req['skills'] = json.loads(req['skills'])
                except:
                    req['skills'] = []
            # Calculate remaining time
            expires_at = datetime.fromisoformat(req['expires_at'])
            remaining = (expires_at - datetime.now()).total_seconds()
            req['remaining_seconds'] = max(0, int(remaining))

    return {"requests": requests, "count": len(requests)}


@router.get("/join/{token}")
async def get_join_request(token: str):
    """
    取得申請詳情 (管理員用)
    """
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM staff_join_requests WHERE qr_token = ?",
            (token,)
        )
        row = cursor.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="申請不存在")

        request = dict_from_row(row)

        # Check expiry
        expires_at = datetime.fromisoformat(request['expires_at'])
        if datetime.now() > expires_at and request['status'] == 'PENDING':
            # Mark as expired
            conn.execute(
                "UPDATE staff_join_requests SET status = 'EXPIRED' WHERE qr_token = ?",
                (token,)
            )
            request['status'] = 'EXPIRED'

        # Parse skills JSON
        if request.get('skills'):
            try:
                request['skills'] = json.loads(request['skills'])
            except:
                request['skills'] = []

        # Get role config for display
        role_config = get_role_config(conn, request['claimed_role'])
        request['role_display'] = role_config if role_config else {'display_name': request['claimed_role']}

        # Calculate remaining time
        if request['status'] == 'PENDING':
            remaining = (expires_at - datetime.now()).total_seconds()
            request['remaining_seconds'] = max(0, int(remaining))

    return request


@router.post("/join/{token}/approve")
async def approve_join_request(token: str, approval: JoinApproval):
    """
    核准申請並建立人員
    """
    with write_db() as conn:
        # Get request
        cursor = conn.execute(
            "SELECT * FROM staff_join_requests WHERE qr_token = ?",
            (token,)
        )
        row = cursor.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="申請不存在")

        request = dict_from_row(row)

        if request['status'] != 'PENDING':
            raise HTTPException(status_code=400, detail=f"此申請已 {request['status']}")

        # Check expiry
        expires_at = datetime.fromisoformat(request['expires_at'])
        if datetime.now() > expires_at:
            conn.execute(
                "UPDATE staff_join_requests SET status = 'EXPIRED' WHERE qr_token = ?",
                (token,)
            )
            raise HTTPException(status_code=400, detail="申請已過期")

        # Generate person ID
        person_id = generate_person_id(conn)

        # Determine final role and verification status
        final_role = approval.override_role or request['claimed_role']
        verification_status = 'VERIFIED' if approval.verified else 'UNVERIFIED'

        # Calculate shift_end
        shift_end = datetime.now() + timedelta(hours=request['expected_hours'])

        # Create person
        conn.execute("""
            INSERT INTO person (
                id, display_name, phone_hash, role,
                staff_role, staff_status, verification_status,
                verified_at, verified_by, shift_start, shift_end,
                expected_hours, skills, checked_in_at
            ) VALUES (?, ?, ?, 'staff', ?, 'ACTIVE', ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (
            person_id,
            request['display_name'],
            request['phone'],  # Store as-is for now (could hash in production)
            final_role,
            verification_status,
            datetime.now().isoformat() if approval.verified else None,
            approval.approver_id if approval.verified else None,
            datetime.now().isoformat(),
            shift_end.isoformat(),
            request['expected_hours'],
            request['skills']
        ))

        # Update request status
        conn.execute("""
            UPDATE staff_join_requests
            SET status = 'APPROVED', processed_at = ?, processed_by = ?, person_id = ?
            WHERE qr_token = ?
        """, (datetime.now().isoformat(), approval.approver_id, person_id, token))

        # Log event
        conn.execute("""
            INSERT INTO event_log (event_type, person_id, notes)
            VALUES ('CHECK_IN', ?, ?)
        """, (person_id, f"自助登錄核准: {final_role}"))

    return {
        "success": True,
        "person_id": person_id,
        "display_name": request['display_name'],
        "staff_role": final_role,
        "staff_status": "ACTIVE",
        "verification_status": verification_status,
        "shift_end": shift_end.isoformat()
    }


@router.post("/join/{token}/reject")
async def reject_join_request(token: str, approver_id: str = Query(...)):
    """
    拒絕申請
    """
    with write_db() as conn:
        cursor = conn.execute(
            "SELECT status FROM staff_join_requests WHERE qr_token = ?",
            (token,)
        )
        row = cursor.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="申請不存在")

        if row['status'] != 'PENDING':
            raise HTTPException(status_code=400, detail=f"此申請已 {row['status']}")

        conn.execute("""
            UPDATE staff_join_requests
            SET status = 'REJECTED', processed_at = ?, processed_by = ?
            WHERE qr_token = ?
        """, (datetime.now().isoformat(), approver_id, token))

    return {"success": True, "message": "申請已拒絕"}


# ============================================================================
# Staff Management API
# ============================================================================

@router.get("")
async def list_staff(
    status: Optional[str] = Query(None, description="Filter by staff_status"),
    role: Optional[str] = Query(None, description="Filter by staff_role")
):
    """
    列出所有工作人員
    """
    with get_db() as conn:
        query = """
            SELECT p.*, r.display_name as role_display, r.color_hex, r.icon_name
            FROM person p
            LEFT JOIN staff_role_config r ON p.staff_role = r.role_code
            WHERE p.staff_role IS NOT NULL
        """
        params = []

        if status:
            query += " AND p.staff_status = ?"
            params.append(status)

        if role:
            query += " AND p.staff_role = ?"
            params.append(role)

        query += " ORDER BY p.staff_status DESC, p.display_name"

        cursor = conn.execute(query, params)
        staff = rows_to_list(cursor.fetchall())

        # Remove sensitive data
        for s in staff:
            s.pop('pin_hash', None)
            s.pop('national_id_hash', None)
            if s.get('skills'):
                try:
                    s['skills'] = json.loads(s['skills'])
                except:
                    pass

    return {"staff": staff, "count": len(staff)}


@router.post("")
async def create_staff(request: StaffCreate):
    """
    新增工作人員 (管理員手動)
    """
    with write_db() as conn:
        person_id = generate_person_id(conn)
        shift_end = datetime.now() + timedelta(hours=request.expected_hours)

        verification_status = 'VERIFIED' if request.verified else 'UNVERIFIED'

        conn.execute("""
            INSERT INTO person (
                id, display_name, phone_hash, role,
                staff_role, staff_status, verification_status,
                shift_start, shift_end, expected_hours, skills, checked_in_at
            ) VALUES (?, ?, ?, 'staff', ?, 'ACTIVE', ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (
            person_id,
            request.display_name,
            request.phone,
            request.staff_role,
            verification_status,
            datetime.now().isoformat(),
            shift_end.isoformat(),
            request.expected_hours,
            json.dumps(request.skills or [], ensure_ascii=False)
        ))

        conn.execute("""
            INSERT INTO event_log (event_type, person_id, notes)
            VALUES ('CHECK_IN', ?, ?)
        """, (person_id, f"管理員手動新增: {request.staff_role}"))

    return {
        "success": True,
        "person_id": person_id,
        "staff_role": request.staff_role,
        "staff_status": "ACTIVE",
        "shift_end": shift_end.isoformat()
    }


# ============================================================================
# Static Routes (must be before /{staff_id} to avoid being caught by dynamic route)
# ============================================================================

@router.get("/summary/stats")
async def get_staff_summary():
    """
    人力摘要統計
    """
    with get_db() as conn:
        # Total registered staff
        cursor = conn.execute(
            "SELECT COUNT(*) as count FROM person WHERE staff_role IS NOT NULL"
        )
        total_registered = cursor.fetchone()['count']

        # By status (weighted)
        cursor = conn.execute("""
            SELECT
                staff_role,
                SUM(CASE WHEN staff_status = 'ACTIVE' THEN 1 ELSE 0 END) as active,
                SUM(CASE WHEN staff_status = 'STANDBY' THEN 1 ELSE 0 END) as standby,
                SUM(CASE WHEN staff_status = 'OFF_DUTY' THEN 1 ELSE 0 END) as off_duty,
                COUNT(*) as total
            FROM person
            WHERE staff_role IS NOT NULL
            GROUP BY staff_role
        """)

        by_role = {}
        total_active = 0
        total_standby = 0
        total_effective = 0

        for row in cursor.fetchall():
            role = row['staff_role']
            active = row['active'] or 0
            standby = row['standby'] or 0
            effective = active * 1.0 + standby * 0.5

            by_role[role] = {
                'active': active,
                'standby': standby,
                'off_duty': row['off_duty'] or 0,
                'total': row['total'],
                'effective': round(effective, 1)
            }

            total_active += active
            total_standby += standby
            total_effective += effective

        # Get required staff from rules
        cursor = conn.execute("""
            SELECT * FROM staffing_rules WHERE is_essential = 1
        """)
        rules = cursor.fetchall()

        # Get population for requirement calculation
        cursor = conn.execute(
            "SELECT population_count FROM resilience_config WHERE station_id = 'default'"
        )
        config = cursor.fetchone()
        population = config['population_count'] if config else 0

        required = {}
        shortages = []
        import math

        for rule in rules:
            role_code = rule['role_code']
            params = json.loads(rule['calc_params'])

            if rule['calc_mode'] == 'PER_N_PEOPLE':
                n = params.get('n', 100)
                qty = params.get('qty', 1)
                req = math.ceil((population / n) * qty) if n > 0 else qty
            elif rule['calc_mode'] == 'FIXED_MIN':
                req = params.get('min_qty', 1)
            else:
                req = 1

            req = max(1, req)
            required[role_code] = req

            # Check for shortage
            effective = by_role.get(role_code, {}).get('effective', 0)
            if effective < req:
                shortages.append({
                    'role': role_code,
                    'role_name': rule['role_name'],
                    'required': req,
                    'effective': effective,
                    'gap': round(req - effective, 1)
                })

        # Impending shortages
        cursor = conn.execute("""
            SELECT p.id, p.display_name, p.staff_role, p.shift_end
            FROM person p
            WHERE p.staff_status = 'ACTIVE'
              AND p.shift_end IS NOT NULL
              AND p.shift_end <= datetime('now', '+30 minutes')
              AND p.shift_end > datetime('now')
            ORDER BY p.shift_end
        """)
        impending = rows_to_list(cursor.fetchall())

        # Calculate coverage score
        if required:
            coverage_scores = []
            for role, req in required.items():
                eff = by_role.get(role, {}).get('effective', 0)
                coverage_scores.append(min(100, (eff / req * 100)) if req > 0 else 100)
            coverage_score = sum(coverage_scores) / len(coverage_scores)
        else:
            coverage_score = 100

    return {
        "total_registered": total_registered,
        "active_count": total_active,
        "standby_count": total_standby,
        "effective_staff": round(total_effective, 1),
        "by_role": by_role,
        "required": required,
        "shortages": shortages,
        "impending_shortages": impending,
        "coverage_score": round(coverage_score, 1)
    }


@router.get("/on-duty")
async def list_on_duty():
    """
    列出目前在值人員
    """
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT p.id, p.display_name, p.staff_role, p.staff_status,
                   p.shift_start, p.shift_end, p.verification_status,
                   r.display_name as role_display, r.color_hex, r.icon_name
            FROM person p
            LEFT JOIN staff_role_config r ON p.staff_role = r.role_code
            WHERE p.staff_role IS NOT NULL
              AND p.staff_status IN ('ACTIVE', 'STANDBY')
            ORDER BY p.staff_status DESC, p.shift_start
        """)
        staff = rows_to_list(cursor.fetchall())

    return {"staff": staff, "count": len(staff)}


@router.get("/role-config")
async def get_role_configs():
    """
    取得職能角色設定
    """
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM staff_role_config ORDER BY sort_order"
        )
        roles = rows_to_list(cursor.fetchall())

    return {"roles": roles}


# ============================================================================
# Dynamic Staff ID Routes
# ============================================================================

@router.get("/{staff_id}")
async def get_staff(staff_id: str):
    """
    取得工作人員詳情
    """
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT p.*, r.display_name as role_display, r.color_hex, r.icon_name
            FROM person p
            LEFT JOIN staff_role_config r ON p.staff_role = r.role_code
            WHERE p.id = ? AND p.staff_role IS NOT NULL
        """, (staff_id,))
        staff = dict_from_row(cursor.fetchone())

        if not staff:
            raise HTTPException(status_code=404, detail="工作人員不存在")

        # Remove sensitive data
        staff.pop('pin_hash', None)
        staff.pop('national_id_hash', None)

        if staff.get('skills'):
            try:
                staff['skills'] = json.loads(staff['skills'])
            except:
                pass

    return staff


@router.post("/{staff_id}/verify")
async def verify_staff(staff_id: str, request: StaffVerify):
    """
    驗證工作人員 (查驗證件)
    """
    with write_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM person WHERE id = ? AND staff_role IS NOT NULL",
            (staff_id,)
        )
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="工作人員不存在")

        conn.execute("""
            UPDATE person
            SET verification_status = 'VERIFIED',
                verified_at = ?,
                verified_by = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (datetime.now().isoformat(), request.verifier_id, staff_id))

        conn.execute("""
            INSERT INTO event_log (event_type, person_id, operator_id, notes)
            VALUES ('VERIFY', ?, ?, ?)
        """, (staff_id, request.verifier_id, request.notes or "證件查驗通過"))

    return {"success": True, "message": "驗證成功"}


# ============================================================================
# Clock In/Out API
# ============================================================================

@router.post("/{staff_id}/clock-in")
async def clock_in(staff_id: str, request: ClockInRequest):
    """
    報到上班
    """
    with write_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM person WHERE id = ? AND staff_role IS NOT NULL",
            (staff_id,)
        )
        person = cursor.fetchone()

        if not person:
            raise HTTPException(status_code=404, detail="工作人員不存在")

        if person['staff_status'] == 'ACTIVE':
            raise HTTPException(status_code=400, detail="已在值中")

        shift_end = datetime.now() + timedelta(hours=request.expected_hours)

        conn.execute("""
            UPDATE person
            SET staff_status = 'ACTIVE',
                shift_start = ?,
                shift_end = ?,
                expected_hours = ?,
                checked_in_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (datetime.now().isoformat(), shift_end.isoformat(), request.expected_hours, staff_id))

        conn.execute("""
            INSERT INTO event_log (event_type, person_id, notes)
            VALUES ('CLOCK_IN', ?, ?)
        """, (staff_id, request.notes or f"報到，預計 {request.expected_hours} 小時"))

    return {
        "success": True,
        "staff_status": "ACTIVE",
        "shift_start": datetime.now().isoformat(),
        "shift_end": shift_end.isoformat()
    }


@router.post("/{staff_id}/clock-out")
async def clock_out(staff_id: str):
    """
    離班下班
    Returns Fast Pass badge token for quick return
    """
    with write_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM person WHERE id = ? AND staff_role IS NOT NULL",
            (staff_id,)
        )
        person = cursor.fetchone()

        if not person:
            raise HTTPException(status_code=404, detail="工作人員不存在")

        if person['staff_status'] != 'ACTIVE':
            raise HTTPException(status_code=400, detail="目前未在值")

        # Generate Fast Pass badge token (12 hours valid)
        badge_token = generate_token("BT-")
        badge_expires = datetime.now() + timedelta(hours=12)

        # Save badge token
        conn.execute("""
            INSERT INTO staff_badge_tokens (token_id, person_id, expires_at)
            VALUES (?, ?, ?)
        """, (badge_token, staff_id, badge_expires.isoformat()))

        # Update person status
        conn.execute("""
            UPDATE person
            SET staff_status = 'OFF_DUTY',
                shift_end = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (staff_id,))

        conn.execute("""
            INSERT INTO event_log (event_type, person_id, notes)
            VALUES ('CLOCK_OUT', ?, ?)
        """, (staff_id, f"離班，發放通行證 {badge_token}"))

    return {
        "success": True,
        "staff_status": "OFF_DUTY",
        "badge_token": badge_token,
        "badge_expires": badge_expires.isoformat(),
        "message": "辛苦了！明天可使用快速通關"
    }


@router.post("/fast-pass")
async def use_fast_pass(request: FastPassRequest):
    """
    使用快速通關
    """
    with write_db() as conn:
        cursor = conn.execute("""
            SELECT t.*, p.display_name, p.staff_role, p.staff_status
            FROM staff_badge_tokens t
            JOIN person p ON t.person_id = p.id
            WHERE t.token_id = ?
        """, (request.badge_token,))
        row = cursor.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="通行證無效")

        token = dict_from_row(row)

        if token['is_revoked']:
            raise HTTPException(status_code=400, detail="通行證已撤銷")

        expires_at = datetime.fromisoformat(token['expires_at'])
        if datetime.now() > expires_at:
            raise HTTPException(status_code=400, detail="通行證已過期")

        if token['staff_status'] == 'ACTIVE':
            raise HTTPException(status_code=400, detail="已在值中")

        # Clock in with default 4 hours
        shift_end = datetime.now() + timedelta(hours=4)

        conn.execute("""
            UPDATE person
            SET staff_status = 'ACTIVE',
                shift_start = ?,
                shift_end = ?,
                expected_hours = 4,
                checked_in_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (datetime.now().isoformat(), shift_end.isoformat(), token['person_id']))

        # Revoke used token
        conn.execute(
            "UPDATE staff_badge_tokens SET is_revoked = 1 WHERE token_id = ?",
            (request.badge_token,)
        )

        conn.execute("""
            INSERT INTO event_log (event_type, person_id, notes)
            VALUES ('CLOCK_IN', ?, ?)
        """, (token['person_id'], "快速通關報到"))

    return {
        "success": True,
        "person_id": token['person_id'],
        "display_name": token['display_name'],
        "staff_role": token['staff_role'],
        "staff_status": "ACTIVE",
        "shift_end": shift_end.isoformat()
    }
