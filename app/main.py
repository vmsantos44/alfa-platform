"""
Alfa Operations Platform - Main Application
FastAPI entry point with Jinja2 templates
"""
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from contextlib import asynccontextmanager

from app.config import HOST, PORT, DEBUG
from app.core.database import init_db
from app.routes import chat, api, webhooks, oauth, dashboard, candidates, sync, interviews, reports, tasks, alerts
from app.services.scheduler import start_scheduler, stop_scheduler

# Template directory
BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    # Startup
    print("=" * 50)
    print("  ALFA OPERATIONS PLATFORM")
    print("=" * 50)
    print(f"  Host: {HOST}")
    print(f"  Port: {PORT}")
    print(f"  Debug: {DEBUG}")

    # Initialize database
    await init_db()

    # Start background scheduler for auto-sync (every 30 minutes)
    print("  Starting auto-sync scheduler...")
    start_scheduler(interval_minutes=30, run_immediately=False)

    print("=" * 50)
    yield
    # Shutdown
    print("Stopping scheduler...")
    stop_scheduler()
    print("Alfa Operations Platform shutting down...")


app = FastAPI(
    title="Alfa Operations Platform",
    description="Unified operations dashboard for interpreter recruitment",
    version="2.0.0",
    lifespan=lifespan
)

# Templates
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routers
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["Dashboard"])
app.include_router(candidates.router, prefix="/api/candidates", tags=["Candidates"])
app.include_router(interviews.router, prefix="/api/interviews", tags=["Interviews"])
app.include_router(tasks.router, prefix="/api/tasks", tags=["Tasks"])
app.include_router(alerts.router, prefix="/api/alerts", tags=["Alerts"])
app.include_router(sync.router, prefix="/api/sync", tags=["Sync"])
app.include_router(reports.router, prefix="/api/reports", tags=["Reports"])
app.include_router(chat.router, prefix="/api/chat", tags=["Chat"])
app.include_router(api.router, prefix="/api", tags=["API"])
app.include_router(webhooks.router, prefix="/webhooks", tags=["Webhooks"])
app.include_router(oauth.router, prefix="/oauth", tags=["OAuth"])


# Health check endpoint
@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "alfa-platform"}


# ============================================
# Page Routes (Server-rendered HTML)
# ============================================

@app.get("/", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    """Dashboard home page"""
    return templates.TemplateResponse("dashboard.html", {"request": request})


@app.get("/candidates", response_class=HTMLResponse)
async def candidates_page(request: Request):
    """Candidate pipeline page"""
    return templates.TemplateResponse("candidates.html", {"request": request})


@app.get("/candidates/{candidate_id}", response_class=HTMLResponse)
async def candidate_detail_page(request: Request, candidate_id: int):
    """Candidate detail page"""
    return templates.TemplateResponse("candidate_detail.html", {"request": request})


@app.get("/scheduling", response_class=HTMLResponse)
async def scheduling_page(request: Request):
    """Scheduling/Calendar page"""
    return templates.TemplateResponse("scheduling.html", {"request": request})


@app.get("/billing", response_class=HTMLResponse)
async def billing_page(request: Request):
    """Billing page (Zoho Books)"""
    return templates.TemplateResponse("billing.html", {"request": request})


@app.get("/reports", response_class=HTMLResponse)
async def reports_page(request: Request):
    """Reports page"""
    return templates.TemplateResponse("reports.html", {"request": request})


@app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    """Chat assistant page"""
    return templates.TemplateResponse("chat.html", {"request": request})


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """Settings page"""
    return templates.TemplateResponse("settings.html", {"request": request})


# Mount static files - must be last
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=HOST,
        port=PORT,
        reload=DEBUG
    )
