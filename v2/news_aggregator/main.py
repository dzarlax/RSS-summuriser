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

import logging
from typing import Dict, Any
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def _check_multiple_categories_needed(db: AsyncSession) -> bool:
    """Check if multiple categories migration is needed."""
    try:
        # Check if categories table exists by trying to query it
        try:
            await db.execute(text("SELECT 1 FROM categories LIMIT 1"))
            await db.execute(text("SELECT 1 FROM article_categories LIMIT 1"))
        except:
            logger.info("📋 Categories tables not found - migration needed")
            return True
        
        # Check if we have any composite categories to migrate
        result = await db.execute(text("""
            SELECT COUNT(*) FROM articles 
            WHERE category IS NOT NULL 
            AND (
                category LIKE '%|%' OR 
                category LIKE '%/%' OR 
                category LIKE '%,%' OR 
                category LIKE '% and %' OR 
                category LIKE '% & %'
            )
        """))
        
        composite_count = result.scalar()
        
        # Check if we have articles with categories but no article_categories entries
        result = await db.execute(text("""
            SELECT COUNT(*) FROM articles a
            WHERE a.category IS NOT NULL 
            AND NOT EXISTS (
                SELECT 1 FROM article_categories ac 
                WHERE ac.article_id = a.id
            )
        """))
        
        unmigrated_count = result.scalar()
        
        if composite_count > 0:
            logger.info(f"📊 Found {composite_count} composite categories to migrate")
            return True
            
        if unmigrated_count > 0:
            logger.info(f"📊 Found {unmigrated_count} unmigrated articles")
            return True
        
        logger.info("✅ Multiple categories migration not needed")
        return False
        
    except Exception as e:
        logger.warning(f"Could not check migration status: {e}")
        # If we can't check, assume migration is needed for safety
        return True


async def _migrate_multiple_categories(db: AsyncSession) -> Dict[str, Any]:
    """Execute multiple categories migration."""
    migration_result = {
        'schema_created': False,
        'simple_categories_migrated': 0,
        'composite_categories_migrated': 0,
        'total_relationships_created': 0,
        'errors': []
    }
    
    try:
        logger.info("🔧 Creating schema for multiple categories...")
        
        # Step 1: Create schema
        schema_sql = """
        -- Create categories table
        CREATE TABLE IF NOT EXISTS categories (
            id SERIAL PRIMARY KEY,
            name VARCHAR(50) NOT NULL UNIQUE,
            display_name VARCHAR(100) NOT NULL,
            description TEXT,
            color VARCHAR(7) DEFAULT '#6c757d',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Create junction table
        CREATE TABLE IF NOT EXISTS article_categories (
            id SERIAL PRIMARY KEY,
            article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
            category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
            confidence FLOAT DEFAULT 1.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(article_id, category_id)
        );

        -- Create indexes
        CREATE INDEX IF NOT EXISTS idx_article_categories_article_id ON article_categories(article_id);
        CREATE INDEX IF NOT EXISTS idx_article_categories_category_id ON article_categories(category_id);
        CREATE INDEX IF NOT EXISTS idx_article_categories_confidence ON article_categories(confidence);
        """
        
        statements = [stmt.strip() for stmt in schema_sql.split(';') if stmt.strip()]
        for stmt in statements:
            if stmt.strip():
                await db.execute(text(stmt))
        
        await db.commit()
        migration_result['schema_created'] = True
        logger.info("✅ Schema created")
        
        # Step 2: Insert default categories
        await db.execute(text("""
            INSERT INTO categories (name, display_name, description, color) VALUES
                ('Business', 'Бизнес', 'Экономика, финансы, компании, инвестиции', '#28a745'),
                ('Tech', 'Технологии', 'IT, софтвер, инновации, стартапы', '#007bff'),
                ('Science', 'Наука', 'Исследования, медицина, открытия', '#6f42c1'),
                ('Serbia', 'Сербия', 'Новости Сербии, политика, общество', '#dc3545'),
                ('Other', 'Прочее', 'Остальные новости', '#6c757d')
            ON CONFLICT (name) DO NOTHING
        """))
        await db.commit()
        logger.info("✅ Default categories inserted")
        
        # Step 3: Migrate simple categories (including unmigrated articles)
        result = await db.execute(text("""
            INSERT INTO article_categories (article_id, category_id, confidence)
            SELECT 
                a.id as article_id,
                c.id as category_id,
                1.0 as confidence
            FROM articles a
            JOIN categories c ON c.name = a.category
            WHERE a.category IS NOT NULL
              AND a.category NOT LIKE '%|%'
              AND a.category NOT LIKE '%/%'
              AND a.category NOT LIKE '%,%'
              AND a.category NOT LIKE '% and %'
              AND a.category NOT LIKE '% & %'
              AND NOT EXISTS (
                  SELECT 1 FROM article_categories ac 
                  WHERE ac.article_id = a.id
              )
            ON CONFLICT (article_id, category_id) DO NOTHING
        """))
        
        migration_result['simple_categories_migrated'] = result.rowcount
        await db.commit()
        logger.info(f"✅ Migrated {result.rowcount} simple categories")
        
        # Step 4: Migrate composite categories
        composite_result = await _migrate_composite_categories_internal(db)
        migration_result['composite_categories_migrated'] = composite_result['processed']
        migration_result['total_relationships_created'] += composite_result['relationships_created']
        
        # Step 5: Get final statistics
        result = await db.execute(text("SELECT COUNT(*) FROM article_categories"))
        migration_result['total_relationships_created'] = result.scalar()
        
        logger.info(f"🎉 Migration completed successfully!")
        logger.info(f"   Simple categories: {migration_result['simple_categories_migrated']}")
        logger.info(f"   Composite categories: {migration_result['composite_categories_migrated']}")
        logger.info(f"   Total relationships: {migration_result['total_relationships_created']}")
        
        return migration_result
        
    except Exception as e:
        error_msg = f"Migration failed: {str(e)}"
        logger.error(error_msg)
        migration_result['errors'].append(error_msg)
        await db.rollback()
        raise


async def _migrate_composite_categories_internal(db: AsyncSession) -> Dict[str, int]:
    """Internal function to migrate composite categories."""
    logger.info("🔀 Migrating composite categories...")
    
    # Find composite categories
    result = await db.execute(text("""
        SELECT id, category, title 
        FROM articles 
        WHERE category IS NOT NULL 
        AND (
            category LIKE '%|%' OR 
            category LIKE '%/%' OR 
            category LIKE '%,%' OR 
            category LIKE '% and %' OR 
            category LIKE '% & %'
        )
        ORDER BY id
    """))
    
    composite_articles = result.fetchall()
    logger.info(f"🔍 Found {len(composite_articles)} composite categories")
    
    if not composite_articles:
        return {'processed': 0, 'relationships_created': 0}
    
    # Get valid categories
    cat_result = await db.execute(text("SELECT name, id FROM categories"))
    valid_categories = {name: cat_id for name, cat_id in cat_result.fetchall()}
    
    stats = {'processed': 0, 'relationships_created': 0}
    
    for article_id, composite_category, title in composite_articles:
        try:
            # Parse composite category
            categories_to_assign = []
            separators = ['|', '/', ',', ' and ', ' & ']
            parts = [composite_category]
            
            for sep in separators:
                if sep in composite_category:
                    parts = [p.strip() for p in composite_category.split(sep)]
                    break
            
            # Find valid categories
            for part in parts:
                clean_part = part.strip()
                if clean_part in valid_categories:
                    categories_to_assign.append((clean_part, valid_categories[clean_part]))
            
            if not categories_to_assign and 'Other' in valid_categories:
                categories_to_assign.append(('Other', valid_categories['Other']))
            
            # Remove existing relationships for this article
            await db.execute(
                text("DELETE FROM article_categories WHERE article_id = :article_id"),
                {'article_id': article_id}
            )
            
            # Add new relationships
            for cat_name, cat_id in categories_to_assign:
                await db.execute(text("""
                    INSERT INTO article_categories (article_id, category_id, confidence)
                    VALUES (:article_id, :category_id, 1.0)
                    ON CONFLICT (article_id, category_id) DO NOTHING
                """), {
                    'article_id': article_id,
                    'category_id': cat_id
                })
                stats['relationships_created'] += 1
            
            # Update the legacy category field to the first assigned category
            if categories_to_assign:
                first_category = categories_to_assign[0][0]
                await db.execute(text("""
                    UPDATE articles SET category = :category WHERE id = :article_id
                """), {
                    'category': first_category,
                    'article_id': article_id
                })
            
            stats['processed'] += 1
            
            # Commit every 100 articles to avoid long transactions
            if stats['processed'] % 100 == 0:
                await db.commit()
                logger.info(f"   Processed {stats['processed']} composite categories...")
            
        except Exception as e:
            logger.warning(f"Failed to migrate article {article_id}: {e}")
            continue
    
    await db.commit()
    logger.info(f"✅ Composite categories migration completed: {stats['processed']} articles, {stats['relationships_created']} relationships")
    
    return stats


# Create migration manager
migration_manager = create_migration_manager(AsyncSessionLocal, "RSS Summarizer v2")

# Register multiple categories migration
migration_manager.register_custom_migration(
    migration_id='002_multiple_categories',
    description='Add support for multiple categories per article',
    version='2.0.0',
    check_function=_check_multiple_categories_needed,
    migrate_function=_migrate_multiple_categories
)


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
    await db_queue.start()
    
    # Start task scheduler
    from .services.scheduler import start_scheduler
    await start_scheduler()
    
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