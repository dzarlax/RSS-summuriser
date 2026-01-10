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
    
    def get_fallback_category(self, title: str, content: str = "") -> str:
        """
        Get fallback category based on title and content keywords.

        Uses weighted keyword scoring for better accuracy within the original category set.
        """
        # Combine title and content for better accuracy
        text_to_analyze = f"{title} {content}".lower()

        # Enhanced keyword mapping for original categories with weights
        category_keywords = {
            "AI": {
                "high": ["gpt", "chatgpt", "openai", "gemini", "claude", "llm", "large language model", "generative ai"],
                "medium": ["artificial intelligence", "machine learning", "neural network", "deep learning", "transformer", "ai model", "llms"],
                "low": ["ai", "a.i.", "automated", "intelligent", "machine learning"]
            },
            "Tech": {
                "high": ["blockchain", "cryptocurrency", "cybersecurity", "cloud computing", "software development"],
                "medium": ["software", "algorithm", "programming", "coding", "developer", "api", "cloud", "startup", "app"],
                "low": ["tech", "technology", "digital", "computer", "internet", "data", "online", "platform"]
            },
            "Business": {
                "high": ["stock market", "ipo", "merger", "acquisition", "bankruptcy", "ceo", "startup funding"],
                "medium": ["economy", "economic", "financial", "investment", "revenue", "profit", "startup", "trading"],
                "low": ["business", "company", "money", "market", "trade", "finance", "economic"]
            },
            "Science": {
                "high": ["quantum", "genomics", "nanotechnology", "astrophysics", "biochemistry", "breakthrough"],
                "medium": ["research", "study", "scientist", "discovery", "experiment", "hypothesis", "published", "journal"],
                "low": ["science", "scientific", "physics", "chemistry", "biology", "research", "study"]
            },
            "Nature": {
                "high": ["biodiversity", "ecosystem", "climate change", "conservation", "endangered species", "species"],
                "medium": ["environment", "wildlife", "ecology", "animal", "forest", "ocean", "carbon", "emissions"],
                "low": ["nature", "natural", "earth", "planet", "green", "climate", "environmental"]
            },
            "Serbia": {
                "high": ["belgrade", "novi sad", "niš", "kragujevac", "vojvodina", "srbija"],
                "medium": ["serbian", "beograd", "republic of serbia", "serbia's", "serbs", "serbian"],
                "low": ["serbia", "serb", "belgrade"]
            },
            "Marketing": {
                "high": ["advertising campaign", "brand strategy", "social media marketing", "influencer", "digital marketing"],
                "medium": ["marketing", "advertising", "brand", "promotion", "seo", "campaign", "social media"],
                "low": ["ad", "commercial", "branding", "promotion"]
            }
        }

        # Score each category
        category_scores = {}

        for category, keywords in category_keywords.items():
            score = 0

            # High weight keywords (3 points)
            for keyword in keywords.get("high", []):
                if keyword in text_to_analyze:
                    score += 3

            # Medium weight keywords (2 points)
            for keyword in keywords.get("medium", []):
                if keyword in text_to_analyze:
                    score += 2

            # Low weight keywords (1 point)
            for keyword in keywords.get("low", []):
                if keyword in text_to_analyze:
                    score += 1

            if score > 0:
                category_scores[category] = score

        # Return category with highest score, or default
        if category_scores:
            best_category = max(category_scores, key=category_scores.get)
            # Only use if confidence is reasonable (at least 2 points)
            if category_scores[best_category] >= 2:
                return best_category

        return self.get_default_category()