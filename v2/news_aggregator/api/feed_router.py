"""Feed API router - handles news feed endpoints."""

import html
from datetime import datetime, timedelta
from typing import Optional
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func
from sqlalchemy.orm import selectinload

from ..database import get_db
from ..models import Article, ArticleCategory, Category


router = APIRouter()


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
            "restore": "/api/v1/restore - Restore from backup",
            "system": {
                "process_monitor": "/api/v1/system/process-monitor - Process monitor status",
                "cleanup": "/api/v1/system/process-monitor/cleanup - Manual process cleanup"
            }
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
    # Get category display service for mapping AI categories to display categories
    from ..services.category_display_service import get_category_display_service
    category_display_service = await get_category_display_service(db)
    
    for article in articles:
        domain = extract_domain(article.url) if article.url else "unknown"
        
        # Clean summary from service text
        cleaned_summary = clean_summary_text(article.summary) if article.summary else None
        
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
            "category": primary_display_category,  # Primary mapped category for backward compatibility
            "categories": display_categories,  # Mapped display categories
            "ai_categories": ai_categories,  # Original AI categories for reference
            "published_at": article.published_at.isoformat() if article.published_at else None,
            "fetched_at": article.fetched_at.isoformat() if article.fetched_at else None,
            # Advertising detection data
            "is_advertisement": bool(getattr(article, 'is_advertisement', False)),
            "ad_confidence": float(getattr(article, 'ad_confidence', 0.0)),
            "ad_type": getattr(article, 'ad_type', None),
            "ad_reasoning": getattr(article, 'ad_reasoning', None),
            "ad_markers": getattr(article, 'ad_markers', [])
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
    
    return Response(
        content=reparsed.toprettyxml(indent="  "),
        media_type="application/rss+xml"
    )

