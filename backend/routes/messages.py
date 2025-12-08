"""
CIRS Messages Routes (Local Communication Board)
"""
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timedelta
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import get_db, write_db, dict_from_row, rows_to_list

router = APIRouter()


class MessageCreate(BaseModel):
    content: str
    category: Optional[str] = "general"  # 'seek_person', 'seek_item', 'offer_help', 'report', 'general'
    author_name: Optional[str] = "匿名"
    author_id: Optional[str] = None
    image_data: Optional[str] = None  # Base64 image


class BroadcastCreate(BaseModel):
    content: str
    is_pinned: bool = True


@router.get("")
async def list_messages(
    category: Optional[str] = Query(None, description="Filter by category"),
    limit: int = Query(50, le=200),
    offset: int = Query(0)
):
    """List messages (excluding broadcasts)"""
    with get_db() as conn:
        query = """
            SELECT * FROM message
            WHERE message_type = 'post'
        """
        params = []

        if category:
            query += " AND category = ?"
            params.append(category)

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor = conn.execute(query, params)
        messages = rows_to_list(cursor.fetchall())

    return {"messages": messages, "count": len(messages)}


@router.get("/broadcast")
async def get_current_broadcast():
    """Get current pinned broadcast"""
    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT * FROM message
            WHERE message_type = 'broadcast' AND is_pinned = 1
            ORDER BY created_at DESC
            LIMIT 1
            """
        )
        broadcast = dict_from_row(cursor.fetchone())

    return {"broadcast": broadcast}


@router.get("/all-broadcasts")
async def list_broadcasts(limit: int = Query(20, le=100)):
    """List all broadcasts"""
    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT * FROM message
            WHERE message_type = 'broadcast'
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,)
        )
        broadcasts = rows_to_list(cursor.fetchall())

    return {"broadcasts": broadcasts, "count": len(broadcasts)}


@router.post("")
async def create_message(message: MessageCreate, request: Request):
    """Create a new message post"""
    # Get client IP for anti-abuse
    client_ip = request.client.host if request.client else "unknown"

    # Validate image size
    if message.image_data and len(message.image_data) > 700000:  # ~500KB base64
        raise HTTPException(status_code=400, detail="Image too large. Max 500KB.")

    # Set expiration (3 days)
    expires_at = (datetime.now() + timedelta(days=3)).isoformat()

    with write_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO message (message_type, category, content, author_name, author_id, image_data, client_ip, expires_at)
            VALUES ('post', ?, ?, ?, ?, ?, ?, ?)
            """,
            (message.category, message.content, message.author_name,
             message.author_id, message.image_data, client_ip, expires_at)
        )
        new_id = cursor.lastrowid

    return {"id": new_id, "message": "Message posted successfully"}


@router.post("/broadcast")
async def create_broadcast(broadcast: BroadcastCreate):
    """Create a broadcast (Admin only)"""
    with write_db() as conn:
        # Unpin previous broadcasts if this one is pinned
        if broadcast.is_pinned:
            conn.execute("UPDATE message SET is_pinned = 0 WHERE message_type = 'broadcast'")

        cursor = conn.execute(
            """
            INSERT INTO message (message_type, content, is_pinned, author_name)
            VALUES ('broadcast', ?, ?, '管理員')
            """,
            (broadcast.content, 1 if broadcast.is_pinned else 0)
        )
        new_id = cursor.lastrowid

    return {"id": new_id, "message": "Broadcast created successfully"}


@router.put("/{message_id}/resolve")
async def resolve_message(message_id: int):
    """Mark a message as resolved (e.g., person found)"""
    with write_db() as conn:
        cursor = conn.execute("SELECT * FROM message WHERE id = ?", (message_id,))
        if cursor.fetchone() is None:
            raise HTTPException(status_code=404, detail="Message not found")

        conn.execute(
            "UPDATE message SET is_resolved = 1 WHERE id = ?",
            (message_id,)
        )

    return {"message": "Message marked as resolved"}


@router.delete("/{message_id}")
async def delete_message(message_id: int):
    """Delete a message"""
    with write_db() as conn:
        cursor = conn.execute("SELECT * FROM message WHERE id = ?", (message_id,))
        if cursor.fetchone() is None:
            raise HTTPException(status_code=404, detail="Message not found")

        conn.execute("DELETE FROM message WHERE id = ?", (message_id,))

    return {"message": "Message deleted successfully"}


@router.get("/stats")
async def get_message_stats():
    """Get message statistics"""
    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN category = 'seek_person' THEN 1 ELSE 0 END) as seek_person,
                SUM(CASE WHEN category = 'seek_item' THEN 1 ELSE 0 END) as seek_item,
                SUM(CASE WHEN category = 'offer_help' THEN 1 ELSE 0 END) as offer_help,
                SUM(CASE WHEN category = 'report' THEN 1 ELSE 0 END) as report,
                SUM(CASE WHEN is_resolved = 1 THEN 1 ELSE 0 END) as resolved
            FROM message
            WHERE message_type = 'post'
            """
        )
        stats = dict_from_row(cursor.fetchone())

    return stats
