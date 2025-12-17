"""
CIRS - Community Inventory Resilience System
FastAPI Backend Entry Point
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
import os
from pathlib import Path

from database import init_db, get_db, dict_from_row, IS_VERCEL, reset_memory_db

# Use pathlib for cross-platform path safety
BACKEND_DIR = Path(__file__).parent
BASE_DIR = BACKEND_DIR.parent
FRONTEND_DIR = BASE_DIR / 'frontend'
MOBILE_DIR = BASE_DIR / 'frontend' / 'mobile'
PORTAL_DIR = BASE_DIR / 'portal'
FILES_DIR = BASE_DIR / 'files'

# Import routes
from routes import auth, inventory, person, events, messages, system, backup, zone, resilience, staff


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    # Startup: Initialize database
    print("Starting CIRS Backend...")
    init_db()

    # Seed demo data if running on Vercel
    if IS_VERCEL:
        from seeder import seed_cirs_demo
        from database import get_db
        with get_db() as conn:
            seed_cirs_demo(conn)
        print("[CIRS] Demo mode initialized with sample data")

    yield
    # Shutdown
    print("Shutting down CIRS Backend...")


# Create FastAPI app
app = FastAPI(
    title="CIRS API",
    description="Community Inventory Resilience System API",
    version="1.0.0-demo" if IS_VERCEL else "1.0.0",
    lifespan=lifespan
)

# CORS middleware (allow all for development/demo)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(inventory.router, prefix="/api/inventory", tags=["Inventory"])
app.include_router(person.router, prefix="/api/person", tags=["Person"])
app.include_router(events.router, prefix="/api/events", tags=["Events"])
app.include_router(messages.router, prefix="/api/messages", tags=["Messages"])
app.include_router(system.router, prefix="/api/system", tags=["System"])
app.include_router(backup.router, prefix="/api/backup", tags=["Backup"])
app.include_router(zone.router, prefix="/api/zone", tags=["Zone"])
app.include_router(resilience.router, prefix="/api/resilience", tags=["Resilience"])
app.include_router(staff.router, prefix="/api/staff", tags=["Staff"])


@app.get("/")
async def root():
    """Root endpoint - redirect to Portal"""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/portal")


@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "demo_mode": IS_VERCEL}


# ============================================================================
# Demo Mode Endpoints
# ============================================================================

@app.get("/api/demo-status")
async def get_demo_status():
    """Get demo mode status"""
    return {
        "is_demo": IS_VERCEL,
        "version": "1.0.0-demo" if IS_VERCEL else "1.0.0",
        "message": "此為線上展示版，資料將在頁面重整後重置" if IS_VERCEL else None,
        "github_url": "https://github.com/cutemo0953/CIRS"
    }


@app.post("/api/demo/reset")
async def reset_demo():
    """Reset demo database (only available in Vercel mode)"""
    if not IS_VERCEL:
        raise HTTPException(
            status_code=403,
            detail="Reset is only available in demo mode"
        )

    try:
        # Reset the in-memory database
        reset_memory_db()

        # Re-seed with demo data
        from seeder import seed_cirs_demo
        with get_db() as conn:
            seed_cirs_demo(conn)

        return {
            "success": True,
            "message": "Demo data has been reset successfully"
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to reset demo: {str(e)}"
        )


# ============================================================================
# Public Status API
# ============================================================================

@app.get("/api/public/status")
async def get_public_status():
    """
    Public status endpoint for Portal (交通燈系統)
    Returns simplified status without sensitive data.
    No authentication required.
    """
    with get_db() as conn:
        # Get headcount (checked_in only)
        cursor = conn.execute("""
            SELECT COUNT(*) as checked_in FROM person
            WHERE role = 'public' AND checked_in_at IS NOT NULL
        """)
        headcount = cursor.fetchone()['checked_in'] or 0

        # Get water and food totals
        cursor = conn.execute("""
            SELECT category, SUM(quantity) as total
            FROM inventory
            WHERE category IN ('water', 'food')
            GROUP BY category
        """)
        resources = {row['category']: row['total'] for row in cursor.fetchall()}

        # Get config for per-person consumption
        cursor = conn.execute("SELECT key, value FROM config WHERE key IN ('water_per_person_per_day', 'food_per_person_per_day')")
        config = {row['key']: float(row['value']) for row in cursor.fetchall()}

        # Calculate survival days
        people_count = headcount if headcount > 0 else 1
        water_per_day = config.get('water_per_person_per_day', 3)
        food_per_day = config.get('food_per_person_per_day', 2100)

        water_days = resources.get('water', 0) / (water_per_day * people_count)
        food_days = resources.get('food', 0) / (food_per_day * people_count)

        # Traffic light logic: >3 days = green, 1-3 days = yellow, <1 day = red
        def to_traffic_light(days):
            if days >= 3:
                return "green"
            elif days >= 1:
                return "yellow"
            else:
                return "red"

        # Equipment status (check for issues)
        cursor = conn.execute("""
            SELECT COUNT(*) as count FROM inventory
            WHERE category = 'equipment'
            AND check_status IN ('NEEDS_REPAIR', 'OUT_OF_SERVICE')
        """)
        equipment_issues = cursor.fetchone()['count']

        cursor = conn.execute("""
            SELECT COUNT(*) as count FROM inventory WHERE category = 'equipment'
        """)
        equipment_total = cursor.fetchone()['count']

        # Equipment light: all OK = green, some issues = yellow, most issues = red
        if equipment_total == 0:
            equipment_light = "green"
        elif equipment_issues == 0:
            equipment_light = "green"
        elif equipment_issues / equipment_total < 0.3:
            equipment_light = "yellow"
        else:
            equipment_light = "red"

        # Get current broadcast
        cursor = conn.execute("""
            SELECT content FROM message
            WHERE message_type = 'broadcast' AND is_pinned = 1
            ORDER BY created_at DESC LIMIT 1
        """)
        broadcast_row = cursor.fetchone()
        broadcast = broadcast_row['content'] if broadcast_row else None

        # Shelter capacity (using zone data if available)
        cursor = conn.execute("""
            SELECT SUM(capacity) as total_capacity FROM zone WHERE is_active = 1
        """)
        capacity_row = cursor.fetchone()
        total_capacity = capacity_row['total_capacity'] if capacity_row and capacity_row['total_capacity'] else 100

        # Shelter light: <50% = green, 50-90% = yellow, >90% = red
        occupancy_rate = headcount / total_capacity if total_capacity > 0 else 0
        if occupancy_rate < 0.5:
            shelter_light = "green"
        elif occupancy_rate < 0.9:
            shelter_light = "yellow"
        else:
            shelter_light = "red"

    return {
        "shelter": {
            "status": shelter_light,
            "headcount": headcount,
            "capacity": total_capacity
        },
        "water": {
            "status": to_traffic_light(water_days),
            "days": round(water_days, 1)
        },
        "food": {
            "status": to_traffic_light(food_days),
            "days": round(food_days, 1)
        },
        "equipment": {
            "status": equipment_light,
            "issues": equipment_issues
        },
        "broadcast": broadcast,
        "is_demo": IS_VERCEL
    }


@app.get("/api/stats")
async def get_stats():
    """Get system statistics"""
    with get_db() as conn:
        # Headcount by triage status
        cursor = conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN triage_status = 'GREEN' THEN 1 ELSE 0 END) as green,
                SUM(CASE WHEN triage_status = 'YELLOW' THEN 1 ELSE 0 END) as yellow,
                SUM(CASE WHEN triage_status = 'RED' THEN 1 ELSE 0 END) as red,
                SUM(CASE WHEN triage_status = 'BLACK' THEN 1 ELSE 0 END) as black,
                SUM(CASE WHEN checked_in_at IS NOT NULL THEN 1 ELSE 0 END) as checked_in
            FROM person
            WHERE role = 'public'
        """)
        headcount = dict_from_row(cursor.fetchone())

        # Inventory total count (excluding equipment)
        cursor = conn.execute("""
            SELECT COUNT(*) as count FROM inventory WHERE category != 'equipment'
        """)
        inventory_total = cursor.fetchone()['count']

        # Equipment OK count (check_status = 'OK' or NULL with no check needed)
        cursor = conn.execute("""
            SELECT COUNT(*) as count FROM inventory
            WHERE category = 'equipment'
            AND (check_status IS NULL OR check_status = 'OK')
        """)
        equipment_ok = cursor.fetchone()['count']

        # Messages pending (unresolved, excluding replies and broadcasts)
        cursor = conn.execute("""
            SELECT COUNT(*) as count FROM message
            WHERE (is_resolved IS NULL OR is_resolved = 0)
            AND message_type = 'post'
        """)
        messages_pending = cursor.fetchone()['count']

        # Inventory alerts (below min_quantity)
        cursor = conn.execute("""
            SELECT id, name, quantity, min_quantity, unit
            FROM inventory
            WHERE quantity < min_quantity AND min_quantity > 0
        """)
        alerts = [dict_from_row(row) for row in cursor.fetchall()]

        # Get water and food for survival days calculation
        cursor = conn.execute("""
            SELECT category, SUM(quantity) as total
            FROM inventory
            WHERE category IN ('water', 'food')
            GROUP BY category
        """)
        resources = {row['category']: row['total'] for row in cursor.fetchall()}

        # Get config for per-person consumption
        cursor = conn.execute("SELECT key, value FROM config WHERE key IN ('water_per_person_per_day', 'food_per_person_per_day')")
        config = {row['key']: float(row['value']) for row in cursor.fetchall()}

        # Calculate survival days
        people_count = headcount['checked_in'] or 1
        water_days = (resources.get('water', 0) / (config.get('water_per_person_per_day', 3) * people_count)) if people_count > 0 else 0
        food_days = (resources.get('food', 0) / (config.get('food_per_person_per_day', 2100) * people_count)) if people_count > 0 else 0

        # Equipment pending checks count
        cursor = conn.execute("""
            SELECT COUNT(*) as count FROM inventory
            WHERE category = 'equipment'
            AND check_interval_days IS NOT NULL
            AND (
                last_check_date IS NULL
                OR DATE(last_check_date, '+' || check_interval_days || ' days') <= DATE('now')
            )
        """)
        equipment_pending = cursor.fetchone()['count']

        return {
            "headcount": headcount,
            "inventory_total": inventory_total,
            "equipment_ok": equipment_ok,
            "messages_pending": messages_pending,
            "survival_days": {
                "water": round(water_days, 1),
                "food": round(food_days, 1)
            },
            "inventory_alerts": alerts,
            "equipment_pending": equipment_pending,
            "is_demo": IS_VERCEL
        }


# ============================================================================
# Static File Serving
# ============================================================================

# Portal entry page
@app.get("/portal")
@app.get("/portal/")
async def serve_portal():
    """Serve portal index.html"""
    portal_index = PORTAL_DIR / 'index.html'
    if portal_index.exists():
        return FileResponse(str(portal_index))
    return {"error": "Portal not found"}

# Frontend PWA
@app.get("/frontend")
@app.get("/frontend/")
async def serve_frontend():
    """Serve frontend index.html"""
    frontend_index = FRONTEND_DIR / 'index.html'
    if frontend_index.exists():
        return FileResponse(str(frontend_index))
    return {"error": "Frontend not found"}

# Mount static directories (only if they exist and not on Vercel)
# On Vercel, static files are served by the static build
if not IS_VERCEL:
    # Mount mobile PWA first (more specific path)
    if MOBILE_DIR.exists():
        app.mount("/mobile", StaticFiles(directory=str(MOBILE_DIR), html=True), name="mobile")

    if FRONTEND_DIR.exists():
        app.mount("/frontend", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")

    if PORTAL_DIR.exists():
        app.mount("/portal", StaticFiles(directory=str(PORTAL_DIR), html=True), name="portal")

    if FILES_DIR.exists():
        app.mount("/files", StaticFiles(directory=str(FILES_DIR), html=True), name="files")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8090)
