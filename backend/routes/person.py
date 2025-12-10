"""
CIRS Person Routes
"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
import hashlib
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import get_db, write_db, dict_from_row, rows_to_list
from routes.auth import hash_pin

router = APIRouter()


def generate_sequence_id(conn):
    """Generate sequential ID like P0001, P0002, etc."""
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


def hash_national_id(national_id: str) -> str:
    """Hash national ID for privacy protection"""
    # Use SHA-256 with salt for secure hashing
    salt = "CIRS_NID_SALT_2024"
    return hashlib.sha256(f"{salt}{national_id.upper()}".encode()).hexdigest()


class PersonCreate(BaseModel):
    display_name: str
    national_id: Optional[str] = None  # 身分證字號（選填，無法辨識身分時可空）
    phone: Optional[str] = None        # 手機號碼（選填）
    role: str = "public"
    pin: Optional[str] = None
    metadata: Optional[str] = None
    current_location: Optional[str] = None
    triage_status: Optional[str] = None  # 'GREEN', 'YELLOW', 'RED', 'BLACK'
    photo_data: Optional[str] = None   # Base64 照片
    physical_desc: Optional[str] = None # 外觀特徵描述


class PersonUpdate(BaseModel):
    display_name: Optional[str] = None
    phone_hash: Optional[str] = None
    role: Optional[str] = None
    metadata: Optional[str] = None
    current_location: Optional[str] = None
    triage_status: Optional[str] = None


class TriageRequest(BaseModel):
    status: str  # 'GREEN', 'YELLOW', 'RED', 'BLACK'
    notes: Optional[str] = None


class RoleChangeRequest(BaseModel):
    role: str  # 'admin', 'staff', 'medic', 'public'


class BatchCheckoutRequest(BaseModel):
    person_ids: list[str]
    reason: Optional[str] = None  # 'DISCHARGE' 正常離站, 'TRANSFER' 轉送, 'OTHER' 其他
    destination: Optional[str] = None  # 離開後去向
    notes: Optional[str] = None  # 備註


@router.get("")
async def list_persons(
    role: Optional[str] = Query(None, description="Filter by role"),
    triage_status: Optional[str] = Query(None, description="Filter by triage status"),
    checked_in: Optional[bool] = Query(None, description="Filter by check-in status")
):
    """List all persons"""
    with get_db() as conn:
        query = "SELECT * FROM person WHERE 1=1"
        params = []

        if role:
            query += " AND role = ?"
            params.append(role)

        if triage_status:
            query += " AND triage_status = ?"
            params.append(triage_status)

        if checked_in is not None:
            if checked_in:
                query += " AND checked_in_at IS NOT NULL"
            else:
                query += " AND checked_in_at IS NULL"

        query += " ORDER BY checked_in_at DESC, display_name"

        cursor = conn.execute(query, params)
        persons = rows_to_list(cursor.fetchall())

        # Remove sensitive data
        for p in persons:
            p.pop('pin_hash', None)
            p.pop('national_id_hash', None)

    return {"persons": persons, "count": len(persons)}


@router.get("/lookup")
async def lookup_by_national_id(national_id: str = Query(..., description="身分證字號")):
    """Lookup person by national ID (身分證查詢)"""
    nid_hash = hash_national_id(national_id)

    with get_db() as conn:
        cursor = conn.execute(
            "SELECT id, display_name, triage_status, current_location, checked_in_at FROM person WHERE national_id_hash = ?",
            (nid_hash,)
        )
        person = dict_from_row(cursor.fetchone())

    if person is None:
        return {"found": False, "message": "查無此人"}

    return {"found": True, "person": person}


@router.get("/{person_id}")
async def get_person(person_id: str):
    """Get a single person by system ID"""
    with get_db() as conn:
        cursor = conn.execute("SELECT * FROM person WHERE id = ?", (person_id,))
        person = dict_from_row(cursor.fetchone())

    if person is None:
        raise HTTPException(status_code=404, detail="Person not found")

    # Remove sensitive data
    person.pop('pin_hash', None)
    person.pop('national_id_hash', None)  # Never expose hash
    return person


@router.post("")
async def create_person(person: PersonCreate):
    """Create a new person (register/check-in)"""
    pin_hash_val = hash_pin(person.pin) if person.pin else None

    # Validate triage status if provided
    if person.triage_status and person.triage_status not in ['GREEN', 'YELLOW', 'RED', 'BLACK']:
        raise HTTPException(status_code=400, detail="Invalid triage status")

    # Hash national ID if provided
    national_id_hash = hash_national_id(person.national_id) if person.national_id else None
    phone_hash = hashlib.sha256(person.phone.encode()).hexdigest() if person.phone else None

    with write_db() as conn:
        # Check if national ID already registered
        if national_id_hash:
            cursor = conn.execute(
                "SELECT id, display_name FROM person WHERE national_id_hash = ?",
                (national_id_hash,)
            )
            existing = cursor.fetchone()
            if existing:
                # Person already registered - return existing ID
                return {
                    "id": existing['id'],
                    "message": f"已登記: {existing['display_name']}",
                    "existing": True
                }

        # Generate new sequential ID
        new_id = generate_sequence_id(conn)

        # Determine ID status
        id_status = 'confirmed' if national_id_hash else 'unidentified'

        try:
            conn.execute(
                """
                INSERT INTO person (id, national_id_hash, display_name, phone_hash, role, pin_hash,
                    metadata, current_location, triage_status, photo_data, physical_desc, id_status, checked_in_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (new_id, national_id_hash, person.display_name, phone_hash, person.role,
                 pin_hash_val, person.metadata, person.current_location, person.triage_status,
                 person.photo_data, person.physical_desc, id_status)
            )

            # Log check-in event
            conn.execute(
                """
                INSERT INTO event_log (event_type, person_id, location, status_value, notes)
                VALUES ('CHECK_IN', ?, ?, ?, ?)
                """,
                (new_id, person.current_location, person.triage_status, f"報到: {person.display_name}")
            )

            # Log triage event if status provided
            if person.triage_status:
                conn.execute(
                    """
                    INSERT INTO event_log (event_type, person_id, status_value, notes)
                    VALUES ('TRIAGE', ?, ?, ?)
                    """,
                    (new_id, person.triage_status, "報到時初始檢傷")
                )
        except Exception as e:
            if "UNIQUE constraint" in str(e):
                raise HTTPException(status_code=400, detail="此身分證已登記")
            raise

    return {"id": new_id, "message": "報到成功", "existing": False}


@router.put("/{person_id}")
async def update_person(person_id: str, person: PersonUpdate):
    """Update a person's info"""
    updates = []
    params = []

    for field, value in person.model_dump(exclude_unset=True).items():
        if value is not None:
            updates.append(f"{field} = ?")
            params.append(value)

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    updates.append("updated_at = CURRENT_TIMESTAMP")
    params.append(person_id)

    with write_db() as conn:
        cursor = conn.execute("SELECT * FROM person WHERE id = ?", (person_id,))
        if cursor.fetchone() is None:
            raise HTTPException(status_code=404, detail="Person not found")

        query = f"UPDATE person SET {', '.join(updates)} WHERE id = ?"
        conn.execute(query, params)

    return {"message": "Person updated successfully"}


@router.post("/{person_id}/checkin")
async def check_in(person_id: str, location: Optional[str] = None):
    """Check in a person"""
    with write_db() as conn:
        cursor = conn.execute("SELECT * FROM person WHERE id = ?", (person_id,))
        person = cursor.fetchone()

        if person is None:
            raise HTTPException(status_code=404, detail="Person not found")

        conn.execute(
            """
            UPDATE person SET checked_in_at = CURRENT_TIMESTAMP, current_location = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (location, person_id)
        )

        conn.execute(
            """
            INSERT INTO event_log (event_type, person_id, location)
            VALUES ('CHECK_IN', ?, ?)
            """,
            (person_id, location)
        )

    return {"message": "Check-in successful"}


@router.post("/{person_id}/checkout")
async def check_out(person_id: str):
    """Check out a person"""
    with write_db() as conn:
        cursor = conn.execute("SELECT * FROM person WHERE id = ?", (person_id,))
        person = cursor.fetchone()

        if person is None:
            raise HTTPException(status_code=404, detail="Person not found")

        conn.execute(
            """
            UPDATE person SET checked_in_at = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (person_id,)
        )

        conn.execute(
            """
            INSERT INTO event_log (event_type, person_id)
            VALUES ('CHECK_OUT', ?)
            """,
            (person_id,)
        )

    return {"message": "Check-out successful"}


@router.post("/batch-checkout")
async def batch_checkout(request: BatchCheckoutRequest):
    """Batch checkout multiple persons (批次退場)"""
    if not request.person_ids:
        raise HTTPException(status_code=400, detail="No person IDs provided")

    results = {"success": [], "failed": [], "not_found": []}

    with write_db() as conn:
        for person_id in request.person_ids:
            # Check if person exists and is checked in
            cursor = conn.execute(
                "SELECT id, display_name, checked_in_at FROM person WHERE id = ?",
                (person_id,)
            )
            person = cursor.fetchone()

            if person is None:
                results["not_found"].append(person_id)
                continue

            if person['checked_in_at'] is None:
                results["failed"].append({
                    "id": person_id,
                    "name": person['display_name'],
                    "reason": "未在站內"
                })
                continue

            # Perform checkout
            conn.execute(
                """
                UPDATE person SET checked_in_at = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (person_id,)
            )

            # Log event with details
            notes = []
            if request.reason:
                reason_names = {
                    'DISCHARGE': '正常離站',
                    'TRANSFER': '轉送醫院',
                    'OTHER': '其他原因'
                }
                notes.append(reason_names.get(request.reason, request.reason))
            if request.destination:
                notes.append(f"去向: {request.destination}")
            if request.notes:
                notes.append(request.notes)

            conn.execute(
                """
                INSERT INTO event_log (event_type, person_id, notes)
                VALUES ('CHECK_OUT', ?, ?)
                """,
                (person_id, " | ".join(notes) if notes else None)
            )

            results["success"].append({
                "id": person_id,
                "name": person['display_name']
            })

    return {
        "message": f"批次退場完成: {len(results['success'])} 人成功",
        "results": results
    }


@router.post("/{person_id}/triage")
async def triage_person(person_id: str, request: TriageRequest):
    """Set triage status for a person (START Protocol)"""
    valid_statuses = ['GREEN', 'YELLOW', 'RED', 'BLACK']
    if request.status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {valid_statuses}")

    with write_db() as conn:
        cursor = conn.execute("SELECT * FROM person WHERE id = ?", (person_id,))
        person = cursor.fetchone()

        if person is None:
            raise HTTPException(status_code=404, detail="Person not found")

        conn.execute(
            """
            UPDATE person SET triage_status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (request.status, person_id)
        )

        conn.execute(
            """
            INSERT INTO event_log (event_type, person_id, status_value, notes)
            VALUES ('TRIAGE', ?, ?, ?)
            """,
            (person_id, request.status, request.notes)
        )

    return {"message": f"Triage status set to {request.status}"}


@router.post("/{person_id}/role")
async def change_role(person_id: str, request: RoleChangeRequest):
    """Change a person's role (Admin only)"""
    valid_roles = ['admin', 'staff', 'medic', 'public']
    if request.role not in valid_roles:
        raise HTTPException(status_code=400, detail=f"Invalid role. Must be one of: {valid_roles}")

    with write_db() as conn:
        cursor = conn.execute("SELECT * FROM person WHERE id = ?", (person_id,))
        person = dict_from_row(cursor.fetchone())

        if person is None:
            raise HTTPException(status_code=404, detail="Person not found")

        old_role = person['role']

        conn.execute(
            """
            UPDATE person SET role = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (request.role, person_id)
        )

        conn.execute(
            """
            INSERT INTO event_log (event_type, person_id, status_value, notes)
            VALUES ('ROLE_CHANGE', ?, ?, ?)
            """,
            (person_id, request.role, f"Changed from {old_role} to {request.role}")
        )

    return {"message": f"Role changed to {request.role}"}


@router.get("/{person_id}/history")
async def get_person_history(person_id: str, limit: int = Query(50, le=200)):
    """Get event history for a person"""
    with get_db() as conn:
        # Check person exists
        cursor = conn.execute("SELECT * FROM person WHERE id = ?", (person_id,))
        if cursor.fetchone() is None:
            raise HTTPException(status_code=404, detail="Person not found")

        cursor = conn.execute(
            """
            SELECT e.*, i.name as item_name
            FROM event_log e
            LEFT JOIN inventory i ON e.item_id = i.id
            WHERE e.person_id = ?
            ORDER BY e.timestamp DESC
            LIMIT ?
            """,
            (person_id, limit)
        )
        events = rows_to_list(cursor.fetchall())

    return {"events": events, "count": len(events)}


# ============================================
# Admin Person Management (管理員人員管理)
# ============================================

# Reason codes for corrections
REASON_CODES = {
    'TYPO': '輸入錯誤',
    'ID_CONFIRMED': '身分確認',
    'DUPLICATE': '重複登記',
    'CORRECTION': '資料更正',
    'OTHER': '其他'
}


class AdminPersonUpdate(BaseModel):
    display_name: Optional[str] = None
    national_id: Optional[str] = None  # 補登或修正身分證
    phone: Optional[str] = None
    current_location: Optional[str] = None
    physical_desc: Optional[str] = None
    reason_code: str  # Required: 'TYPO', 'ID_CONFIRMED', 'DUPLICATE', 'CORRECTION', 'OTHER'
    reason_text: Optional[str] = None  # Additional notes
    operator_id: str  # Who is making the change


class ConfirmIdentityRequest(BaseModel):
    national_id: str
    operator_id: str
    reason_text: Optional[str] = None


@router.put("/{person_id}/admin-update")
async def admin_update_person(person_id: str, request: AdminPersonUpdate):
    """Admin update person with audit log (管理員修改人員資料)"""
    if request.reason_code not in REASON_CODES:
        raise HTTPException(status_code=400, detail=f"Invalid reason_code. Must be one of: {list(REASON_CODES.keys())}")

    with write_db() as conn:
        # Get current person data
        cursor = conn.execute("SELECT * FROM person WHERE id = ?", (person_id,))
        person = dict_from_row(cursor.fetchone())

        if person is None:
            raise HTTPException(status_code=404, detail="Person not found")

        # Build update
        updates = []
        params = []
        old_values = {}
        new_values = {}

        if request.display_name is not None:
            old_values['display_name'] = person['display_name']
            new_values['display_name'] = request.display_name
            updates.append("display_name = ?")
            params.append(request.display_name)

        if request.national_id is not None:
            nid_hash = hash_national_id(request.national_id)
            old_values['national_id_hash'] = person.get('national_id_hash')
            new_values['national_id_hash'] = nid_hash
            updates.append("national_id_hash = ?")
            params.append(nid_hash)
            # Also update id_status to confirmed
            updates.append("id_status = 'confirmed'")

        if request.phone is not None:
            phone_hash = hashlib.sha256(request.phone.encode()).hexdigest()
            old_values['phone_hash'] = person.get('phone_hash')
            new_values['phone_hash'] = phone_hash
            updates.append("phone_hash = ?")
            params.append(phone_hash)

        if request.current_location is not None:
            old_values['current_location'] = person.get('current_location')
            new_values['current_location'] = request.current_location
            updates.append("current_location = ?")
            params.append(request.current_location)

        if request.physical_desc is not None:
            old_values['physical_desc'] = person.get('physical_desc')
            new_values['physical_desc'] = request.physical_desc
            updates.append("physical_desc = ?")
            params.append(request.physical_desc)

        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")

        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(person_id)

        # Update person
        query = f"UPDATE person SET {', '.join(updates)} WHERE id = ?"
        conn.execute(query, params)

        # Create audit log
        import json
        conn.execute(
            """
            INSERT INTO audit_log (action_type, target_type, target_id, operator_id, reason_code, reason_text, old_value, new_value)
            VALUES ('PERSON_UPDATE', 'person', ?, ?, ?, ?, ?, ?)
            """,
            (person_id, request.operator_id, request.reason_code, request.reason_text,
             json.dumps(old_values, ensure_ascii=False), json.dumps(new_values, ensure_ascii=False))
        )

    return {"message": "Person updated successfully", "reason": REASON_CODES.get(request.reason_code)}


@router.post("/{person_id}/confirm-identity")
async def confirm_identity(person_id: str, request: ConfirmIdentityRequest):
    """Confirm identity of an unidentified person (確認身分)"""
    nid_hash = hash_national_id(request.national_id)

    with write_db() as conn:
        # Check person exists
        cursor = conn.execute("SELECT * FROM person WHERE id = ?", (person_id,))
        person = dict_from_row(cursor.fetchone())

        if person is None:
            raise HTTPException(status_code=404, detail="Person not found")

        if person.get('id_status') == 'confirmed':
            raise HTTPException(status_code=400, detail="Person already confirmed")

        # Check if national_id already used
        cursor = conn.execute(
            "SELECT id FROM person WHERE national_id_hash = ? AND id != ?",
            (nid_hash, person_id)
        )
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail="此身分證已被其他人員使用")

        # Update
        conn.execute(
            """
            UPDATE person SET national_id_hash = ?, id_status = 'confirmed', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (nid_hash, person_id)
        )

        # Audit log
        import json
        conn.execute(
            """
            INSERT INTO audit_log (action_type, target_type, target_id, operator_id, reason_code, reason_text, old_value, new_value)
            VALUES ('ID_CONFIRM', 'person', ?, ?, 'ID_CONFIRMED', ?, ?, ?)
            """,
            (person_id, request.operator_id, request.reason_text,
             json.dumps({'id_status': person.get('id_status')}, ensure_ascii=False),
             json.dumps({'id_status': 'confirmed'}, ensure_ascii=False))
        )

    return {"message": "Identity confirmed successfully"}


@router.get("/{person_id}/audit-log")
async def get_person_audit_log(person_id: str, limit: int = Query(50, le=200)):
    """Get audit log for a person (查詢人員修改記錄)"""
    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT a.*, p.display_name as operator_name
            FROM audit_log a
            LEFT JOIN person p ON a.operator_id = p.id
            WHERE a.target_type = 'person' AND a.target_id = ?
            ORDER BY a.timestamp DESC
            LIMIT ?
            """,
            (person_id, limit)
        )
        logs = rows_to_list(cursor.fetchall())

    return {"logs": logs, "count": len(logs)}


@router.get("/unidentified/list")
async def list_unidentified():
    """List all unidentified persons (列出待辨識人員)"""
    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT id, display_name, triage_status, current_location, physical_desc,
                   photo_data IS NOT NULL as has_photo, checked_in_at, created_at
            FROM person
            WHERE id_status = 'unidentified'
            ORDER BY created_at DESC
            """
        )
        persons = rows_to_list(cursor.fetchall())

    return {"persons": persons, "count": len(persons)}
