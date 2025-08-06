"""Public interface routes."""

import logging
from fastapi import APIRouter, Request, Query, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func, text
from datetime import datetime, timedelta
from typing import Optional

from .database import get_db
from .models import Article

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


@router.get("/news", response_class=RedirectResponse)
async def news_redirect():
    """Redirect /news to root."""
    return RedirectResponse(url="/", status_code=301)


@router.get("/feed", response_class=HTMLResponse)
async def public_feed_alias(request: Request):
    """Alternative feed endpoint."""
    return templates.TemplateResponse("public/feed.html", {
        "request": request,
        "title": "Новости"
    })


@router.get("/api/public/feed") 
async def get_public_feed(
    limit: int = Query(20, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    since_hours: Optional[int] = Query(None, ge=1, le=168),
    category: Optional[str] = Query(None)
):
    """Public feed endpoint without authentication (for main page)."""
    from .database import AsyncSessionLocal
    
    
    try:
        async with AsyncSessionLocal() as session:
            # Import Source model
            from .models import Source
            
            # Build query for articles with source information
            query = select(Article, Source).join(Source, Article.source_id == Source.id).order_by(desc(Article.published_at))
            
            # Apply time filter
            if since_hours:
                since_time = datetime.utcnow() - timedelta(hours=since_hours)
                query = query.where(Article.published_at >= since_time)
            
            # Apply category filter 
            if category and category.lower() != 'all':
                if category.lower() == 'advertisements':
                    query = query.where(Article.is_advertisement == True)
                else:
                    # Simple case conversion - capitalize first letter to match database format
                    category_capitalized = category.capitalize()
                    query = query.where(Article.category == category_capitalized)
            else:
                # By default, exclude advertisements from public feed
                query = query.where(Article.is_advertisement != True)
            
            # Apply pagination
            query = query.offset(offset).limit(limit)
            
            # Execute query
            result = await session.execute(query)
            rows = result.all()
            
            # Convert to dict format
            articles_data = []
            for article, source in rows:
                article_dict = {
                    "id": article.id,
                    "title": article.title,
                    "summary": article.summary,
                    "url": article.url,
                    "image_url": article.image_url,
                    "source_id": article.source_id,
                    "source_name": source.name,
                    "category": article.category,
                    "published_at": article.published_at.isoformat() if article.published_at else None,
                    "fetched_at": article.fetched_at.isoformat() if article.fetched_at else None,
                    "is_advertisement": article.is_advertisement or False,
                    "ad_confidence": article.ad_confidence or 0.0,
                    "ad_type": article.ad_type
                }
                articles_data.append(article_dict)
            
            return {
                "articles": articles_data,
                "total": len(articles_data),
                "limit": limit,
                "offset": offset
            }
    
    except Exception as e:
        # If DB fails, return mock data
        print(f"Database error: {e}")
        mock_articles = [
            {
                "id": 1,
                "title": "⚠️ База данных недоступна",
                "summary": "Показываем тестовые данные. Проверьте подключение к БД.",
                "url": "https://example.com/db-error",
                "source": "Система",
                "category": "Error",
                "published_at": datetime.utcnow().isoformat(),
                "created_at": datetime.utcnow().isoformat(),
                "is_advertisement": False,
                "ad_confidence": 0.0,
                "ad_type": None
            }
        ]
        
        return {
            "articles": mock_articles,
            "total": len(mock_articles),
            "limit": limit,
            "offset": offset
        }


@router.get("/api/public/categories")
async def get_public_categories():
    """Get category statistics for public feed."""
    from .database import AsyncSessionLocal
    
    try:
        async with AsyncSessionLocal() as session:
            # Count total articles (excluding advertisements)
            total_query = select(func.count(Article.id)).where(Article.is_advertisement != True)
            total_result = await session.execute(total_query)
            total_count = total_result.scalar() or 0
            
            # Count by category (excluding advertisements)
            category_query = select(
                Article.category, 
                func.count(Article.id).label('count')
            ).where(
                Article.is_advertisement != True
            ).group_by(Article.category)
            
            category_result = await session.execute(category_query)
            categories = category_result.all()
            
            # Count advertisements
            ads_query = select(func.count(Article.id)).where(Article.is_advertisement == True)
            ads_result = await session.execute(ads_query)
            ads_count = ads_result.scalar() or 0
            
            # Build category stats
            category_stats = {"all": total_count}
            
            for category, count in categories:
                if category:
                    category_stats[category.lower()] = count
            
            if ads_count > 0:
                category_stats["advertisements"] = ads_count
            
            return {"categories": category_stats}
            
    except Exception as e:
        print(f"Categories error: {e}")
        return {"categories": {"all": 0}}