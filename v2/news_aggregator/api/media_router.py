"""Media caching API routes."""

from typing import Optional, List
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel

from ..auth import get_current_admin_user
from ..processing.media_cache_manager import MediaCacheManager

router = APIRouter()


# Media Cache Models
class MediaCacheStatsResponse(BaseModel):
    total_files: int
    total_size_mb: float
    by_type: dict
    cache_dir: str


class MediaCacheProcessResponse(BaseModel):
    articles_processed: int
    media_cached: int
    media_failed: int
    media_skipped: int
    errors: List[str] = []


# Media Cache Endpoints
@router.post("/cache", response_model=MediaCacheProcessResponse)
async def cache_media_files(
    article_ids: Optional[List[int]] = None,
    limit: int = Query(50, ge=1, le=500, description="Maximum number of articles to process"),
    admin_user: str = Depends(get_current_admin_user)
):
    """Cache media files for articles."""
    try:
        media_cache_manager = MediaCacheManager()
        
        if article_ids:
            stats = await media_cache_manager.cache_media_for_articles(article_ids=article_ids, limit=limit)
        else:
            stats = await media_cache_manager.cache_media_for_articles(limit=limit)
        
        return MediaCacheProcessResponse(**stats)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Media caching failed: {str(e)}")


@router.get("/cache/stats", response_model=MediaCacheStatsResponse)
async def get_media_cache_stats(
    admin_user: str = Depends(get_current_admin_user)
):
    """Get media cache usage statistics."""
    try:
        from ..services.media_cache_service import get_media_cache_service
        media_cache_service = get_media_cache_service()
        stats = await media_cache_service.get_cache_stats()
        
        if 'error' in stats:
            raise HTTPException(status_code=500, detail=stats['error'])
        
        return MediaCacheStatsResponse(**stats)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get cache stats: {str(e)}")


@router.delete("/cache/cleanup")
async def cleanup_media_cache(
    admin_user: str = Depends(get_current_admin_user)
):
    """Clean up old cached media files."""
    try:
        from ..services.media_cache_service import get_media_cache_service
        media_cache_service = get_media_cache_service()
        result = await media_cache_service.cleanup_old_cache()
        
        if 'error' in result:
            raise HTTPException(status_code=500, detail=result['error'])
        
        return {
            "message": "Cache cleanup completed",
            "cleaned_files": result['cleaned_files'],
            "freed_mb": result['freed_mb']
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cache cleanup failed: {str(e)}")