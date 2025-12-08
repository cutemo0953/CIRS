"""
CIRS - Community Inventory Resilience System
FastAPI Backend Entry Point
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import os

from database import init_db

# Import routes
from routes import auth, inventory, person, events, messages, system


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    # Startup: Initialize database
    print("Starting CIRS Backend...")
    init_db()
    yield
    # Shutdown
    print("Shutting down CIRS Backend...")


# Create FastAPI app
app = FastAPI(
    title="CIRS API",
    description="Community Inventory Resilience System API",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware (allow all for development)
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


@app.get("/")
async def root():
    """Root endpoint - redirect to API docs"""
    return {
        "name": "CIRS API",
        "version": "1.0.0",
        "docs": "/docs",
        "status": "running"
    }


@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}


@app.get("/api/stats")
async def get_stats():
    """Get system statistics"""
    from database import get_db, dict_from_row

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

        return {
            "headcount": headcount,
            "survival_days": {
                "water": round(water_days, 1),
                "food": round(food_days, 1)
            },
            "inventory_alerts": alerts
        }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8090)
