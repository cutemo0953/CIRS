"""
CIRS Database Connection Module
SQLite with WAL mode for concurrent access
"""
import sqlite3
from contextlib import contextmanager
import threading
import os

# Database path
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "cirs.db")

# Global lock for write operations
db_lock = threading.Lock()


def get_connection():
    """Create a new database connection with optimized settings"""
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
        # Read and execute schema
        schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
        if os.path.exists(schema_path):
            with open(schema_path, "r") as f:
                conn.executescript(f.read())
            print(f"Database initialized at {DB_PATH}")
        else:
            print(f"Warning: schema.sql not found at {schema_path}")

        # Apply migrations for existing databases
        apply_migrations(conn)


def apply_migrations(conn):
    """Apply schema migrations for existing databases"""
    cursor = conn.execute("PRAGMA table_info(inventory)")
    columns = [row['name'] for row in cursor.fetchall()]

    # Migration: Add specification column
    if 'specification' not in columns:
        print("Migration: Adding 'specification' column to inventory")
        conn.execute("ALTER TABLE inventory ADD COLUMN specification TEXT")

    # Migration: Add equipment check columns
    if 'last_check_date' not in columns:
        print("Migration: Adding equipment check columns to inventory")
        conn.execute("ALTER TABLE inventory ADD COLUMN last_check_date DATE")
        conn.execute("ALTER TABLE inventory ADD COLUMN check_interval_days INTEGER")
        conn.execute("ALTER TABLE inventory ADD COLUMN check_status TEXT")

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
