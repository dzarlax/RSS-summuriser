"""Public interface routes."""

import logging
from fastapi import APIRouter, Request, Query, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func, text
from sqlalchemy.orm import selectinload
from datetime import datetime, timedelta
from typing import Optional

from .database import get_db, AsyncSessionLocal
from .database_helpers import fetch_raw_all, count_query, execute_custom_read
from .models import Article, Category, ArticleCategory

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
        
        # Apply category filter (support multiple, comma-separated)
        if category and category.lower() != 'all':
            cats = [c.strip().lower() for c in category.split(',') if c.strip()]
            if len(cats) == 1 and cats[0] == 'advertisements':
                query = query.where(Article.is_advertisement == True)
            elif cats:
                subquery_new = (
                    select(Article.id)
                    .join(ArticleCategory)
                    .join(Category)
                    .where(func.lower(Category.name).in_(cats))
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
            # Extract images from content using shared function
            existing_media = article.media_files or []
            content_images = extract_images_from_content(article.content or '')
            all_media_files = list(existing_media) + content_images
            all_images = [m for m in all_media_files if m.get('type') == 'image']
            
            # Determine primary image
            primary_image = article.image_url
            if not primary_image and all_images:
                primary_image = all_images[0]['url']
            
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
                # Add media fields with extracted images
                "media_files": all_media_files,
                "images": all_images,
                "videos": [m for m in all_media_files if m.get('type') == 'video'],
                "documents": [m for m in all_media_files if m.get('type') == 'document'],
                "primary_image": primary_image
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


@router.get("/api/public/article/{article_id}")
async def get_public_article(article_id: int):
    """Get full article content for modal display."""
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
        
        # Use direct session like in other endpoints
        async with AsyncSessionLocal() as session:
            # Simple query without complex joins to avoid issues
            query = select(Article).where(Article.id == article_id)
            result = await session.execute(query)
            article = result.scalar_one_or_none()
            
            if not article:
                raise HTTPException(status_code=404, detail="Article not found")
            
            # Get source separately if needed
            source_name = "Unknown"
            if article.source_id:
                from .models import Source
                source_query = select(Source).where(Source.id == article.source_id)
                source_result = await session.execute(source_query)
                source = source_result.scalar_one_or_none()
                if source:
                    source_name = source.name
            
            # Get all data within session to avoid lazy loading issues
            article_data = {
                "id": article.id,
                "title": article.title,
                "summary": article.summary,
                "content": article.content,
                "url": article.url,
                "image_url": article.image_url,
                "source_name": source_name,
                "published_at": (article.published_at or article.fetched_at).isoformat(),
                "fetched_at": article.fetched_at.isoformat() if article.fetched_at else None,
                "is_advertisement": article.is_advertisement or False,
                "ad_confidence": article.ad_confidence or 0.0,
                "ad_type": article.ad_type,
                "ad_reasoning": getattr(article, 'ad_reasoning', None),
                "ad_markers": getattr(article, 'ad_markers', []),
            }
            
            # Get categories manually to avoid lazy loading
            from .models import ArticleCategory, Category
            categories_query = (
                select(Category.name, Category.display_name, Category.color, 
                       ArticleCategory.confidence, ArticleCategory.ai_category)
                .join(ArticleCategory)
                .where(ArticleCategory.article_id == article_id)
                .order_by(ArticleCategory.confidence.desc())
            )
            categories_result = await session.execute(categories_query)
            categories = categories_result.fetchall()
            
            # Build categories list and AI categories list
            categories_list = []
            ai_categories = []
            primary_category = "other"
            for cat_row in categories:
                categories_list.append({
                    "name": cat_row.name,
                    "display_name": cat_row.display_name,
                    "color": cat_row.color,
                    "confidence": cat_row.confidence
                })
                # If there's an original AI category, add to AI categories list
                if cat_row.ai_category:
                    ai_categories.append({
                        'category': cat_row.ai_category,
                        'confidence': cat_row.confidence,
                        'mapped_to': cat_row.display_name or cat_row.name
                    })
                if not primary_category or primary_category == "other":
                    primary_category = cat_row.name
            
            article_data["category"] = primary_category
            article_data["categories"] = categories_list
            
            # Handle media files safely using shared function
            existing_media = article.media_files or []
            content_images = extract_images_from_content(article.content or '')
            all_media_files = list(existing_media) + content_images
            
            images = [m for m in all_media_files if m.get('type') == 'image'] if all_media_files else []
            videos = [m for m in all_media_files if m.get('type') == 'video'] if all_media_files else []
            documents = [m for m in all_media_files if m.get('type') == 'document'] if all_media_files else []
            
            # Primary image fallback
            primary_image = None
            if images:
                primary_image = images[0].get('url')
            elif article.image_url:
                primary_image = article.image_url
            
            # AI categories already built above in the categories loop
            
            article_data.update({
                "media_files": all_media_files,
                "images": images,
                "videos": videos,
                "documents": documents,
                "primary_image": primary_image,
                "ai_categories": ai_categories
            })
        
        # Return data (session is now closed)
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
async def get_public_categories_config():
    """Get categories configuration with colors and display names for UI."""
    from .database import AsyncSessionLocal
    from .models import Category
    
    try:
        async with AsyncSessionLocal() as session:
            # Get all categories with their UI properties
            query = select(Category.name, Category.display_name, Category.color)
            result = await session.execute(query)
            categories = result.fetchall()
            
            # Build category config object
            category_config = {}
            for cat in categories:
                category_config[cat.name.lower()] = {
                    "name": cat.display_name or cat.name,
                    "color": cat.color or "#6c757d"
                }
            
            # Add special 'all' category
            category_config["all"] = {
                "name": "Все",
                "color": "#17a2b8"
            }
            
            return {"categories": category_config}
            
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
    hide_ads: bool = Query(True)
):
    """Get category statistics for public feed.
    Supports optional time window and ads visibility to match the feed.
    """
    from .database import AsyncSessionLocal
    
    try:
        # Base filter conditions
        conditions = []
        if hide_ads:
            conditions.append(Article.is_advertisement != True)
        if since_hours:
            since_time = datetime.utcnow() - timedelta(hours=since_hours)
            conditions.append(Article.published_at >= since_time)

        # Count total articles (respect filters)
        total_query = select(func.count(Article.id))
        if conditions:
            for cond in conditions:
                total_query = total_query.where(cond)
        total_count = await count_query(total_query)
        
        # Count by category using new system
        category_query = select(
            Category.name, 
            func.count(ArticleCategory.article_id).label('count')
        ).join(ArticleCategory).join(Article)
        if conditions:
            for cond in conditions:
                category_query = category_query.where(cond)
        category_query = category_query.group_by(Category.name)
        
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
