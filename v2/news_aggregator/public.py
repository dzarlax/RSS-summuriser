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
import magic

from .database import get_db, AsyncSessionLocal
from .database_helpers import fetch_raw_all, count_query, execute_custom_read
from .models import Article, Category, ArticleCategory, MediaFile
from .config import get_settings

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


def process_cached_media(article, image_url=None, media_files=None):
    """Process article media to return cached URLs when available."""
    if not hasattr(article, 'cached_media_files') or not article.cached_media_files:
        return image_url or article.image_url, media_files or article.media_files or []
    
    # Create a mapping of original URLs to cached media
    cached_media_map = {mf.original_url: mf for mf in article.cached_media_files if mf.cache_status == 'cached'}
    
    # Process image_url
    processed_image_url = image_url or article.image_url
    if processed_image_url and processed_image_url in cached_media_map:
        cached_media = cached_media_map[processed_image_url]
        cached_url = cached_media.get_cached_url('optimized') or cached_media.get_cached_url('original')
        if cached_url:
            processed_image_url = cached_url
    
    # Process media_files array
    processed_media_files = list(media_files or article.media_files or [])
    for media_item in processed_media_files:
        if isinstance(media_item, dict) and 'url' in media_item:
            original_url = media_item['url']
            if original_url in cached_media_map:
                cached_media = cached_media_map[original_url]
                cached_url = cached_media.get_cached_url('optimized') or cached_media.get_cached_url('original')
                if cached_url:
                    media_item['cached_url'] = cached_url
                    media_item['cache_status'] = 'cached'
                    media_item['file_size'] = cached_media.file_size
                    if cached_media.width:
                        media_item['width'] = cached_media.width
                    if cached_media.height:
                        media_item['height'] = cached_media.height
    
    return processed_image_url, processed_media_files

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
    hide_ads: bool = Query(True, description="Hide advertisements from feed")
):
    """Public feed endpoint without authentication (for main page)."""
    from .database import AsyncSessionLocal
    
    
    try:
        # Import required models
        from .models import Source, ArticleCategory, Category, MediaFile
        from sqlalchemy.orm import selectinload
        
        # Build query for articles with source and categories information
        query = select(Article).options(
            selectinload(Article.source),
            selectinload(Article.article_categories).selectinload(ArticleCategory.category),
            selectinload(Article.cached_media_files)
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
            # Process cached media URLs first
            processed_image_url, processed_media_files = process_cached_media(article)
            
            # Extract images from content using shared function
            content_images = extract_images_from_content(article.content or '')
            all_media_files = list(processed_media_files) + content_images
            all_images = [m for m in all_media_files if m.get('type') == 'image']
            
            # Determine primary image (prefer cached URL)
            primary_image = processed_image_url
            if not primary_image and all_images:
                primary_image = all_images[0].get('cached_url') or all_images[0]['url']
            
            # Get mapped categories for display
            from .services.category_display_service import get_category_display_service
            category_display_service = await get_category_display_service(session)
            
            # Map AI categories to display categories
            ai_categories = [
                {
                    'ai_category': ac.ai_category or 'Other',
                    'confidence': ac.confidence or 1.0
                }
                for ac in article.article_categories
            ]
            
            display_categories = await category_display_service.get_article_display_categories(ai_categories)
            primary_display_category = display_categories[0]['name'] if display_categories else 'Other'
            
            article_dict = {
                "id": article.id,
                "title": article.title,
                "summary": article.summary,
                "url": article.url,
                "image_url": processed_image_url,
                "source_id": article.source_id,
                "source_name": article.source.name if article.source else "Unknown",
                "category": primary_display_category,  # Primary mapped category
                "categories": display_categories,  # Mapped display categories
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
            
            # Get AI categories and map them to display categories
            from .models import ArticleCategory
            from .services.category_display_service import get_category_display_service
            
            # Get AI categories from database
            ai_categories_query = (
                select(ArticleCategory.ai_category, ArticleCategory.confidence)
                .where(ArticleCategory.article_id == article_id)
                .order_by(ArticleCategory.confidence.desc())
            )
            ai_categories_result = await session.execute(ai_categories_query)
            ai_categories_data = ai_categories_result.fetchall()
            
            # Map AI categories to display categories
            category_display_service = await get_category_display_service(session)
            
            ai_categories = [
                {
                    'ai_category': row.ai_category or 'Other',
                    'confidence': row.confidence or 1.0
                }
                for row in ai_categories_data
            ]
            
            # Filter out empty AI categories for cleaner display
            filtered_ai_categories = [
                cat for cat in ai_categories 
                if cat['ai_category'] and cat['ai_category'] != 'Other' and cat['ai_category'].strip()
            ]
            
            display_categories = await category_display_service.get_article_display_categories(ai_categories)
            primary_display_category = display_categories[0]['name'] if display_categories else 'Other'
                    
            article_data["category"] = primary_display_category
            article_data["categories"] = display_categories
            article_data["ai_categories"] = filtered_ai_categories  # Only meaningful AI categories
            
            # Handle cached media files properly
            cached_media_files = []
            cached_image_url = article_data["image_url"]  # Default to original
            
            # Get cached media files from database relationship
            from .models import MediaFile
            cached_query = select(MediaFile).where(
                MediaFile.article_id == article_id,
                MediaFile.cache_status == 'cached'
            )
            cached_result = await session.execute(cached_query)
            cached_files = cached_result.scalars().all()
            
            # Check if main image_url has a cached version
            for cached_file in cached_files:
                if cached_file.original_url == article_data["image_url"]:
                    cached_url = cached_file.get_cached_url('optimized') or cached_file.get_cached_url('original')
                    if cached_url:
                        cached_image_url = cached_url
                        break
            
            article_data["image_url"] = cached_image_url
            
            for cached_file in cached_files:
                cached_media_files.append({
                    'type': cached_file.media_type,
                    'url': cached_file.get_cached_url('optimized') or cached_file.get_cached_url('original'),
                    'thumbnail_url': cached_file.get_cached_url('thumbnail'),
                    'original_url': cached_file.original_url,
                    'filename': cached_file.filename,
                    'mime_type': cached_file.mime_type,
                    'file_size': cached_file.file_size,
                    'width': cached_file.width,
                    'height': cached_file.height,
                    'duration': cached_file.duration,
                    'cached_urls': {
                        'original': cached_file.get_cached_url('original'),
                        'thumbnail': cached_file.get_cached_url('thumbnail'),
                        'optimized': cached_file.get_cached_url('optimized')
                    },
                    'source': 'cached'
                })
            
            # Add content images
            content_images = extract_images_from_content(article.content or '')
            all_media_files = cached_media_files + content_images
            
            images = [m for m in all_media_files if m.get('type') == 'image'] if all_media_files else []
            videos = [m for m in all_media_files if m.get('type') == 'video'] if all_media_files else []
            documents = [m for m in all_media_files if m.get('type') == 'document'] if all_media_files else []
            
            # Primary image fallback
            primary_image = None
            if images:
                primary_image = images[0].get('url')
            elif article.image_url:
                primary_image = article.image_url
            
            # AI categories were filtered above
            
            article_data.update({
                "media_files": all_media_files,
                "images": images,
                "videos": videos,
                "documents": documents,
                "primary_image": primary_image
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


@router.get("/api/public/search")
async def search_articles(
    q: str = Query(..., min_length=2, description="Search query"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    category: Optional[str] = Query(None, description="Filter by category"),
    since_hours: Optional[int] = Query(None, ge=1, le=8760, description="Filter articles from last N hours"),
    sort: str = Query("relevance", regex="^(relevance|date|title)$", description="Sort by: relevance, date, title"),
    hide_ads: bool = Query(True, description="Hide advertisements from results")
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
        
        # Execute queries
        async with AsyncSessionLocal() as session:
            # Get articles
            result = await session.execute(query)
            articles = result.scalars().all()
            
            # Get total count
            try:
                count_result = await session.execute(count_query_stmt)
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


@router.get("/media/{media_type}/{variant}/{filename}")
async def serve_cached_media(
    media_type: str,  # images, videos, documents
    variant: str,     # original, thumbnails, optimized
    filename: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Serve cached media files.
    
    Path parameters:
        - media_type: Type of media (images, videos, documents)
        - variant: File variant (original, thumbnails, optimized)
        - filename: Media file name
        
    Returns cached media file with appropriate headers for browser caching.
    """
    try:
        settings = get_settings()
        
        # Validate media type and variant
        valid_media_types = ['images', 'videos', 'documents']
        valid_variants = ['original', 'thumbnails', 'optimized']
        
        if media_type not in valid_media_types:
            raise HTTPException(status_code=400, detail=f"Invalid media type. Must be one of: {valid_media_types}")
        
        if variant not in valid_variants:
            raise HTTPException(status_code=400, detail=f"Invalid variant. Must be one of: {valid_variants}")
        
        # Construct file path
        file_path = Path(settings.media_cache_dir) / media_type / variant / filename
        
        # Security check - ensure file is within cache directory
        try:
            file_path.resolve().relative_to(Path(settings.media_cache_dir).resolve())
        except ValueError:
            logging.warning(f"⚠️ Security violation: Attempted to access file outside cache dir: {file_path}")
            raise HTTPException(status_code=403, detail="Access denied")
        
        # Check if file exists
        if not file_path.exists() or not file_path.is_file():
            logging.warning(f"⚠️ Media file not found: {file_path}")
            raise HTTPException(status_code=404, detail="Media file not found")
        
        # Update access time in database for LRU tracking
        try:
            # Find media file record by filename/path pattern
            result = await db.execute(
                select(MediaFile).where(
                    MediaFile.cached_original_path.contains(filename) |
                    MediaFile.cached_thumbnail_path.contains(filename) |
                    MediaFile.cached_optimized_path.contains(filename)
                ).limit(1)
            )
            media_record = result.scalar_one_or_none()
            
            if media_record:
                media_record.accessed_at = datetime.utcnow()
                await db.commit()
                
        except Exception as e:
            logging.warning(f"⚠️ Could not update access time for {filename}: {e}")
            # Continue serving file even if DB update fails
        
        # Determine MIME type
        try:
            mime_type = magic.from_file(str(file_path), mime=True)
        except Exception:
            # Fallback to extension-based detection
            extension = file_path.suffix.lower()
            mime_map = {
                '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
                '.png': 'image/png', '.gif': 'image/gif',
                '.webp': 'image/webp', '.bmp': 'image/bmp',
                '.mp4': 'video/mp4', '.avi': 'video/avi',
                '.pdf': 'application/pdf', '.txt': 'text/plain'
            }
            mime_type = mime_map.get(extension, 'application/octet-stream')
        
        # Set cache headers for optimal browser caching
        headers = {
            "Cache-Control": "public, max-age=31536000, immutable",  # Cache for 1 year
            "ETag": f'"{filename}-{file_path.stat().st_mtime}"',  # ETag based on filename and modification time
        }
        
        # Add content-specific headers
        if media_type == 'images':
            headers["X-Content-Type-Options"] = "nosniff"
        
        logging.info(f"📁 Serving cached media: {file_path} (MIME: {mime_type})")
        
        return FileResponse(
            path=file_path,
            media_type=mime_type,
            headers=headers,
            filename=filename  # Suggests download filename
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"❌ Error serving media file {media_type}/{variant}/{filename}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/media/stats")
async def get_media_cache_stats():
    """Get media cache statistics."""
    try:
        from .services.media_cache_service import get_media_cache_service
        
        cache_service = get_media_cache_service()
        stats = await cache_service.get_cache_stats()
        
        return {
            "cache_stats": stats,
            "status": "success"
        }
        
    except Exception as e:
        logging.error(f"❌ Error getting media cache stats: {e}")
        raise HTTPException(status_code=500, detail="Could not retrieve cache statistics")
