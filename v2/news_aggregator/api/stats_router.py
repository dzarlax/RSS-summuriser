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


@router.get("/ai-usage")
async def get_ai_usage_stats(
    days: int = Query(30, ge=1, le=90),
    db: AsyncSession = Depends(get_db)
):
    """Get AI API usage statistics."""
    try:
        since_date = datetime.utcnow() - timedelta(days=days)

        # Total usage stats
        total_result = await db.execute(
            text("""
                SELECT
                    COUNT(*) as total_requests,
                    COALESCE(SUM(tokens_used), 0) as total_tokens,
                    COALESCE(SUM(credits_cost), 0) as total_cost,
                    COALESCE(SUM(patterns_discovered), 0) as patterns_discovered,
                    COALESCE(SUM(patterns_successful), 0) as patterns_successful
                FROM ai_usage_tracking
                WHERE created_at >= :since_date
            """),
            {"since_date": since_date}
        )
        total_stats = total_result.first()

        # Today's usage
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_result = await db.execute(
            text("""
                SELECT
                    COUNT(*) as requests,
                    COALESCE(SUM(tokens_used), 0) as tokens,
                    COALESCE(SUM(credits_cost), 0) as cost
                FROM ai_usage_tracking
                WHERE created_at >= :today
            """),
            {"today": today}
        )
        today_stats = today_result.first()

        # Usage by analysis type
        by_type_result = await db.execute(
            text("""
                SELECT
                    analysis_type,
                    COUNT(*) as requests,
                    COALESCE(SUM(tokens_used), 0) as tokens,
                    COALESCE(SUM(credits_cost), 0) as cost
                FROM ai_usage_tracking
                WHERE created_at >= :since_date
                GROUP BY analysis_type
                ORDER BY tokens DESC
            """),
            {"since_date": since_date}
        )
        by_type = [
            {
                "type": row.analysis_type,
                "requests": row.requests,
                "tokens": int(row.tokens),
                "cost": float(row.cost)
            }
            for row in by_type_result.fetchall()
        ]

        # Daily usage for chart
        daily_result = await db.execute(
            text("""
                SELECT
                    DATE(created_at) as date,
                    COUNT(*) as requests,
                    COALESCE(SUM(tokens_used), 0) as tokens,
                    COALESCE(SUM(credits_cost), 0) as cost
                FROM ai_usage_tracking
                WHERE created_at >= :since_date
                GROUP BY DATE(created_at)
                ORDER BY date ASC
            """),
            {"since_date": since_date}
        )
        daily = [
            {
                "date": row.date.isoformat() if row.date else None,
                "requests": row.requests,
                "tokens": int(row.tokens),
                "cost": float(row.cost)
            }
            for row in daily_result.fetchall()
        ]

        # Top domains by usage
        top_domains_result = await db.execute(
            text("""
                SELECT
                    domain,
                    COUNT(*) as requests,
                    COALESCE(SUM(tokens_used), 0) as tokens,
                    COALESCE(SUM(credits_cost), 0) as cost
                FROM ai_usage_tracking
                WHERE created_at >= :since_date
                GROUP BY domain
                ORDER BY tokens DESC
                LIMIT 10
            """),
            {"since_date": since_date}
        )
        top_domains = [
            {
                "domain": row.domain,
                "requests": row.requests,
                "tokens": int(row.tokens),
                "cost": float(row.cost)
            }
            for row in top_domains_result.fetchall()
        ]

        return {
            "period_days": days,
            "total": {
                "requests": total_stats.total_requests if total_stats else 0,
                "tokens": int(total_stats.total_tokens) if total_stats else 0,
                "cost": float(total_stats.total_cost) if total_stats else 0,
                "patterns_discovered": int(total_stats.patterns_discovered) if total_stats else 0,
                "patterns_successful": int(total_stats.patterns_successful) if total_stats else 0
            },
            "today": {
                "requests": today_stats.requests if today_stats else 0,
                "tokens": int(today_stats.tokens) if today_stats else 0,
                "cost": float(today_stats.cost) if today_stats else 0
            },
            "by_type": by_type,
            "daily": daily,
            "top_domains": top_domains,
            "timestamp": datetime.utcnow().isoformat()
        }

    except Exception as e:
        return {
            "error": str(e),
            "period_days": days,
            "total": {"requests": 0, "tokens": 0, "cost": 0},
            "today": {"requests": 0, "tokens": 0, "cost": 0},
            "by_type": [],
            "daily": [],
            "top_domains": [],
            "timestamp": datetime.utcnow().isoformat()
        }


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

