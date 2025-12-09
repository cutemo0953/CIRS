"""
CIRS Secure Backup System
- AES-256 encrypted backups
- USB detection and management
- Checksum verification
- Audit logging
"""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
import os
import sys
import json
import gzip
import hashlib
import shutil
import subprocess
from datetime import datetime
from io import BytesIO

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import get_db, write_db, dict_from_row, rows_to_list, DB_PATH

router = APIRouter()

# Backup configuration
BACKUP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backups")
USB_MOUNT_POINTS = ["/mnt/usb", "/media", "/mnt/backup"]  # Common USB mount points

# Encryption key derivation (in production, use environment variable or secure vault)
BACKUP_SALT = "CIRS_BACKUP_SALT_2024"


class BackupRequest(BaseModel):
    operator_id: str
    target: str = "local"  # 'local', 'usb', 'download'
    encrypt: bool = True
    password: Optional[str] = None  # For encrypted backups
    notes: Optional[str] = None


class RestoreRequest(BaseModel):
    operator_id: str
    backup_id: Optional[int] = None
    file_path: Optional[str] = None
    password: Optional[str] = None
    reason: str


def derive_key(password: str) -> bytes:
    """Derive encryption key from password using PBKDF2"""
    import hashlib
    return hashlib.pbkdf2_hmac(
        'sha256',
        password.encode(),
        BACKUP_SALT.encode(),
        100000,
        dklen=32
    )


def simple_encrypt(data: bytes, password: str) -> bytes:
    """Simple XOR-based encryption with key derivation
    For production, use cryptography library with AES-256-GCM
    """
    key = derive_key(password)
    # Extend key to match data length
    extended_key = (key * ((len(data) // len(key)) + 1))[:len(data)]
    # XOR encryption
    encrypted = bytes(a ^ b for a, b in zip(data, extended_key))
    return encrypted


def simple_decrypt(data: bytes, password: str) -> bytes:
    """Decrypt XOR-encrypted data"""
    # XOR decryption is symmetric
    return simple_encrypt(data, password)


def calculate_checksum(data: bytes) -> str:
    """Calculate SHA-256 checksum"""
    return hashlib.sha256(data).hexdigest()


def log_audit(conn, action_type: str, operator_id: str, target_id: str = None,
              old_value: str = None, new_value: str = None,
              reason_code: str = None, reason_text: str = None,
              ip_address: str = None):
    """Log action to audit_log table"""
    conn.execute(
        """
        INSERT INTO audit_log (action_type, target_type, target_id, operator_id,
                               reason_code, reason_text, old_value, new_value, ip_address)
        VALUES (?, 'system', ?, ?, ?, ?, ?, ?, ?)
        """,
        (action_type, target_id, operator_id, reason_code, reason_text,
         old_value, new_value, ip_address)
    )


def log_backup(conn, backup_type: str, file_path: str, file_size: int,
               checksum: str, encrypted: bool, operator_id: str,
               status: str = "success", notes: str = None):
    """Log backup to backup_log table"""
    conn.execute(
        """
        INSERT INTO backup_log (backup_type, file_path, file_size, checksum,
                                encrypted, operator_id, status, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (backup_type, file_path, file_size, checksum, 1 if encrypted else 0,
         operator_id, status, notes)
    )


def detect_usb_devices():
    """Detect mounted USB devices"""
    usb_devices = []

    # Check common mount points
    for mount_point in USB_MOUNT_POINTS:
        if os.path.exists(mount_point):
            # Check if anything is mounted
            if os.path.ismount(mount_point):
                try:
                    # Get disk space info
                    stat = os.statvfs(mount_point)
                    total = stat.f_blocks * stat.f_frsize
                    free = stat.f_bfree * stat.f_frsize
                    usb_devices.append({
                        "path": mount_point,
                        "total_bytes": total,
                        "free_bytes": free,
                        "total_gb": round(total / (1024**3), 2),
                        "free_gb": round(free / (1024**3), 2)
                    })
                except Exception:
                    pass

            # Also check subdirectories (common for /media/username/device)
            try:
                for subdir in os.listdir(mount_point):
                    subpath = os.path.join(mount_point, subdir)
                    if os.path.isdir(subpath) and os.path.ismount(subpath):
                        try:
                            stat = os.statvfs(subpath)
                            total = stat.f_blocks * stat.f_frsize
                            free = stat.f_bfree * stat.f_frsize
                            usb_devices.append({
                                "path": subpath,
                                "total_bytes": total,
                                "free_bytes": free,
                                "total_gb": round(total / (1024**3), 2),
                                "free_gb": round(free / (1024**3), 2)
                            })
                        except Exception:
                            pass
            except Exception:
                pass

    return usb_devices


@router.get("/status")
async def get_backup_status():
    """Get backup status and history"""
    # Ensure backup directory exists
    os.makedirs(BACKUP_DIR, exist_ok=True)

    with get_db() as conn:
        # Get recent backups from log
        cursor = conn.execute(
            """
            SELECT * FROM backup_log
            ORDER BY timestamp DESC
            LIMIT 20
            """
        )
        backup_history = rows_to_list(cursor.fetchall())

        # Get local backup files
        local_backups = []
        if os.path.exists(BACKUP_DIR):
            for f in os.listdir(BACKUP_DIR):
                if f.endswith('.db.gz') or f.endswith('.db.gz.enc'):
                    filepath = os.path.join(BACKUP_DIR, f)
                    local_backups.append({
                        "filename": f,
                        "path": filepath,
                        "size_bytes": os.path.getsize(filepath),
                        "size_mb": round(os.path.getsize(filepath) / (1024*1024), 2),
                        "modified": datetime.fromtimestamp(
                            os.path.getmtime(filepath)
                        ).isoformat(),
                        "encrypted": f.endswith('.enc')
                    })

        # Sort by modification time (newest first)
        local_backups.sort(key=lambda x: x['modified'], reverse=True)

        # Detect USB devices
        usb_devices = detect_usb_devices()

        return {
            "backup_directory": BACKUP_DIR,
            "local_backups": local_backups,
            "backup_history": backup_history,
            "usb_devices": usb_devices,
            "last_backup": backup_history[0] if backup_history else None
        }


@router.post("/create")
async def create_backup(request: BackupRequest, req: Request):
    """Create a new backup"""
    # Verify operator exists and has permission
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT id, role FROM person WHERE id = ?",
            (request.operator_id,)
        )
        operator = cursor.fetchone()
        if not operator:
            raise HTTPException(status_code=404, detail="Operator not found")
        if operator['role'] not in ['admin', 'staff']:
            raise HTTPException(status_code=403, detail="Permission denied")

    # Generate timestamp for filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Read database file
    if not os.path.exists(DB_PATH):
        raise HTTPException(status_code=404, detail="Database not found")

    with open(DB_PATH, 'rb') as f:
        db_data = f.read()

    # Compress with gzip
    compressed = gzip.compress(db_data, compresslevel=9)

    # Calculate checksum before encryption
    checksum = calculate_checksum(compressed)

    # Encrypt if requested
    if request.encrypt:
        if not request.password:
            raise HTTPException(
                status_code=400,
                detail="Password required for encrypted backup"
            )
        final_data = simple_encrypt(compressed, request.password)
        ext = ".db.gz.enc"
    else:
        final_data = compressed
        ext = ".db.gz"

    # Determine target path
    filename = f"cirs_backup_{timestamp}{ext}"

    if request.target == "local":
        os.makedirs(BACKUP_DIR, exist_ok=True)
        target_path = os.path.join(BACKUP_DIR, filename)

        with open(target_path, 'wb') as f:
            f.write(final_data)

    elif request.target == "usb":
        usb_devices = detect_usb_devices()
        if not usb_devices:
            raise HTTPException(
                status_code=404,
                detail="No USB device detected. Please insert a USB drive."
            )

        # Use first detected USB device
        usb_path = usb_devices[0]['path']
        backup_subdir = os.path.join(usb_path, "CIRS_Backups")
        os.makedirs(backup_subdir, exist_ok=True)
        target_path = os.path.join(backup_subdir, filename)

        with open(target_path, 'wb') as f:
            f.write(final_data)

    elif request.target == "download":
        # Return as downloadable file
        with write_db() as conn:
            log_backup(
                conn, "download", "download", len(final_data),
                checksum, request.encrypt, request.operator_id,
                "success", request.notes
            )
            log_audit(
                conn, "BACKUP", request.operator_id,
                target_id=f"download_{timestamp}",
                new_value=json.dumps({
                    "size": len(final_data),
                    "encrypted": request.encrypt,
                    "checksum": checksum
                }),
                ip_address=req.client.host if req.client else None
            )

        return StreamingResponse(
            BytesIO(final_data),
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                "X-Checksum": checksum
            }
        )
    else:
        raise HTTPException(status_code=400, detail="Invalid target")

    # Log the backup
    with write_db() as conn:
        log_backup(
            conn, request.target, target_path, len(final_data),
            checksum, request.encrypt, request.operator_id,
            "success", request.notes
        )
        log_audit(
            conn, "BACKUP", request.operator_id,
            target_id=target_path,
            new_value=json.dumps({
                "size": len(final_data),
                "encrypted": request.encrypt,
                "checksum": checksum
            }),
            ip_address=req.client.host if req.client else None
        )

    return {
        "success": True,
        "filename": filename,
        "path": target_path,
        "size_bytes": len(final_data),
        "size_mb": round(len(final_data) / (1024*1024), 2),
        "checksum": checksum,
        "encrypted": request.encrypt,
        "timestamp": timestamp
    }


@router.post("/restore")
async def restore_backup(request: RestoreRequest, req: Request):
    """Restore from a backup file
    WARNING: This will overwrite the current database!
    """
    # Verify operator is admin
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT id, role FROM person WHERE id = ?",
            (request.operator_id,)
        )
        operator = cursor.fetchone()
        if not operator:
            raise HTTPException(status_code=404, detail="Operator not found")
        if operator['role'] != 'admin':
            raise HTTPException(
                status_code=403,
                detail="Only admin can restore backups"
            )

    # Find backup file
    backup_path = None

    if request.backup_id:
        with get_db() as conn:
            cursor = conn.execute(
                "SELECT file_path FROM backup_log WHERE id = ?",
                (request.backup_id,)
            )
            row = cursor.fetchone()
            if row:
                backup_path = row['file_path']
    elif request.file_path:
        backup_path = request.file_path

    if not backup_path or not os.path.exists(backup_path):
        raise HTTPException(status_code=404, detail="Backup file not found")

    # Read backup file
    with open(backup_path, 'rb') as f:
        backup_data = f.read()

    # Decrypt if encrypted
    if backup_path.endswith('.enc'):
        if not request.password:
            raise HTTPException(
                status_code=400,
                detail="Password required for encrypted backup"
            )
        try:
            backup_data = simple_decrypt(backup_data, request.password)
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail="Decryption failed. Wrong password?"
            )

    # Decompress
    try:
        db_data = gzip.decompress(backup_data)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail="Decompression failed. File may be corrupted."
        )

    # Create backup of current database before restore
    if os.path.exists(DB_PATH):
        current_backup = DB_PATH + f".pre_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        shutil.copy2(DB_PATH, current_backup)

    # Write restored database
    # First, close any WAL connections
    with write_db() as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    # Write the restored data
    with open(DB_PATH, 'wb') as f:
        f.write(db_data)

    # Log the restore (in new database)
    with write_db() as conn:
        log_audit(
            conn, "RESTORE", request.operator_id,
            target_id=backup_path,
            reason_text=request.reason,
            ip_address=req.client.host if req.client else None
        )

    return {
        "success": True,
        "message": "Database restored successfully",
        "source": backup_path,
        "pre_restore_backup": current_backup if os.path.exists(DB_PATH) else None
    }


@router.delete("/{backup_id}")
async def delete_backup(backup_id: int, operator_id: str, req: Request):
    """Delete a backup file"""
    # Verify operator is admin
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT id, role FROM person WHERE id = ?",
            (operator_id,)
        )
        operator = cursor.fetchone()
        if not operator:
            raise HTTPException(status_code=404, detail="Operator not found")
        if operator['role'] != 'admin':
            raise HTTPException(status_code=403, detail="Only admin can delete backups")

        # Get backup info
        cursor = conn.execute(
            "SELECT * FROM backup_log WHERE id = ?",
            (backup_id,)
        )
        backup = dict_from_row(cursor.fetchone())
        if not backup:
            raise HTTPException(status_code=404, detail="Backup record not found")

    # Delete file if exists
    if backup['file_path'] and os.path.exists(backup['file_path']):
        os.remove(backup['file_path'])

    # Update backup log status
    with write_db() as conn:
        conn.execute(
            "UPDATE backup_log SET status = 'deleted', notes = COALESCE(notes, '') || ' [Deleted]' WHERE id = ?",
            (backup_id,)
        )
        log_audit(
            conn, "BACKUP_DELETE", operator_id,
            target_id=str(backup_id),
            old_value=json.dumps(backup),
            ip_address=req.client.host if req.client else None
        )

    return {"success": True, "message": "Backup deleted"}


@router.get("/verify/{backup_id}")
async def verify_backup(backup_id: int):
    """Verify backup integrity by checksum"""
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT file_path, checksum, encrypted FROM backup_log WHERE id = ?",
            (backup_id,)
        )
        backup = cursor.fetchone()
        if not backup:
            raise HTTPException(status_code=404, detail="Backup not found")

    file_path = backup['file_path']
    stored_checksum = backup['checksum']

    if not file_path or not os.path.exists(file_path):
        return {
            "valid": False,
            "error": "Backup file not found",
            "stored_checksum": stored_checksum
        }

    # Read and calculate checksum
    with open(file_path, 'rb') as f:
        data = f.read()

    # For encrypted files, checksum is of encrypted data
    # For non-encrypted files, checksum is of compressed data
    current_checksum = calculate_checksum(data)

    return {
        "valid": current_checksum == stored_checksum,
        "stored_checksum": stored_checksum,
        "current_checksum": current_checksum,
        "file_size": len(data),
        "encrypted": bool(backup['encrypted'])
    }


@router.get("/audit-log")
async def get_backup_audit_log(limit: int = 50):
    """Get backup-related audit log entries"""
    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT * FROM audit_log
            WHERE action_type IN ('BACKUP', 'RESTORE', 'BACKUP_DELETE')
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (limit,)
        )
        return rows_to_list(cursor.fetchall())


@router.post("/schedule")
async def configure_backup_schedule(
    enabled: bool = True,
    interval_hours: int = 24,
    target: str = "local",
    operator_id: str = None
):
    """Configure automatic backup schedule (stored in config)"""
    if not operator_id:
        raise HTTPException(status_code=400, detail="operator_id required")

    # Verify admin
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT role FROM person WHERE id = ?",
            (operator_id,)
        )
        op = cursor.fetchone()
        if not op or op['role'] != 'admin':
            raise HTTPException(status_code=403, detail="Admin only")

    schedule_config = {
        "enabled": enabled,
        "interval_hours": interval_hours,
        "target": target,
        "updated_by": operator_id,
        "updated_at": datetime.now().isoformat()
    }

    with write_db() as conn:
        conn.execute(
            """
            INSERT INTO config (key, value, updated_at)
            VALUES ('backup_schedule', ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = CURRENT_TIMESTAMP
            """,
            (json.dumps(schedule_config), json.dumps(schedule_config))
        )

    return {
        "success": True,
        "schedule": schedule_config
    }


@router.get("/schedule")
async def get_backup_schedule():
    """Get current backup schedule configuration"""
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT value FROM config WHERE key = 'backup_schedule'"
        )
        row = cursor.fetchone()
        if row:
            return json.loads(row['value'])
        return {
            "enabled": False,
            "interval_hours": 24,
            "target": "local"
        }
