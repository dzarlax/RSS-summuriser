"""API routes."""

import os
import logging
import asyncio
import subprocess
import html
from datetime import datetime, timedelta
from typing import List, Optional
from pathlib import Path

from fastapi import APIRouter, Depends, Query, HTTPException, BackgroundTasks, UploadFile, File, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func, text
from sqlalchemy.orm import selectinload

from .database import get_db, engine, AsyncSessionLocal
from .config import settings
from .models import Article, Source, ProcessingStat, DailySummary, ScheduleSettings, CategoryMapping
from .services.source_manager import SourceManager
from .main import migration_manager
# from .security import require_api_read, require_api_write, require_admin, limiter
from .services.extraction_memory import get_extraction_memory


class CreateSourceRequest(BaseModel):
    name: str
    source_type: str
    url: str
    is_active: bool = True
    update_interval: int = 60


class UpdateSourceRequest(BaseModel):
    name: Optional[str] = None
    source_type: Optional[str] = None
    url: Optional[str] = None
    is_active: Optional[bool] = None
    update_interval: Optional[int] = None

router = APIRouter()


@router.get("/")
async def api_root():
    """API root endpoint with available endpoints."""
    return {
        "message": "RSS Summarizer v2 API",
        "version": "2.0.0",
        "endpoints": {
            "feed": "/api/v1/feed - Get news feed",
            "rss": "/api/v1/feed.rss - RSS feed",
            "categories": "/api/v1/categories - Get categories",
            "sources": "/api/v1/sources - Get sources",
            "summaries": "/api/v1/summaries/daily - Daily summaries",
            "generate_summaries": "/api/v1/summaries/generate - Generate daily summaries",
            "process": "/api/v1/process - Trigger processing",
            "telegram": "/api/v1/telegram/send-digest - Send Telegram digest",
            "backup": "/api/v1/backup - Backup management",
            "restore": "/api/v1/restore - Restore from backup"
        },
        "documentation": "/docs",
        "timestamp": datetime.utcnow().isoformat()
    }


@router.get("/feed")
async def get_main_feed(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    since_hours: Optional[int] = Query(None, ge=1, le=168),  # Max 1 week
    category: Optional[str] = Query(None, description="Filter by category"),
    db: AsyncSession = Depends(get_db)
):
    """Get main news feed in JSON format."""
    # Build query for articles with categories
    from .models import ArticleCategory
    query = select(Article).options(
        selectinload(Article.source),
        selectinload(Article.article_categories).selectinload(ArticleCategory.category)
    ).order_by(desc(Article.fetched_at))
    
    # Apply time filter
    if since_hours:
        since_time = datetime.utcnow() - timedelta(hours=since_hours)
        query = query.where(Article.published_at >= since_time)
    
    # Apply category filter
    if category and category.lower() != 'all':
        if category.lower() == 'advertisements':
            # Filter for advertising content
            query = query.where(Article.is_advertisement == True)
        else:
            # Filter by category using new junction table
            from .models import ArticleCategory, Category
            query = query.join(ArticleCategory).join(Category).where(
                func.lower(Category.name) == category.lower()
            )
    
    # Apply pagination
    query = query.offset(offset).limit(limit)
    
    # Execute query
    result = await db.execute(query)
    articles = result.scalars().all()
    
    # Format response
    feed_items = []
    for article in articles:
        domain = extract_domain(article.url) if article.url else "unknown"
        
        # Clean summary from service text
        cleaned_summary = clean_summary_text(article.summary) if article.summary else None
        
        feed_items.append({
            "article_id": article.id,
            "title": clean_html_entities(article.title) if article.title else None,
            "summary": clean_html_entities(cleaned_summary) if cleaned_summary else None,
            "content": clean_html_entities(article.content[:500] + "..." if article.content and len(article.content) > 500 else article.content) if article.content else None,
            "image_url": article.image_url,  # Legacy single image field for backward compatibility
            "media_files": article.media_files or [],  # New multiple media files
            "images": article.images,  # Convenience property for images only
            "videos": article.videos,  # Convenience property for videos only
            "documents": article.documents,  # Convenience property for documents only
            "primary_image": article.primary_image,  # Primary image URL (first image or legacy image_url)
            "url": article.url,
            "domain": domain,
            "category": article.primary_category,  # Primary category for backward compatibility
            "categories": article.categories_with_confidence,  # New multiple categories
            "published_at": article.published_at.isoformat() if article.published_at else None,
            "fetched_at": article.fetched_at.isoformat() if article.fetched_at else None,
            # Advertising detection data
            "is_advertisement": bool(getattr(article, 'is_advertisement', False)),
            "ad_confidence": float(getattr(article, 'ad_confidence', 0.0)),
            "ad_type": getattr(article, 'ad_type', None),
            "ad_reasoning": getattr(article, 'ad_reasoning', None)
        })
    
    return {
        "version": "2.0",
        "title": "RSS Summarizer v2 Feed",
        "updated_at": datetime.utcnow().isoformat(),
        "items": feed_items,
        "pagination": {
            "limit": limit,
            "offset": offset,
            "count": len(feed_items),
            "category": category  # Include current filter in response
        }
    }


@router.get("/feed.rss")
async def get_rss_feed(
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db)
):
    """RSS compatibility endpoint."""
    from xml.etree.ElementTree import Element, SubElement, tostring
    from xml.dom import minidom
    
    # Get articles
    query = select(Article).order_by(desc(Article.published_at)).limit(limit)
    
    result = await db.execute(query)
    articles = result.scalars().all()
    
    # Create RSS XML
    rss = Element("rss", version="2.0")
    channel = SubElement(rss, "channel")
    
    # Channel metadata
    SubElement(channel, "title").text = "RSS Summarizer v2"
    SubElement(channel, "link").text = "http://localhost:8000"
    SubElement(channel, "description").text = "Aggregated news feed"
    SubElement(channel, "generator").text = "RSS Summarizer v2.0"
    SubElement(channel, "lastBuildDate").text = datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT")
    
    # Add items
    for article in articles:
        item = SubElement(channel, "item")
        SubElement(item, "title").text = clean_html_entities(article.title) if article.title else ""
        SubElement(item, "link").text = article.url
        SubElement(item, "description").text = clean_html_entities(article.summary or article.title) if (article.summary or article.title) else ""
        SubElement(item, "guid").text = str(article.id)
        if article.published_at:
            SubElement(item, "pubDate").text = article.published_at.strftime("%a, %d %b %Y %H:%M:%S GMT")
    
    # Format XML
    rough_string = tostring(rss, 'utf-8')
    reparsed = minidom.parseString(rough_string)
    
    from fastapi.responses import Response
    return Response(
        content=reparsed.toprettyxml(indent="  "),
        media_type="application/rss+xml"
    )


@router.get("/health/db")
async def health_db():
    """Database health and pool metrics."""
    # Pool metrics
    pool_status = "unavailable"
    pool_details = {}
    try:
        # Basic aggregate string
        pool_status = engine.pool.status()
        # Extended metrics when available
        # Note: SQLAlchemy's public API exposes only status() string; any deeper
        # pool internals are implementation details and may not be stable.
        pool_details = {"raw_status": str(pool_status)}
    except Exception:
        pass
    # Simple connectivity check using a short session
    try:
        from sqlalchemy import text
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return {"ok": True, "pool": {"status": str(pool_status), **pool_details}}
    except Exception as e:
        return {"ok": False, "pool": {"status": str(pool_status), **pool_details}, "error": str(e)}


@router.get("/categories")
async def get_categories(db: AsyncSession = Depends(get_db)):
    """Get all available categories with article counts."""
    from .models import Category, ArticleCategory
    
    # Get categories from new table with article counts
    result = await db.execute(
        select(
            Category.name,
            Category.display_name,
            Category.description,
            Category.color,
            func.count(ArticleCategory.article_id).label('count')
        )
        .outerjoin(ArticleCategory)
        .group_by(Category.id, Category.name, Category.display_name, Category.description, Category.color)
        .order_by(func.count(ArticleCategory.article_id).desc())
    )
    
    categories = []
    total_count = 0
    
    for name, display_name, description, color, count in result.all():
        categories.append({
            "category": name,
            "display_name": display_name,
            "description": description,
            "color": color,
            "count": count
        })
        total_count += count
    
    # Get advertising count
    ad_result = await db.execute(
        select(func.count(Article.id).label('ad_count'))
        .where(Article.is_advertisement == True)
    )
    ad_count = ad_result.scalar() or 0
    
    # Add advertising as a special category if there are any ads
    if ad_count > 0:
        categories.append({
            "category": "advertisements",
            "count": ad_count
        })
    
    return {
        "categories": categories,
        "total_articles": total_count,
        "advertisements": ad_count
    }


@router.get("/sources")
async def get_sources_api(
    db: AsyncSession = Depends(get_db)
):
    """Get all news sources."""
    source_manager = SourceManager()
    sources = await source_manager.get_sources(db)
    
    # Get article counts for each source
    article_counts = {}
    for source in sources:
        count_result = await db.execute(
            select(func.count(Article.id)).where(Article.source_id == source.id)
        )
        article_counts[source.id] = count_result.scalar() or 0
    
    return {
        "sources": [
            {
                "id": source.id,
                "name": source.name,
                "source_type": source.source_type,
                "url": source.url,
                "is_active": source.enabled,
                "last_updated": source.last_fetch.isoformat() if source.last_fetch else None,
                "last_success": source.last_success.isoformat() if source.last_success else None,
                "articles_count": article_counts.get(source.id, 0),
                "error_count": source.error_count,
                "last_error": source.last_error
            }
            for source in sources
        ]
    }


@router.post("/sources")
async def create_source(
    source_data: CreateSourceRequest,
    db: AsyncSession = Depends(get_db)
    # TODO: Add admin auth when security is fixed
):
    """Create a new news source."""
    try:
        print(f"Creating source with data: {source_data}")
        source_manager = SourceManager()
        
        # Create source
        source = await source_manager.create_source(
            db,
            name=source_data.name,
            source_type=source_data.source_type,
            url=source_data.url
        )
        
        # Set active status
        source.enabled = source_data.is_active
        await db.commit()
        
        return {
            "id": source.id,
            "name": source.name,
            "source_type": source.source_type,
            "url": source.url,
            "is_active": source.enabled,
            "created_at": source.created_at.isoformat() if source.created_at else None
        }
        
    except Exception as e:
        print(f"Error creating source: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/sources/{source_id}/test")
async def test_source(source_id: int, db: AsyncSession = Depends(get_db)):
    """Test a specific source connection."""
    try:
        source_manager = SourceManager()
        
        # Get the source
        source = await db.get(Source, source_id)
        if not source:
            raise HTTPException(status_code=404, detail="Source not found")
        
        # Test the source
        success = await source_manager.test_source_connection(db, source_id)
        
        if success:
            return {
                "success": True,
                "message": "Source connection successful",
                "source_id": source_id,
                "source_name": source.name
            }
        else:
            return {
                "success": False,
                "message": "Source connection failed",
                "source_id": source_id,
                "source_name": source.name
            }
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error testing source: {str(e)}")


@router.put("/sources/{source_id}")
async def update_source(
    source_id: int,
    source_data: UpdateSourceRequest, 
    db: AsyncSession = Depends(get_db)
):
    """Update an existing source."""
    try:
        source_manager = SourceManager()
        
        # Get the source
        source = await db.get(Source, source_id)
        if not source:
            raise HTTPException(status_code=404, detail="Source not found")
        
        # Update only provided fields
        update_fields = {}
        if source_data.name is not None:
            update_fields['name'] = source_data.name
        if source_data.source_type is not None:
            update_fields['source_type'] = source_data.source_type
        if source_data.url is not None:
            update_fields['url'] = source_data.url
        if source_data.is_active is not None:
            update_fields['enabled'] = source_data.is_active
        if source_data.update_interval is not None:
            update_fields['fetch_interval'] = source_data.update_interval
        
        # Update the source
        updated_source = await source_manager.update_source(db, source_id, **update_fields)
        
        if not updated_source:
            raise HTTPException(status_code=404, detail="Source not found")
        
        return {
            "success": True,
            "message": "Source updated successfully",
            "source": {
                "id": updated_source.id,
                "name": updated_source.name,
                "source_type": updated_source.source_type,
                "url": updated_source.url,
                "is_active": updated_source.enabled,
                "update_interval": updated_source.fetch_interval,
                "updated_at": updated_source.updated_at.isoformat() if updated_source.updated_at else None
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating source: {str(e)}")


@router.patch("/sources/{source_id}/toggle")
async def toggle_source_status(source_id: int, db: AsyncSession = Depends(get_db)):
    """Toggle source active/inactive status."""
    try:
        source_manager = SourceManager()
        
        # Get the source
        source = await db.get(Source, source_id)
        if not source:
            raise HTTPException(status_code=404, detail="Source not found")
        
        # Toggle the enabled status
        new_status = not source.enabled
        updated_source = await source_manager.update_source(db, source_id, enabled=new_status)
        
        return {
            "success": True,
            "message": f"Source {'activated' if new_status else 'deactivated'} successfully",
            "source_id": source_id,
            "is_active": new_status
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error toggling source status: {str(e)}")


@router.delete("/sources/{source_id}")
async def delete_source(
    source_id: int, 
    db: AsyncSession = Depends(get_db)
    # TODO: Add admin auth when security is fixed
):
    """Delete a source."""
    try:
        source_manager = SourceManager()
        
        # Get the source
        source = await db.get(Source, source_id)
        if not source:
            raise HTTPException(status_code=404, detail="Source not found")
        
        # Delete the source
        await source_manager.delete_source(db, source_id)
        
        return {
            "success": True,
            "message": "Source deleted successfully",
            "source_id": source_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting source: {str(e)}")




@router.get("/export/daily")
async def export_daily_data(
    date: Optional[str] = Query(None, description="YYYY-MM-DD format"),
    db: AsyncSession = Depends(get_db)
):
    """Export daily processing data."""
    from datetime import date as date_type
    
    if date:
        try:
            target_date = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    else:
        target_date = datetime.utcnow().date()
    
    # Get articles published on target date
    query = select(Article).where(
        func.date(Article.published_at) == target_date
    ).order_by(Article.published_at.desc())
    
    result = await db.execute(query)
    articles = result.scalars().all()
    
    # Format export data
    export_data = {
        "export_date": target_date.isoformat(),
        "generated_at": datetime.utcnow().isoformat(),
        "articles_count": len(articles),
        "articles": [
            {
                "id": article.id,
                "title": clean_html_entities(article.title) if article.title else None,
                "summary": clean_html_entities(article.summary) if article.summary else None,
                "url": article.url,
                "published_at": article.published_at.isoformat() if article.published_at else None,
                "fetched_at": article.fetched_at.isoformat() if article.fetched_at else None
            }
            for article in articles
        ]
    }
    
    return export_data


@router.get("/stats/dashboard")
async def get_dashboard_stats(db: AsyncSession = Depends(get_db)):
    """Get comprehensive dashboard statistics."""
    from sqlalchemy import func, text, desc
    from datetime import datetime, timedelta
    
    today = datetime.utcnow().date()
    
    # Get sources statistics
    sources_result = await db.execute(
        select(func.count(Source.id)).where(Source.enabled == True)
    )
    active_sources = sources_result.scalar() or 0
    
    total_sources_result = await db.execute(select(func.count(Source.id)))
    total_sources = total_sources_result.scalar() or 0
    
    disabled_sources = total_sources - active_sources
    
    # Get articles statistics
    today_articles_result = await db.execute(
        select(func.count(Article.id)).where(
            func.date(Article.published_at) == today
        )
    )
    today_articles = today_articles_result.scalar() or 0
    
    total_articles_result = await db.execute(select(func.count(Article.id)))
    total_articles = total_articles_result.scalar() or 0
    
    # Get processed articles today
    processed_today_result = await db.execute(
        select(func.count(Article.id)).where(
            func.date(Article.fetched_at) == today,
            Article.processed == True
        )
    )
    processed_today = processed_today_result.scalar() or 0
    
    # Get categories statistics using new system
    from .models import Category, ArticleCategory
    categories_result = await db.execute(
        select(func.count(func.distinct(Category.id)))
        .join(ArticleCategory)
    )
    categories_count = categories_result.scalar() or 0
    
    # Get most popular category using new system
    top_category_result = await db.execute(
        select(Category.name, func.count(ArticleCategory.article_id).label('count'))
        .join(ArticleCategory)
        .group_by(Category.name)
        .order_by(desc('count'))
        .limit(1)
    )
    top_category_row = top_category_result.first()
    top_category = top_category_row[0] if top_category_row else 'N/A'
    
    # Get latest sync time
    latest_sync_result = await db.execute(
        select(func.max(Source.last_fetch)).where(Source.last_fetch.isnot(None))
    )
    last_sync = latest_sync_result.scalar()
    
    # Get processing stats
    recent_stats_result = await db.execute(
        select(ProcessingStat).where(ProcessingStat.date == today)
    )
    recent_stats = recent_stats_result.scalar_one_or_none()
    
    if recent_stats:
        api_calls_today = recent_stats.api_calls_made or 0
        errors_today = recent_stats.errors_count or 0
        articles_processed = recent_stats.articles_processed or 0
        processing_time = recent_stats.processing_time_seconds or 0
        
        # Calculate API success rate
        if api_calls_today > 0:
            successful_calls = max(0, api_calls_today - errors_today)
            api_success_rate = round((successful_calls / api_calls_today) * 100)
        else:
            api_success_rate = 100
            
        # Calculate average processing time per article
        if articles_processed > 0:
            avg_processing_time = processing_time / articles_processed * 1000  # in ms
        else:
            avg_processing_time = 0
            
        # Calculate articles per hour
        if processing_time > 0:
            articles_per_hour = round((articles_processed / processing_time) * 3600)
        else:
            articles_per_hour = 0
    else:
        api_calls_today = 0
        errors_today = 0
        api_success_rate = 100
        avg_processing_time = 0
        articles_per_hour = 0
    
    return {
        "total_sources": total_sources,
        "active_sources": active_sources,
        "disabled_sources": disabled_sources,
        "today_articles": today_articles,
        "total_articles": total_articles,
        "processed_today": processed_today,
        "categories_count": categories_count,
        "top_category": top_category,
        "api_calls_today": api_calls_today,
        "api_success_rate": api_success_rate,
        "errors_today": errors_today,
        "avg_processing_time": avg_processing_time,
        "articles_per_hour": articles_per_hour,
        "last_sync": last_sync.isoformat() if last_sync else None,
        "last_update": last_sync.isoformat() if last_sync else None
    }


@router.post("/process/run")
async def run_manual_processing():
    # TODO: Add admin auth when security is fixed
    """Run manual news processing."""
    try:
        from .orchestrator import NewsOrchestrator
        import asyncio
        
        # Create orchestrator and run processing
        orchestrator = NewsOrchestrator()
        
        # Run processing in background
        task = asyncio.create_task(orchestrator.run_full_cycle())
        
        return {
            "success": True,
            "message": "News processing started",
            "status": "running"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error starting processing: {str(e)}")


@router.post("/telegram/send-digest")
async def send_telegram_digest():
    """Send current news digest to Telegram."""
    try:
        from .orchestrator import NewsOrchestrator
        
        # Create orchestrator and send digest
        orchestrator = NewsOrchestrator()
        stats = await orchestrator.send_telegram_digest()
        
        return {
            "success": True,
            "message": "Digest sent successfully to Telegram",
            "stats": stats
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error sending digest: {str(e)}")


@router.get("/summaries/daily")
async def get_daily_summaries(
    date: Optional[str] = Query(None, description="YYYY-MM-DD format"),
    category: Optional[str] = Query(None, description="Filter by category"),
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db)
):
    """Get daily summaries by date and/or category."""
    from datetime import date as date_type
    
    query = select(DailySummary).order_by(DailySummary.date.desc(), DailySummary.category)
    
    # Filter by date if provided
    if date:
        try:
            target_date = datetime.strptime(date, "%Y-%m-%d").date()
            query = query.where(func.date(DailySummary.date) == target_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    
    # Filter by category if provided
    if category:
        query = query.where(DailySummary.category == category)
    
    # Apply pagination
    query = query.offset(offset).limit(limit)
    
    result = await db.execute(query)
    summaries = result.scalars().all()
    
    # Format response
    summaries_data = []
    for summary in summaries:
        summaries_data.append({
            "id": summary.id,
            "date": summary.date.isoformat(),
            "category": summary.category,
            "summary_text": summary.summary_text,
            "articles_count": summary.articles_count,
            "created_at": summary.created_at.isoformat() if summary.created_at else None,
            "updated_at": summary.updated_at.isoformat() if summary.updated_at else None
        })
    
    return {
        "summaries": summaries_data,
        "total_count": len(summaries_data),
        "filters": {
            "date": date,
            "category": category
        }
    }


@router.get("/summaries/categories")
async def get_available_categories(db: AsyncSession = Depends(get_db)):
    """Get list of available categories from articles (not legacy daily summaries)."""
    from .models import Category, ArticleCategory
    
    # Get categories from current articles, not legacy daily summaries
    result = await db.execute(
        select(Category.name, func.count(ArticleCategory.article_id).label('count'))
        .join(ArticleCategory)
        .group_by(Category.name)
        .order_by(func.count(ArticleCategory.article_id).desc())
    )
    
    categories = []
    for category_name, count in result.all():
        categories.append({
            "category": category_name,
            "summaries_count": count  # Keep same field name for compatibility
        })
    
    return {
        "categories": categories
    }


@router.post("/summaries/generate")
async def generate_daily_summaries(
    date: Optional[str] = Query(None, description="YYYY-MM-DD format, defaults to today"),
    force_regenerate: bool = Query(False, description="Force regenerate existing summaries"),
    db: AsyncSession = Depends(get_db)
):
    """Generate daily summaries for specified date."""
    from datetime import date as date_type
    from .orchestrator import NewsOrchestrator
    
    # Parse target date
    if date:
        try:
            target_date = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    else:
        target_date = datetime.utcnow().date()
    
    try:
        # Check if summaries already exist for this date
        existing_summaries = await db.execute(
            select(DailySummary).where(func.date(DailySummary.date) == target_date)
        )
        existing = existing_summaries.scalars().all()
        
        if existing and not force_regenerate:
            return {
                "success": True,
                "message": f"Summaries already exist for {target_date}",
                "existing_summaries": len(existing),
                "date": target_date.isoformat(),
                "force_regenerate": False
            }
        
        # Get articles for the target date
        articles_result = await db.execute(
            select(Article).where(
                func.date(Article.published_at) == target_date,
                Article.is_advertisement != True  # Exclude advertisements
            )
            .order_by(Article.published_at.desc())
        )
        articles = articles_result.scalars().all()
        
        if not articles:
            return {
                "success": False,
                "message": f"No articles found for {target_date}",
                "date": target_date.isoformat(),
                "articles_count": 0
            }
        
        # Group articles by category (using primary category to avoid duplicates)
        categories = {}
        for article in articles:
            # Use primary category (highest confidence) to prevent duplication
            category = article.primary_category
            if category not in categories:
                categories[category] = []
            
            categories[category].append({
                'headline': article.title,
                'link': article.url,
                'links': [article.url],
                'description': article.summary or article.content[:500] + "..." if article.content else "",
                'category': category,
                'image_url': article.image_url,
                'categories_info': article.categories_with_confidence  # For reference
            })
        
        # Generate summaries using orchestrator logic
        orchestrator = NewsOrchestrator()
        
        # Delete existing summaries if force regenerate
        if existing and force_regenerate:
            for summary in existing:
                await db.delete(summary)
            await db.commit()
        
        # Generate new summaries
        await orchestrator._generate_and_save_daily_summaries(db, target_date, categories)
        
        # Get the newly created summaries
        new_summaries_result = await db.execute(
            select(DailySummary).where(func.date(DailySummary.date) == target_date)
        )
        new_summaries = new_summaries_result.scalars().all()
        
        summaries_data = []
        for summary in new_summaries:
            summaries_data.append({
                "id": summary.id,
                "category": summary.category,
                "summary_text": summary.summary_text,
                "articles_count": summary.articles_count,
                "created_at": summary.created_at.isoformat() if summary.created_at else None
            })
        
        return {
            "success": True,
            "message": f"Daily summaries generated successfully for {target_date}",
            "date": target_date.isoformat(),
            "articles_processed": len(articles),
            "categories_found": len(categories),
            "summaries_generated": len(new_summaries),
            "summaries": summaries_data,
            "force_regenerate": force_regenerate
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating summaries: {str(e)}")


@router.get("/migrations/status")
async def get_migrations_status(db: AsyncSession = Depends(get_db)):
    """Get current migration status."""
    try:
        # Check if multiple categories migration is needed
        # Get migration info from universal manager
        migration_info = migration_manager.get_migration_info('002_multiple_categories')
        if migration_info:
            # Check if migration is needed using the registered check function
            migrations = migration_manager.migrations
            if '002_multiple_categories' in migrations:
                migration = migrations['002_multiple_categories']
                if hasattr(migration, 'check_needed'):
                    is_needed = await migration.check_needed(db)
                else:
                    is_needed = await migration['check_function'](db)
            else:
                is_needed = False
        else:
            is_needed = False
        
        # Get some basic stats
        result = await db.execute(text("SELECT COUNT(*) FROM articles WHERE category IS NOT NULL"))
        articles_with_categories = result.scalar() or 0
        
        # Check if new tables exist by trying to query them
        has_categories_table = False
        has_article_categories_table = False
        
        try:
            await db.execute(text("SELECT 1 FROM categories LIMIT 1"))
            has_categories_table = True
        except:
            pass
            
        try:
            await db.execute(text("SELECT 1 FROM article_categories LIMIT 1"))
            has_article_categories_table = True
        except:
            pass
        
        # Get article_categories count if table exists
        relationships_count = 0
        if has_article_categories_table:
            result = await db.execute(text("SELECT COUNT(*) FROM article_categories"))
            relationships_count = result.scalar() or 0
        
        return {
            "migration_needed": is_needed,
            "tables_exist": {
                "categories": has_categories_table,
                "article_categories": has_article_categories_table
            },
            "statistics": {
                "articles_with_categories": articles_with_categories,
                "category_relationships": relationships_count
            },
            "available_migrations": list(migration_manager.migrations.keys())
        }
        
    except Exception as e:
        return {
            "error": str(e),
            "migration_needed": True  # Assume needed if we can't check
        }


@router.post("/migrations/run")
async def run_migrations():
    """Manually trigger migrations."""
    try:
        results = await migration_manager.check_and_run_migrations()
        return {
            "success": True,
            "results": results
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@router.get("/schedule/settings")
async def get_schedule_settings(db: AsyncSession = Depends(get_db)):
    """Get all schedule settings."""
    result = await db.execute(
        select(ScheduleSettings).order_by(ScheduleSettings.task_name)
    )
    settings = result.scalars().all()
    
    settings_data = []
    for setting in settings:
        settings_data.append({
            "id": setting.id,
            "task_name": setting.task_name,
            "enabled": setting.enabled,
            "schedule_type": setting.schedule_type,
            "hour": setting.hour,
            "minute": setting.minute,
            "weekdays": setting.weekdays,
            "timezone": setting.timezone,
            "task_config": setting.task_config,
            "last_run": setting.last_run.isoformat() if setting.last_run else None,
            "next_run": setting.next_run.isoformat() if setting.next_run else None,
            "is_running": setting.is_running,
            "updated_at": setting.updated_at.isoformat() if setting.updated_at else None
        })
    
    return {
        "settings": settings_data
    }


class UpdateScheduleRequest(BaseModel):
    enabled: bool = False
    schedule_type: str = "daily"  # daily, hourly, interval
    hour: int = 9
    minute: int = 0
    weekdays: List[int] = [1,2,3,4,5,6,7]
    timezone: str = "Europe/Belgrade"
    task_config: dict = {}


@router.put("/schedule/settings/{task_name}")
async def update_schedule_setting(
    task_name: str,
    schedule_data: UpdateScheduleRequest,
    db: AsyncSession = Depends(get_db)
):
    """Update schedule setting for a specific task."""
    # Validate task_name
    valid_tasks = ["telegram_digest", "news_processing", "daily_summaries"]
    if task_name not in valid_tasks:
        raise HTTPException(status_code=400, detail=f"Invalid task name. Must be one of: {valid_tasks}")
    
    # Validate schedule data
    if not (0 <= schedule_data.hour <= 23):
        raise HTTPException(status_code=400, detail="Hour must be between 0 and 23")
    if not (0 <= schedule_data.minute <= 59):
        raise HTTPException(status_code=400, detail="Minute must be between 0 and 59")
    if not all(1 <= day <= 7 for day in schedule_data.weekdays):
        raise HTTPException(status_code=400, detail="Weekdays must be between 1 (Monday) and 7 (Sunday)")
    
    # Get existing setting or create new one
    result = await db.execute(
        select(ScheduleSettings).where(ScheduleSettings.task_name == task_name)
    )
    setting = result.scalar_one_or_none()
    
    if not setting:
        setting = ScheduleSettings(task_name=task_name)
        db.add(setting)
    
    # Update settings
    setting.enabled = schedule_data.enabled
    setting.schedule_type = schedule_data.schedule_type
    setting.hour = schedule_data.hour
    setting.minute = schedule_data.minute
    setting.weekdays = schedule_data.weekdays
    setting.timezone = schedule_data.timezone
    setting.task_config = schedule_data.task_config
    
    # Calculate next run time if enabled
    if schedule_data.enabled:
        from datetime import datetime, timedelta
        import pytz
        
        try:
            tz = pytz.timezone(schedule_data.timezone)
            now = datetime.now(tz)
            
            # Calculate next run based on schedule type
            if schedule_data.schedule_type == "daily":
                next_run = now.replace(hour=schedule_data.hour, minute=schedule_data.minute, second=0, microsecond=0)
                if next_run <= now:
                    next_run += timedelta(days=1)
            elif schedule_data.schedule_type == "hourly":
                next_run = now.replace(minute=schedule_data.minute, second=0, microsecond=0)
                if next_run <= now:
                    next_run += timedelta(hours=1)
            elif schedule_data.schedule_type == "interval":
                # Use interval_minutes from task_config, default 30
                interval_minutes = int(schedule_data.task_config.get('interval_minutes', 30)) if schedule_data.task_config else 30
                interval_minutes = max(1, min(interval_minutes, 24*60))
                next_run = now + timedelta(minutes=interval_minutes)
            else:
                next_run = None
            
            setting.next_run = next_run.astimezone(pytz.UTC).replace(tzinfo=None) if next_run else None
            
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid timezone: {e}")
    else:
        setting.next_run = None
    
    await db.commit()
    await db.refresh(setting)
    
    return {
        "success": True,
        "message": f"Schedule setting for {task_name} updated successfully",
        "setting": {
            "id": setting.id,
            "task_name": setting.task_name,
            "enabled": setting.enabled,
            "schedule_type": setting.schedule_type,
            "hour": setting.hour,
            "minute": setting.minute,
            "weekdays": setting.weekdays,
            "timezone": setting.timezone,
            "next_run": setting.next_run.isoformat() if setting.next_run else None
        }
    }


@router.get("/schedule/status")
async def get_scheduler_status():
    """Get scheduler status."""
    from .services.scheduler import get_scheduler
    
    scheduler = get_scheduler()
    status = await scheduler.get_status()
    
    return status


def extract_domain(url: str) -> str:
    """Extract domain from URL."""
    try:
        from urllib.parse import urlparse
        return urlparse(url).netloc.lower()
    except Exception:
        return "unknown"


def clean_html_entities(text: str) -> str:
    """Clean HTML entities from text, preventing double escaping issues."""
    if not text:
        return text
    
    # First, unescape any existing HTML entities
    cleaned = html.unescape(text)
    
    # Clean up any remaining problematic sequences that might cause display issues
    import re
    from bs4 import BeautifulSoup
    
    # Remove sequences like "> or '> that might appear from malformed entities
    cleaned = re.sub(r'["\']>', ' ', cleaned)
    
    # Remove problematic HTML sequences manually instead of using BeautifulSoup
    # This is more reliable for malformed HTML
    import re
    
    # Remove malformed HTML links like "a href='url text /a"
    cleaned = re.sub(r'<?\s*a\s+href=[\'"]?[^\s\'"<>]*[\'"]?\s*[^<>]*/?a\s*>?', ' ', cleaned)
    
    # Remove any remaining HTML tags
    cleaned = re.sub(r'<[^>]*>', '', cleaned)
    
    # Remove patterns like "@serbia /url_path Читать оригинал"
    cleaned = re.sub(r'@\w+\s+/[^\s]*\s+Читать оригинал', '', cleaned)
    
    # Remove any remaining < > characters
    cleaned = cleaned.replace('<', ' ').replace('>', ' ')
    
    # Clean up extra whitespace
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    
    return cleaned


def clean_summary_text(raw_summary: str) -> str:
    """Clean AI-generated summary from service text and prompt repetition."""
    if not raw_summary:
        return ""
    
    import re
    
    # Remove common service phrases that AI sometimes includes
    service_phrases = [
        r'^Краткое содержание статьи на русском языке с основными тезисами:\s*',
        r'^Краткое содержание статьи на русском языке:\s*',
        r'^Краткое содержание:\s*',
        r'^Основные тезисы статьи:\s*',
        r'^Основные тезисы:\s*',
        r'^Суммаризация статьи:\s*',
        r'^Пересказ статьи:\s*',
        r'^Содержание статьи:\s*',
        r'^Вот краткое содержание:\s*',
        r'^Вот основные тезисы:\s*',
        r'^Статья содержит следующие основные моменты:\s*',
        r'^Статья рассказывает о следующем:\s*',
        r'^ПЕРЕСКАЗ:\s*'
    ]
    
    cleaned_summary = raw_summary
    
    # Remove service phrases from the beginning
    for phrase_pattern in service_phrases:
        cleaned_summary = re.sub(phrase_pattern, '', cleaned_summary, flags=re.IGNORECASE | re.MULTILINE)
    
    # Remove leading/trailing whitespace and newlines
    cleaned_summary = cleaned_summary.strip()
    
    # Remove empty bullet points or dashes at the beginning
    cleaned_summary = re.sub(r'^[-•·*]\s*', '', cleaned_summary, flags=re.MULTILINE)
    cleaned_summary = re.sub(r'^\d+\.\s*$', '', cleaned_summary, flags=re.MULTILINE)
    
    # Clean up multiple newlines
    cleaned_summary = re.sub(r'\n\s*\n', '\n\n', cleaned_summary)
    
    # Remove trailing periods/colons if they look like service text endings
    cleaned_summary = re.sub(r':\s*$', '', cleaned_summary)
    
    return cleaned_summary.strip()


# Backup/Restore API Endpoints

class BackupRequest(BaseModel):
    """Request model for backup operations."""
    description: Optional[str] = None


class RestoreRequest(BaseModel):
    """Request model for restore operations."""
    backup_file: str


class BackupScheduleRequest(BaseModel):
    """Request model for backup schedule."""
    enabled: bool
    schedule_time: str  # HH:MM format
    keep_days: int = 30


async def run_backup_script() -> dict:
    """Run backup script and return result."""
    try:
        # Check if we're running inside Docker container
        is_docker = os.path.exists('/.dockerenv')
        
        if is_docker:
            # Running inside Docker - use direct backup logic
            return await run_docker_backup()
        else:
            # Running on host - use backup script
            project_root = Path(__file__).parent.parent
            backup_script = project_root / "scripts" / "backup.sh"
            
            if not backup_script.exists():
                raise HTTPException(status_code=404, detail="Backup script not found")
            
            # Run backup script
            process = await asyncio.create_subprocess_exec(
                str(backup_script),
                cwd=str(project_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                return {
                    "success": True,
                    "message": "Backup completed successfully",
                    "output": stdout.decode(),
                    "timestamp": datetime.utcnow().isoformat()
                }
            else:
                return {
                    "success": False,
                    "message": "Backup failed",
                    "error": stderr.decode(),
                    "output": stdout.decode(),
                    "timestamp": datetime.utcnow().isoformat()
                }
    except Exception as e:
        return {
            "success": False,
            "message": f"Backup script execution failed: {str(e)}",
            "timestamp": datetime.utcnow().isoformat()
        }


async def run_docker_backup() -> dict:
    """Run backup from inside Docker container."""
    try:
        backup_dir = f"./backups/{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        os.makedirs(backup_dir, exist_ok=True)
        
        output_lines = []
        output_lines.append("🗄️ RSS Summarizer v2 - Docker Backup Starting...")
        output_lines.append(f"📁 Backup directory: {backup_dir}")
        
        # 1. Database Backup using pg_dump
        output_lines.append("📊 Backing up PostgreSQL database...")
        try:
            # Parse DB URL for connection parameters
            from urllib.parse import urlparse
            parsed = urlparse(settings.database_url)
            host = parsed.hostname or "localhost"
            port = str(parsed.port or 5432)
            user = parsed.username or "postgres"
            password = parsed.password or ""
            dbname = (parsed.path or "/postgres").lstrip('/')

            env = {**os.environ}
            if password:
                env["PGPASSWORD"] = password

            result = subprocess.run([
                "pg_dump", "-h", host, "-p", port, "-U", user, "-d", dbname,
                "--data-only", "--column-inserts", "--rows-per-insert=1"
            ], 
            capture_output=True, text=True, env=env)
            
            if result.returncode == 0:
                with open(f"{backup_dir}/database.sql", 'w') as f:
                    f.write(result.stdout)
                output_lines.append("✅ Database backup completed (pg_dump)")
            else:
                output_lines.append(f"⚠️ pg_dump failed: {result.stderr}")
                # Fallback to direct method
                await backup_database_direct(backup_dir, output_lines)
        except FileNotFoundError:
            output_lines.append("⚠️ pg_dump not found, using direct method...")
            await backup_database_direct(backup_dir, output_lines)
        
        # 2. Configuration Backup - НЕ НУЖНА
        # docker-compose.yml и init.sql уже есть в репозитории
        output_lines.append("ℹ️  Note: config files (docker-compose.yml, init.sql) are in repository")
        
        # 3. Application Data Backup
        output_lines.append("📂 Backing up application data...")
        
        if os.path.exists("./data"):
            subprocess.run(["cp", "-r", "./data", f"{backup_dir}/"], check=False)
            output_lines.append("✅ Application data copied")
        
        if os.path.exists("./logs"):
            subprocess.run(["cp", "-r", "./logs", f"{backup_dir}/"], check=False)
            output_lines.append("✅ Logs copied")
        
        # 4. Create metadata
        output_lines.append("📋 Creating backup metadata...")
        with open(f"{backup_dir}/backup_info.txt", 'w') as f:
            f.write(f"""RSS Summarizer v2 - Backup Information
======================================
Backup Date: {datetime.utcnow().strftime('%a %b %d %H:%M:%S UTC %Y')}
Database: newsdb
Container: v2-postgres-1
Version: v2.0
Source: Docker API
Host: {os.uname().nodename if hasattr(os, 'uname') else 'unknown'}

Contents:
- database.sql: Full PostgreSQL dump (data only)
- data/: Application data files (if any)
- logs/: Application logs

NOT included (available in repository):
- docker-compose.yml: Docker configuration (in repository)
- init.sql: Database schema (in repository: db/init.sql)
- migrations: Database migrations (in repository: db/migrate_*.sql)

Restore Instructions:
1. Upload backup via web interface: http://localhost:8000/admin/backup
2. Or use CLI: ./scripts/restore.sh {backup_dir}
3. Database schema auto-created from repository init.sql
""")
        
        # 5. Create archive
        output_lines.append("📦 Creating backup archive...")
        archive_name = f"news_aggregator_backup_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.tar.gz"
        
        # Create archive using tar command
        process = await asyncio.create_subprocess_exec(
            "tar", "-czf", f"./backups/{archive_name}", 
            "-C", "./backups", os.path.basename(backup_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0:
            output_lines.append("✅ Backup completed successfully!")
            output_lines.append(f"📁 Backup location: {backup_dir}")
            output_lines.append(f"📦 Archive created: ./backups/{archive_name}")
        else:
            output_lines.append(f"❌ Archive creation failed: {stderr.decode()}")
        
        return {
            "success": process.returncode == 0,
            "message": "Docker backup completed",
            "output": "\n".join(output_lines),
            "timestamp": datetime.utcnow().isoformat(),
            "archive": archive_name if process.returncode == 0 else None
        }
        
    except Exception as e:
        return {
            "success": False,
            "message": f"Docker backup failed: {str(e)}",
            "timestamp": datetime.utcnow().isoformat()
        }


async def backup_database_direct(backup_dir: str, output_lines: list):
    """Backup database using direct connection (fallback method)."""
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        
        # Connect to database using settings.database_url
        from urllib.parse import urlparse
        parsed = urlparse(settings.database_url)
        host = parsed.hostname or 'localhost'
        port = str(parsed.port or 5432)
        user = parsed.username or 'postgres'
        password = parsed.password or ''
        dbname = (parsed.path or '/postgres').lstrip('/')
        conn = psycopg2.connect(dbname=dbname, user=user, password=password, host=host, port=port)
        cursor = conn.cursor()
        
        output_lines.append("📊 Using direct database connection for backup...")
        
        # Get all table names
        cursor.execute("""
            SELECT table_name FROM information_schema.tables 
            WHERE table_schema = 'public'
        """)
        tables = [row[0] for row in cursor.fetchall()]
        
        # Create basic SQL dump
        sql_lines = []
        sql_lines.append("-- RSS Summarizer v2 Database Backup")
        sql_lines.append(f"-- Generated: {datetime.utcnow().isoformat()}")
        sql_lines.append("")
        
        for table in tables:
            # Get table schema
            cursor.execute(f"""
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns 
                WHERE table_name = '{table}' AND table_schema = 'public'
                ORDER BY ordinal_position
            """)
            columns = cursor.fetchall()
            
            # Create table structure (simplified)
            sql_lines.append(f"-- Table: {table}")
            
            # Get table data
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            count = cursor.fetchone()[0]
            
            if count > 0:
                cursor.execute(f"SELECT * FROM {table}")
                rows = cursor.fetchall()
                sql_lines.append(f"-- {count} rows")
                for row in rows:
                    # Basic INSERT statement (simplified)
                    values = ", ".join([f"'{str(val).replace(chr(39), chr(39)+chr(39))}'" if val is not None else "NULL" for val in row])
                    sql_lines.append(f"INSERT INTO {table} VALUES ({values});")
            
            sql_lines.append("")
        
        # Save to file
        with open(f"{backup_dir}/database.sql", 'w') as f:
            f.write("\n".join(sql_lines))
        
        cursor.close()
        conn.close()
        output_lines.append("✅ Database backup completed (direct method)")
        
    except Exception as e:
        output_lines.append(f"⚠️ Direct database backup also failed: {str(e)}")


async def run_restore_script(backup_file: str) -> dict:
    """Run restore script and return result."""
    try:
        # Get project root directory
        project_root = Path(__file__).parent.parent
        restore_script = project_root / "scripts" / "restore.sh"
        
        if not restore_script.exists():
            raise HTTPException(status_code=404, detail="Restore script not found")
        
        # Validate backup file exists
        backup_path = project_root / backup_file
        if not backup_path.exists():
            raise HTTPException(status_code=404, detail=f"Backup file not found: {backup_file}")
        
        # Run restore script
        process = await asyncio.create_subprocess_exec(
            str(restore_script),
            str(backup_path),
            cwd=str(project_root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0:
            return {
                "success": True,
                "message": "Restore completed successfully",
                "output": stdout.decode(),
                "timestamp": datetime.utcnow().isoformat()
            }
        else:
            return {
                "success": False,
                "message": "Restore failed",
                "error": stderr.decode(),
                "output": stdout.decode(),
                "timestamp": datetime.utcnow().isoformat()
            }
    except Exception as e:
        return {
            "success": False,
            "message": f"Restore script execution failed: {str(e)}",
            "timestamp": datetime.utcnow().isoformat()
        }


@router.get("/backups")
async def list_backups():
    """List available backup files."""
    try:
        project_root = Path(__file__).parent.parent
        backups_dir = project_root / "backups"
        
        if not backups_dir.exists():
            return {"backups": [], "message": "No backups directory found"}
        
        backups = []
        for backup_file in backups_dir.glob("*.tar.gz"):
            stat = backup_file.stat()
            backups.append({
                "filename": backup_file.name,
                "filepath": f"backups/{backup_file.name}",
                "size": stat.st_size,
                "size_mb": round(stat.st_size / (1024 * 1024), 2),
                "created_at": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat()
            })
        
        # Sort by creation time (newest first)
        backups.sort(key=lambda x: x["created_at"], reverse=True)
        
        return {"backups": backups}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list backups: {str(e)}")


@router.get("/backup/download/{filename}")
async def download_backup(filename: str):
    """Download backup file."""
    try:
        # Security: validate filename (prevent directory traversal)
        if not filename.endswith('.tar.gz') or '..' in filename or '/' in filename:
            raise HTTPException(status_code=400, detail="Invalid filename")
        
        # Find project root and backup file
        project_root = Path(__file__).parent.parent
        backup_file = project_root / "backups" / filename
        
        if not backup_file.exists():
            raise HTTPException(status_code=404, detail=f"Backup file not found: {filename}")
        
        # Return file for download
        return FileResponse(
            path=str(backup_file),
            filename=filename,
            media_type='application/gzip',
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to download backup: {str(e)}")


@router.post("/backup")
async def create_backup(
    request: BackupRequest,
    background_tasks: BackgroundTasks
):
    """Create a new backup."""
    background_tasks.add_task(run_backup_script)
    
    return {
        "message": "Backup started in background",
        "description": request.description,
        "status": "running",
        "started_at": datetime.utcnow().isoformat()
    }


@router.post("/backup/sync")
async def create_backup_sync(request: BackupRequest):
    """Create a new backup synchronously."""
    result = await run_backup_script()
    
    if request.description and result.get("success"):
        # Could store description in a metadata file here
        pass
    
    return result


@router.post("/restore")
async def restore_backup(
    request: RestoreRequest,
    background_tasks: BackgroundTasks
):
    """Restore from backup file."""
    background_tasks.add_task(run_restore_script, request.backup_file)
    
    return {
        "message": "Restore started in background",
        "backup_file": request.backup_file,
        "status": "running",
        "started_at": datetime.utcnow().isoformat()
    }


@router.post("/restore/sync")
async def restore_backup_sync(request: RestoreRequest):
    """Restore from backup file synchronously."""
    return await run_restore_script(request.backup_file)


@router.get("/backup/schedule")
async def get_backup_schedule():
    """Get backup schedule settings."""
    from .services.backup_service import get_backup_service
    
    try:
        backup_service = get_backup_service()
        return await backup_service.get_schedule_config()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get backup schedule: {str(e)}")


@router.post("/backup/schedule")
async def set_backup_schedule(request: BackupScheduleRequest):
    """Set backup schedule settings."""
    from .services.backup_service import get_backup_service
    
    try:
        backup_service = get_backup_service()
        config = await backup_service.set_schedule_config(
            request.enabled,
            request.schedule_time,
            request.keep_days
        )
        
        return {
            "message": "Backup schedule updated",
            "config": config
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to set backup schedule: {str(e)}")


@router.get("/backup/history")
async def get_backup_history():
    """Get backup history and statistics."""
    from .services.backup_service import get_backup_service
    
    try:
        backup_service = get_backup_service()
        return await backup_service.get_backup_history()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get backup history: {str(e)}")


@router.post("/backup/cleanup")
async def cleanup_old_backups(keep_days: int = 30):
    """Clean up old backup files."""
    from .services.backup_service import get_backup_service
    
    try:
        backup_service = get_backup_service()
        result = await backup_service.cleanup_old_backups(keep_days)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to cleanup backups: {str(e)}")


@router.post("/admin/cleanup")
async def cleanup_old_data(
    days_to_keep: int = 30,
    db: AsyncSession = Depends(get_db)
):
    """Clean up old articles and processing logs."""
    try:
        from datetime import datetime, timedelta
        from sqlalchemy import delete, func
        
        cutoff_date = datetime.utcnow() - timedelta(days=days_to_keep)
        
        # Delete old articles
        articles_result = await db.execute(
            delete(Article).where(Article.published_at < cutoff_date)
        )
        deleted_articles = articles_result.rowcount or 0
        
        # Delete old processing stats
        stats_result = await db.execute(
            delete(ProcessingStat).where(ProcessingStat.date < cutoff_date.date())
        )
        deleted_stats = stats_result.rowcount or 0
        
        # Delete old daily summaries
        summaries_result = await db.execute(
            delete(DailySummary).where(DailySummary.date < cutoff_date.date())
        )
        deleted_summaries = summaries_result.rowcount or 0
        
        await db.commit()
        
        return {
            "success": True,
            "deleted_articles": deleted_articles,
            "deleted_stats": deleted_stats,
            "deleted_summaries": deleted_summaries,
            "deleted_logs": deleted_stats + deleted_summaries,  # For dashboard compatibility
            "cutoff_date": cutoff_date.isoformat(),
            "days_kept": days_to_keep
        }
        
    except Exception as e:
        await db.rollback()
        logging.error(f"Cleanup failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to cleanup data: {str(e)}")


@router.post("/backup/upload")
async def upload_backup_file(file: UploadFile = File(...)):
    """Upload backup file for restore."""
    try:
        # Validate file type
        if not file.filename.endswith('.tar.gz'):
            raise HTTPException(status_code=400, detail="Only .tar.gz backup files are supported")
        
        # Create backups directory if not exists
        backups_dir = Path("./backups")
        backups_dir.mkdir(exist_ok=True)
        
        # Save uploaded file
        file_path = backups_dir / file.filename
        
        with open(file_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)
        
        return {
            "success": True,
            "message": f"Backup file uploaded successfully: {file.filename}",
            "filename": file.filename,
            "size": len(content),
            "path": str(file_path)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to upload backup: {str(e)}")


@router.post("/restore/upload")
async def restore_from_uploaded_backup(filename: str, background_tasks: BackgroundTasks):
    """Restore from uploaded backup file."""
    try:
        backup_file = Path(f"./backups/{filename}")
        
        if not backup_file.exists():
            raise HTTPException(status_code=404, detail=f"Backup file not found: {filename}")
        
        # Run restore in background
        background_tasks.add_task(run_restore_script, str(backup_file))
        
        return {
            "success": True,
            "message": f"Restore from {filename} started in background",
            "filename": filename
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start restore: {str(e)}")


@router.get("/stats/queue")
async def get_queue_stats():
    """Get universal database queue statistics with pool metrics."""
    try:
        # Get global database queue manager
        from .services.database_queue import get_database_queue
        queue_manager = get_database_queue()
        stats = queue_manager.get_stats()
        # Add engine pool status
        try:
            stats["db_pool_status"] = str(engine.pool.status())
        except Exception:
            stats["db_pool_status"] = "unavailable"
        return {
            "success": True,
            "stats": stats,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get queue stats: {str(e)}")


@router.get("/stats/extractor")
async def get_extractor_stats():
    """Return aggregated extraction efficiency stats and per-domain breakdown."""
    try:
        memory = await get_extraction_memory()
        overall = await memory.get_extraction_efficiency_stats()
        # Build per-domain summary (top N domains by attempts)
        # Note: access internal state carefully; it's an in-memory service
        domain_stats = []
        # Best-effort access to internal dict
        domains = list(getattr(memory, "_domain_stats", {}).items())
        # Sort by total attempts desc
        domains.sort(key=lambda kv: kv[1].get('total_attempts', 0), reverse=True)
        for domain, stats in domains[:50]:
            domain_stats.append({
                "domain": domain,
                "total_attempts": stats.get('total_attempts', 0),
                "successful_attempts": stats.get('successful_attempts', 0),
                "success_rate": (stats.get('successful_attempts', 0) / stats.get('total_attempts', 1) * 100) if stats.get('total_attempts', 0) > 0 else 0,
                "methods": stats.get('methods', {})
            })
        return {
            "success": True,
            "overall": overall,
            "domains": domain_stats,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get extractor stats: {str(e)}")


# Category Mapping API endpoints
class CategoryMappingRequest(BaseModel):
    ai_category: str
    fixed_category: str
    confidence_threshold: Optional[float] = 0.0
    description: Optional[str] = None

class CategoryMappingResponse(BaseModel):
    id: int
    ai_category: str
    fixed_category: str
    confidence_threshold: float
    description: Optional[str]
    created_by: str
    usage_count: int
    last_used: Optional[datetime]
    is_active: bool
    created_at: datetime
    updated_at: datetime

class CategoryMappingUpdateResponse(BaseModel):
    id: int
    ai_category: str
    fixed_category: str
    confidence_threshold: float
    description: Optional[str]
    created_by: str
    usage_count: int
    last_used: Optional[datetime]
    is_active: bool
    created_at: datetime
    updated_at: datetime
    updated_articles_count: int

@router.get("/category-mappings", response_model=List[CategoryMappingResponse])
async def get_category_mappings(
    active_only: bool = Query(True, description="Return only active mappings"),
    db: AsyncSession = Depends(get_db)
):
    """Get all category mappings."""
    try:
        query = select(CategoryMapping).order_by(CategoryMapping.ai_category)
        if active_only:
            query = query.where(CategoryMapping.is_active == True)
        
        result = await db.execute(query)
        mappings = result.scalars().all()
        
        return [CategoryMappingResponse(
            id=mapping.id,
            ai_category=mapping.ai_category,
            fixed_category=mapping.fixed_category,
            confidence_threshold=mapping.confidence_threshold,
            description=mapping.description,
            created_by=mapping.created_by,
            usage_count=mapping.usage_count,
            last_used=mapping.last_used,
            is_active=mapping.is_active,
            created_at=mapping.created_at,
            updated_at=mapping.updated_at
        ) for mapping in mappings]
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get category mappings: {str(e)}")

@router.post("/category-mappings", response_model=CategoryMappingResponse)
async def create_category_mapping(
    mapping_request: CategoryMappingRequest,
    db: AsyncSession = Depends(get_db)
):
    """Create new category mapping."""
    try:
        from .services.category_service import CategoryService
        service = CategoryService(db)
        
        # Validate that fixed_category is one of our allowed categories
        if mapping_request.fixed_category not in service.ALLOWED_CATEGORIES:
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid fixed_category. Must be one of: {list(service.ALLOWED_CATEGORIES.keys())}"
            )
        
        # Check if mapping already exists
        existing = await db.execute(
            select(CategoryMapping).where(CategoryMapping.ai_category == mapping_request.ai_category)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Mapping for this AI category already exists")
        
        # Create new mapping
        mapping = CategoryMapping(
            ai_category=mapping_request.ai_category.strip(),
            fixed_category=mapping_request.fixed_category,
            confidence_threshold=mapping_request.confidence_threshold,
            description=mapping_request.description,
            created_by="admin"  # TODO: Get from auth
        )
        
        db.add(mapping)
        await db.commit()
        await db.refresh(mapping)
        
        return CategoryMappingResponse(
            id=mapping.id,
            ai_category=mapping.ai_category,
            fixed_category=mapping.fixed_category,
            confidence_threshold=mapping.confidence_threshold,
            description=mapping.description,
            created_by=mapping.created_by,
            usage_count=mapping.usage_count,
            last_used=mapping.last_used,
            is_active=mapping.is_active,
            created_at=mapping.created_at,
            updated_at=mapping.updated_at
        )
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to create category mapping: {str(e)}")

@router.put("/category-mappings/{mapping_id}", response_model=CategoryMappingUpdateResponse)
async def update_category_mapping(
    mapping_id: int,
    mapping_request: CategoryMappingRequest,
    db: AsyncSession = Depends(get_db)
):
    """Update existing category mapping and apply changes to existing articles."""
    try:
        from .services.category_service import CategoryService
        service = CategoryService(db)
        
        # Validate that fixed_category is one of our allowed categories
        if mapping_request.fixed_category not in service.ALLOWED_CATEGORIES:
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid fixed_category. Must be one of: {list(service.ALLOWED_CATEGORIES.keys())}"
            )
        
        # Get existing mapping
        result = await db.execute(
            select(CategoryMapping).where(CategoryMapping.id == mapping_id)
        )
        mapping = result.scalar_one_or_none()
        if not mapping:
            raise HTTPException(status_code=404, detail="Category mapping not found")
        
        # Store old values for change detection
        old_ai_category = mapping.ai_category
        old_fixed_category = mapping.fixed_category
        
        # Update mapping
        mapping.ai_category = mapping_request.ai_category.strip()
        mapping.fixed_category = mapping_request.fixed_category
        mapping.confidence_threshold = mapping_request.confidence_threshold
        mapping.description = mapping_request.description
        mapping.updated_at = func.now()
        
        await db.commit()
        await db.refresh(mapping)
        
        # Apply changes to existing articles if fixed_category changed
        updated_articles_count = 0
        if old_fixed_category != mapping_request.fixed_category:
            updated_articles_count = await service.apply_mapping_changes_to_existing_articles(
                old_ai_category, old_fixed_category, mapping_request.fixed_category
            )
        
        return CategoryMappingUpdateResponse(
            id=mapping.id,
            ai_category=mapping.ai_category,
            fixed_category=mapping.fixed_category,
            confidence_threshold=mapping.confidence_threshold,
            description=mapping.description,
            created_by=mapping.created_by,
            usage_count=mapping.usage_count,
            last_used=mapping.last_used,
            is_active=mapping.is_active,
            created_at=mapping.created_at,
            updated_at=mapping.updated_at,
            updated_articles_count=updated_articles_count
        )
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to update category mapping: {str(e)}")

@router.delete("/category-mappings/{mapping_id}")
async def delete_category_mapping(
    mapping_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Delete category mapping."""
    try:
        # Get existing mapping
        result = await db.execute(
            select(CategoryMapping).where(CategoryMapping.id == mapping_id)
        )
        mapping = result.scalar_one_or_none()
        if not mapping:
            raise HTTPException(status_code=404, detail="Category mapping not found")
        
        await db.delete(mapping)
        await db.commit()
        
        return {"success": True, "message": "Category mapping deleted"}
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete category mapping: {str(e)}")

@router.post("/category-mappings/{mapping_id}/toggle")
async def toggle_category_mapping(
    mapping_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Toggle active status of category mapping."""
    try:
        # Get existing mapping
        result = await db.execute(
            select(CategoryMapping).where(CategoryMapping.id == mapping_id)
        )
        mapping = result.scalar_one_or_none()
        if not mapping:
            raise HTTPException(status_code=404, detail="Category mapping not found")
        
        # Toggle active status
        mapping.is_active = not mapping.is_active
        mapping.updated_at = func.now()
        
        await db.commit()
        
        return {
            "success": True, 
            "message": f"Category mapping {'activated' if mapping.is_active else 'deactivated'}",
            "is_active": mapping.is_active
        }
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to toggle category mapping: {str(e)}")

@router.get("/category-mappings/fixed-categories")
async def get_fixed_categories():
    """Get list of available fixed categories."""
    try:
        from .services.category_service import CategoryService
        # Create a temporary service instance just to access the allowed categories
        service = CategoryService(None)
        
        return {
            "categories": [
                {"key": key, "display_name": display_name}
                for key, display_name in service.ALLOWED_CATEGORIES.items()
            ]
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get fixed categories: {str(e)}")


@router.get("/category-mappings/unmapped")
async def get_unmapped_ai_categories(db: AsyncSession = Depends(get_db)):
    """Get AI categories that don't have mappings yet."""
    try:
        # Get all existing mapped categories
        mapped_result = await db.execute(
            select(CategoryMapping.ai_category).where(CategoryMapping.is_active == True)
        )
        mapped_categories = {row[0].lower() for row in mapped_result.all()}
        
        # Look for common AI category patterns in content
        simple_query = text("""
            SELECT DISTINCT 
                'business' as ai_category, COUNT(*) as usage_count
            FROM articles WHERE summary ILIKE '%business%' OR title ILIKE '%business%'
            UNION ALL
            SELECT DISTINCT 
                'technology' as ai_category, COUNT(*) as usage_count  
            FROM articles WHERE summary ILIKE '%technology%' OR title ILIKE '%tech%'
            UNION ALL
            SELECT DISTINCT 
                'health' as ai_category, COUNT(*) as usage_count
            FROM articles WHERE summary ILIKE '%health%' OR title ILIKE '%medical%'
            UNION ALL
            SELECT DISTINCT 
                'environment' as ai_category, COUNT(*) as usage_count
            FROM articles WHERE summary ILIKE '%environment%' OR title ILIKE '%climate%'
            UNION ALL
            SELECT DISTINCT 
                'education' as ai_category, COUNT(*) as usage_count
            FROM articles WHERE summary ILIKE '%education%' OR title ILIKE '%university%'
            ORDER BY usage_count DESC
        """)
        
        result = await db.execute(simple_query)
        ai_categories = result.all()
        
        # Filter out already mapped categories
        unmapped = []
        for ai_category, usage_count in ai_categories:
            if ai_category and ai_category.lower() not in mapped_categories:
                unmapped.append({
                    "ai_category": ai_category,
                    "usage_count": usage_count,
                    "suggested_mapping": _suggest_fixed_category(ai_category)
                })
        
        return {"unmapped_categories": unmapped[:10]}  # Limit to top 10
        
    except Exception as e:
        logging.error(f"Failed to get unmapped categories: {e}")
        # Return fallback data
        return {"unmapped_categories": []}


def _suggest_fixed_category(ai_category: str) -> str:
    """Suggest a fixed category based on AI category name."""
    ai_lower = ai_category.lower()
    
    if any(word in ai_lower for word in ['business', 'economy', 'finance', 'trade']):
        return 'Business'
    elif any(word in ai_lower for word in ['tech', 'technology', 'digital', 'software']):
        return 'Tech'
    elif any(word in ai_lower for word in ['health', 'medical', 'science', 'research']):
        return 'Science'
    elif any(word in ai_lower for word in ['serbia', 'belgrade', 'balkan']):
        return 'Serbia'
    elif any(word in ai_lower for word in ['politics', 'government', 'law']):
        return 'Politics'
    elif any(word in ai_lower for word in ['international', 'global', 'world']):
        return 'International'
    else:
        return 'Other'