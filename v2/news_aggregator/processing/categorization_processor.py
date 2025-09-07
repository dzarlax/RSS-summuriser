"""Categorization processor for articles using AI and fallback methods."""

import logging
from typing import Dict, Any, List

from ..models import Article
from ..services.ai_client import get_ai_client


class CategorizationProcessor:
    """Handles article categorization using AI and fallback methods."""
    
    def __init__(self):
        self.ai_client = None
    
    async def _ensure_ai_client(self):
        """Ensure AI client is initialized."""
        if not self.ai_client:
            self.ai_client = get_ai_client()
    
    async def categorize_by_source_type_new(self, article: Article, source_type: str, stats: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Categorize article using new AI system that returns multiple categories."""
        await self._ensure_ai_client()
        
        try:
            content_for_analysis = article.summary or article.content or article.title or ""
            
            if not content_for_analysis.strip():
                return []
            
            # Use analyze_article_complete which returns categories array
            analysis_result = await self.ai_client.analyze_article_complete(
                article.title or "", 
                content_for_analysis,
                article.url or ""
            )
            
            if analysis_result and 'categories' in analysis_result:
                categories = analysis_result['categories']
                original_categories = analysis_result.get('original_categories', [])
                stats['api_calls_made'] += 1
                
                # Ensure each category dict has ai_category field for original AI category tracking
                processed_categories = []
                for i, cat in enumerate(categories):
                    # Get corresponding original category
                    original_cat = original_categories[i] if i < len(original_categories) else None
                    
                    if isinstance(cat, str):
                        # If category is just a string, convert to dict format
                        processed_categories.append({
                            'name': cat,
                            'confidence': 1.0,
                            'ai_category': original_cat or cat  # Use original AI category if available
                        })
                    elif isinstance(cat, dict):
                        # If already a dict, ensure ai_category field exists
                        processed_categories.append({
                            'name': cat.get('name', cat.get('category', 'Other')),
                            'confidence': cat.get('confidence', 1.0),
                            'ai_category': original_cat or cat.get('ai_category', cat.get('name', cat.get('category', 'Other')))
                        })
                
                return processed_categories
            else:
                return []
                
        except Exception as e:
            logging.error(f"Error categorizing article {article.url}: {e}")
            return []

    async def categorize_by_source_type(self, article: Article, source_type: str, stats: Dict[str, Any]) -> str:
        """Categorize article using AI for all source types."""
        await self._ensure_ai_client()
        
        try:
            content_for_categorization = article.summary or article.title or ""
            
            # Ensure we have content to categorize
            if not content_for_categorization.strip():
                return "Other"
            
            # Use unified analysis to get category
            analysis_result = await self.ai_client.analyze_article_complete(
                url=article.url or "https://example.com/article",
                content=content_for_categorization,
                title=article.title or ""
            )
            
            category = analysis_result.get('category', 'Other') if analysis_result else 'Other'
            stats['api_calls_made'] += 1
            return category
                
        except Exception as e:
            logging.error(f"Error categorizing article {article.url}: {e}")
            return "Other"
    
    def get_default_category(self) -> str:
        """Get default category."""
        return "Other"
    
    def get_fallback_category(self, title: str) -> str:
        """Get fallback category based on title keywords."""
        title_lower = title.lower()
        
        # Simple keyword-based categorization
        if any(word in title_lower for word in ['tech', 'technology', 'software', 'AI', 'artificial intelligence', 'digital', 'computer', 'internet']):
            return "Tech"
        elif any(word in title_lower for word in ['business', 'economy', 'market', 'finance', 'money', 'investment', 'stock']):
            return "Business"
        elif any(word in title_lower for word in ['science', 'research', 'study', 'scientist', 'discovery']):
            return "Science"
        elif any(word in title_lower for word in ['nature', 'environment', 'climate', 'wildlife', 'ecology']):
            return "Nature"
        elif any(word in title_lower for word in ['serbia', 'serbian', 'belgrade', 'novi sad', 'srbija']):
            return "Serbia"
        elif any(word in title_lower for word in ['marketing', 'advertising', 'brand', 'campaign']):
            return "Marketing"
        else:
            return self.get_default_category()