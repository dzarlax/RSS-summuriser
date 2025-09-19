"""Public interface routes."""

import logging
from fastapi import APIRouter, Request, Query, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func, text
from sqlalchemy.orm import selectinload
from datetime import datetime, timedelta
from typing import Optional
from pathlib import Path
try:
    import magic
    MAGIC_AVAILABLE = True
except ImportError:
    MAGIC_AVAILABLE = False
    print("⚠️ python-magic not available - MIME type detection disabled")

from .database import get_db
from .database_helpers import fetch_raw_all, count_query, execute_custom_read
from .models import Article, Category, ArticleCategory
from .config import get_settings
from .services.data_service import DataService, get_data_service

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")



def extract_images_from_content(content: str) -> list:
    """Extract images from HTML content and return as media file objects."""
    if not content:
        return []
    
    import re
    import html
    
    content_images = []
    # Find all img tags in content
    img_pattern = r'<img[^>]+src=["\']([^"\']+)["\'][^>]*>'
    img_matches = re.findall(img_pattern, content, re.IGNORECASE)
    
    for i, img_url in enumerate(img_matches):
        # Clean up URL (decode HTML entities)
        clean_url = html.unescape(img_url)
        
        # Create media file object
        content_images.append({
            'type': 'image',
            'url': clean_url,
            'thumbnail_url': clean_url,
            'filename': f'content_image_{i+1}.jpg',
            'source': 'content_html'
        })
    
    return content_images


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


@router.get("/search", response_class=HTMLResponse)
async def public_search_view(request: Request):
    """Public search page."""
    return templates.TemplateResponse("public/search.html", {
        "request": request,
        "title": "Поиск новостей"
    })


@router.get("/api/public/feed") 
async def get_public_feed(
    limit: int = Query(20, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    since_hours: Optional[int] = Query(None, ge=1, le=168),
    category: Optional[str] = Query(None),
    hide_ads: bool = Query(True, description="Hide advertisements from feed"),
    data_service: DataService = Depends(get_data_service)
):
    """Public feed endpoint using unified DataService."""
    
    try:
        # Use DataService for clean database access
        articles_data = await data_service.get_articles_feed(
            limit=limit,
            offset=offset,
            since_hours=since_hours,
            category=category,
            hide_ads=hide_ads
        )
        
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


@router.get("/api/public/article/{article_id}")
async def get_public_article(
    article_id: int, 
    data_service: DataService = Depends(get_data_service)
):
    """Get full article content using unified DataService."""
    try:
        # Handle mock data case (when database is not available)
        if article_id == 1:
            return {
                "id": 1,
                "title": "⚠️ База данных недоступна",
                "summary": "Показываем тестовые данные. Проверьте подключение к БД.",
                "content": "К сожалению, база данных недоступна. Это тестовая статья. Пожалуйста, проверьте подключение к базе данных и перезапустите приложение.",
                "url": "https://example.com/db-error",
                "image_url": None,
                "source_name": "Система",
                "category": "other",
                "categories": [],
                "published_at": datetime.utcnow().isoformat(),
                "fetched_at": datetime.utcnow().isoformat(),
                "is_advertisement": False,
                "ad_confidence": 0.0,
                "ad_type": None,
                "ad_reasoning": None,
                "ad_markers": [],
                "media_files": [],
                "images": [],
                "videos": [],
                "documents": [],
                "primary_image": None,
                "ai_categories": [
                    {"category": "system", "confidence": 0.95},
                    {"category": "notification", "confidence": 0.80}
                ]
            }
        
        # Use DataService for clean database access
        article_data = await data_service.get_article_by_id(article_id)
        
        if not article_data:
            raise HTTPException(status_code=404, detail="Article not found")
        
        return article_data
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error getting article {article_id}: {e}")
        import traceback
        traceback.print_exc()
        
        # Return mock error data instead of 500 error
        return {
            "id": article_id,
            "title": "❌ Ошибка загрузки статьи",
            "summary": f"Не удалось загрузить статью с ID {article_id}",
            "content": f"Произошла ошибка при загрузке статьи: {str(e)[:200]}...",
            "url": "#",
            "image_url": None,
            "source_name": "Система",
            "category": "other",
            "categories": [],
            "published_at": datetime.utcnow().isoformat(),
            "fetched_at": datetime.utcnow().isoformat(),
            "is_advertisement": False,
            "ad_confidence": 0.0,
            "ad_type": None,
            "ad_reasoning": None,
            "ad_markers": [],
            "media_files": [],
            "images": [],
            "videos": [],
            "documents": [],
            "primary_image": None,
            "ai_categories": []
        }


@router.get("/api/public/categories/config")
async def get_public_categories_config(data_service: DataService = Depends(get_data_service)):
    """Get categories configuration using unified DataService."""
    
    try:
        return await data_service.get_categories_config()
            
    except Exception as e:
        print(f"Categories config error: {e}")
        # Return minimal fallback config
        return {
            "categories": {
                "all": {"name": "Все", "color": "#17a2b8"},
                "other": {"name": "Разное", "color": "#6c757d"}
            }
        }


@router.get("/api/public/categories")
async def get_public_categories(
    since_hours: Optional[int] = Query(None, ge=1, le=168),
    hide_ads: bool = Query(True),
    data_service: DataService = Depends(get_data_service)
):
    """Get category statistics using unified DataService."""
    
    try:
        return await data_service.get_categories_stats(
            since_hours=since_hours,
            hide_ads=hide_ads
        )
            
    except Exception as e:
        print(f"Categories error: {e}")
        return {"categories": {"all": 0}}


@router.get("/api/public/search")
async def search_articles(
    q: str = Query(..., min_length=2, description="Search query"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    category: Optional[str] = Query(None, description="Filter by category"),
    since_hours: Optional[int] = Query(None, ge=1, le=8760, description="Filter articles from last N hours"),
    sort: str = Query("relevance", regex="^(relevance|date|title)$", description="Sort by: relevance, date, title"),
    hide_ads: bool = Query(True, description="Hide advertisements from results"),
    db: AsyncSession = Depends(get_db)
):
    """
    Search articles by content, title, and summary.
    
    Supports:
    - Full-text search across title, summary, and content
    - Category filtering
    - Time-based filtering
    - Multiple sorting options
    - Pagination
    - Relevance scoring
    """
    try:
        from .models import Source, ArticleCategory, Category
        from sqlalchemy.orm import selectinload
        from sqlalchemy import or_, and_, case
        
        # Clean and prepare search query
        search_query = q.strip()
        if len(search_query) < 2:
            raise HTTPException(status_code=400, detail="Search query must be at least 2 characters")
        
        # Build base query with relationships
        query = select(Article).options(
            selectinload(Article.source),
            selectinload(Article.article_categories).selectinload(ArticleCategory.category)
        )
        
        # Full-text search across title, summary, and content
        # Using PostgreSQL ILIKE for case-insensitive partial matching
        search_conditions = []
        
        # Split search query into words for better matching
        search_words = [word.strip() for word in search_query.split() if len(word.strip()) >= 2]
        
        for word in search_words:
            word_pattern = f"%{word}%"
            word_condition = or_(
                Article.title.ilike(word_pattern),
                Article.summary.ilike(word_pattern),
                Article.content.ilike(word_pattern)
            )
            search_conditions.append(word_condition)
        
        # Combine all word conditions (AND logic for better precision)
        if search_conditions:
            if len(search_conditions) == 1:
                query = query.where(search_conditions[0])
            else:
                query = query.where(and_(*search_conditions))
        
        # Apply category filter
        if category and category.lower() != 'all':
            cats = [c.strip().lower() for c in category.split(',') if c.strip()]
            if len(cats) == 1 and cats[0] == 'advertisements':
                query = query.where(Article.is_advertisement == True)
            elif cats:
                subquery_categories = (
                    select(Article.id)
                    .join(ArticleCategory)
                    .join(Category)
                    .where(func.lower(Category.name).in_(cats))
                )
                query = query.where(Article.id.in_(subquery_categories))
        
        # Apply time filter
        if since_hours:
            since_time = datetime.utcnow() - timedelta(hours=since_hours)
            query = query.where(Article.published_at >= since_time)
        
        # Hide advertisements if requested (default: true)
        if hide_ads:
            query = query.where(Article.is_advertisement != True)
        
        # Apply sorting
        if sort == "date":
            query = query.order_by(desc(Article.published_at))
        elif sort == "title":
            query = query.order_by(Article.title)
        else:  # relevance (default)
            # Simple relevance: prioritize title matches, then summary, then content
            # Using CASE to create a relevance score
            relevance_score = case(
                (Article.title.ilike(f"%{search_query}%"), 3),
                (Article.summary.ilike(f"%{search_query}%"), 2),
                else_=1
            )
            query = query.order_by(desc(relevance_score), desc(Article.published_at))
        
        # Count total results for pagination
        count_query_stmt = select(func.count()).select_from(
            query.order_by(None).offset(None).limit(None).alias("search_results")
        )
        
        # Apply pagination
        query = query.offset(offset).limit(limit)
        
        # Execute queries using dependency injection
        # Get articles
        result = await db.execute(query)
        articles = result.scalars().all()
        
        # Get total count
        try:
            count_result = await db.execute(count_query_stmt)
            total_count = count_result.scalar()
        except Exception as count_error:
            logging.warning(f"Count query failed, using fallback: {count_error}")
            # Fallback: count current results
            total_count = len(articles) + offset
        
        # Convert to dict format (reuse logic from get_public_feed)
        articles_data = []
        for article in articles:
            # Extract images from content using shared function
            existing_media = article.media_files or []
            content_images = extract_images_from_content(article.content or '')
            all_media_files = list(existing_media) + content_images
            all_images = [m for m in all_media_files if m.get('type') == 'image']
            
            # Determine primary image
            primary_image = article.image_url
            if not primary_image and all_images:
                primary_image = all_images[0]['url']
            
            # Calculate simple relevance score for display
            relevance_score = 0
            title_lower = (article.title or '').lower()
            summary_lower = (article.summary or '').lower()
            content_lower = (article.content or '').lower()
            query_lower = search_query.lower()
            
            if query_lower in title_lower:
                relevance_score += 3
            if query_lower in summary_lower:
                relevance_score += 2
            if query_lower in content_lower:
                relevance_score += 1
            
            article_dict = {
                "id": article.id,
                "title": article.title,
                "summary": article.summary,
                "url": article.url,
                "image_url": article.image_url,
                "primary_image": primary_image,
                "source_id": article.source_id,
                "source_name": article.source.name if article.source else "Unknown",
                "category": article.primary_category,
                "categories": [
                    {
                        "name": ac.category.name,
                        "display_name": ac.category.display_name,
                        "color": ac.category.color,
                        "confidence": ac.confidence
                    }
                    for ac in article.article_categories
                ],
                "published_at": article.published_at.isoformat() if article.published_at else None,
                "fetched_at": article.fetched_at.isoformat() if article.fetched_at else None,
                "is_advertisement": article.is_advertisement,
                "media_files": all_media_files,
                "images": all_images,
                "relevance_score": relevance_score
            }
            articles_data.append(article_dict)
        
        return {
            "articles": articles_data,
            "pagination": {
                "total": total_count,
                "limit": limit,
                "offset": offset,
                "has_more": offset + limit < total_count
            },
            "query": search_query,
            "filters": {
                "category": category,
                "since_hours": since_hours,
                "sort": sort,
                "hide_ads": hide_ads
            },
            "results_count": len(articles_data)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error in search_articles: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# Media caching endpoint removed - functionality disabled


