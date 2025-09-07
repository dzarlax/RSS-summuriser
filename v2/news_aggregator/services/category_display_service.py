"""
Service for mapping AI categories to display categories at runtime.
"""

from typing import List, Dict, Optional, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from ..models import Category, CategoryMapping


class CategoryDisplayService:
    """Service for mapping AI categories to display categories."""
    
    # Fixed list of allowed display categories
    FIXED_CATEGORIES = {
        'Serbia': {'display_name': 'Сербия', 'color': '#dc3545'},
        'Tech': {'display_name': 'Технологии', 'color': '#007bff'},
        'Business': {'display_name': 'Бизнес', 'color': '#28a745'},
        'Science': {'display_name': 'Наука', 'color': '#6f42c1'},
        'Politics': {'display_name': 'Политика', 'color': '#839933'},
        'International': {'display_name': 'Международные', 'color': '#cd51bc'},
        'Other': {'display_name': 'Прочее', 'color': '#6c757d'}
    }
    
    # Default mapping rules
    DEFAULT_MAPPING = {
        # Technology terms
        'technology': 'Tech',
        'tech': 'Tech',
        'software': 'Tech',
        'ai': 'Tech',
        'artificial intelligence': 'Tech',
        'computer': 'Tech',
        'digital': 'Tech',
        'internet': 'Tech',
        'programming': 'Tech',
        'innovation': 'Tech',
        'технологии': 'Tech',
        'компьютер': 'Tech',
        'программирование': 'Tech',
        'интернет': 'Tech',
        'цифровой': 'Tech',
        
        # Business terms
        'business': 'Business',
        'economy': 'Business',
        'finance': 'Business',
        'market': 'Business',
        'trade': 'Business',
        'investment': 'Business',
        'company': 'Business',
        'startup': 'Business',
        'бизнес': 'Business',
        'экономика': 'Business',
        'финансы': 'Business',
        'торговля': 'Business',
        'инвестиции': 'Business',
        'компания': 'Business',
        
        # Politics terms
        'politics': 'Politics',
        'government': 'Politics',
        'election': 'Politics',
        'policy': 'Politics',
        'law': 'Politics',
        'legal': 'Politics',
        'parliament': 'Politics',
        'president': 'Politics',
        'minister': 'Politics',
        'политика': 'Politics',
        'правительство': 'Politics',
        'выборы': 'Politics',
        'закон': 'Politics',
        'парламент': 'Politics',
        'президент': 'Politics',
        'министр': 'Politics',
        
        # International terms
        'international': 'International',
        'world': 'International',
        'global': 'International',
        'foreign': 'International',
        'europe': 'International',
        'usa': 'International',
        'china': 'International',
        'russia': 'International',
        'nato': 'International',
        'eu': 'International',
        'международные': 'International',
        'мир': 'International',
        'глобальный': 'International',
        'европа': 'International',
        'россия': 'International',
        'китай': 'International',
        
        # Serbia terms
        'serbia': 'Serbia',
        'belgrade': 'Serbia',
        'serbian': 'Serbia',
        'вучич': 'Serbia',
        'белград': 'Serbia',
        'сербия': 'Serbia',
        'сербский': 'Serbia',
        
        # Science terms
        'science': 'Science',
        'research': 'Science',
        'study': 'Science',
        'health': 'Science',
        'medicine': 'Science',
        'environment': 'Science',
        'climate': 'Science',
        'nature': 'Science',
        'наука': 'Science',
        'исследование': 'Science',
        'здоровье': 'Science',
        'медицина': 'Science',
        'природа': 'Science',
        'климат': 'Science',
        
        # General/Other terms
        'news': 'Other',
        'general': 'Other',
        'other': 'Other',
        'society': 'Other',
        'culture': 'Other',
        'sports': 'Other',
        'entertainment': 'Other',
        'новости': 'Other',
        'общество': 'Other',
        'культура': 'Other',
        'спорт': 'Other',
        'развлечения': 'Other',
        'образование': 'Other',
        'общее': 'Other',
    }
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def map_ai_category_to_display(self, ai_category: str) -> Dict[str, Any]:
        """Map AI category to display category with details."""
        if not ai_category or ai_category.strip() == '':
            ai_category = 'Other'
        
        # First try database mapping
        try:
            result = await self.db.execute(
                select(CategoryMapping).where(
                    func.lower(CategoryMapping.ai_category) == ai_category.lower().strip(),
                    CategoryMapping.is_active == True
                )
            )
            db_mapping = result.scalar_one_or_none()
            
            if db_mapping:
                # Update usage stats
                db_mapping.usage_count += 1
                db_mapping.last_used = func.now()
                await self.db.commit()
                
                fixed_category = db_mapping.fixed_category
                display_info = self.FIXED_CATEGORIES.get(fixed_category, self.FIXED_CATEGORIES['Other'])
                
                return {
                    'name': fixed_category,
                    'display_name': display_info['display_name'],
                    'color': display_info['color'],
                    'ai_category': ai_category,
                    'mapping_source': 'database'
                }
        except Exception as e:
            print(f"  ⚠️ Database mapping lookup failed for '{ai_category}': {e}")
        
        # Try default mapping rules
        ai_lower = ai_category.lower().strip()
        
        # Exact match
        if ai_lower in self.DEFAULT_MAPPING:
            fixed_category = self.DEFAULT_MAPPING[ai_lower]
            display_info = self.FIXED_CATEGORIES.get(fixed_category, self.FIXED_CATEGORIES['Other'])
            
            return {
                'name': fixed_category,
                'display_name': display_info['display_name'],
                'color': display_info['color'],
                'ai_category': ai_category,
                'mapping_source': 'default_exact'
            }
        
        # Partial match
        for keyword, fixed_category in self.DEFAULT_MAPPING.items():
            if keyword in ai_lower or ai_lower in keyword:
                display_info = self.FIXED_CATEGORIES.get(fixed_category, self.FIXED_CATEGORIES['Other'])
                
                return {
                    'name': fixed_category,
                    'display_name': display_info['display_name'],
                    'color': display_info['color'],
                    'ai_category': ai_category,
                    'mapping_source': f'default_partial:{keyword}'
                }
        
        # Fallback to Other
        display_info = self.FIXED_CATEGORIES['Other']
        return {
            'name': 'Other',
            'display_name': display_info['display_name'],
            'color': display_info['color'],
            'ai_category': ai_category,
            'mapping_source': 'fallback'
        }
    
    async def get_article_display_categories(self, ai_categories: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert list of AI categories to display categories."""
        display_categories = []
        
        for ai_cat in ai_categories:
            ai_category_name = ai_cat.get('ai_category') or ai_cat.get('name', 'Other')
            confidence = ai_cat.get('confidence', 1.0)
            
            # Map to display category
            display_cat = await self.map_ai_category_to_display(ai_category_name)
            display_cat['confidence'] = confidence
            
            display_categories.append(display_cat)
        
        # Remove duplicates (if AI gave same category mapped to same fixed category)
        unique_categories = {}
        for cat in display_categories:
            key = cat['name']
            if key not in unique_categories or cat['confidence'] > unique_categories[key]['confidence']:
                unique_categories[key] = cat
        
        return list(unique_categories.values())
    
    async def get_all_display_categories(self) -> List[Dict[str, Any]]:
        """Get all available display categories."""
        categories = []
        
        for name, info in self.FIXED_CATEGORIES.items():
            categories.append({
                'name': name,
                'display_name': info['display_name'],
                'color': info['color']
            })
        
        return categories


async def get_category_display_service(db: AsyncSession) -> CategoryDisplayService:
    """Get category display service instance."""
    return CategoryDisplayService(db)