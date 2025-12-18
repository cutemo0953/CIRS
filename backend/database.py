"""
CIRS Database Connection Module
SQLite with WAL mode for concurrent access
Supports both file-based (production) and in-memory (Vercel demo) modes
"""
import sqlite3
from contextlib import contextmanager
import threading
import os
from pathlib import Path

# ============================================================================
# Environment Detection
# ============================================================================
IS_VERCEL = os.environ.get("VERCEL") == "1"

# Use pathlib for cross-platform path safety
BACKEND_DIR = Path(__file__).parent
PROJECT_ROOT = BACKEND_DIR.parent

if IS_VERCEL:
    # In-memory database for Vercel serverless
    DB_PATH = ":memory:"
    print("[CIRS DB] Running in Vercel demo mode (in-memory)")
else:
    # File-based database for local/production
    DB_PATH = str(BACKEND_DIR / "data" / "cirs.db")
    print(f"[CIRS DB] Running in production mode: {DB_PATH}")

# Global lock for write operations
db_lock = threading.Lock()

# Singleton connection for in-memory mode (persists across requests)
_memory_connection = None


def get_connection():
    """Create a new database connection with optimized settings"""
    global _memory_connection

    if IS_VERCEL:
        # For in-memory mode, reuse the same connection
        if _memory_connection is None:
            _memory_connection = sqlite3.connect(
                DB_PATH,
                check_same_thread=False,
                timeout=30.0
            )
            _memory_connection.row_factory = sqlite3.Row
            # Basic pragmas for in-memory
            _memory_connection.execute("PRAGMA foreign_keys=ON;")
        return _memory_connection
    else:
        # For file-based mode, create new connection each time
        # Ensure data directory exists
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

        conn = sqlite3.connect(
            DB_PATH,
            check_same_thread=False,
            timeout=30.0  # Wait up to 30 seconds for lock
        )
        conn.row_factory = sqlite3.Row

        # Critical optimizations for Raspberry Pi
        conn.execute("PRAGMA journal_mode=WAL;")        # Write-Ahead Logging
        conn.execute("PRAGMA synchronous=NORMAL;")      # Balance performance/safety
        conn.execute("PRAGMA cache_size=-64000;")       # 64MB cache
        conn.execute("PRAGMA temp_store=MEMORY;")       # Temp tables in memory
        conn.execute("PRAGMA mmap_size=268435456;")     # 256MB mmap
        conn.execute("PRAGMA foreign_keys=ON;")         # Enable foreign keys

        return conn


@contextmanager
def get_db():
    """Thread-safe database connection context manager"""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        # Only close for file-based mode; keep in-memory connection alive
        if not IS_VERCEL:
            conn.close()


@contextmanager
def write_db():
    """Serialized write operations to prevent 'database is locked' errors"""
    with db_lock:
        with get_db() as conn:
            yield conn


def init_db():
    """Initialize database with schema and apply migrations"""
    with get_db() as conn:
        # For Vercel, always initialize fresh
        if IS_VERCEL:
            schema_path = BACKEND_DIR / "schema.sql"
            if schema_path.exists():
                with open(schema_path, "r") as f:
                    conn.executescript(f.read())
                print("[CIRS DB] In-memory database initialized with schema")
            return

        # For file-based: check if inventory table exists and apply migrations BEFORE schema
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='inventory'")
        if cursor.fetchone():
            # Existing database - apply migrations first
            apply_migrations(conn)

        # Then execute schema (CREATE IF NOT EXISTS is safe)
        schema_path = BACKEND_DIR / "schema.sql"
        if schema_path.exists():
            with open(schema_path, "r") as f:
                conn.executescript(f.read())
            print(f"[CIRS DB] Database initialized at {DB_PATH}")
        else:
            print(f"[CIRS DB] Warning: schema.sql not found at {schema_path}")


def reset_memory_db():
    """Reset in-memory database (for demo reset feature)"""
    global _memory_connection

    if not IS_VERCEL or _memory_connection is None:
        return False

    # Close existing connection
    try:
        _memory_connection.close()
    except:
        pass

    _memory_connection = None

    # Reinitialize
    init_db()
    return True


def apply_migrations(conn):
    """Apply schema migrations for existing databases"""
    # Inventory migrations
    cursor = conn.execute("PRAGMA table_info(inventory)")
    inv_columns = [row['name'] for row in cursor.fetchall()]

    # Migration: Add specification column
    if 'specification' not in inv_columns:
        print("Migration: Adding 'specification' column to inventory")
        conn.execute("ALTER TABLE inventory ADD COLUMN specification TEXT")

    # Migration: Add equipment check columns
    if 'last_check_date' not in inv_columns:
        print("Migration: Adding equipment check columns to inventory")
        conn.execute("ALTER TABLE inventory ADD COLUMN last_check_date DATE")
        conn.execute("ALTER TABLE inventory ADD COLUMN check_interval_days INTEGER")
        conn.execute("ALTER TABLE inventory ADD COLUMN check_status TEXT")

    # Message migrations
    cursor = conn.execute("PRAGMA table_info(message)")
    msg_columns = [row['name'] for row in cursor.fetchall()]

    # Migration: Add parent_id column for replies
    if msg_columns and 'parent_id' not in msg_columns:
        print("Migration: Adding 'parent_id' column to message for replies")
        conn.execute("ALTER TABLE message ADD COLUMN parent_id INTEGER")

    # Person migrations
    cursor = conn.execute("PRAGMA table_info(person)")
    person_columns = [row['name'] for row in cursor.fetchall()]

    # Migration: Add national_id_hash column
    if person_columns and 'national_id_hash' not in person_columns:
        print("Migration: Adding 'national_id_hash' column to person")
        conn.execute("ALTER TABLE person ADD COLUMN national_id_hash TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_person_national_id ON person(national_id_hash)")

    # Migration: Add photo and identification columns
    if person_columns and 'photo_data' not in person_columns:
        print("Migration: Adding photo and identification columns to person")
        conn.execute("ALTER TABLE person ADD COLUMN photo_data TEXT")
        conn.execute("ALTER TABLE person ADD COLUMN physical_desc TEXT")
        conn.execute("ALTER TABLE person ADD COLUMN id_status TEXT DEFAULT 'confirmed'")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_person_id_status ON person(id_status)")

    # Staff Management v1.1 migrations
    if 'staff_role' not in person_columns:
        print("Migration: Adding Staff Management v1.1 columns to person")
        conn.execute("ALTER TABLE person ADD COLUMN staff_role TEXT")
        conn.execute("ALTER TABLE person ADD COLUMN staff_status TEXT DEFAULT 'OFF_DUTY'")
        conn.execute("ALTER TABLE person ADD COLUMN verification_status TEXT DEFAULT 'UNVERIFIED'")
        conn.execute("ALTER TABLE person ADD COLUMN verified_at DATETIME")
        conn.execute("ALTER TABLE person ADD COLUMN verified_by TEXT")
        conn.execute("ALTER TABLE person ADD COLUMN shift_start DATETIME")
        conn.execute("ALTER TABLE person ADD COLUMN shift_end DATETIME")
        conn.execute("ALTER TABLE person ADD COLUMN expected_hours REAL")
        conn.execute("ALTER TABLE person ADD COLUMN skills TEXT")
        conn.execute("ALTER TABLE person ADD COLUMN emergency_contact TEXT")
        conn.execute("ALTER TABLE person ADD COLUMN certification TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_person_staff_role ON person(staff_role)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_person_staff_status ON person(staff_status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_person_verification ON person(verification_status)")

        # Migrate existing roles to staff_role
        conn.execute("UPDATE person SET staff_role = 'NURSE' WHERE role = 'medic' AND staff_role IS NULL")
        conn.execute("UPDATE person SET staff_role = 'COORDINATOR' WHERE role = 'admin' AND staff_role IS NULL")
        conn.execute("UPDATE person SET staff_role = 'VOLUNTEER' WHERE role = 'staff' AND staff_role IS NULL")

        # Set staff_status based on checked_in_at
        conn.execute("""
            UPDATE person SET staff_status = 'ACTIVE'
            WHERE staff_role IS NOT NULL AND checked_in_at IS NOT NULL
        """)

        # Set verification_status for existing staff
        conn.execute("""
            UPDATE person SET verification_status = 'VERIFIED', verified_at = CURRENT_TIMESTAMP
            WHERE staff_role IS NOT NULL AND role IN ('admin', 'medic')
        """)

    # Staff Join Requests table migration
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='staff_join_requests'")
    if not cursor.fetchone():
        print("Migration: Creating staff_join_requests table")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS staff_join_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                qr_token TEXT UNIQUE NOT NULL,
                display_name TEXT NOT NULL,
                phone TEXT,
                claimed_role TEXT NOT NULL,
                skills TEXT,
                expected_hours REAL DEFAULT 4,
                notes TEXT,
                status TEXT DEFAULT 'PENDING',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                expires_at DATETIME NOT NULL,
                processed_at DATETIME,
                processed_by TEXT,
                person_id TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_join_request_token ON staff_join_requests(qr_token)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_join_request_status ON staff_join_requests(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_join_request_expires ON staff_join_requests(expires_at)")

    # Staff Badge Tokens table migration
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='staff_badge_tokens'")
    if not cursor.fetchone():
        print("Migration: Creating staff_badge_tokens table")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS staff_badge_tokens (
                token_id TEXT PRIMARY KEY,
                person_id TEXT NOT NULL,
                issued_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                expires_at DATETIME NOT NULL,
                is_revoked INTEGER DEFAULT 0,
                FOREIGN KEY (person_id) REFERENCES person(id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_badge_token_person ON staff_badge_tokens(person_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_badge_token_expires ON staff_badge_tokens(expires_at)")

    # Staff Role Config table migration
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='staff_role_config'")
    if not cursor.fetchone():
        print("Migration: Creating staff_role_config table")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS staff_role_config (
                role_code TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                display_name_en TEXT,
                color_hex TEXT NOT NULL,
                icon_name TEXT,
                resilience_weight REAL DEFAULT 1.0,
                requires_verification INTEGER DEFAULT 0,
                sort_order INTEGER DEFAULT 0
            )
        """)
        # Insert default role configs
        conn.executemany(
            "INSERT OR IGNORE INTO staff_role_config VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ('MEDIC', '醫師', 'Doctor', '#E53935', 'medical_services', 1.0, 1, 1),
                ('NURSE', '護理師', 'Nurse', '#E91E63', 'vaccines', 1.0, 1, 2),
                ('VOLUNTEER', '志工', 'Volunteer', '#4CAF50', 'volunteer_activism', 1.0, 0, 3),
                ('ADMIN', '行政人員', 'Admin', '#FFC107', 'assignment_ind', 1.0, 0, 4),
                ('SECURITY', '保全人員', 'Security', '#2196F3', 'security', 1.0, 0, 5),
                ('COORDINATOR', '指揮官', 'Coordinator', '#9C27B0', 'campaign', 1.0, 1, 6),
            ]
        )

    # Zone table migration
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='zone'")
    if not cursor.fetchone():
        print("Migration: Creating zone table and default zones")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS zone (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                zone_type TEXT NOT NULL,
                capacity INTEGER DEFAULT 0,
                description TEXT,
                icon TEXT,
                sort_order INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_zone_type ON zone(zone_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_zone_active ON zone(is_active)")
        # Insert default zones
        conn.executemany(
            "INSERT OR IGNORE INTO zone (id, name, zone_type, capacity, description, icon, sort_order) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                ('rest_area', '休息區', 'shelter', 100, '一般收容民眾休息區', 'moon', 10),
                ('dining_area', '用餐區', 'shelter', 80, '用餐及飲水供應區', 'cake', 11),
                ('family_area', '家庭區', 'shelter', 50, '有幼兒/長者的家庭優先', 'user-group', 12),
                ('elderly_area', '長者區', 'shelter', 30, '行動不便者及長者專區', 'heart', 13),
                ('children_area', '兒童區', 'shelter', 40, '兒童遊戲及照護區', 'face-smile', 14),
                ('triage_area', '檢傷區', 'medical', 20, 'START 檢傷分類處', 'clipboard-document-check', 20),
                ('green_area', '輕傷區', 'medical', 50, 'GREEN - 可延後處理', 'check-circle', 21),
                ('yellow_area', '中傷區', 'medical', 30, 'YELLOW - 需優先處理', 'exclamation-triangle', 22),
                ('red_area', '重傷區', 'medical', 10, 'RED - 立即處理', 'exclamation-circle', 23),
                ('observation_area', '觀察區', 'medical', 20, '症狀觀察及隔離區', 'eye', 24),
                ('registration', '報到處', 'service', 0, '人員報到登記', 'clipboard-document-list', 30),
                ('supply_station', '物資發放區', 'service', 0, '物資領取處', 'cube', 31),
                ('info_desk', '服務台', 'service', 0, '諮詢及協助', 'information-circle', 32),
                ('warehouse', '倉庫', 'restricted', 0, '物資儲存區 (管制)', 'building-storefront', 40),
                ('office', '辦公室', 'restricted', 0, '行政管理區 (管制)', 'building-office', 41),
                ('equipment_room', '設備間', 'restricted', 0, '發電機/通訊設備 (管制)', 'cog-6-tooth', 42),
            ]
        )

    # Satellite Pairing Codes table migration (v1.1)
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='satellite_pairing_codes'")
    if not cursor.fetchone():
        print("Migration: Creating satellite_pairing_codes table")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS satellite_pairing_codes (
                code TEXT PRIMARY KEY,
                hub_name TEXT NOT NULL,
                allowed_roles TEXT DEFAULT 'volunteer',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                expires_at DATETIME NOT NULL,
                used_at DATETIME,
                used_by_device_id TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pairing_code_expires ON satellite_pairing_codes(expires_at)")
    else:
        # v1.3.1: Add allowed_roles column if missing
        cursor = conn.execute("PRAGMA table_info(satellite_pairing_codes)")
        pairing_columns = [row['name'] for row in cursor.fetchall()]
        if 'allowed_roles' not in pairing_columns:
            print("Migration: Adding 'allowed_roles' column to satellite_pairing_codes")
            conn.execute("ALTER TABLE satellite_pairing_codes ADD COLUMN allowed_roles TEXT DEFAULT 'volunteer'")

    # Action Logs table migration (v1.1)
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='action_logs'")
    if not cursor.fetchone():
        print("Migration: Creating action_logs table")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS action_logs (
                action_id TEXT PRIMARY KEY,
                batch_id TEXT,
                action_type TEXT NOT NULL,
                device_id TEXT,
                payload TEXT,
                processed_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_action_logs_batch ON action_logs(batch_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_action_logs_device ON action_logs(device_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_action_logs_time ON action_logs(processed_at)")

    conn.commit()
    print("Migrations applied successfully")


def dict_from_row(row):
    """Convert sqlite3.Row to dict"""
    if row is None:
        return None
    return dict(row)


def rows_to_list(rows):
    """Convert list of sqlite3.Row to list of dict"""
    return [dict_from_row(row) for row in rows]
