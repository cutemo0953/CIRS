"""
CIRS Zone Management Routes
區域管理 API
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import get_db, write_db, dict_from_row, rows_to_list

router = APIRouter()


# ============================================
# Models
# ============================================

class ZoneCreate(BaseModel):
    id: str
    name: str
    zone_type: str  # 'shelter', 'medical', 'service', 'restricted'
    capacity: int = 0
    description: Optional[str] = None
    icon: Optional[str] = None
    sort_order: int = 0


class ZoneUpdate(BaseModel):
    name: Optional[str] = None
    zone_type: Optional[str] = None
    capacity: Optional[int] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class BatchMoveRequest(BaseModel):
    person_ids: List[str]
    target_zone_id: str
    operator_id: str
    notes: Optional[str] = None


# ============================================
# Zone CRUD API
# ============================================

@router.get("")
async def list_zones(
    zone_type: Optional[str] = None,
    active_only: bool = True
):
    """List all zones with optional filtering"""
    with get_db() as conn:
        query = "SELECT z.*, (SELECT COUNT(*) FROM person WHERE current_location = z.id) as current_count FROM zone z WHERE 1=1"
        params = []

        if zone_type:
            query += " AND z.zone_type = ?"
            params.append(zone_type)

        if active_only:
            query += " AND z.is_active = 1"

        query += " ORDER BY z.sort_order, z.name"

        cursor = conn.execute(query, params)
        zones = rows_to_list(cursor.fetchall())

    return {"zones": zones, "count": len(zones)}


@router.get("/types")
async def get_zone_types():
    """Get available zone types with labels (icon = heroicon name)"""
    return {
        "types": [
            {"id": "shelter", "name": "收容區域", "icon": "home", "description": "一般收容民眾使用"},
            {"id": "medical", "name": "醫療區域", "icon": "heart", "description": "醫療及檢傷相關"},
            {"id": "service", "name": "服務區域", "icon": "clipboard-document-list", "description": "報到、發放等服務"},
            {"id": "restricted", "name": "管制區域", "icon": "lock-closed", "description": "僅限工作人員進入"}
        ]
    }


@router.get("/stats")
async def get_zone_stats():
    """Get statistics for all zones"""
    with get_db() as conn:
        # Zone occupancy
        cursor = conn.execute("""
            SELECT
                z.id, z.name, z.zone_type, z.capacity, z.icon,
                COUNT(p.id) as current_count,
                CASE
                    WHEN z.capacity > 0 THEN ROUND(COUNT(p.id) * 100.0 / z.capacity, 1)
                    ELSE 0
                END as occupancy_rate
            FROM zone z
            LEFT JOIN person p ON p.current_location = z.id AND p.role = 'public'
            WHERE z.is_active = 1
            GROUP BY z.id
            ORDER BY z.sort_order
        """)
        zones = rows_to_list(cursor.fetchall())

        # Summary by type
        cursor = conn.execute("""
            SELECT
                z.zone_type,
                COUNT(DISTINCT z.id) as zone_count,
                SUM(z.capacity) as total_capacity,
                COUNT(p.id) as total_people
            FROM zone z
            LEFT JOIN person p ON p.current_location = z.id AND p.role = 'public'
            WHERE z.is_active = 1
            GROUP BY z.zone_type
        """)
        summary = rows_to_list(cursor.fetchall())

    return {
        "zones": zones,
        "summary": summary
    }


@router.get("/{zone_id}")
async def get_zone(zone_id: str):
    """Get a single zone with current occupants"""
    with get_db() as conn:
        cursor = conn.execute("SELECT * FROM zone WHERE id = ?", (zone_id,))
        zone = dict_from_row(cursor.fetchone())

        if zone is None:
            raise HTTPException(status_code=404, detail="Zone not found")

        # Get current occupants
        cursor = conn.execute("""
            SELECT id, display_name, triage_status, checked_in_at
            FROM person
            WHERE current_location = ? AND role = 'public'
            ORDER BY checked_in_at DESC
        """, (zone_id,))
        occupants = rows_to_list(cursor.fetchall())

        zone["occupants"] = occupants
        zone["current_count"] = len(occupants)

    return zone


@router.post("")
async def create_zone(zone: ZoneCreate):
    """Create a new zone (Admin only)"""
    with write_db() as conn:
        # Check if ID already exists
        cursor = conn.execute("SELECT id FROM zone WHERE id = ?", (zone.id,))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail="Zone ID already exists")

        conn.execute(
            """
            INSERT INTO zone (id, name, zone_type, capacity, description, icon, sort_order)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (zone.id, zone.name, zone.zone_type, zone.capacity,
             zone.description, zone.icon, zone.sort_order)
        )

    return {"id": zone.id, "message": "Zone created successfully"}


@router.put("/{zone_id}")
async def update_zone(zone_id: str, zone: ZoneUpdate):
    """Update a zone (Admin only)"""
    with write_db() as conn:
        cursor = conn.execute("SELECT * FROM zone WHERE id = ?", (zone_id,))
        existing = cursor.fetchone()
        if existing is None:
            raise HTTPException(status_code=404, detail="Zone not found")

        updates = []
        params = []

        if zone.name is not None:
            updates.append("name = ?")
            params.append(zone.name)
        if zone.zone_type is not None:
            updates.append("zone_type = ?")
            params.append(zone.zone_type)
        if zone.capacity is not None:
            updates.append("capacity = ?")
            params.append(zone.capacity)
        if zone.description is not None:
            updates.append("description = ?")
            params.append(zone.description)
        if zone.icon is not None:
            updates.append("icon = ?")
            params.append(zone.icon)
        if zone.sort_order is not None:
            updates.append("sort_order = ?")
            params.append(zone.sort_order)
        if zone.is_active is not None:
            updates.append("is_active = ?")
            params.append(1 if zone.is_active else 0)

        if updates:
            updates.append("updated_at = CURRENT_TIMESTAMP")
            params.append(zone_id)
            conn.execute(
                f"UPDATE zone SET {', '.join(updates)} WHERE id = ?",
                params
            )

    return {"message": "Zone updated successfully"}


@router.delete("/{zone_id}")
async def delete_zone(zone_id: str):
    """Delete a zone (Admin only) - only if empty"""
    with write_db() as conn:
        # Check if zone exists
        cursor = conn.execute("SELECT * FROM zone WHERE id = ?", (zone_id,))
        if cursor.fetchone() is None:
            raise HTTPException(status_code=404, detail="Zone not found")

        # Check if zone has occupants
        cursor = conn.execute(
            "SELECT COUNT(*) as count FROM person WHERE current_location = ?",
            (zone_id,)
        )
        if cursor.fetchone()['count'] > 0:
            raise HTTPException(
                status_code=400,
                detail="Cannot delete zone with occupants. Move people first."
            )

        conn.execute("DELETE FROM zone WHERE id = ?", (zone_id,))

    return {"message": "Zone deleted successfully"}


# ============================================
# Person Movement API
# ============================================

@router.post("/move")
async def batch_move_people(request: BatchMoveRequest):
    """Move multiple people to a target zone"""
    with write_db() as conn:
        # Verify target zone exists and is active
        cursor = conn.execute(
            "SELECT * FROM zone WHERE id = ? AND is_active = 1",
            (request.target_zone_id,)
        )
        target_zone = cursor.fetchone()
        if target_zone is None:
            raise HTTPException(status_code=404, detail="Target zone not found or inactive")

        # Check capacity
        if target_zone['capacity'] > 0:
            cursor = conn.execute(
                "SELECT COUNT(*) as count FROM person WHERE current_location = ?",
                (request.target_zone_id,)
            )
            current_count = cursor.fetchone()['count']
            if current_count + len(request.person_ids) > target_zone['capacity']:
                raise HTTPException(
                    status_code=400,
                    detail=f"Zone capacity exceeded. Current: {current_count}, Capacity: {target_zone['capacity']}"
                )

        moved = []
        failed = []

        for person_id in request.person_ids:
            # Get person's current location
            cursor = conn.execute(
                "SELECT id, display_name, current_location FROM person WHERE id = ?",
                (person_id,)
            )
            person = cursor.fetchone()

            if person is None:
                failed.append({"id": person_id, "reason": "Person not found"})
                continue

            from_location = person['current_location']

            # Update location
            conn.execute(
                "UPDATE person SET current_location = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (request.target_zone_id, person_id)
            )

            # Log the movement event
            conn.execute(
                """
                INSERT INTO event_log (event_type, person_id, operator_id, location, status_value, notes)
                VALUES ('LOCATION_CHANGE', ?, ?, ?, ?, ?)
                """,
                (person_id, request.operator_id, request.target_zone_id,
                 f"{from_location} → {request.target_zone_id}",
                 request.notes or f"移動至 {target_zone['name']}")
            )

            moved.append({
                "id": person_id,
                "name": person['display_name'],
                "from": from_location,
                "to": request.target_zone_id
            })

    return {
        "message": f"Moved {len(moved)} people to {target_zone['name']}",
        "moved": moved,
        "failed": failed,
        "target_zone": dict(target_zone)
    }


@router.get("/{zone_id}/history")
async def get_zone_movement_history(zone_id: str, limit: int = 50):
    """Get movement history for a zone"""
    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT
                e.id, e.event_type, e.person_id, e.operator_id,
                e.location, e.status_value, e.notes, e.timestamp,
                p.display_name as person_name,
                op.display_name as operator_name
            FROM event_log e
            LEFT JOIN person p ON e.person_id = p.id
            LEFT JOIN person op ON e.operator_id = op.id
            WHERE e.event_type = 'LOCATION_CHANGE'
            AND (e.location = ? OR e.status_value LIKE ?)
            ORDER BY e.timestamp DESC
            LIMIT ?
            """,
            (zone_id, f"%{zone_id}%", limit)
        )
        history = rows_to_list(cursor.fetchall())

    return {"history": history, "count": len(history)}
