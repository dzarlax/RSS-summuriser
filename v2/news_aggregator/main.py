"""Main FastAPI application."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse

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

# Auth routes
from .auth_api import router as auth_router
app.include_router(auth_router)

# Admin routes
from .admin import router as admin_router
app.include_router(admin_router, prefix="/admin")

# Public routes
from .public import router as public_router
app.include_router(public_router)


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Main page - news feed."""
    return templates.TemplateResponse("public/feed.html", {
        "request": request,
        "title": "Новости"
    })


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.get("/auth-status")
async def auth_status():
    """Check authentication configuration status."""
    from .auth import get_admin_auth_status
    return get_admin_auth_status()


@app.get("/test-db")
async def test_db():
    """Test database connection."""
    from .database import AsyncSessionLocal
    from .models import Article
    from sqlalchemy import select, func
    
    try:
        async with AsyncSessionLocal() as session:
            # Count articles
            count_result = await session.execute(select(func.count(Article.id)))
            count = count_result.scalar()
            
            # Get latest articles
            result = await session.execute(
                select(Article).order_by(Article.fetched_at.desc()).limit(3)
            )
            articles = result.scalars().all()
            
            return {
                "status": "success",
                "total_articles": count,
                "latest_articles": [
                    {
                        "id": a.id,
                        "title": a.title[:50] + "..." if len(a.title) > 50 else a.title,
                        "source_id": a.source_id,
                        "fetched_at": a.fetched_at.isoformat() if a.fetched_at else None
                    }
                    for a in articles
                ]
            }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }


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