"""Categories API router - handles categories and category mappings."""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete, update
from sqlalchemy.orm import selectinload

from ..database import get_db
from ..models import Article, Category, ArticleCategory, CategoryMapping


router = APIRouter()


# ============================================================================
# Pydantic Models for Categories
# ============================================================================

class CategoryCreateRequest(BaseModel):
    name: str
    display_name: str
    description: Optional[str] = None
    color: Optional[str] = "#6c757d"


class CategoryResponse(BaseModel):
    id: int
    name: str
    display_name: str
    description: Optional[str]
    color: str
    created_at: datetime


class CategoryUpdateRequest(BaseModel):
    display_name: str
    color: Optional[str] = None
    description: Optional[str] = None


# ============================================================================
# Pydantic Models for Category Mappings
# ============================================================================

class CategoryMappingRequest(BaseModel):
    ai_category: str
    fixed_category: str
    confidence_threshold: Optional[float] = 0.0
    description: Optional[str] = None


class CategoryMappingResponse(BaseModel):
    id: int
    ai_category: str
    fixed_category: str
    confidence_threshold: float
    description: Optional[str]
    created_by: str
    usage_count: int
    last_used: Optional[datetime]
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CategoryMappingUpdateResponse(BaseModel):
    id: int
    ai_category: str
    fixed_category: str
    confidence_threshold: float
    description: Optional[str]
    is_active: bool
    updated_at: datetime


# ============================================================================
# Categories Endpoints
# ============================================================================

@router.get("/")
async def get_categories(db: AsyncSession = Depends(get_db)):
    """Get all available categories with article counts."""
    
    # Get categories from new table with article counts
    result = await db.execute(
        select(
            Category.id,
            Category.name,
            Category.display_name,
            Category.description,
            Category.color,
            func.count(ArticleCategory.article_id).label('count')
        )
        .outerjoin(ArticleCategory)
        .group_by(Category.id, Category.name, Category.display_name, Category.description, Category.color)
        .order_by(func.count(ArticleCategory.article_id).desc())
    )
    
    categories = []
    total_count = 0
    
    for id, name, display_name, description, color, count in result.all():
        categories.append({
            "id": id,
            "category": name,
            "display_name": display_name,
            "description": description,
            "color": color,
            "count": count
        })
        total_count += count
    
    # Get advertising count
    ad_result = await db.execute(
        select(func.count(Article.id).label('ad_count'))
        .where(Article.is_advertisement == True)
    )
    ad_count = ad_result.scalar() or 0
    
    # Add advertising as a special category if there are any ads
    if ad_count > 0:
        categories.append({
            "category": "advertisements",
            "count": ad_count
        })
    
    return {
        "categories": categories,
        "total_articles": total_count,
        "advertisements": ad_count
    }


@router.post("/", response_model=CategoryResponse)
async def create_category(
    payload: CategoryCreateRequest,
    db: AsyncSession = Depends(get_db)
):
    """Create a main category (admin)."""
    # TODO: Add admin auth when security is fixed
    
    # Check if category already exists
    existing_result = await db.execute(
        select(Category).where(Category.name == payload.name)
    )
    
    if existing_result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Category already exists")
    
    # Create new category
    category = Category(
        name=payload.name,
        display_name=payload.display_name,
        description=payload.description,
        color=payload.color
    )
    
    db.add(category)
    await db.commit()
    await db.refresh(category)
    
    return category


@router.put("/{category_id}", response_model=CategoryResponse)
async def update_category(
    category_id: int,
    payload: CategoryUpdateRequest,
    db: AsyncSession = Depends(get_db)
):
    """Update a category (admin)."""
    # TODO: Add admin auth when security is fixed
    
    # Find category
    result = await db.execute(
        select(Category).where(Category.id == category_id)
    )
    category = result.scalar_one_or_none()
    
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    
    # Update fields
    category.display_name = payload.display_name
    if payload.color:
        category.color = payload.color
    if payload.description is not None:
        category.description = payload.description
    
    await db.commit()
    await db.refresh(category)
    
    return category


# ============================================================================
# Category Mappings Endpoints
# ============================================================================

@router.get("/mappings", response_model=List[CategoryMappingResponse])
async def get_category_mappings(
    active_only: bool = True,
    db: AsyncSession = Depends(get_db)
):
    """Get all category mappings with their usage statistics."""
    query = select(CategoryMapping)
    
    if active_only:
        query = query.where(CategoryMapping.is_active == True)
    
    result = await db.execute(query.order_by(CategoryMapping.usage_count.desc()))
    mappings = result.scalars().all()
    
    return [
        CategoryMappingResponse(
            id=mapping.id,
            ai_category=mapping.ai_category,
            fixed_category=mapping.fixed_category,
            confidence_threshold=mapping.confidence_threshold,
            description=mapping.description,
            created_by=mapping.created_by,
            usage_count=mapping.usage_count,
            last_used=mapping.last_used,
            is_active=mapping.is_active,
            created_at=mapping.created_at,
            updated_at=mapping.updated_at
        ) for mapping in mappings
    ]


@router.post("/mappings", response_model=CategoryMappingResponse)
async def create_category_mapping(
    payload: CategoryMappingRequest,
    db: AsyncSession = Depends(get_db)
):
    """Create a new AI category to fixed category mapping."""
    # TODO: Add admin auth when security is fixed
    
    # Check if mapping already exists
    existing_result = await db.execute(
        select(CategoryMapping).where(
            CategoryMapping.ai_category == payload.ai_category,
            CategoryMapping.fixed_category == payload.fixed_category
        )
    )
    
    if existing_result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Mapping already exists")
    
    # Create new mapping
    mapping = CategoryMapping(
        ai_category=payload.ai_category,
        fixed_category=payload.fixed_category,
        confidence_threshold=payload.confidence_threshold or 0.0,
        description=payload.description,
        created_by="admin",  # TODO: Get from auth
        usage_count=0,
        is_active=True
    )
    
    db.add(mapping)
    await db.commit()
    await db.refresh(mapping)
    
    return CategoryMappingResponse(
        id=mapping.id,
        ai_category=mapping.ai_category,
        fixed_category=mapping.fixed_category,
        confidence_threshold=mapping.confidence_threshold,
        description=mapping.description,
        created_by=mapping.created_by,
        usage_count=mapping.usage_count,
        last_used=mapping.last_used,
        is_active=mapping.is_active,
        created_at=mapping.created_at,
        updated_at=mapping.updated_at
    )


@router.put("/mappings/{mapping_id}", response_model=CategoryMappingUpdateResponse)
async def update_category_mapping(
    mapping_id: int,
    payload: CategoryMappingRequest,
    db: AsyncSession = Depends(get_db)
):
    """Update an existing category mapping."""
    # TODO: Add admin auth when security is fixed
    
    # Find mapping
    result = await db.execute(
        select(CategoryMapping).where(CategoryMapping.id == mapping_id)
    )
    mapping = result.scalar_one_or_none()
    
    if not mapping:
        raise HTTPException(status_code=404, detail="Mapping not found")
    
    # Update fields
    mapping.ai_category = payload.ai_category
    mapping.fixed_category = payload.fixed_category
    mapping.confidence_threshold = payload.confidence_threshold or 0.0
    mapping.description = payload.description
    mapping.updated_at = datetime.utcnow()
    
    await db.commit()
    await db.refresh(mapping)
    
    return CategoryMappingUpdateResponse(
        id=mapping.id,
        ai_category=mapping.ai_category,
        fixed_category=mapping.fixed_category,
        confidence_threshold=mapping.confidence_threshold,
        description=mapping.description,
        is_active=mapping.is_active,
        updated_at=mapping.updated_at
    )


@router.delete("/mappings/{mapping_id}")
async def delete_category_mapping(
    mapping_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Delete a category mapping."""
    # TODO: Add admin auth when security is fixed
    
    # Find mapping
    result = await db.execute(
        select(CategoryMapping).where(CategoryMapping.id == mapping_id)
    )
    mapping = result.scalar_one_or_none()
    
    if not mapping:
        raise HTTPException(status_code=404, detail="Mapping not found")
    
    # Delete mapping
    await db.execute(delete(CategoryMapping).where(CategoryMapping.id == mapping_id))
    await db.commit()
    
    return {"message": "Mapping deleted successfully"}


@router.post("/mappings/{mapping_id}/toggle")
async def toggle_category_mapping(
    mapping_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Toggle active status of a category mapping."""
    # TODO: Add admin auth when security is fixed
    
    # Find mapping
    result = await db.execute(
        select(CategoryMapping).where(CategoryMapping.id == mapping_id)
    )
    mapping = result.scalar_one_or_none()
    
    if not mapping:
        raise HTTPException(status_code=404, detail="Mapping not found")
    
    # Toggle active status
    mapping.is_active = not mapping.is_active
    mapping.updated_at = datetime.utcnow()
    
    await db.commit()
    
    return {
        "message": f"Mapping {'activated' if mapping.is_active else 'deactivated'}",
        "is_active": mapping.is_active
    }


@router.get("/mappings/fixed-categories")
async def get_fixed_categories(db: AsyncSession = Depends(get_db)):
    """Get all available fixed categories from the main categories table."""
    result = await db.execute(
        select(Category.name).order_by(Category.name)
    )
    
    fixed_categories = [row[0] for row in result.all()]
    
    return {"fixed_categories": fixed_categories}


@router.get("/mappings/unmapped")
async def get_unmapped_ai_categories(
    limit: int = 100,
    db: AsyncSession = Depends(get_db)
):
    """Get AI categories that don't have mappings yet."""
    
    # Get all unique AI categories from article_categories
    # that don't have mappings in category_mapping table
    from sqlalchemy import text
    
    query = text("""
        SELECT DISTINCT ac.ai_category, COUNT(*) as usage_count
        FROM article_categories ac 
        LEFT JOIN category_mapping cm ON LOWER(ac.ai_category) = LOWER(cm.ai_category) 
            AND cm.is_active = true
        WHERE ac.ai_category IS NOT NULL 
          AND ac.ai_category != ''
          AND cm.ai_category IS NULL
        GROUP BY ac.ai_category 
        ORDER BY usage_count DESC, ac.ai_category
        LIMIT :limit
    """)
    
    result = await db.execute(query, {"limit": limit})
    unmapped_data = result.fetchall()
    
    unmapped_categories = [
        {
            "ai_category": row.ai_category,
            "usage_count": row.usage_count,
            "suggested_fixed_category": _suggest_fixed_category(row.ai_category),
            "examples": []  # Could be populated with article titles using this category
        }
        for row in unmapped_data
    ]
    
    return {
        "message": "Unmapped AI categories analysis",
        "unmapped_categories": unmapped_categories,
        "total_unmapped": len(unmapped_categories),
        "note": "These AI categories need manual mapping to fixed categories"
    }


def _suggest_fixed_category(ai_category: str) -> str:
    """Suggest a fixed category based on AI category name."""
    if not ai_category:
        return "Other"
    
    ai_lower = ai_category.lower()
    
    # Technology keywords
    if any(keyword in ai_lower for keyword in [
        'tech', 'software', 'innovation', 'digital', 'ai', 'computer', 'programming'
    ]):
        return "Tech"
    
    # Business keywords  
    elif any(keyword in ai_lower for keyword in [
        'business', 'economy', 'finance', 'market', 'trade', 'investment', 'company'
    ]):
        return "Business"
    
    # Politics keywords
    elif any(keyword in ai_lower for keyword in [
        'politics', 'government', 'election', 'policy', 'law', 'legal', 'parliament'
    ]):
        return "Politics"
    
    # International keywords
    elif any(keyword in ai_lower for keyword in [
        'international', 'world', 'global', 'foreign', 'europe', 'russia', 'china'
    ]):
        return "International"
    
    # Serbia keywords
    elif any(keyword in ai_lower for keyword in [
        'serbia', 'belgrade', 'serbian', 'вучич', 'белград', 'сербия'
    ]):
        return "Serbia"
    
    # Science keywords
    elif any(keyword in ai_lower for keyword in [
        'science', 'research', 'study', 'health', 'medicine', 'environment', 'education'
    ]):
        return "Science"
    
    else:
        return "Other"

