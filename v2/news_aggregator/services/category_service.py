"""
Category management service for handling multiple categories per article.
"""

from typing import List, Dict, Optional, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func
from sqlalchemy.orm import selectinload

from ..models import Article, Category, ArticleCategory
from .category_parser import parse_category


class CategoryService:
    """Service for managing article categories."""
    
    # Fixed list of allowed categories (only these 7 categories allowed)
    ALLOWED_CATEGORIES = {
        'Serbia': 'Сербия',
        'Tech': 'Технологии', 
        'Business': 'Бизнес',
        'Science': 'Наука',
        'Politics': 'Политика',
        'International': 'Международные',
        'Other': 'Прочее'
    }
    
    # Mapping of common category names to our fixed categories
    CATEGORY_MAPPING = {
        # International relations
        'russia': 'International',
        'europe': 'International', 
        'international relations': 'International',
        'world': 'International',
        'global': 'International',
        'foreign': 'International',
        
        # Health/Medical -> Science
        'health': 'Science',
        'medical': 'Science',
        'medicine': 'Science',
        'healthcare': 'Science',
        
        # Events/Society -> Other  
        'events': 'Other',
        'society': 'Other',
        'culture': 'Other',
        'lifestyle': 'Other',
        'entertainment': 'Other',
        'sports': 'Other',
        
        # Security/Legal -> Politics
        'security': 'Politics',
        'legal': 'Politics',
        'law': 'Politics',
        'government': 'Politics',
        'human rights': 'Politics',
        
        # Nature/Environment -> Science
        'nature': 'Science',
        'environment': 'Science',
        'climate': 'Science',
        'ecology': 'Science',
        
        # Generic news -> Other
        'news': 'Other',
        'general': 'Other',
    }
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def normalize_category_name(self, category_name: str) -> str:
        """Normalize category name to one of the allowed categories using database mappings."""
        if not category_name:
            return 'Other'
            
        # Check if it's already an allowed category
        if category_name in self.ALLOWED_CATEGORIES:
            return category_name
            
        # Try database mapping first
        from ..models import CategoryMapping
        from sqlalchemy import select

        # Prepare lowercase version for comparisons (define early to avoid UnboundLocalError)
        category_lower = category_name.lower().strip()

        try:
            # Look for exact match in database
            result = await self.db.execute(
                select(CategoryMapping).where(
                    CategoryMapping.ai_category == category_name,
                    CategoryMapping.is_active == True
                )
            )
            db_mapping = result.scalar_one_or_none()

            if db_mapping:
                # Update usage statistics (handle NULL)
                db_mapping.usage_count = (db_mapping.usage_count or 0) + 1
                db_mapping.last_used = func.now()
                await self.db.commit()

                print(f"  🔄 DB Mapped '{category_name}' → '{db_mapping.fixed_category}'")
                return db_mapping.fixed_category

            # Look for case-insensitive match in database
            result = await self.db.execute(
                select(CategoryMapping).where(
                    func.lower(CategoryMapping.ai_category) == category_lower,
                    CategoryMapping.is_active == True
                )
            )
            db_mapping = result.scalar_one_or_none()
            
            if db_mapping:
                # Update usage statistics (handle NULL)
                db_mapping.usage_count = (db_mapping.usage_count or 0) + 1
                db_mapping.last_used = func.now()
                await self.db.commit()

                print(f"  🔄 DB Mapped '{category_name}' → '{db_mapping.fixed_category}' (case-insensitive)")
                return db_mapping.fixed_category
                
        except Exception as e:
            print(f"  ⚠️ Database mapping lookup failed: {e}")
        
        # Fallback to hardcoded mapping
        mapped_category = self.CATEGORY_MAPPING.get(category_lower)
        if mapped_category:
            print(f"  🔄 Hardcoded mapped '{category_name}' → '{mapped_category}'")
            return mapped_category
            
        # Check partial matches for flexible mapping
        for key, mapped in self.CATEGORY_MAPPING.items():
            if key in category_lower or category_lower in key:
                print(f"  🔄 Partial mapped '{category_name}' → '{mapped}' (via '{key}')")
                return mapped
                
        # Default fallback - suggest creating a mapping
        print(f"  ⚠️ Unknown category '{category_name}' mapped to 'Other' - consider adding to database mapping")
        return 'Other'
    
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
    
    async def assign_categories_with_confidences(
        self, 
        article_id: int, 
        categories_with_confidence: List[Dict[str, Any]]
    ) -> List[Dict]:
        """
        Assign multiple categories with predefined confidence scores to an article.
        
        Args:
            article_id: Article ID
            categories_with_confidence: List of {'name': str, 'confidence': float}
            
        Returns:
            List of assigned categories with confidence scores
        """
        # Remove existing categories for this article
        await self.db.execute(
            delete(ArticleCategory).where(ArticleCategory.article_id == article_id)
        )
        
        assigned_categories = []
        
        for cat_data in categories_with_confidence:
            original_category_name = cat_data['name']
            confidence = cat_data['confidence']
            ai_category = cat_data.get('ai_category', original_category_name)  # Get original AI category
            
            # Normalize category name to allowed list
            normalized_category_name = await self.normalize_category_name(original_category_name)
            
            # Log mapping if category was changed
            if original_category_name != normalized_category_name:
                print(f"  🔄 Mapped '{original_category_name}' → '{normalized_category_name}'")
            
            # Get existing category (must exist in our fixed list)
            category = await self.get_category_by_name(normalized_category_name)
            if not category:
                print(f"  ❌ Category '{normalized_category_name}' not found in database - this should not happen!")
                continue
            
            # Create article-category relationship
            article_category = ArticleCategory(
                article_id=article_id,
                category_id=category.id,
                confidence=confidence,
                ai_category=ai_category  # Store original AI category
            )
            self.db.add(article_category)
            
            assigned_categories.append({
                'id': category.id,
                'name': category.name,
                'display_name': category.display_name,
                'confidence': confidence
            })
        
        await self.db.commit()
        return assigned_categories
    
    async def apply_mapping_changes_to_existing_articles(self, ai_category: str, old_fixed_category: str, new_fixed_category: str) -> int:
        """
        Apply category mapping changes to all existing articles.
        
        Args:
            ai_category: The AI category that was remapped
            old_fixed_category: Previous fixed category
            new_fixed_category: New fixed category
            
        Returns:
            Number of articles updated
        """
        if old_fixed_category == new_fixed_category:
            return 0
            
        print(f"🔄 Applying mapping change: {ai_category} ({old_fixed_category} → {new_fixed_category})")
        
        # Get category IDs
        old_category = await self.get_category_by_name(old_fixed_category)
        new_category = await self.get_category_by_name(new_fixed_category)
        
        if not old_category or not new_category:
            print(f"❌ Category not found: {old_fixed_category} or {new_fixed_category}")
            return 0
        
        # Find articles that were categorized with this specific AI category
        # Now we can be precise - update only articles that originally had this AI category
        from sqlalchemy import text
        
        # Update articles that have the specific AI category, regardless of current category
        result = await self.db.execute(text('''
            UPDATE article_categories 
            SET category_id = :new_category_id
            WHERE ai_category = :ai_category
            RETURNING article_id
        '''), {
            'ai_category': ai_category,
            'new_category_id': new_category.id
        })
        
        updated_articles = result.fetchall()
        await self.db.commit()
        
        count = len(updated_articles)
        print(f"✅ Updated {count} articles from {old_fixed_category} to {new_fixed_category}")
        
        return count
    
    async def apply_new_mapping_to_existing_articles(self, ai_category: str, fixed_category: str) -> int:
        """
        Apply new category mapping to all existing articles that have this AI category.
        
        Args:
            ai_category: The AI category to look for
            fixed_category: The fixed category to map to
            
        Returns:
            Number of articles updated
        """
        print(f"🔄 Applying new mapping to existing articles: {ai_category} → {fixed_category}")
        
        # Get the fixed category ID
        new_category = await self.get_category_by_name(fixed_category)
        if not new_category:
            print(f"❌ Fixed category not found: {fixed_category}")
            return 0
        
        # Find all articles that have this AI category and update their category_id
        from sqlalchemy import text
        result = await self.db.execute(text('''
            UPDATE article_categories 
            SET category_id = :new_category_id
            WHERE ai_category = :ai_category
            RETURNING article_id
        '''), {
            'ai_category': ai_category,
            'new_category_id': new_category.id
        })
        
        updated_articles = result.fetchall()
        await self.db.commit()
        
        count = len(updated_articles)
        print(f"✅ Applied new mapping to {count} articles: {ai_category} → {fixed_category}")
        
        return count
    
    async def bulk_recategorize_by_mapping(self, ai_category: str) -> int:
        """
        Recategorize all articles that should use a specific AI category mapping.
        This performs fresh AI analysis to ensure accuracy.
        
        Args:
            ai_category: The AI category to recategorize
            
        Returns:
            Number of articles recategorized
        """
        from ..models import CategoryMapping
        from sqlalchemy import text
        
        # Get the current mapping
        result = await self.db.execute(
            select(CategoryMapping).where(
                CategoryMapping.ai_category == ai_category,
                CategoryMapping.is_active == True
            )
        )
        mapping = result.scalar_one_or_none()
        
        if not mapping:
            print(f"❌ No active mapping found for AI category: {ai_category}")
            return 0
        
        print(f"🔍 Bulk recategorizing articles for: {ai_category} → {mapping.fixed_category}")
        
        # This would require AI re-analysis, which is expensive
        # For now, we'll implement a simpler approach in the next method
        return 0
    
    async def update_category_mapping(self, ai_category: str, new_fixed_category: str, description: str = None) -> bool:
        """
        Update a category mapping and apply changes to existing articles.
        
        Args:
            ai_category: AI category name to update
            new_fixed_category: New fixed category to map to
            description: Optional description for the change
            
        Returns:
            True if successful, False otherwise
        """
        from ..models import CategoryMapping
        from sqlalchemy import select
        
        # Get current mapping
        result = await self.db.execute(
            select(CategoryMapping).where(CategoryMapping.ai_category == ai_category)
        )
        mapping = result.scalar_one_or_none()
        
        if not mapping:
            # Create new mapping
            mapping = CategoryMapping(
                ai_category=ai_category,
                fixed_category=new_fixed_category,
                description=description or f"Auto-created mapping for {ai_category}",
                created_by="admin"
            )
            self.db.add(mapping)
            await self.db.commit()
            print(f"✅ Created new mapping: {ai_category} → {new_fixed_category}")
            return True
        
        old_fixed_category = mapping.fixed_category
        
        if old_fixed_category == new_fixed_category:
            print(f"⚠️ Mapping unchanged: {ai_category} → {new_fixed_category}")
            return True
        
        # Update mapping
        mapping.fixed_category = new_fixed_category
        if description:
            mapping.description = description
        await self.db.commit()
        
        # Apply to existing articles
        updated_count = await self.apply_mapping_changes_to_existing_articles(
            ai_category, old_fixed_category, new_fixed_category
        )
        
        print(f"✅ Updated mapping: {ai_category} ({old_fixed_category} → {new_fixed_category})")
        print(f"📊 Applied to {updated_count} existing articles")
        
        return True

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
