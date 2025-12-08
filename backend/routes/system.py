"""
CIRS System Routes
Time sync, config, backup status
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import subprocess
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import get_db, write_db, dict_from_row, rows_to_list, DB_PATH

router = APIRouter()


class TimeSyncRequest(BaseModel):
    client_time: str  # ISO format


class ConfigUpdate(BaseModel):
    key: str
    value: str


@router.get("/time")
async def get_server_time():
    """Get server time (for sync check)"""
    return {
        "time": datetime.now().isoformat(),
        "timezone": "Asia/Taipei",
        "utc_offset": "+08:00"
    }


@router.post("/time")
async def sync_time(request: TimeSyncRequest):
    """Sync server time from client (Admin only, use with caution)"""
    try:
        # Parse ISO format time
        dt = datetime.fromisoformat(request.client_time.replace('Z', '+00:00'))

        # Only allow sync if running on Linux (Raspberry Pi)
        if os.name != 'nt':
            try:
                subprocess.run(
                    ['sudo', 'date', '-s', dt.strftime('%Y-%m-%d %H:%M:%S')],
                    check=True,
                    capture_output=True
                )
                return {"success": True, "synced_to": dt.isoformat()}
            except subprocess.CalledProcessError as e:
                return {"success": False, "error": "Failed to set system time", "detail": str(e)}
        else:
            return {"success": False, "error": "Time sync only available on Linux"}

    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid time format: {e}")


@router.get("/config")
async def get_config():
    """Get all configuration values"""
    with get_db() as conn:
        cursor = conn.execute("SELECT key, value FROM config")
        config = {row['key']: row['value'] for row in cursor.fetchall()}

    return config


@router.put("/config")
async def update_config(config: ConfigUpdate):
    """Update a configuration value"""
    with write_db() as conn:
        conn.execute(
            """
            INSERT INTO config (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = CURRENT_TIMESTAMP
            """,
            (config.key, config.value, config.value)
        )

    return {"message": f"Config '{config.key}' updated"}


@router.get("/status")
async def get_system_status():
    """Get system status"""
    import sqlite3

    # Database size
    db_size = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0

    # WAL file size
    wal_path = DB_PATH + "-wal"
    wal_size = os.path.getsize(wal_path) if os.path.exists(wal_path) else 0

    # Record counts
    with get_db() as conn:
        counts = {}
        for table in ['inventory', 'person', 'event_log', 'message']:
            cursor = conn.execute(f"SELECT COUNT(*) as count FROM {table}")
            counts[table] = cursor.fetchone()['count']

    # Disk space (Linux only)
    disk_info = {}
    if os.name != 'nt':
        try:
            result = subprocess.run(['df', '-h', '/'], capture_output=True, text=True)
            lines = result.stdout.strip().split('\n')
            if len(lines) > 1:
                parts = lines[1].split()
                disk_info = {
                    "total": parts[1],
                    "used": parts[2],
                    "available": parts[3],
                    "percent": parts[4]
                }
        except Exception:
            pass

    # Backup status
    backup_dir = "/mnt/backup/cirs"
    backup_status = {
        "mounted": os.path.ismount("/mnt/backup"),
        "backup_count": 0,
        "last_backup": None
    }

    if os.path.exists(backup_dir):
        backups = [f for f in os.listdir(backup_dir) if f.endswith('.db.gz')]
        backup_status["backup_count"] = len(backups)
        if backups:
            backups.sort(reverse=True)
            backup_status["last_backup"] = backups[0]

    return {
        "database": {
            "size_bytes": db_size,
            "size_mb": round(db_size / 1024 / 1024, 2),
            "wal_size_bytes": wal_size,
            "record_counts": counts
        },
        "disk": disk_info,
        "backup": backup_status,
        "server_time": datetime.now().isoformat()
    }


@router.post("/backup")
async def trigger_backup():
    """Manually trigger a backup (Admin only)"""
    backup_script = "/home/pi/CIRS/scripts/backup.sh"

    if not os.path.exists(backup_script):
        raise HTTPException(status_code=404, detail="Backup script not found")

    try:
        result = subprocess.run(
            ['bash', backup_script],
            capture_output=True,
            text=True,
            timeout=60
        )

        if result.returncode == 0:
            return {"success": True, "output": result.stdout}
        else:
            return {"success": False, "error": result.stderr}

    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="Backup timed out")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cleanup")
async def trigger_cleanup():
    """Manually trigger cleanup (Admin only)"""
    cleanup_script = "/home/pi/CIRS/scripts/cleanup.sh"

    if not os.path.exists(cleanup_script):
        # Run inline cleanup
        with write_db() as conn:
            # EventLog: keep 90 days
            conn.execute("DELETE FROM event_log WHERE timestamp < datetime('now', '-90 days')")

            # Resolved messages: keep 3 days
            conn.execute("DELETE FROM message WHERE is_resolved = 1 AND created_at < datetime('now', '-3 days')")

            # VACUUM
            conn.execute("VACUUM")

        return {"success": True, "message": "Inline cleanup completed"}

    try:
        result = subprocess.run(
            ['bash', cleanup_script],
            capture_output=True,
            text=True,
            timeout=120
        )

        if result.returncode == 0:
            return {"success": True, "output": result.stdout}
        else:
            return {"success": False, "error": result.stderr}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
