"""
Category management service for handling multiple categories per article.
"""

from typing import List, Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload

from ..models import Article, Category, ArticleCategory
from .category_parser import parse_category


class CategoryService:
    """Service for managing article categories."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_all_categories(self) -> List[Category]:
        """Get all available categories."""
        result = await self.db.execute(
            select(Category).order_by(Category.name)
        )
        return result.scalars().all()
    
    async def get_category_by_name(self, name: str) -> Optional[Category]:
        """Get category by name."""
        result = await self.db.execute(
            select(Category).where(Category.name == name)
        )
        return result.scalar_one_or_none()
    
    async def assign_categories_to_article(
        self, 
        article_id: int, 
        category_raw: str, 
        title: str = None, 
        content: str = None
    ) -> List[Dict]:
        """
        Parse and assign multiple categories to an article.
        
        Args:
            article_id: Article ID
            category_raw: Raw category string from AI
            title: Article title for context
            content: Article content for context
            
        Returns:
            List of assigned categories with confidence scores
        """
        # Parse categories with confidence scores
        categories_data = parse_category(
            category_raw, 
            title=title, 
            content=content, 
            return_multiple=True
        )
        
        if not isinstance(categories_data, list):
            # Fallback for single category
            categories_data = [{'name': categories_data, 'confidence': 1.0}]
        
        # Remove existing categories for this article
        await self.db.execute(
            delete(ArticleCategory).where(ArticleCategory.article_id == article_id)
        )
        
        assigned_categories = []
        
        for cat_data in categories_data:
            category_name = cat_data['name']
            confidence = cat_data['confidence']
            
            # Get category from database
            category = await self.get_category_by_name(category_name)
            if not category:
                print(f"⚠️ Category '{category_name}' not found, skipping")
                continue
            
            # Create article-category relationship
            article_category = ArticleCategory(
                article_id=article_id,
                category_id=category.id,
                confidence=confidence
            )
            
            self.db.add(article_category)
            assigned_categories.append({
                'name': category.name,
                'display_name': category.display_name,
                'confidence': confidence,
                'color': category.color
            })
        
        await self.db.commit()
        
        print(f"  🏷️ Assigned {len(assigned_categories)} categories to article {article_id}")
        for cat in assigned_categories:
            print(f"    - {cat['display_name']} ({cat['confidence']} confidence)")
        
        return assigned_categories
    
    async def get_article_categories(self, article_id: int) -> List[Dict]:
        """Get all categories for an article with details."""
        result = await self.db.execute(
            select(ArticleCategory)
            .options(selectinload(ArticleCategory.category))
            .where(ArticleCategory.article_id == article_id)
            .order_by(ArticleCategory.confidence.desc())
        )
        
        article_categories = result.scalars().all()
        
        return [
            {
                'name': ac.category.name,
                'display_name': ac.category.display_name,
                'confidence': ac.confidence,
                'color': ac.category.color
            }
            for ac in article_categories
        ]
    
    async def get_articles_by_category(
        self, 
        category_name: str, 
        limit: int = 50, 
        offset: int = 0
    ) -> List[Article]:
        """Get articles belonging to a specific category."""
        result = await self.db.execute(
            select(Article)
            .join(ArticleCategory)
            .join(Category)
            .where(Category.name == category_name)
            .options(selectinload(Article.source))
            .order_by(Article.fetched_at.desc())
            .limit(limit)
            .offset(offset)
        )
        
        return result.scalars().all()
    
    async def get_category_stats(self) -> Dict[str, int]:
        """Get article count for each category."""
        result = await self.db.execute(
            select(Category.name, Category.display_name)
            .outerjoin(ArticleCategory)
            .group_by(Category.id, Category.name, Category.display_name)
        )
        
        # This is a simplified version - in real implementation you'd count articles
        categories = result.all()
        stats = {}
        
        for category_name, display_name in categories:
            count_result = await self.db.execute(
                select(ArticleCategory.article_id)
                .join(Category)
                .where(Category.name == category_name)
            )
            count = len(count_result.scalars().all())
            stats[category_name] = {
                'display_name': display_name,
                'count': count
            }
        
        return stats


async def get_category_service(db: AsyncSession) -> CategoryService:
    """Get category service instance."""
    return CategoryService(db)
