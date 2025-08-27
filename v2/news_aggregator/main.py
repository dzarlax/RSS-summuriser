"""Main FastAPI application."""

from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse

from .config import settings
from .database import init_db, AsyncSessionLocal
from .migrations.universal_migration_manager import create_migration_manager
from .migrations.multiple_categories_migration import MultipleCategoriesMigration
from .migrations.media_files_migration import MediaFilesMigration
from .migrations.remove_legacy_category_migration import RemoveLegacyCategoryMigration
from .migrations.fixed_categories_migration import FixedCategoriesMigration
from .migrations.category_mapping_migration import CategoryMappingMigration

import logging

logger = logging.getLogger(__name__)


# Create migration manager
migration_manager = create_migration_manager(AsyncSessionLocal, "RSS Summarizer v2")

# Register migrations
multiple_categories_migration = MultipleCategoriesMigration()
migration_manager.register_migration(multiple_categories_migration)

media_files_migration = MediaFilesMigration()
migration_manager.register_migration(media_files_migration)

remove_legacy_category_migration = RemoveLegacyCategoryMigration()
migration_manager.register_migration(remove_legacy_category_migration)

fixed_categories_migration = FixedCategoriesMigration()
migration_manager.register_migration(fixed_categories_migration)

category_mapping_migration = CategoryMappingMigration()
migration_manager.register_migration(category_mapping_migration)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    # Record application start time for health endpoints
    app.state.started_at = datetime.utcnow()
    await init_db()
    
    # Run automatic migrations
    try:
        print("🔍 Checking for database migrations...")
        migration_results = await migration_manager.check_and_run_migrations()
        
        if migration_results['migrations_run']:
            print(f"✅ Applied {len(migration_results['migrations_run'])} migrations")
            for migration in migration_results['migrations_run']:
                print(f"   - {migration['id']}: {migration['description']}")
        
        if migration_results['errors']:
            print(f"⚠️ Migration errors: {migration_results['errors']}")
            
    except Exception as e:
        print(f"❌ Migration system error: {e}")
        # Don't prevent app startup on migration errors
    
    # Start universal database queue system
    from .services.database_queue import get_database_queue
    db_queue = get_database_queue()
    try:
        print("🔄 Starting database queue...")
        await db_queue.start()
        print("✅ Database queue started successfully")
    except Exception as e:
        print(f"❌ Database queue startup error: {e}")
        import traceback
        traceback.print_exc()
        # Don't prevent app startup on queue errors
    
    # Start task scheduler
    from .services.scheduler import start_scheduler
    try:
        print("🔄 Starting task scheduler...")
        await start_scheduler()
        print("✅ Task scheduler started successfully")
    except Exception as e:
        print(f"❌ Task scheduler startup error: {e}")
        import traceback
        traceback.print_exc()
        # Don't prevent app startup on scheduler errors
    
    yield
    
    # Shutdown
    from .services.scheduler import stop_scheduler
    await stop_scheduler()
    
    # Stop database queue system
    await db_queue.stop()


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
    """Main page - news list (default view)."""
    return templates.TemplateResponse("public/list.html", {
        "request": request,
        "title": "Лента новостей"
    })



@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.get("/health/app")
async def health_app():
    """Application health info with version and start time."""
    started_at = getattr(app.state, "started_at", None)
    started_at_iso = started_at.isoformat() if started_at else None
    uptime_seconds = (datetime.utcnow() - started_at).total_seconds() if started_at else None
    return {
        "version": app.version,
        "started_at": started_at_iso,
        "uptime_seconds": uptime_seconds
    }


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