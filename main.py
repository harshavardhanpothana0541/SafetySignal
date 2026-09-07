# main.py
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from app.database import engine
from app import models
from app.routers import emergency, auth, telephony, aiops_engine
from app.routers.emergency import monitor_abandoned_incidents, admin_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Launch the anti-abandonment watchdog loop
    watchdog_task = asyncio.create_task(monitor_abandoned_incidents())
    yield
    # Shutdown: Cleanly cancel the background task
    watchdog_task.cancel()

# Create SQLite tables
models.Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="SafetySignal AIOps & Autonomous Dispatch API",
    version="2.0.0",
    description="Multi-Channel Telemetry Ingestion, Dynamic Correlation, and Self-Healing Infrastructure Engine",
    lifespan=lifespan
)

# Enable CORS for Cross-Origin PWA Handshakes
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static directory for CSS, JS, and Assets
app.mount("/static", StaticFiles(directory="static"), name="static")

# Mount Routers
app.include_router(emergency.router)
app.include_router(admin_router)        # Step 1 & Step 4: Admin Purge & Responder Management
app.include_router(auth.router)
app.include_router(telephony.router)
app.include_router(aiops_engine.router)

# --- Template Routes ---

@app.get("/")
async def serve_home():
    """Victim Mobile-First 1-Tap SOS Interface"""
    return FileResponse("templates/index.html")

@app.get("/responder")
async def serve_responder():
    """Tactical Responder / SRE HUD with Live Map & Geofence Lock"""
    return FileResponse("templates/responder.html")

@app.get("/admin/dashboard")
async def serve_dashboard():
    """Admin Telemetry, 112 CAD Integration & Fleet Oversight"""
    return FileResponse("templates/dashboard.html")

# Root PWA Manifest Link
@app.get("/manifest.json")
async def serve_manifest():
    return FileResponse("static/manifest.json", media_type="application/manifest+json")

# Root Service Worker Link (with Root-Scope permission header)
@app.get("/sw.js")
async def serve_sw():
    return FileResponse(
        "static/sw.js",
        media_type="application/javascript",
        headers={
            "Service-Worker-Allowed": "/",
            "Cache-Control": "no-cache, no-store, must-revalidate"
        }
    )