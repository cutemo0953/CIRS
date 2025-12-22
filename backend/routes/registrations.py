"""
xIRS Patient Registration Routes

Handles patient registration (掛號) for the medical workflow:
- Create registration from person record
- Generate QR code for Doctor PWA
- Track registration status
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timedelta
import secrets
import hashlib
import hmac
import json
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import get_db, write_db, dict_from_row, rows_to_list
from routes.auth import get_current_user

router = APIRouter()

# HMAC secret for QR code signing (in production, load from config)
REGISTRATION_HMAC_SECRET = os.environ.get('REGISTRATION_HMAC_SECRET', 'xIRS_REG_SECRET_2025')


def init_registrations_table():
    """Initialize the registrations table if it doesn't exist"""
    with write_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS registrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reg_id TEXT UNIQUE NOT NULL,
                person_id TEXT NOT NULL,
                patient_ref TEXT NOT NULL,
                display_name TEXT,
                age_group TEXT,
                gender TEXT,
                triage TEXT,
                priority TEXT DEFAULT 'ROUTINE',
                chief_complaint TEXT,
                status TEXT DEFAULT 'WAITING',
                registered_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                registered_by TEXT,
                called_at DATETIME,
                completed_at DATETIME,
                claimed_by TEXT,
                claimed_at DATETIME,
                notes TEXT,
                FOREIGN KEY (person_id) REFERENCES person(id)
            )
        """)

        # Add claimed_by column if not exists (migration)
        try:
            conn.execute("ALTER TABLE registrations ADD COLUMN claimed_by TEXT")
        except:
            pass  # Column already exists
        try:
            conn.execute("ALTER TABLE registrations ADD COLUMN claimed_at DATETIME")
        except:
            pass  # Column already exists

        # Create index for faster lookups
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_registrations_status
            ON registrations(status)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_registrations_person
            ON registrations(person_id)
        """)


# Initialize table on module load
init_registrations_table()


class RegistrationCreate(BaseModel):
    person_id: str
    priority: str = 'ROUTINE'  # STAT, URGENT, ROUTINE
    chief_complaint: Optional[str] = None
    notes: Optional[str] = None


class RegistrationUpdate(BaseModel):
    status: Optional[str] = None  # WAITING, IN_PROGRESS, COMPLETED, CANCELLED
    notes: Optional[str] = None


def generate_reg_id() -> str:
    """Generate registration ID like REG-20251222-001"""
    today = datetime.now().strftime('%Y%m%d')

    with get_db() as conn:
        cursor = conn.execute(
            "SELECT reg_id FROM registrations WHERE reg_id LIKE ? ORDER BY reg_id DESC LIMIT 1",
            (f"REG-{today}-%",)
        )
        row = cursor.fetchone()

        if row:
            try:
                last_num = int(row['reg_id'].split('-')[-1])
                return f"REG-{today}-{last_num + 1:03d}"
            except (ValueError, IndexError):
                pass

        return f"REG-{today}-001"


def generate_patient_ref(person_id: str) -> str:
    """Generate masked patient reference like ***0042"""
    # Extract numeric part from person_id (e.g., P0042 -> 0042)
    numeric = ''.join(filter(str.isdigit, person_id))
    if len(numeric) >= 4:
        return f"***{numeric[-4:]}"
    return f"***{numeric.zfill(4)}"


def generate_qr_hmac(payload: dict) -> str:
    """Generate HMAC for QR payload verification"""
    # Create signable string (sorted keys, no hmac field)
    signable = {k: v for k, v in sorted(payload.items()) if k != 'hmac'}
    message = json.dumps(signable, separators=(',', ':'), ensure_ascii=False)

    signature = hmac.new(
        REGISTRATION_HMAC_SECRET.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()[:16]  # Shortened for QR code size

    return signature


def build_qr_payload(registration: dict, person: dict) -> dict:
    """Build QR code payload for Doctor PWA"""
    payload = {
        "type": "CIRS_REG",
        "ver": 1,
        "reg_id": registration['reg_id'],
        "patient_ref": registration['patient_ref'],
        "display_name": registration.get('display_name', ''),
        "age_group": person.get('age_group', 'adult'),
        "gender": person.get('gender', 'U'),
        "triage": registration.get('triage', 'GREEN'),
        "chief_complaint": registration.get('chief_complaint', ''),
        "priority": registration.get('priority', 'ROUTINE'),
        "registered_at": registration.get('registered_at', datetime.now().isoformat()),
        "registered_by": registration.get('registered_by', '')
    }

    # Add HMAC signature
    payload['hmac'] = generate_qr_hmac(payload)

    return payload


@router.post("")
async def create_registration(
    request: RegistrationCreate,
    current_user: dict = Depends(get_current_user)
):
    """Create a new patient registration"""

    # Validate priority
    if request.priority not in ['STAT', 'URGENT', 'ROUTINE']:
        raise HTTPException(status_code=400, detail="Invalid priority. Must be STAT, URGENT, or ROUTINE")

    # Get person details
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT id, display_name, triage_status, metadata FROM person WHERE id = ?",
            (request.person_id,)
        )
        person = cursor.fetchone()

        if not person:
            raise HTTPException(status_code=404, detail="Person not found")

        person = dict_from_row(person)

    # Parse metadata for age_group and gender
    metadata = {}
    if person.get('metadata'):
        try:
            metadata = json.loads(person['metadata'])
        except json.JSONDecodeError:
            pass

    # Generate registration ID and patient reference
    reg_id = generate_reg_id()
    patient_ref = generate_patient_ref(request.person_id)

    # Create registration record
    with write_db() as conn:
        conn.execute("""
            INSERT INTO registrations (
                reg_id, person_id, patient_ref, display_name,
                age_group, gender, triage, priority,
                chief_complaint, status, registered_by, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'WAITING', ?, ?)
        """, (
            reg_id,
            request.person_id,
            patient_ref,
            person.get('display_name', ''),
            metadata.get('age_group', 'adult'),
            metadata.get('gender', 'U'),
            person.get('triage_status', 'GREEN'),
            request.priority,
            request.chief_complaint,
            current_user.get('sub', 'admin'),
            request.notes
        ))

    # Build response with QR payload
    registration = {
        'reg_id': reg_id,
        'person_id': request.person_id,
        'patient_ref': patient_ref,
        'display_name': person.get('display_name', ''),
        'triage': person.get('triage_status', 'GREEN'),
        'priority': request.priority,
        'chief_complaint': request.chief_complaint,
        'status': 'WAITING',
        'registered_at': datetime.now().isoformat(),
        'registered_by': current_user.get('sub', 'admin')
    }

    qr_payload = build_qr_payload(registration, {
        'age_group': metadata.get('age_group', 'adult'),
        'gender': metadata.get('gender', 'U')
    })

    return {
        "reg_id": reg_id,
        "patient_ref": patient_ref,
        "display_name": person.get('display_name', ''),
        "triage": person.get('triage_status', 'GREEN'),
        "priority": request.priority,
        "qr_payload": qr_payload
    }


@router.get("")
async def list_registrations(
    status: Optional[str] = None,
    priority: Optional[str] = None,
    today_only: bool = True,
    current_user: dict = Depends(get_current_user)
):
    """List registrations with optional filters"""

    query = "SELECT * FROM registrations WHERE 1=1"
    params = []

    if status:
        query += " AND status = ?"
        params.append(status)

    if priority:
        query += " AND priority = ?"
        params.append(priority)

    if today_only:
        today = datetime.now().strftime('%Y-%m-%d')
        query += " AND DATE(registered_at) = ?"
        params.append(today)

    # Order by priority (STAT first) then by registration time
    query += """
        ORDER BY
            CASE priority
                WHEN 'STAT' THEN 0
                WHEN 'URGENT' THEN 1
                WHEN 'ROUTINE' THEN 2
            END,
            registered_at ASC
    """

    with get_db() as conn:
        cursor = conn.execute(query, params)
        registrations = rows_to_list(cursor.fetchall())

    return {"registrations": registrations}


@router.get("/{reg_id}")
async def get_registration(
    reg_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get a specific registration by ID"""

    with get_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM registrations WHERE reg_id = ?",
            (reg_id,)
        )
        registration = cursor.fetchone()

        if not registration:
            raise HTTPException(status_code=404, detail="Registration not found")

        registration = dict_from_row(registration)

        # Get person details for QR regeneration
        cursor = conn.execute(
            "SELECT metadata FROM person WHERE id = ?",
            (registration['person_id'],)
        )
        person = cursor.fetchone()

        metadata = {}
        if person and person['metadata']:
            try:
                metadata = json.loads(person['metadata'])
            except json.JSONDecodeError:
                pass

    # Build QR payload
    qr_payload = build_qr_payload(registration, {
        'age_group': metadata.get('age_group', 'adult'),
        'gender': metadata.get('gender', 'U')
    })

    registration['qr_payload'] = qr_payload

    return registration


@router.patch("/{reg_id}")
async def update_registration(
    reg_id: str,
    request: RegistrationUpdate,
    current_user: dict = Depends(get_current_user)
):
    """Update registration status"""

    # Validate status if provided
    valid_statuses = ['WAITING', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED']
    if request.status and request.status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
        )

    with get_db() as conn:
        # Check if registration exists
        cursor = conn.execute(
            "SELECT * FROM registrations WHERE reg_id = ?",
            (reg_id,)
        )
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Registration not found")

    # Build update query
    updates = []
    params = []

    if request.status:
        updates.append("status = ?")
        params.append(request.status)

        # Set timestamp based on status
        if request.status == 'IN_PROGRESS':
            updates.append("called_at = CURRENT_TIMESTAMP")
        elif request.status in ['COMPLETED', 'CANCELLED']:
            updates.append("completed_at = CURRENT_TIMESTAMP")

    if request.notes is not None:
        updates.append("notes = ?")
        params.append(request.notes)

    if not updates:
        raise HTTPException(status_code=400, detail="No updates provided")

    params.append(reg_id)

    with write_db() as conn:
        conn.execute(
            f"UPDATE registrations SET {', '.join(updates)} WHERE reg_id = ?",
            params
        )

    # Return updated registration
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM registrations WHERE reg_id = ?",
            (reg_id,)
        )
        registration = dict_from_row(cursor.fetchone())

    return registration


@router.delete("/{reg_id}")
async def cancel_registration(
    reg_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Cancel a registration (soft delete by setting status)"""

    with get_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM registrations WHERE reg_id = ?",
            (reg_id,)
        )
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Registration not found")

    with write_db() as conn:
        conn.execute(
            "UPDATE registrations SET status = 'CANCELLED', completed_at = CURRENT_TIMESTAMP WHERE reg_id = ?",
            (reg_id,)
        )

    return {"message": "Registration cancelled", "reg_id": reg_id}


@router.get("/stats/today")
async def get_today_stats(
    current_user: dict = Depends(get_current_user)
):
    """Get today's registration statistics"""

    today = datetime.now().strftime('%Y-%m-%d')

    with get_db() as conn:
        # Total today
        cursor = conn.execute(
            "SELECT COUNT(*) as count FROM registrations WHERE DATE(registered_at) = ?",
            (today,)
        )
        total = cursor.fetchone()['count']

        # By status
        cursor = conn.execute("""
            SELECT status, COUNT(*) as count
            FROM registrations
            WHERE DATE(registered_at) = ?
            GROUP BY status
        """, (today,))
        by_status = {row['status']: row['count'] for row in cursor.fetchall()}

        # By priority
        cursor = conn.execute("""
            SELECT priority, COUNT(*) as count
            FROM registrations
            WHERE DATE(registered_at) = ?
            GROUP BY priority
        """, (today,))
        by_priority = {row['priority']: row['count'] for row in cursor.fetchall()}

    return {
        "date": today,
        "total": total,
        "by_status": {
            "WAITING": by_status.get('WAITING', 0),
            "IN_PROGRESS": by_status.get('IN_PROGRESS', 0),
            "COMPLETED": by_status.get('COMPLETED', 0),
            "CANCELLED": by_status.get('CANCELLED', 0)
        },
        "by_priority": {
            "STAT": by_priority.get('STAT', 0),
            "URGENT": by_priority.get('URGENT', 0),
            "ROUTINE": by_priority.get('ROUTINE', 0)
        }
    }


# QR Code verification endpoint (for Doctor PWA)
@router.post("/verify-qr")
async def verify_registration_qr(payload: dict):
    """Verify a registration QR code payload (no auth required for Doctor PWA)"""

    if payload.get('type') not in ['CIRS_REG', 'PATIENT_REGISTRATION', 'REGISTRATION']:
        raise HTTPException(status_code=400, detail="Invalid QR type")

    # Verify HMAC
    received_hmac = payload.get('hmac', '')
    expected_hmac = generate_qr_hmac(payload)

    if not hmac.compare_digest(received_hmac, expected_hmac):
        raise HTTPException(status_code=401, detail="Invalid QR signature")

    # Check if registration exists and is valid
    reg_id = payload.get('reg_id')

    with get_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM registrations WHERE reg_id = ?",
            (reg_id,)
        )
        registration = cursor.fetchone()

        if not registration:
            raise HTTPException(status_code=404, detail="Registration not found")

        registration = dict_from_row(registration)

        # Check if already completed
        if registration['status'] == 'COMPLETED':
            return {
                "valid": True,
                "warning": "ALREADY_COMPLETED",
                "message": "此掛號已完成看診",
                "registration": registration
            }

        if registration['status'] == 'CANCELLED':
            return {
                "valid": False,
                "error": "CANCELLED",
                "message": "此掛號已取消"
            }

    return {
        "valid": True,
        "registration": {
            "reg_id": payload['reg_id'],
            "patient_ref": payload['patient_ref'],
            "display_name": payload.get('display_name', ''),
            "age_group": payload.get('age_group', 'adult'),
            "gender": payload.get('gender', 'U'),
            "triage": payload.get('triage', 'GREEN'),
            "chief_complaint": payload.get('chief_complaint', ''),
            "priority": payload.get('priority', 'ROUTINE'),
            "registered_at": payload.get('registered_at', '')
        }
    }


# ============================================================================
# Doctor PWA Endpoints (v1.1)
# ============================================================================

@router.get("/waiting/list")
async def get_waiting_registrations():
    """
    Get all waiting registrations for Doctor PWA.
    No authentication required - simplified for disaster scenarios.
    Returns registrations that are WAITING and not claimed.
    """
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT
                reg_id, patient_ref, display_name, age_group, gender,
                triage, priority, chief_complaint, status,
                registered_at, claimed_by, claimed_at
            FROM registrations
            WHERE status = 'WAITING'
            AND (claimed_by IS NULL OR claimed_by = '')
            ORDER BY
                CASE priority
                    WHEN 'STAT' THEN 0
                    WHEN 'URGENT' THEN 1
                    ELSE 2
                END,
                registered_at ASC
        """)
        registrations = [dict_from_row(row) for row in cursor.fetchall()]

    return {
        "count": len(registrations),
        "registrations": registrations
    }


class ClaimRequest(BaseModel):
    doctor_id: str
    doctor_name: Optional[str] = None


@router.post("/{reg_id}/claim")
async def claim_registration(reg_id: str, request: ClaimRequest):
    """
    Claim a registration for a specific doctor.
    This removes it from other doctors' waiting lists.
    """
    with get_db() as conn:
        # Check if registration exists and is waiting
        cursor = conn.execute(
            "SELECT * FROM registrations WHERE reg_id = ?",
            (reg_id,)
        )
        registration = cursor.fetchone()

        if not registration:
            raise HTTPException(status_code=404, detail="Registration not found")

        registration = dict_from_row(registration)

        # Check if already claimed by another doctor
        if registration.get('claimed_by') and registration['claimed_by'] != request.doctor_id:
            raise HTTPException(
                status_code=409,
                detail=f"Already claimed by {registration['claimed_by']}"
            )

        if registration['status'] not in ['WAITING', 'IN_PROGRESS']:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot claim registration with status: {registration['status']}"
            )

    # Claim the registration
    with write_db() as conn:
        conn.execute("""
            UPDATE registrations
            SET claimed_by = ?,
                claimed_at = CURRENT_TIMESTAMP,
                status = 'IN_PROGRESS',
                called_at = COALESCE(called_at, CURRENT_TIMESTAMP)
            WHERE reg_id = ?
        """, (request.doctor_id, reg_id))

    return {
        "success": True,
        "reg_id": reg_id,
        "claimed_by": request.doctor_id,
        "message": "Registration claimed successfully"
    }


@router.post("/{reg_id}/release")
async def release_registration(reg_id: str, request: ClaimRequest):
    """
    Release a claimed registration back to waiting list.
    """
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT claimed_by, status FROM registrations WHERE reg_id = ?",
            (reg_id,)
        )
        registration = cursor.fetchone()

        if not registration:
            raise HTTPException(status_code=404, detail="Registration not found")

        registration = dict_from_row(registration)

        # Only the claimer can release
        if registration.get('claimed_by') != request.doctor_id:
            raise HTTPException(
                status_code=403,
                detail="Can only release registrations you claimed"
            )

    with write_db() as conn:
        conn.execute("""
            UPDATE registrations
            SET claimed_by = NULL,
                claimed_at = NULL,
                status = 'WAITING'
            WHERE reg_id = ?
        """, (reg_id,))

    return {
        "success": True,
        "reg_id": reg_id,
        "message": "Registration released"
    }


@router.post("/{reg_id}/complete")
async def complete_registration(reg_id: str, request: ClaimRequest):
    """
    Mark a registration as completed after doctor finishes consultation.
    """
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT claimed_by, status FROM registrations WHERE reg_id = ?",
            (reg_id,)
        )
        registration = cursor.fetchone()

        if not registration:
            raise HTTPException(status_code=404, detail="Registration not found")

        registration = dict_from_row(registration)

        # Only the claimer can complete
        if registration.get('claimed_by') and registration['claimed_by'] != request.doctor_id:
            raise HTTPException(
                status_code=403,
                detail="Can only complete registrations you claimed"
            )

    with write_db() as conn:
        conn.execute("""
            UPDATE registrations
            SET status = 'COMPLETED',
                completed_at = CURRENT_TIMESTAMP
            WHERE reg_id = ?
        """, (reg_id,))

    return {
        "success": True,
        "reg_id": reg_id,
        "message": "Registration completed"
    }


@router.get("/doctor/{doctor_id}/patients")
async def get_doctor_patients(doctor_id: str):
    """
    Get all registrations claimed by a specific doctor.
    Returns both in-progress and recently completed.
    """
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT
                reg_id, patient_ref, display_name, age_group, gender,
                triage, priority, chief_complaint, status,
                registered_at, claimed_at, completed_at
            FROM registrations
            WHERE claimed_by = ?
            AND (
                status = 'IN_PROGRESS'
                OR (status = 'COMPLETED' AND DATE(completed_at) = DATE('now'))
            )
            ORDER BY
                CASE status WHEN 'IN_PROGRESS' THEN 0 ELSE 1 END,
                claimed_at DESC
        """, (doctor_id,))
        patients = [dict_from_row(row) for row in cursor.fetchall()]

    return {
        "doctor_id": doctor_id,
        "count": len(patients),
        "patients": patients
    }
