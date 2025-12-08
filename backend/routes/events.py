"""
CIRS Events Routes
"""
from fastapi import APIRouter, Query
from typing import Optional
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import get_db, rows_to_list

router = APIRouter()


@router.get("")
async def list_events(
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    person_id: Optional[str] = Query(None, description="Filter by person"),
    item_id: Optional[int] = Query(None, description="Filter by inventory item"),
    from_date: Optional[str] = Query(None, description="From date (YYYY-MM-DD)"),
    to_date: Optional[str] = Query(None, description="To date (YYYY-MM-DD)"),
    limit: int = Query(100, le=500),
    offset: int = Query(0)
):
    """List events with filters"""
    with get_db() as conn:
        query = """
            SELECT e.*, p.display_name as person_name, i.name as item_name
            FROM event_log e
            LEFT JOIN person p ON e.person_id = p.id
            LEFT JOIN inventory i ON e.item_id = i.id
            WHERE 1=1
        """
        params = []

        if event_type:
            query += " AND e.event_type = ?"
            params.append(event_type)

        if person_id:
            query += " AND e.person_id = ?"
            params.append(person_id)

        if item_id:
            query += " AND e.item_id = ?"
            params.append(item_id)

        if from_date:
            query += " AND DATE(e.timestamp) >= ?"
            params.append(from_date)

        if to_date:
            query += " AND DATE(e.timestamp) <= ?"
            params.append(to_date)

        query += " ORDER BY e.timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor = conn.execute(query, params)
        events = rows_to_list(cursor.fetchall())

    return {"events": events, "count": len(events), "limit": limit, "offset": offset}


@router.get("/summary")
async def get_events_summary(
    from_date: Optional[str] = Query(None, description="From date (YYYY-MM-DD)"),
    to_date: Optional[str] = Query(None, description="To date (YYYY-MM-DD)")
):
    """Get summary of events by type"""
    with get_db() as conn:
        query = """
            SELECT event_type, COUNT(*) as count
            FROM event_log
            WHERE 1=1
        """
        params = []

        if from_date:
            query += " AND DATE(timestamp) >= ?"
            params.append(from_date)

        if to_date:
            query += " AND DATE(timestamp) <= ?"
            params.append(to_date)

        query += " GROUP BY event_type"

        cursor = conn.execute(query, params)
        summary = {row['event_type']: row['count'] for row in cursor.fetchall()}

    return {"summary": summary}


@router.get("/person/{person_id}")
async def get_person_events(person_id: str, limit: int = Query(50, le=200)):
    """Get all events for a specific person"""
    with get_db() as conn:
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


@router.get("/item/{item_id}")
async def get_item_events(item_id: int, limit: int = Query(50, le=200)):
    """Get all events for a specific inventory item"""
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
