"""
CIRS Inventory Routes
"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import os
import sys
import json

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import get_db, write_db, dict_from_row, rows_to_list

router = APIRouter()

# Load bundles configuration
BUNDLES_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "bundles.json")

def load_bundles():
    """Load bundles from JSON file"""
    if os.path.exists(BUNDLES_PATH):
        with open(BUNDLES_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"bundles": []}

def save_bundles(data):
    """Save bundles to JSON file"""
    os.makedirs(os.path.dirname(BUNDLES_PATH), exist_ok=True)
    with open(BUNDLES_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


class InventoryCreate(BaseModel):
    name: str
    specification: Optional[str] = None
    category: str
    quantity: float = 0
    unit: Optional[str] = None
    location: Optional[str] = None
    expiry_date: Optional[str] = None
    min_quantity: float = 0
    tags: Optional[str] = None
    notes: Optional[str] = None
    # Equipment fields
    check_interval_days: Optional[int] = None
    check_status: Optional[str] = None


class InventoryUpdate(BaseModel):
    name: Optional[str] = None
    specification: Optional[str] = None
    category: Optional[str] = None
    quantity: Optional[float] = None
    unit: Optional[str] = None
    location: Optional[str] = None
    expiry_date: Optional[str] = None
    min_quantity: Optional[float] = None
    tags: Optional[str] = None
    notes: Optional[str] = None
    # Equipment fields
    last_check_date: Optional[str] = None
    check_interval_days: Optional[int] = None
    check_status: Optional[str] = None


class DistributeRequest(BaseModel):
    person_id: str
    quantity: float
    notes: Optional[str] = None


@router.get("")
async def list_inventory(
    category: Optional[str] = Query(None, description="Filter by category"),
    below_min: bool = Query(False, description="Show only items below min_quantity")
):
    """List all inventory items"""
    with get_db() as conn:
        query = "SELECT * FROM inventory WHERE 1=1"
        params = []

        if category:
            query += " AND category = ?"
            params.append(category)

        if below_min:
            query += " AND quantity < min_quantity AND min_quantity > 0"

        query += " ORDER BY category, name"

        cursor = conn.execute(query, params)
        items = rows_to_list(cursor.fetchall())

    return {"items": items, "count": len(items)}


# ============================================
# Bundles (組套) API - MUST be before /{item_id} to avoid route conflict
# ============================================

# Bundle Item model
class BundleItem(BaseModel):
    name: str
    specification: Optional[str] = None
    category: str
    quantity: float
    unit: Optional[str] = None


class BundleCreate(BaseModel):
    name: str
    description: Optional[str] = None
    icon: Optional[str] = "📦"
    items: List[BundleItem]


class BundleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    items: Optional[List[BundleItem]] = None


class BundleIntakeRequest(BaseModel):
    bundle_id: str
    multiplier: int = 1  # How many sets of the bundle to add
    location: Optional[str] = None
    notes: Optional[str] = None
    selected_indices: Optional[List[int]] = None  # 勾選的項目索引，None 表示全選


@router.get("/bundles")
async def list_bundles():
    """List all available bundles (組套)"""
    bundles_data = load_bundles()
    return {"bundles": bundles_data.get("bundles", [])}


@router.post("/bundles")
async def create_bundle(bundle: BundleCreate):
    """Create a new bundle (Admin only)"""
    bundles_data = load_bundles()

    # Generate unique ID from name
    import re
    base_id = re.sub(r'[^a-z0-9]', '_', bundle.name.lower())
    bundle_id = base_id

    # Ensure unique ID
    existing_ids = {b["id"] for b in bundles_data.get("bundles", [])}
    counter = 1
    while bundle_id in existing_ids:
        bundle_id = f"{base_id}_{counter}"
        counter += 1

    new_bundle = {
        "id": bundle_id,
        "name": bundle.name,
        "description": bundle.description or "",
        "icon": bundle.icon or "📦",
        "items": [item.model_dump() for item in bundle.items]
    }

    bundles_data["bundles"].append(new_bundle)
    save_bundles(bundles_data)

    return {"id": bundle_id, "message": "Bundle created successfully", "bundle": new_bundle}


@router.post("/bundles/intake")
async def intake_bundle(request: BundleIntakeRequest):
    """Add all items from a bundle to inventory (組套入庫)"""
    bundles_data = load_bundles()

    # Find the bundle
    bundle = None
    for b in bundles_data.get("bundles", []):
        if b["id"] == request.bundle_id:
            bundle = b
            break

    if bundle is None:
        raise HTTPException(status_code=404, detail="Bundle not found")

    created_items = []
    updated_items = []

    # 過濾要入庫的項目（如果有指定 selected_indices）
    all_items = bundle["items"]
    if request.selected_indices is not None:
        items_to_intake = [all_items[i] for i in request.selected_indices if i < len(all_items)]
    else:
        items_to_intake = all_items

    with write_db() as conn:
        for item in items_to_intake:
            quantity = item["quantity"] * request.multiplier

            # Check if similar item exists (same name and specification)
            cursor = conn.execute(
                """
                SELECT id, name, quantity FROM inventory
                WHERE name = ? AND (specification = ? OR (specification IS NULL AND ? IS NULL))
                """,
                (item["name"], item.get("specification"), item.get("specification"))
            )
            existing = cursor.fetchone()

            if existing:
                # Update existing item quantity
                new_quantity = existing['quantity'] + quantity
                conn.execute(
                    "UPDATE inventory SET quantity = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (new_quantity, existing['id'])
                )
                # Log event
                conn.execute(
                    """
                    INSERT INTO event_log (event_type, item_id, quantity_change, notes)
                    VALUES ('RESOURCE_IN', ?, ?, ?)
                    """,
                    (existing['id'], quantity, f"組套入庫: {bundle['name']}")
                )
                updated_items.append({
                    "id": existing['id'],
                    "name": item["name"],
                    "added": quantity,
                    "new_quantity": new_quantity
                })
            else:
                # Create new item
                cursor = conn.execute(
                    """
                    INSERT INTO inventory (name, specification, category, quantity, unit, location)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (item["name"], item.get("specification"), item["category"],
                     quantity, item.get("unit"), request.location)
                )
                new_id = cursor.lastrowid
                # Log event
                conn.execute(
                    """
                    INSERT INTO event_log (event_type, item_id, quantity_change, notes)
                    VALUES ('RESOURCE_IN', ?, ?, ?)
                    """,
                    (new_id, quantity, f"組套入庫: {bundle['name']} - 新增 {item['name']}")
                )
                created_items.append({
                    "id": new_id,
                    "name": item["name"],
                    "quantity": quantity
                })

    return {
        "message": f"Bundle '{bundle['name']}' added successfully",
        "bundle": bundle["name"],
        "multiplier": request.multiplier,
        "created": created_items,
        "updated": updated_items,
        "total_items": len(created_items) + len(updated_items)
    }


@router.get("/bundles/{bundle_id}")
async def get_bundle(bundle_id: str):
    """Get a specific bundle by ID"""
    bundles_data = load_bundles()
    for bundle in bundles_data.get("bundles", []):
        if bundle["id"] == bundle_id:
            return bundle
    raise HTTPException(status_code=404, detail="Bundle not found")


@router.put("/bundles/{bundle_id}")
async def update_bundle(bundle_id: str, bundle: BundleUpdate):
    """Update an existing bundle (Admin only)"""
    bundles_data = load_bundles()

    # Find bundle
    bundle_index = None
    for i, b in enumerate(bundles_data.get("bundles", [])):
        if b["id"] == bundle_id:
            bundle_index = i
            break

    if bundle_index is None:
        raise HTTPException(status_code=404, detail="Bundle not found")

    # Update fields
    existing = bundles_data["bundles"][bundle_index]
    if bundle.name is not None:
        existing["name"] = bundle.name
    if bundle.description is not None:
        existing["description"] = bundle.description
    if bundle.icon is not None:
        existing["icon"] = bundle.icon
    if bundle.items is not None:
        existing["items"] = [item.model_dump() for item in bundle.items]

    save_bundles(bundles_data)

    return {"message": "Bundle updated successfully", "bundle": existing}


@router.delete("/bundles/{bundle_id}")
async def delete_bundle(bundle_id: str):
    """Delete a bundle (Admin only)"""
    bundles_data = load_bundles()

    # Find and remove bundle
    original_len = len(bundles_data.get("bundles", []))
    bundles_data["bundles"] = [b for b in bundles_data.get("bundles", []) if b["id"] != bundle_id]

    if len(bundles_data["bundles"]) == original_len:
        raise HTTPException(status_code=404, detail="Bundle not found")

    save_bundles(bundles_data)

    return {"message": "Bundle deleted successfully"}


# ============================================
# Static Routes (MUST come before /{item_id})
# ============================================

@router.get("/equipment-pending")
async def get_equipment_pending_checks():
    """Get equipment that needs daily check"""
    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT * FROM inventory
            WHERE category = 'equipment'
            AND check_interval_days IS NOT NULL
            AND (
                last_check_date IS NULL
                OR DATE(last_check_date, '+' || check_interval_days || ' days') <= DATE('now')
            )
            ORDER BY last_check_date ASC NULLS FIRST
            """
        )
        items = rows_to_list(cursor.fetchall())

    return {"items": items, "count": len(items)}


@router.get("/expiring")
async def get_expiring_items(days: int = Query(7, description="Days until expiry")):
    """Get items expiring within N days"""
    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT * FROM inventory
            WHERE expiry_date IS NOT NULL
            AND DATE(expiry_date) <= DATE('now', '+' || ? || ' days')
            AND DATE(expiry_date) >= DATE('now')
            ORDER BY expiry_date ASC
            """,
            (days,)
        )
        items = rows_to_list(cursor.fetchall())

    return {"items": items, "count": len(items)}


@router.get("/similar")
async def find_similar_items(name: str = Query(..., min_length=1)):
    """Find items with similar names for smart merge suggestion"""
    with get_db() as conn:
        # Simple LIKE search for similar names
        cursor = conn.execute(
            """
            SELECT id, name, specification, category, quantity, unit
            FROM inventory
            WHERE name LIKE ?
            ORDER BY name
            LIMIT 10
            """,
            (f"%{name}%",)
        )
        items = rows_to_list(cursor.fetchall())

    return {"items": items, "count": len(items)}


# ============================================
# Inventory Item Routes (/{item_id} pattern)
# ============================================

class IntakeRequest(BaseModel):
    quantity: float
    notes: Optional[str] = None


class EquipmentCheckRequest(BaseModel):
    status: str  # 'OK', 'NEEDS_REPAIR', 'OUT_OF_SERVICE'
    notes: Optional[str] = None


@router.get("/{item_id}")
async def get_inventory_item(item_id: int):
    """Get a single inventory item"""
    with get_db() as conn:
        cursor = conn.execute("SELECT * FROM inventory WHERE id = ?", (item_id,))
        item = dict_from_row(cursor.fetchone())

    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")

    return item


@router.post("")
async def create_inventory_item(item: InventoryCreate):
    """Create a new inventory item"""
    with write_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO inventory (name, specification, category, quantity, unit, location, expiry_date, min_quantity, tags, notes, check_interval_days, check_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (item.name, item.specification, item.category, item.quantity, item.unit, item.location,
             item.expiry_date, item.min_quantity, item.tags, item.notes, item.check_interval_days, item.check_status)
        )
        new_id = cursor.lastrowid

        # Log event
        conn.execute(
            """
            INSERT INTO event_log (event_type, item_id, quantity_change, notes)
            VALUES ('RESOURCE_IN', ?, ?, ?)
            """,
            (new_id, item.quantity, f"Created: {item.name}")
        )

    return {"id": new_id, "message": "Item created successfully"}


@router.put("/{item_id}")
async def update_inventory_item(item_id: int, item: InventoryUpdate):
    """Update an inventory item"""
    # Build dynamic update query
    updates = []
    params = []

    for field, value in item.model_dump(exclude_unset=True).items():
        if value is not None:
            updates.append(f"{field} = ?")
            params.append(value)

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    updates.append("updated_at = CURRENT_TIMESTAMP")
    params.append(item_id)

    with write_db() as conn:
        # Check if item exists
        cursor = conn.execute("SELECT * FROM inventory WHERE id = ?", (item_id,))
        if cursor.fetchone() is None:
            raise HTTPException(status_code=404, detail="Item not found")

        query = f"UPDATE inventory SET {', '.join(updates)} WHERE id = ?"
        conn.execute(query, params)

    return {"message": "Item updated successfully"}


@router.delete("/{item_id}")
async def delete_inventory_item(item_id: int):
    """Delete an inventory item"""
    with write_db() as conn:
        cursor = conn.execute("SELECT name FROM inventory WHERE id = ?", (item_id,))
        item = cursor.fetchone()
        if item is None:
            raise HTTPException(status_code=404, detail="Item not found")

        conn.execute("DELETE FROM inventory WHERE id = ?", (item_id,))

        # Log event
        conn.execute(
            """
            INSERT INTO event_log (event_type, item_id, notes)
            VALUES ('RESOURCE_OUT', ?, ?)
            """,
            (item_id, f"Deleted: {item['name']}")
        )

    return {"message": "Item deleted successfully"}


@router.post("/{item_id}/distribute")
async def distribute_inventory(item_id: int, request: DistributeRequest):
    """Distribute inventory to a person"""
    with write_db() as conn:
        # Check item exists and has sufficient quantity
        cursor = conn.execute("SELECT * FROM inventory WHERE id = ?", (item_id,))
        item = dict_from_row(cursor.fetchone())

        if item is None:
            raise HTTPException(status_code=404, detail="Item not found")

        if item['quantity'] < request.quantity:
            raise HTTPException(status_code=400, detail="Insufficient quantity")

        # Check person exists
        cursor = conn.execute("SELECT * FROM person WHERE id = ?", (request.person_id,))
        person = cursor.fetchone()

        if person is None:
            raise HTTPException(status_code=404, detail="Person not found")

        # Update inventory
        new_quantity = item['quantity'] - request.quantity
        conn.execute(
            "UPDATE inventory SET quantity = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (new_quantity, item_id)
        )

        # Log event
        cursor = conn.execute(
            """
            INSERT INTO event_log (event_type, item_id, person_id, quantity_change, notes)
            VALUES ('RESOURCE_OUT', ?, ?, ?, ?)
            """,
            (item_id, request.person_id, -request.quantity, request.notes)
        )
        event_id = cursor.lastrowid

    return {
        "message": "Distribution recorded",
        "event_id": event_id,
        "remaining_quantity": new_quantity
    }


@router.get("/{item_id}/history")
async def get_item_history(item_id: int, limit: int = Query(50, le=200)):
    """Get distribution history for an item"""
    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT e.*, p.display_name as person_name
            FROM event_log e
            LEFT JOIN person p ON e.person_id = p.id
            WHERE e.item_id = ?
            ORDER BY e.timestamp DESC
            LIMIT ?
            """,
            (item_id, limit)
        )
        events = rows_to_list(cursor.fetchall())

    return {"events": events, "count": len(events)}


@router.post("/{item_id}/intake")
async def intake_inventory(item_id: int, request: IntakeRequest):
    """Add quantity to inventory (入庫)"""
    with write_db() as conn:
        cursor = conn.execute("SELECT * FROM inventory WHERE id = ?", (item_id,))
        item = dict_from_row(cursor.fetchone())

        if item is None:
            raise HTTPException(status_code=404, detail="Item not found")

        new_quantity = item['quantity'] + request.quantity
        conn.execute(
            "UPDATE inventory SET quantity = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (new_quantity, item_id)
        )

        # Log event
        cursor = conn.execute(
            """
            INSERT INTO event_log (event_type, item_id, quantity_change, notes)
            VALUES ('RESOURCE_IN', ?, ?, ?)
            """,
            (item_id, request.quantity, request.notes or f"入庫: +{request.quantity}")
        )
        event_id = cursor.lastrowid

    return {
        "message": "Intake recorded",
        "event_id": event_id,
        "new_quantity": new_quantity
    }


@router.post("/{item_id}/check")
async def equipment_check(item_id: int, request: EquipmentCheckRequest):
    """Record equipment daily check"""
    with write_db() as conn:
        cursor = conn.execute("SELECT * FROM inventory WHERE id = ?", (item_id,))
        item = dict_from_row(cursor.fetchone())

        if item is None:
            raise HTTPException(status_code=404, detail="Item not found")

        if item['category'] != 'equipment':
            raise HTTPException(status_code=400, detail="Item is not equipment")

        conn.execute(
            """
            UPDATE inventory
            SET last_check_date = DATE('now'), check_status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (request.status, item_id)
        )

        # Log event
        cursor = conn.execute(
            """
            INSERT INTO event_log (event_type, item_id, status_value, notes)
            VALUES ('EQUIPMENT_CHECK', ?, ?, ?)
            """,
            (item_id, request.status, request.notes)
        )
        event_id = cursor.lastrowid

    return {
        "message": "Check recorded",
        "event_id": event_id,
        "status": request.status
    }
