"""Stats API router - handles statistics and metrics."""

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text

from ..database import get_db
from ..models import Article, ProcessingStat
from ..orchestrator import NewsOrchestrator
from ..services.extraction_memory import get_extraction_memory


router = APIRouter()


@router.get("/dashboard")
async def get_dashboard_stats(
    days: int = Query(7, ge=1, le=30),
    db: AsyncSession = Depends(get_db)
):
    """Get dashboard statistics."""
    try:
        from ..models import Source, Category, ArticleCategory, ProcessingStat
        
        # Get basic article stats
        total_articles_result = await db.execute(select(func.count(Article.id)))
        total_articles = total_articles_result.scalar() or 0
        
        # Articles from today
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_articles_result = await db.execute(
            select(func.count(Article.id)).where(Article.fetched_at >= today)
        )
        today_articles = today_articles_result.scalar() or 0
        
        # Articles from last N days
        since_date = datetime.utcnow() - timedelta(days=days)
        recent_articles_result = await db.execute(
            select(func.count(Article.id)).where(Article.fetched_at >= since_date)
        )
        recent_articles = recent_articles_result.scalar() or 0
        
        # Processing stats
        processed_articles_result = await db.execute(
            select(func.count(Article.id)).where(Article.processed == True)
        )
        processed_articles = processed_articles_result.scalar() or 0
        
        # Processed today
        processed_today_result = await db.execute(
            select(func.count(Article.id)).where(
                Article.processed == True,
                Article.fetched_at >= today
            )
        )
        processed_today = processed_today_result.scalar() or 0
        
        # Advertisement stats
        ads_result = await db.execute(
            select(func.count(Article.id)).where(Article.is_advertisement == True)
        )
        ads_count = ads_result.scalar() or 0
        
        # Source stats
        total_sources_result = await db.execute(select(func.count(Source.id)))
        total_sources = total_sources_result.scalar() or 0
        
        active_sources_result = await db.execute(
            select(func.count(Source.id)).where(Source.enabled == True)
        )
        active_sources = active_sources_result.scalar() or 0
        
        disabled_sources = total_sources - active_sources
        
        # Categories stats
        categories_count_result = await db.execute(select(func.count(Category.id)))
        categories_count = categories_count_result.scalar() or 0
        
        # Top category (most used)
        try:
            top_category_result = await db.execute(
                select(Category.display_name, func.count(ArticleCategory.category_id).label('usage_count'))
                .join(ArticleCategory, Category.id == ArticleCategory.category_id)
                .group_by(Category.id, Category.display_name)
                .order_by(text('usage_count DESC'))
                .limit(1)
            )
            top_category_row = top_category_result.first()
            top_category = top_category_row[0] if top_category_row else "N/A"
        except Exception:
            top_category = "N/A"
        
        # API calls and performance stats (mocked for now - can be implemented with ProcessingStat)
        api_calls_today = 0
        api_success_rate = 100
        errors_today = 0
        avg_processing_time = 2500  # milliseconds
        articles_per_hour = round(today_articles / 24) if today_articles > 0 else 0
        
        # Try to get real stats from ProcessingStat table if it exists
        try:
            stats_result = await db.execute(
                select(
                    func.coalesce(func.sum(ProcessingStat.api_calls), 0).label('api_calls'),
                    func.coalesce(func.sum(ProcessingStat.errors), 0).label('errors'),
                    func.coalesce(func.avg(ProcessingStat.avg_processing_time), avg_processing_time).label('avg_time')
                )
                .where(ProcessingStat.date >= today.date())
            )
            stats_row = stats_result.first()
            if stats_row:
                api_calls_today = int(stats_row.api_calls) if stats_row.api_calls else 0
                errors_today = int(stats_row.errors) if stats_row.errors else 0
                avg_processing_time = float(stats_row.avg_time) if stats_row.avg_time else avg_processing_time
        except Exception as e:
            # Table might not exist yet
            pass
        
        # Get queue stats
        try:
            orchestrator = NewsOrchestrator()
            queue_stats = orchestrator.get_queue_stats()
        except Exception as e:
            queue_stats = {"error": str(e)}
        
        return {
            # New fields expected by dashboard
            "active_sources": active_sources,
            "total_sources": total_sources,
            "disabled_sources": disabled_sources,
            "today_articles": today_articles,
            "processed_today": processed_today,
            "categories_count": categories_count,
            "top_category": top_category,
            "api_calls_today": api_calls_today,
            "api_success_rate": api_success_rate,
            "errors_today": errors_today,
            "avg_processing_time": avg_processing_time,
            "articles_per_hour": articles_per_hour,
            
            # Legacy fields (keep for compatibility)
            "total_articles": total_articles,
            "recent_articles": recent_articles,
            "processed_articles": processed_articles,
            "processing_rate": (processed_articles / total_articles * 100) if total_articles > 0 else 0,
            "advertisements": ads_count,
            "ad_rate": (ads_count / total_articles * 100) if total_articles > 0 else 0,
            "queue_stats": queue_stats,
            "period_days": days,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        return {
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }


@router.get("/queue")
async def get_queue_stats():
    """Get database queue statistics."""
    try:
        orchestrator = NewsOrchestrator()
        return orchestrator.get_queue_stats()
    except Exception as e:
        return {"error": str(e)}


@router.get("/extractor")
async def get_extractor_stats(db: AsyncSession = Depends(get_db)):
    """Get content extractor performance statistics."""
    try:
        extraction_memory = await get_extraction_memory()
        
        # Get domain-based success rates
        domain_stats = await extraction_memory.get_domain_success_rates()
        
        # Get recent extraction stats
        recent_extractions = await db.execute(
            text("""
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN content IS NOT NULL AND LENGTH(content) > 100 THEN 1 ELSE 0 END) as successful,
                    AVG(CASE WHEN content IS NOT NULL THEN LENGTH(content) ELSE 0 END) as avg_content_length
                FROM articles 
                WHERE fetched_at >= NOW() - INTERVAL '7 days'
            """)
        )
        
        stats = recent_extractions.first()
        if stats:
            total, successful, avg_length = stats
            success_rate = (successful / total * 100) if total > 0 else 0
        else:
            total = successful = avg_length = success_rate = 0
        
        return {
            "recent_extractions": {
                "total": total,
                "successful": successful,
                "success_rate": success_rate,
                "avg_content_length": avg_length
            },
            "domain_stats": domain_stats,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        return {
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }

