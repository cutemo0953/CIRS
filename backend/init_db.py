#!/usr/bin/env python3
"""
xIRS Hub Database Initialization Script
Creates the SQLite database and initializes schema

Note: Database renamed from cirs.db to xirs_hub.db (v2.0)
"""
import os
import sqlite3
import sys

# Database path
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
DB_NAME = 'xirs_hub.db'
OLD_DB_NAME = 'cirs.db'
DB_PATH = os.path.join(DATA_DIR, DB_NAME)
OLD_DB_PATH = os.path.join(DATA_DIR, OLD_DB_NAME)
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'schema.sql')


def migrate_old_database():
    """Migrate from cirs.db to xirs_hub.db if needed"""
    if os.path.exists(OLD_DB_PATH) and not os.path.exists(DB_PATH):
        print(f"Migrating database: {OLD_DB_NAME} → {DB_NAME}")
        os.rename(OLD_DB_PATH, DB_PATH)
        # Also migrate WAL and SHM files
        for suffix in ['-wal', '-shm']:
            old_file = OLD_DB_PATH + suffix
            new_file = DB_PATH + suffix
            if os.path.exists(old_file):
                os.rename(old_file, new_file)
        print("Migration complete!")
        return True
    return False


def init_database():
    """Initialize the database with schema"""

    # Create data directory if not exists
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
        print(f"Created data directory: {DATA_DIR}")

    # Try to migrate old database first
    migrated = migrate_old_database()

    # Check if database already exists
    db_exists = os.path.exists(DB_PATH)
    if db_exists and not migrated:
        response = input(f"Database already exists at {DB_PATH}. Reinitialize? (y/N): ")
        if response.lower() != 'y':
            print("Aborted.")
            return
        # Backup existing database
        import shutil
        from datetime import datetime
        backup_path = f"{DB_PATH}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        shutil.copy(DB_PATH, backup_path)
        print(f"Backed up existing database to: {backup_path}")
        # Remove existing database to create fresh one
        os.remove(DB_PATH)
        print(f"Removed old database, creating fresh one...")

    # Read schema
    if not os.path.exists(SCHEMA_PATH):
        print(f"Error: Schema file not found at {SCHEMA_PATH}")
        sys.exit(1)

    with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
        schema_sql = f.read()

    # Create database and apply schema
    conn = sqlite3.connect(DB_PATH)

    # Enable WAL mode
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")

    # Execute schema
    conn.executescript(schema_sql)
    conn.commit()

    # Verify tables created
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
    tables = [row[0] for row in cursor.fetchall()]

    print(f"\nDatabase initialized at: {DB_PATH}")
    print(f"Tables created: {', '.join(tables)}")

    # Show record counts
    print("\nInitial data:")
    for table in tables:
        if table.startswith('sqlite_'):
            continue
        cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
        count = cursor.fetchone()[0]
        print(f"  {table}: {count} records")

    conn.close()
    print("\nDone! You can now start the server with:")
    print("  uvicorn main:app --host 0.0.0.0 --port 8090")


if __name__ == "__main__":
    init_database()
