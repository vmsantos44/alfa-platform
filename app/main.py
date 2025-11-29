"""
Alfa AI Platform - Main Application
FastAPI entry point
"""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.config import HOST, PORT, DEBUG
from app.routes import chat, api, webhooks


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    # Startup
    print("🚀 Alfa AI Platform starting...")
    print(f"   Host: {HOST}")
    print(f"   Port: {PORT}")
    print(f"   Debug: {DEBUG}")
    yield
    # Shutdown
    print("👋 Alfa AI Platform shutting down...")


app = FastAPI(
    title="Alfa AI Platform",
    description="Unified platform for Zoho integrations and AI assistant",
    version="2.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(chat.router, prefix="/chat", tags=["Chat"])
app.include_router(api.router, prefix="/api", tags=["API"])
app.include_router(webhooks.router, prefix="/webhooks", tags=["Webhooks"])


# Health check endpoint
@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "alfa-platform"}


# Mount static files (Chat UI) - must be last
app.mount("/", StaticFiles(directory="static", html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=HOST,
        port=PORT,
        reload=DEBUG
    )
