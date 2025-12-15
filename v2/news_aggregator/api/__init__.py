"""API routers package for RSS Summarizer v2."""

from fastapi import APIRouter, Depends
from ..database import get_db
from ..security import require_admin
from .feed_router import router as feed_router
from .categories_router import router as categories_router
from .sources_router import router as sources_router
from .stats_router import router as stats_router
from .processing_router import router as processing_router
from .telegram_router import router as telegram_router
from .backup_router import router as backup_router
from .articles_router import router as articles_router
from .system_router import router as system_router
from .scheduler_router import router as scheduler_router
from .summaries_router import router as summaries_router


def create_api_router() -> APIRouter:
    """Create the main API router with all sub-routers."""
    router = APIRouter()
    
    # Include all specialized routers
    router.include_router(feed_router, tags=["feed"])
    router.include_router(categories_router, prefix="/categories", tags=["categories"], dependencies=[Depends(require_admin)])
    router.include_router(sources_router, prefix="/sources", tags=["sources"], dependencies=[Depends(require_admin)])
    router.include_router(stats_router, prefix="/stats", tags=["stats"], dependencies=[Depends(require_admin)])
    router.include_router(processing_router, prefix="/process", tags=["processing"], dependencies=[Depends(require_admin)])
    router.include_router(telegram_router, prefix="/telegram", tags=["telegram"], dependencies=[Depends(require_admin)])
    router.include_router(backup_router, prefix="/backup", tags=["backup"], dependencies=[Depends(require_admin)])
    router.include_router(articles_router, prefix="/articles", tags=["articles"], dependencies=[Depends(require_admin)])
    router.include_router(system_router, prefix="/system", tags=["system"], dependencies=[Depends(require_admin)])
    router.include_router(scheduler_router, prefix="/schedule", tags=["scheduler"], dependencies=[Depends(require_admin)])
    router.include_router(summaries_router, prefix="/summaries", tags=["summaries"], dependencies=[Depends(require_admin)])
    
    # Add category-mappings alias endpoints for frontend compatibility
    @router.get("/category-mappings", tags=["category-mappings"])
    async def get_category_mappings_alias(active_only: bool = True, db=Depends(get_db)):
        from .categories_router import get_category_mappings
        return await get_category_mappings(active_only=active_only, db=db)
    
    @router.get("/category-mappings/fixed-categories", tags=["category-mappings"])  
    async def get_fixed_categories_alias(db=Depends(get_db)):
        from .categories_router import get_fixed_categories
        from ..models import Category
        from sqlalchemy import select
        
        # Get categories with display names for frontend
        result = await db.execute(
            select(Category.name, Category.display_name).order_by(Category.name)
        )
        categories = result.all()
        
        # Format for frontend compatibility
        formatted_categories = [
            {
                "key": cat.name,
                "display_name": cat.display_name
            }
            for cat in categories
        ]
        
        return {"categories": formatted_categories}
    
    @router.get("/category-mappings/unmapped", tags=["category-mappings"])
    async def get_unmapped_categories_alias(limit: int = 100, db=Depends(get_db)):
        from .categories_router import get_unmapped_ai_categories
        return await get_unmapped_ai_categories(limit=limit, db=db)
    
    @router.post("/category-mappings", tags=["category-mappings"])
    async def create_category_mapping_alias(payload: dict, db=Depends(get_db)):
        from .categories_router import create_category_mapping, CategoryMappingRequest
        # Convert dict to CategoryMappingRequest
        mapping_request = CategoryMappingRequest(**payload)
        return await create_category_mapping(payload=mapping_request, db=db)
    
    # Add backups alias endpoint for frontend compatibility  
    @router.get("/backups", tags=["backup"])
    async def list_backups_alias():
        from .backup_router import list_backups
        return await list_backups()
    
    return router


# Export the main router
router = create_api_router()

__all__ = ['router']
