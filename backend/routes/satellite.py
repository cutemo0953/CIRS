"""
CIRS Satellite PWA Routes v1.1
Sync Protocol with Action Envelope Pattern for idempotency
"""
from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime
import json
import os
import sys

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import get_db, write_db, dict_from_row
from routes.auth import decode_token

router = APIRouter()
security = HTTPBearer(auto_error=False)


# ============================================================================
# Pydantic Models
# ============================================================================

class ActionPayload(BaseModel):
    """Generic payload for satellite actions"""
    item_id: Optional[int] = None
    person_id: Optional[str] = None
    quantity: Optional[int] = None
    location: Optional[str] = None
    notes: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None


class SatelliteAction(BaseModel):
    """Single action in the Action Envelope"""
    action_id: str  # UUID - critical for idempotency
    type: str  # 'DISPENSE', 'CHECK_IN', 'CHECK_OUT'
    timestamp: int  # Unix timestamp
    payload: ActionPayload


class SyncRequest(BaseModel):
    """Action Envelope for batch sync"""
    batch_id: str  # UUID for the batch
    actions: List[SatelliteAction]


class SyncResponse(BaseModel):
    """Response from sync endpoint"""
    processed: List[str]  # action_ids that were processed
    failed: List[Dict[str, str]]  # action_ids that failed with reasons
    server_time: int  # Server timestamp for client sync


# ============================================================================
# Helper Functions
# ============================================================================

async def get_satellite_device(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """Dependency to get satellite device info from JWT"""
    if credentials is None:
        raise HTTPException(status_code=401, detail="Token required")

    payload = decode_token(credentials.credentials)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    if payload.get("type") != "satellite_pairing":
        raise HTTPException(status_code=401, detail="Invalid token type")

    return {
        "device_id": payload.get("device_id"),
        "hub_name": payload.get("hub_name", "CIRS Hub")
    }


def is_action_processed(conn, action_id: str) -> bool:
    """Check if an action_id has already been processed"""
    cursor = conn.execute(
        "SELECT action_id FROM action_logs WHERE action_id = ?",
        (action_id,)
    )
    return cursor.fetchone() is not None


def record_action(conn, action_id: str, batch_id: str, action_type: str, device_id: str, payload: dict):
    """Record a processed action in action_logs"""
    conn.execute(
        """INSERT INTO action_logs (action_id, batch_id, action_type, device_id, payload)
           VALUES (?, ?, ?, ?, ?)""",
        (action_id, batch_id, action_type, device_id, json.dumps(payload))
    )


def process_dispense(conn, payload: ActionPayload, device_id: str) -> dict:
    """Process a DISPENSE action"""
    if not payload.item_id or not payload.quantity:
        return {"success": False, "error": "Missing item_id or quantity"}

    # Get current inventory
    cursor = conn.execute(
        "SELECT id, name, quantity FROM inventory WHERE id = ?",
        (payload.item_id,)
    )
    item = cursor.fetchone()

    if item is None:
        return {"success": False, "error": f"Item {payload.item_id} not found"}

    current_qty = item['quantity'] or 0
    if current_qty < payload.quantity:
        return {"success": False, "error": f"Insufficient quantity. Have {current_qty}, need {payload.quantity}"}

    # Update inventory
    new_qty = current_qty - payload.quantity
    conn.execute(
        "UPDATE inventory SET quantity = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (new_qty, payload.item_id)
    )

    # Record in event_log
    conn.execute(
        """INSERT INTO event_log (event_type, item_id, quantity_change, notes, operator_id)
           VALUES ('RESOURCE_OUT', ?, ?, ?, ?)""",
        (payload.item_id, -payload.quantity, f"Satellite dispense: {payload.notes or ''}", device_id)
    )

    return {"success": True, "new_quantity": new_qty}


def process_checkin(conn, payload: ActionPayload, device_id: str) -> dict:
    """Process a CHECK_IN action"""
    if not payload.person_id:
        return {"success": False, "error": "Missing person_id"}

    # Get person
    cursor = conn.execute(
        "SELECT id, display_name, checked_in_at FROM person WHERE id = ?",
        (payload.person_id,)
    )
    person = cursor.fetchone()

    if person is None:
        return {"success": False, "error": f"Person {payload.person_id} not found"}

    # Update check-in status
    conn.execute(
        """UPDATE person SET
           checked_in_at = CURRENT_TIMESTAMP,
           current_location = ?,
           updated_at = CURRENT_TIMESTAMP
           WHERE id = ?""",
        (payload.location or 'registration', payload.person_id)
    )

    # Record in event_log
    conn.execute(
        """INSERT INTO event_log (event_type, person_id, location, notes, operator_id)
           VALUES ('CHECK_IN', ?, ?, ?, ?)""",
        (payload.person_id, payload.location, f"Satellite check-in: {payload.notes or ''}", device_id)
    )

    return {"success": True}


def process_checkout(conn, payload: ActionPayload, device_id: str) -> dict:
    """Process a CHECK_OUT action"""
    if not payload.person_id:
        return {"success": False, "error": "Missing person_id"}

    # Get person
    cursor = conn.execute(
        "SELECT id, display_name, checked_in_at FROM person WHERE id = ?",
        (payload.person_id,)
    )
    person = cursor.fetchone()

    if person is None:
        return {"success": False, "error": f"Person {payload.person_id} not found"}

    # Update check-out status
    conn.execute(
        """UPDATE person SET
           checked_in_at = NULL,
           current_location = NULL,
           updated_at = CURRENT_TIMESTAMP
           WHERE id = ?""",
        (payload.person_id,)
    )

    # Record in event_log
    conn.execute(
        """INSERT INTO event_log (event_type, person_id, notes, operator_id)
           VALUES ('CHECK_OUT', ?, ?, ?)""",
        (payload.person_id, f"Satellite check-out: {payload.notes or ''}", device_id)
    )

    return {"success": True}


# ============================================================================
# Endpoints
# ============================================================================

@router.post("/sync", response_model=SyncResponse)
async def sync_actions(request: SyncRequest, device: dict = Depends(get_satellite_device)):
    """
    Sync batch of actions from Satellite PWA (v1.1: Action Envelope Pattern).

    This endpoint ensures idempotency by checking action_id against action_logs.
    If an action_id has already been processed, it will be skipped (not re-processed)
    but reported as successfully processed.

    Flow:
    1. For each action in the batch:
       - Check if action_id already processed → skip but report success
       - Process the action (DISPENSE, CHECK_IN, CHECK_OUT)
       - Record action_id in action_logs
    2. Return list of processed action_ids so client can clear IndexedDB
    """
    processed = []
    failed = []
    device_id = device.get("device_id", "unknown")

    with write_db() as conn:
        for action in request.actions:
            # Check idempotency
            if is_action_processed(conn, action.action_id):
                # Already processed - report as success (idempotent)
                processed.append(action.action_id)
                continue

            # Process based on action type
            try:
                if action.type == "DISPENSE":
                    result = process_dispense(conn, action.payload, device_id)
                elif action.type == "CHECK_IN":
                    result = process_checkin(conn, action.payload, device_id)
                elif action.type == "CHECK_OUT":
                    result = process_checkout(conn, action.payload, device_id)
                else:
                    result = {"success": False, "error": f"Unknown action type: {action.type}"}

                if result.get("success"):
                    # Record in action_logs
                    record_action(
                        conn,
                        action.action_id,
                        request.batch_id,
                        action.type,
                        device_id,
                        action.payload.model_dump()
                    )
                    processed.append(action.action_id)
                else:
                    failed.append({
                        "action_id": action.action_id,
                        "error": result.get("error", "Unknown error")
                    })

            except Exception as e:
                failed.append({
                    "action_id": action.action_id,
                    "error": str(e)
                })

    return SyncResponse(
        processed=processed,
        failed=failed,
        server_time=int(datetime.utcnow().timestamp())
    )


@router.get("/status")
async def get_hub_status(device: dict = Depends(get_satellite_device)):
    """
    Get Hub status for Satellite PWA.
    Returns simplified status for mobile display.
    """
    with get_db() as conn:
        # Headcount
        cursor = conn.execute("""
            SELECT COUNT(*) as count FROM person
            WHERE role = 'public' AND checked_in_at IS NOT NULL
        """)
        headcount = cursor.fetchone()['count']

        # Low stock alerts
        cursor = conn.execute("""
            SELECT COUNT(*) as count FROM inventory
            WHERE quantity < min_quantity AND min_quantity > 0
        """)
        low_stock = cursor.fetchone()['count']

        # Pending messages
        cursor = conn.execute("""
            SELECT COUNT(*) as count FROM message
            WHERE (is_resolved IS NULL OR is_resolved = 0)
            AND message_type = 'post'
        """)
        pending_messages = cursor.fetchone()['count']

    return {
        "hub_name": device.get("hub_name", "CIRS Hub"),
        "headcount": headcount,
        "alerts": {
            "low_stock": low_stock,
            "pending_messages": pending_messages
        },
        "server_time": int(datetime.utcnow().timestamp())
    }


@router.get("/inventory")
async def get_inventory_summary(device: dict = Depends(get_satellite_device)):
    """
    Get inventory summary for Satellite PWA (read-only).
    """
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT id, name, category, quantity, unit, min_quantity
            FROM inventory
            WHERE category != 'equipment'
            ORDER BY category, name
        """)
        items = [dict_from_row(row) for row in cursor.fetchall()]

    return {
        "items": items,
        "server_time": int(datetime.utcnow().timestamp())
    }


@router.get("/persons")
async def get_checked_in_persons(device: dict = Depends(get_satellite_device)):
    """
    Get list of checked-in persons for Satellite PWA (read-only).
    """
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT id, display_name, triage_status, current_location, checked_in_at
            FROM person
            WHERE role = 'public' AND checked_in_at IS NOT NULL
            ORDER BY display_name
        """)
        persons = [dict_from_row(row) for row in cursor.fetchall()]

    return {
        "persons": persons,
        "total": len(persons),
        "server_time": int(datetime.utcnow().timestamp())
    }


@router.get("/action-logs")
async def get_action_logs(
    limit: int = 50,
    device: dict = Depends(get_satellite_device)
):
    """
    Get recent action logs (for debugging/auditing).
    Only returns actions from the requesting device.
    """
    device_id = device.get("device_id")

    with get_db() as conn:
        cursor = conn.execute("""
            SELECT action_id, batch_id, action_type, processed_at
            FROM action_logs
            WHERE device_id = ?
            ORDER BY processed_at DESC
            LIMIT ?
        """, (device_id, limit))
        logs = [dict_from_row(row) for row in cursor.fetchall()]

    return {
        "device_id": device_id,
        "logs": logs,
        "server_time": int(datetime.utcnow().timestamp())
    }
