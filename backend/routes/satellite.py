"""
CIRS Satellite & Station PWA Routes v2.3
Includes:
- Satellite PWA sync (Action Envelope Pattern)
- Station/Pharmacy pairing (v2.3 secure pairing)
"""
from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
import json
import os
import sys
import hashlib
import secrets
import base64

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import get_db, write_db, dict_from_row
from routes.auth import decode_token, get_current_user

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
        "hub_name": payload.get("hub_name", "CIRS Hub"),
        "allowed_roles": payload.get("allowed_roles", "volunteer")
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


@router.get("/zones")
async def get_zones(device: dict = Depends(get_satellite_device)):
    """
    Get available zones for Satellite PWA (v1.3.1).
    Used for new person registration location selection.
    """
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT id, name, zone_type, capacity, description, icon
            FROM zone
            WHERE is_active = 1
            ORDER BY sort_order, name
        """)
        zones = [dict_from_row(row) for row in cursor.fetchall()]

    # Group by zone_type
    grouped = {}
    for zone in zones:
        zone_type = zone.get('zone_type', 'other')
        if zone_type not in grouped:
            grouped[zone_type] = []
        grouped[zone_type].append(zone)

    return {
        "zones": zones,
        "grouped": grouped,
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


# ============================================================================
# Direct Action Endpoints (v1.3.1) - Simpler than batch sync
# ============================================================================

class CheckinRequest(BaseModel):
    """Direct check-in request from Satellite PWA"""
    person_id: str
    name: Optional[str] = None
    action: str = 'checkin'  # 'register', 'checkin', 'checkout'
    triage_status: Optional[str] = 'green'  # green/yellow/red/black
    zone_id: Optional[str] = None
    zone_name: Optional[str] = None
    card_number: Optional[str] = None
    notes: Optional[str] = None
    is_new: Optional[bool] = False
    # v1.4: Admin-only fields
    national_id: Optional[str] = None  # 身分證字號
    phone: Optional[str] = None  # 電話


class SupplyRequest(BaseModel):
    """Direct supply distribution request from Satellite PWA"""
    person_id: str
    person_name: Optional[str] = None
    item_id: Optional[int] = None
    item: Optional[str] = None
    quantity: int = 1


@router.post("/checkin")
async def direct_checkin(request: CheckinRequest, device: dict = Depends(get_satellite_device)):
    """
    Direct check-in/check-out/register endpoint (v1.3.1).
    Simpler alternative to batch sync for individual operations.
    """
    device_id = device.get("device_id", "unknown")
    action = request.action

    with write_db() as conn:
        if action == 'register':
            # Register new person with triage status and zone
            location = request.zone_name or request.zone_id or ''

            # Generate next person ID (P0001, P0002, ...)
            cursor = conn.execute("SELECT MAX(CAST(SUBSTR(id, 2) AS INTEGER)) FROM person WHERE id LIKE 'P%'")
            max_num = cursor.fetchone()[0] or 0
            new_id = f"P{max_num + 1:04d}"

            # Hash sensitive fields for privacy (v1.4)
            national_id_hash = None
            phone_hash = None
            if request.national_id:
                national_id_hash = hashlib.sha256(request.national_id.upper().encode()).hexdigest()
            if request.phone:
                phone_hash = hashlib.sha256(request.phone.encode()).hexdigest()

            cursor = conn.execute(
                """INSERT INTO person (id, display_name, role, triage_status, current_location, notes,
                   national_id_hash, phone_hash, checked_in_at, created_at, updated_at)
                   VALUES (?, ?, 'public', ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
                (new_id, request.name or request.person_id, request.triage_status, location, request.notes,
                 national_id_hash, phone_hash)
            )

            # Record in event_log
            conn.execute(
                """INSERT INTO event_log (event_type, person_id, location, notes, operator_id)
                   VALUES ('REGISTER', ?, ?, ?, ?)""",
                (new_id, location, f"Satellite registration: {request.name} ({request.triage_status})", device_id)
            )

            # Triage status labels for response
            triage_labels = {'green': '輕傷', 'yellow': '延遲', 'red': '立即', 'black': '死亡'}
            triage_label = triage_labels.get(request.triage_status, request.triage_status)

            return {
                "success": True,
                "action": "register",
                "person_id": new_id,
                "name": request.name,
                "triage_status": request.triage_status,
                "location": location,
                "message": f"已登記：{request.name}（{triage_label}）編號 {new_id}"
            }

        elif action == 'checkin':
            # Check in existing person (try to find by ID or name)
            cursor = conn.execute(
                """SELECT id, display_name FROM person
                   WHERE id = ? OR display_name LIKE ? OR card_number = ?""",
                (request.person_id, f"%{request.name or request.person_id}%", request.person_id)
            )
            person = cursor.fetchone()

            if person is None:
                # Auto-register if not found
                cursor = conn.execute(
                    """INSERT INTO person (display_name, role, checked_in_at, created_at, updated_at)
                       VALUES (?, 'public', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
                    (request.name or request.person_id,)
                )
                person_id = cursor.lastrowid
                person_name = request.name or request.person_id
            else:
                person_id = person['id']
                person_name = person['display_name']

                # Update check-in status
                conn.execute(
                    """UPDATE person SET checked_in_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                       WHERE id = ?""",
                    (person_id,)
                )

            # Record in event_log
            conn.execute(
                """INSERT INTO event_log (event_type, person_id, notes, operator_id)
                   VALUES ('CHECK_IN', ?, ?, ?)""",
                (person_id, f"Satellite check-in", device_id)
            )

            return {
                "success": True,
                "action": "checkin",
                "person_id": person_id,
                "name": person_name,
                "message": f"{person_name} 報到成功"
            }

        elif action == 'checkout':
            # Check out
            cursor = conn.execute(
                """SELECT id, display_name FROM person
                   WHERE id = ? OR display_name LIKE ? OR card_number = ?""",
                (request.person_id, f"%{request.name or request.person_id}%", request.person_id)
            )
            person = cursor.fetchone()

            if person is None:
                return {
                    "success": False,
                    "action": "checkout",
                    "message": f"找不到人員：{request.person_id}"
                }

            person_id = person['id']
            person_name = person['display_name']

            # Update check-out status
            conn.execute(
                """UPDATE person SET checked_in_at = NULL, current_location = NULL, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (person_id,)
            )

            # Record in event_log
            conn.execute(
                """INSERT INTO event_log (event_type, person_id, notes, operator_id)
                   VALUES ('CHECK_OUT', ?, ?, ?)""",
                (person_id, f"Satellite check-out", device_id)
            )

            return {
                "success": True,
                "action": "checkout",
                "person_id": person_id,
                "name": person_name,
                "message": f"{person_name} 退場成功"
            }

    return {"success": False, "message": "Unknown action"}


@router.post("/supply")
async def direct_supply(request: SupplyRequest, device: dict = Depends(get_satellite_device)):
    """
    Direct supply distribution endpoint (v1.3.1).
    Simpler alternative to batch sync for individual operations.
    """
    device_id = device.get("device_id", "unknown")

    with write_db() as conn:
        # Find item
        item = None
        if request.item_id:
            cursor = conn.execute(
                "SELECT id, name, quantity FROM inventory WHERE id = ?",
                (request.item_id,)
            )
            item = cursor.fetchone()

        if item is None and request.item:
            # Try to find by name
            cursor = conn.execute(
                "SELECT id, name, quantity FROM inventory WHERE name LIKE ?",
                (f"%{request.item}%",)
            )
            item = cursor.fetchone()

        if item is None:
            return {
                "success": False,
                "message": f"找不到物資：{request.item or request.item_id}"
            }

        # Check quantity
        current_qty = item['quantity'] or 0
        if current_qty < request.quantity:
            return {
                "success": False,
                "message": f"庫存不足：{item['name']} 只剩 {current_qty}"
            }

        # Update inventory
        new_qty = current_qty - request.quantity
        conn.execute(
            "UPDATE inventory SET quantity = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (new_qty, item['id'])
        )

        # Record in event_log
        conn.execute(
            """INSERT INTO event_log (event_type, item_id, quantity_change, notes, operator_id)
               VALUES ('RESOURCE_OUT', ?, ?, ?, ?)""",
            (item['id'], -request.quantity, f"Satellite dispense to {request.person_name or request.person_id}", device_id)
        )

    return {
        "success": True,
        "item_id": item['id'],
        "item_name": item['name'],
        "quantity": request.quantity,
        "remaining": new_qty,
        "message": f"已發放 {item['name']} x{request.quantity} 給 {request.person_name or request.person_id}"
    }


# ============================================================================
# Stocktake Endpoint (v1.4) - Inventory Adjustment from Satellite PWA
# ============================================================================

class StocktakeRequest(BaseModel):
    """Inventory adjustment request from Satellite PWA"""
    item_id: int
    new_quantity: int
    reason: Optional[str] = None


@router.post("/stocktake")
async def stocktake_adjustment(request: StocktakeRequest, device: dict = Depends(get_satellite_device)):
    """
    Adjust inventory quantity (stocktake/盤點) from Satellite PWA (v1.4).
    Only available for admin role.
    """
    device_id = device.get("device_id", "unknown")

    # Check if device has admin role
    allowed_roles = device.get("allowed_roles", "volunteer")
    if "admin" not in allowed_roles:
        return {
            "success": False,
            "message": "權限不足：只有管理員可以調整庫存"
        }

    with write_db() as conn:
        # Get current item
        cursor = conn.execute(
            "SELECT id, name, quantity FROM inventory WHERE id = ?",
            (request.item_id,)
        )
        item = cursor.fetchone()

        if item is None:
            return {
                "success": False,
                "message": f"找不到物資 ID: {request.item_id}"
            }

        old_qty = item['quantity'] or 0
        new_qty = request.new_quantity
        diff = new_qty - old_qty

        # Update inventory
        conn.execute(
            "UPDATE inventory SET quantity = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (new_qty, request.item_id)
        )

        # Record in event_log
        event_type = 'STOCKTAKE_ADJUST' if diff != 0 else 'STOCKTAKE_VERIFY'
        reason = request.reason or '盤點調整'
        conn.execute(
            """INSERT INTO event_log (event_type, item_id, quantity_change, notes, operator_id)
               VALUES (?, ?, ?, ?, ?)""",
            (event_type, request.item_id, diff, f"Satellite 盤點: {reason}", device_id)
        )

    diff_str = f"+{diff}" if diff > 0 else str(diff)
    return {
        "success": True,
        "item_id": item['id'],
        "item_name": item['name'],
        "old_quantity": old_qty,
        "new_quantity": new_qty,
        "difference": diff,
        "message": f"{item['name']}: {old_qty} → {new_qty} ({diff_str})"
    }


# ============================================================================
# Station/Pharmacy Pairing API (v2.3)
# ============================================================================

# In-memory pairing codes storage (in production, use Redis or DB with TTL)
_pairing_codes: Dict[str, dict] = {}


class StationPairRequest(BaseModel):
    """Station pairing request"""
    pairing_code: str
    device_info: Optional[Dict[str, Any]] = None


class StationPairResponse(BaseModel):
    """Station pairing response"""
    station_id: str
    station_type: str  # SUPPLY or PHARMACY
    display_name: str
    config: Dict[str, str]
    prescriber_certs: Optional[List[dict]] = None


def generate_pairing_code() -> str:
    """Generate a 6-character alphanumeric pairing code"""
    chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'  # Exclude ambiguous chars
    return ''.join(secrets.choice(chars) for _ in range(6))


def generate_station_secret() -> str:
    """Generate a 32-byte station secret (Base64 encoded)"""
    return base64.b64encode(secrets.token_bytes(32)).decode('utf-8')


@router.post("/stations/pair", response_model=StationPairResponse)
async def pair_station(request: StationPairRequest):
    """
    Complete station pairing (v2.3 Secure Pairing Protocol).

    The pairing code was generated by the Hub admin and is valid for 10 minutes.
    On successful pairing:
    - Returns station configuration (secrets, keys)
    - For PHARMACY type, also returns prescriber certificates
    """
    code = request.pairing_code.upper().strip()

    # Check if pairing code exists and is valid
    if code not in _pairing_codes:
        raise HTTPException(
            status_code=401,
            detail="INVALID_OR_EXPIRED_CODE"
        )

    pairing_info = _pairing_codes[code]

    # Check expiration
    if datetime.utcnow() > pairing_info['expires_at']:
        del _pairing_codes[code]
        raise HTTPException(
            status_code=401,
            detail="INVALID_OR_EXPIRED_CODE"
        )

    # Generate station credentials
    station_secret = generate_station_secret()

    # Get Hub keys from config (in production, these would be stored securely)
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT key, value FROM config WHERE key IN ('hub_public_key', 'hub_encryption_key')"
        )
        config_rows = {row['key']: row['value'] for row in cursor.fetchall()}

    hub_public_key = config_rows.get('hub_public_key', '')
    hub_encryption_key = config_rows.get('hub_encryption_key', '')

    # If keys don't exist in config, generate placeholder (for demo)
    if not hub_public_key:
        hub_public_key = base64.b64encode(secrets.token_bytes(32)).decode('utf-8')
    if not hub_encryption_key:
        hub_encryption_key = base64.b64encode(secrets.token_bytes(32)).decode('utf-8')

    # Get prescriber certs for PHARMACY type
    prescriber_certs = []
    if pairing_info['station_type'] == 'PHARMACY':
        with get_db() as conn:
            cursor = conn.execute("""
                SELECT id, name, public_key, issued_at, expires_at
                FROM prescriber_certs
                WHERE revoked = 0 AND expires_at > CURRENT_TIMESTAMP
            """)
            for row in cursor.fetchall():
                prescriber_certs.append(dict_from_row(row))

    # Record the pairing in database
    with write_db() as conn:
        # Check if stations table exists, create if not
        conn.execute("""
            CREATE TABLE IF NOT EXISTS stations (
                id TEXT PRIMARY KEY,
                station_type TEXT NOT NULL,
                display_name TEXT,
                secret_hash TEXT NOT NULL,
                device_info TEXT,
                paired_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_seen_at TEXT,
                is_active INTEGER DEFAULT 1
            )
        """)

        # Insert station record
        secret_hash = hashlib.sha256(station_secret.encode()).hexdigest()
        conn.execute("""
            INSERT OR REPLACE INTO stations (id, station_type, display_name, secret_hash, device_info)
            VALUES (?, ?, ?, ?, ?)
        """, (
            pairing_info['station_id'],
            pairing_info['station_type'],
            pairing_info['display_name'],
            secret_hash,
            json.dumps(request.device_info) if request.device_info else None
        ))

    # Remove used pairing code
    del _pairing_codes[code]

    return StationPairResponse(
        station_id=pairing_info['station_id'],
        station_type=pairing_info['station_type'],
        display_name=pairing_info['display_name'],
        config={
            "station_secret": station_secret,
            "hub_public_key": hub_public_key,
            "hub_encryption_key": hub_encryption_key
        },
        prescriber_certs=prescriber_certs if pairing_info['station_type'] == 'PHARMACY' else None
    )


class GenerateStationPairingRequest(BaseModel):
    """Request body for generating station pairing code"""
    station_id: str
    station_type: str = "SUPPLY"
    display_name: Optional[str] = None


@router.post("/stations/generate-pairing")
async def generate_station_pairing(
    request: GenerateStationPairingRequest,
    user: dict = Depends(get_current_user)
):
    """
    Generate a pairing code for a new station (Admin only).

    Returns a QR code payload and the pairing code.
    Code is valid for 10 minutes.
    """
    # Require admin role
    if user is None or user.get('role') != 'admin':
        raise HTTPException(status_code=403, detail="Admin access required")

    # Validate station type
    if request.station_type not in ["SUPPLY", "PHARMACY"]:
        raise HTTPException(status_code=400, detail="Invalid station_type. Must be SUPPLY or PHARMACY.")

    # Generate pairing code
    code = generate_pairing_code()
    expires_at = datetime.utcnow() + timedelta(minutes=10)

    # Store pairing info
    _pairing_codes[code] = {
        'station_id': request.station_id,
        'station_type': request.station_type,
        'display_name': request.display_name or request.station_id,
        'expires_at': expires_at,
        'created_by': user.get('id', 'admin')
    }

    # Generate QR payload
    qr_payload = {
        "type": "STATION_PAIR_INVITE",
        "ver": 1,
        "hub_url": "http://localhost:8090",  # Should be dynamic in production
        "pairing_code": code,
        "station_id": request.station_id,
        "station_type": request.station_type
    }

    return {
        "pairing_code": code,
        "expires_at": expires_at.isoformat(),
        "qr_payload": qr_payload,
        "message": f"配對碼 {code} 已產生，有效期限 10 分鐘"
    }


@router.get("/stations")
async def list_stations(user: dict = Depends(get_current_user)):
    """
    List all paired stations (Admin only).
    """
    # Require admin role
    if user is None or user.get('role') != 'admin':
        raise HTTPException(status_code=403, detail="Admin access required")

    with get_db() as conn:
        # Check if stations table exists
        cursor = conn.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='stations'
        """)
        if cursor.fetchone() is None:
            return {"stations": []}

        cursor = conn.execute("""
            SELECT id, station_type, display_name, paired_at, last_seen_at, is_active
            FROM stations
            ORDER BY paired_at DESC
        """)
        stations = [dict_from_row(row) for row in cursor.fetchall()]

    return {
        "stations": stations,
        "total": len(stations)
    }
