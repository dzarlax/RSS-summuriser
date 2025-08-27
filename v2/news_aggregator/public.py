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
from .database_helpers import fetch_raw_all, count_query, execute_custom_read
from .models import Article, Category, ArticleCategory

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


@router.get("/cards", response_class=HTMLResponse)
async def public_cards_view(request: Request):
    """Cards view for news feed."""
    return templates.TemplateResponse("public/feed.html", {
        "request": request,
        "title": "Новости"
    })


@router.get("/list", response_class=HTMLResponse)
async def public_list_view(request: Request):
    """List view for news feed (alias for compatibility)."""
    return templates.TemplateResponse("public/list.html", {
        "request": request,
        "title": "Лента новостей"
    })


@router.get("/api/public/feed") 
async def get_public_feed(
    limit: int = Query(20, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    since_hours: Optional[int] = Query(None, ge=1, le=168),
    category: Optional[str] = Query(None),
    hide_ads: bool = Query(True, description="Hide advertisements from feed")
):
    """Public feed endpoint without authentication (for main page)."""
    from .database import AsyncSessionLocal
    
    
    try:
        # Import required models
        from .models import Source, ArticleCategory, Category
        from sqlalchemy.orm import selectinload
        
        # Build query for articles with source and categories information
        query = select(Article).options(
            selectinload(Article.source),
            selectinload(Article.article_categories).selectinload(ArticleCategory.category)
        )
        
        # Apply time filter
        if since_hours:
            since_time = datetime.utcnow() - timedelta(hours=since_hours)
            query = query.where(Article.published_at >= since_time)
        
        # Apply category filter (support both new and legacy systems)
        if category and category.lower() != 'all':
            if category.lower() == 'advertisements':
                # Filter for advertising content
                query = query.where(Article.is_advertisement == True)
            else:
                # Use new category system only
                subquery_new = select(Article.id).join(ArticleCategory).join(Category).where(
                    func.lower(Category.name) == category.lower()
                )
                query = query.where(Article.id.in_(subquery_new))
        
        # Hide advertisements if requested (default: true)
        if hide_ads:
            query = query.where(Article.is_advertisement != True)

        # Order: newest first (without advertisement bias)
        query = query.order_by(desc(Article.published_at))
        
        # Apply pagination
        query = query.offset(offset).limit(limit)
        
        # Execute query through direct session
        async with AsyncSessionLocal() as session:
            result = await session.execute(query)
            articles = result.scalars().all()
        
        # Convert to dict format
        articles_data = []
        for article in articles:
            article_dict = {
                "id": article.id,
                "title": article.title,
                "summary": article.summary,
                "url": article.url,
                "image_url": article.image_url,
                "source_id": article.source_id,
                "source_name": article.source.name if article.source else "Unknown",
                "category": article.primary_category,  # Primary category from new system
                "categories": article.categories_with_confidence,  # New multiple categories
                "published_at": (article.published_at or article.fetched_at).isoformat(),
                "fetched_at": article.fetched_at.isoformat() if article.fetched_at else None,
                "is_advertisement": article.is_advertisement or False,
                "ad_confidence": article.ad_confidence or 0.0,
                "ad_type": article.ad_type,
                "ad_reasoning": getattr(article, 'ad_reasoning', None),
                "ad_markers": getattr(article, 'ad_markers', []),
                # Add media fields
                "media_files": article.media_files or [],
                "images": article.images,  # Use property method
                "videos": article.videos,  # Use property method
                "documents": article.documents,  # Use property method
                "primary_image": article.primary_image  # Use property method
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
                "category": "Other",
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
        # Count total articles (including advertisements for "All" category)
        total_query = select(func.count(Article.id))
        total_count = await count_query(total_query)
        
        # Count by category using new system (excluding advertisements)
        category_query = select(
            Category.name, 
            func.count(ArticleCategory.article_id).label('count')
        ).join(ArticleCategory).join(Article).where(
            Article.is_advertisement != True
        ).group_by(Category.name)
        
        categories = await fetch_raw_all(category_query)
        
        # Build category stats (advertisements are excluded, shown as badges)
        category_stats = {"all": total_count}
        
        for category_name, count in categories:
            if category_name:
                category_stats[category_name.lower()] = count
        
        return {"categories": category_stats}
            
    except Exception as e:
        print(f"Categories error: {e}")
        return {"categories": {"all": 0}}