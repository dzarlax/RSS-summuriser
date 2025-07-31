"""Main FastAPI application."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import settings
from .database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    await init_db()
    
    # Start task scheduler
    from .services.scheduler import start_scheduler
    await start_scheduler()
    
    yield
    
    # Shutdown
    from .services.scheduler import stop_scheduler
    await stop_scheduler()


app = FastAPI(
    title="RSS Summarizer v2",
    description="Modern news aggregator with deduplication and web management",
    version="2.0.0",
    lifespan=lifespan
)

# Статические файлы
app.mount("/static", StaticFiles(directory="web/static"), name="static")

# Шаблоны
templates = Jinja2Templates(directory="web/templates")

# API routes
from .api import router as api_router
app.include_router(api_router, prefix="/api/v1")

# Admin routes
from .admin import router as admin_router
app.include_router(admin_router, prefix="/admin")

# Public routes
from .public import router as public_router
app.include_router(public_router)


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "RSS Summarizer v2.0",
        "status": "running",
        "admin": "/admin",
        "api": "/api/v1",
        "docs": "/docs"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


if __name__ == "__main__":
    import sys
    
    # Check if running as CLI
    if len(sys.argv) > 1 and sys.argv[1] in ['process', 'sources', 'add-source', 'test-source', 'stats', 'config']:
        from .cli import cli
        cli()
    else:
        # Run as web server
        import uvicorn
        uvicorn.run(
            "news_aggregator.main:app",
            host="0.0.0.0",
            port=8000,
            reload=settings.development
        )