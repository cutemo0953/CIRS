"""
CIRS Person Routes
"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
import secrets
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import get_db, write_db, dict_from_row, rows_to_list
from routes.auth import hash_pin

router = APIRouter()


def generate_id():
    """Generate an 8-character random ID"""
    return secrets.token_hex(4)


class PersonCreate(BaseModel):
    display_name: str
    phone_hash: Optional[str] = None
    role: str = "public"
    pin: Optional[str] = None
    metadata: Optional[str] = None
    current_location: Optional[str] = None
    triage_status: Optional[str] = None  # 'GREEN', 'YELLOW', 'RED', 'BLACK'


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

    return {"persons": persons, "count": len(persons)}


@router.get("/{person_id}")
async def get_person(person_id: str):
    """Get a single person"""
    with get_db() as conn:
        cursor = conn.execute("SELECT * FROM person WHERE id = ?", (person_id,))
        person = dict_from_row(cursor.fetchone())

    if person is None:
        raise HTTPException(status_code=404, detail="Person not found")

    person.pop('pin_hash', None)
    return person


@router.post("")
async def create_person(person: PersonCreate):
    """Create a new person (register/check-in)"""
    new_id = generate_id()
    pin_hash = hash_pin(person.pin) if person.pin else None

    # Validate triage status if provided
    if person.triage_status and person.triage_status not in ['GREEN', 'YELLOW', 'RED', 'BLACK']:
        raise HTTPException(status_code=400, detail="Invalid triage status")

    with write_db() as conn:
        try:
            conn.execute(
                """
                INSERT INTO person (id, display_name, phone_hash, role, pin_hash, metadata, current_location, triage_status, checked_in_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (new_id, person.display_name, person.phone_hash, person.role,
                 pin_hash, person.metadata, person.current_location, person.triage_status)
            )

            # Log check-in event
            conn.execute(
                """
                INSERT INTO event_log (event_type, person_id, location, status_value, notes)
                VALUES ('CHECK_IN', ?, ?, ?, ?)
                """,
                (new_id, person.current_location, person.triage_status, f"Registered: {person.display_name}")
            )

            # Log triage event if status provided
            if person.triage_status:
                conn.execute(
                    """
                    INSERT INTO event_log (event_type, person_id, status_value, notes)
                    VALUES ('TRIAGE', ?, ?, ?)
                    """,
                    (new_id, person.triage_status, "Initial triage on check-in")
                )
        except Exception as e:
            if "UNIQUE constraint" in str(e):
                raise HTTPException(status_code=400, detail="Phone number already registered")
            raise

    return {"id": new_id, "message": "Person registered successfully"}


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
