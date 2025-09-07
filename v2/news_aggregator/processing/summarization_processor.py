"""Summarization processor for articles based on source type."""

from datetime import datetime
from typing import Dict, Any
from urllib.parse import urlparse

from ..models import Article
from ..services.ai_client import get_ai_client


class SummarizationProcessor:
    """Handles article summarization based on source type."""
    
    def __init__(self):
        self.ai_client = None
    
    async def _ensure_ai_client(self):
        """Ensure AI client is initialized."""
        if not self.ai_client:
            self.ai_client = get_ai_client()
    
    async def get_summary_by_source_type(self, article: Article, source_type: str, stats: Dict[str, Any]) -> str:
        """Get article summary based on source type."""
        await self._ensure_ai_client()
        
        try:
            if source_type == 'rss':
                return await self._process_rss_summary(article, stats)
            elif source_type == 'telegram':
                return await self._process_telegram_summary(article, stats)
            elif source_type == 'reddit':
                return await self._process_reddit_summary(article, stats)
            elif source_type == 'twitter':
                return await self._process_twitter_summary(article, stats)
            elif source_type == 'news_api':
                return await self._process_news_api_summary(article, stats)
            else:
                return await self._process_custom_summary(article, source_type, stats)
                
        except Exception as e:
            print(f"  ⚠️ Error getting summary by source type: {e}")
            # Fallback to original content
            return article.content or article.title
    
    async def _process_rss_summary(self, article: Article, stats: Dict[str, Any]) -> str:
        """Process RSS source summary."""
        # RSS sources: use AI to extract and summarize full article content with metadata
        ai_result = await self.ai_client.get_article_summary_with_metadata(article.url)
        stats['api_calls_made'] += 1
        
        ai_summary = ai_result.get('summary')
        pub_date = ai_result.get('publication_date')
        
        # Update published_at if we found a publication date
        self._update_article_publication_date(article, pub_date, 'RSS')
        
        if ai_summary:
            return ai_summary
        else:
            # Fallback to RSS content
            return article.content or article.title
    
    async def _process_telegram_summary(self, article: Article, stats: Dict[str, Any]) -> str:
        """Process Telegram source summary."""
        # Telegram sources: avoid heavy AI extraction for Telegram domains (t.me/telegram.me)
        # Prefer external original link if present and NOT a Telegram domain
        original_link = None
        try:
            if hasattr(article, 'raw_data') and article.raw_data:
                original_link = article.raw_data.get('original_link')
        except Exception:
            original_link = None

        # Only attempt AI metadata extraction when we have a non-Telegram external link
        if original_link and not self._is_telegram_domain(original_link):
            try:
                ai_result = await self.ai_client.get_article_summary_with_metadata(original_link)
                pub_date = ai_result.get('publication_date')
                # Update published_at if we found a publication date
                self._update_article_publication_date(article, pub_date, 'Telegram')
                ai_summary = ai_result.get('summary')
                if ai_summary:
                    # If AI managed to summarize external article, use it
                    return ai_summary
            except Exception as e:
                print(f"  ⚠️ Skipping Telegram AI extraction (external link failed): {e}")

        # Fallback: use Telegram preview content
        return article.content or article.title
    
    async def _process_reddit_summary(self, article: Article, stats: Dict[str, Any]) -> str:
        """Process Reddit source summary."""
        # Reddit sources: use AI to get full post content + comments context with metadata
        ai_result = await self.ai_client.get_article_summary_with_metadata(article.url)
        stats['api_calls_made'] += 1
        
        ai_summary = ai_result.get('summary')
        pub_date = ai_result.get('publication_date')
        
        # Update published_at if we found a publication date
        self._update_article_publication_date(article, pub_date, 'Reddit')
        
        if ai_summary:
            return ai_summary
        else:
            # Fallback to reddit content
            return article.content or article.title
    
    async def _process_twitter_summary(self, article: Article, stats: Dict[str, Any]) -> str:
        """Process Twitter source summary."""
        # Twitter sources: extract publication date if URL is available
        if article.url and article.url.startswith('http'):
            try:
                ai_result = await self.ai_client.get_article_summary_with_metadata(article.url)
                pub_date = ai_result.get('publication_date')
                
                # Update published_at if we found a publication date
                self._update_article_publication_date(article, pub_date, 'Twitter')
            except Exception as e:
                print(f"  ⚠️ Error extracting Twitter metadata: {e}")
        
        # Tweet content is usually complete, minimal processing
        return article.content or article.title
    
    async def _process_news_api_summary(self, article: Article, stats: Dict[str, Any]) -> str:
        """Process News API source summary."""
        # News API sources: use AI to get full article content with metadata
        ai_result = await self.ai_client.get_article_summary_with_metadata(article.url)
        stats['api_calls_made'] += 1
        
        ai_summary = ai_result.get('summary')
        pub_date = ai_result.get('publication_date')
        
        # Update published_at if we found a publication date
        self._update_article_publication_date(article, pub_date, 'News API')
        
        if ai_summary:
            return ai_summary
        else:
            # Fallback to API content
            return article.content or article.title
    
    async def _process_custom_summary(self, article: Article, source_type: str, stats: Dict[str, Any]) -> str:
        """Process custom or unknown source summary."""
        # Custom or unknown source types: use AI processing with metadata
        ai_result = await self.ai_client.get_article_summary_with_metadata(article.url)
        stats['api_calls_made'] += 1
        
        ai_summary = ai_result.get('summary')
        pub_date = ai_result.get('publication_date')
        
        # Update published_at if we found a publication date
        self._update_article_publication_date(article, pub_date, source_type)
        
        if ai_summary:
            return ai_summary
        else:
            # Fallback to original content
            return article.content or article.title
    
    def _is_telegram_domain(self, url: str) -> bool:
        """Check if URL is a Telegram domain."""
        try:
            host = urlparse(url).netloc.lower()
            return ('t.me' in host) or ('telegram.me' in host)
        except Exception:
            return False
    
    def _update_article_publication_date(self, article: Article, pub_date: str, source_type: str):
        """Update article publication date from extracted date string."""
        if not pub_date:
            return
            
        try:
            import dateutil.parser
            parsed_date = dateutil.parser.parse(pub_date)
            # Remove timezone info to match DateTime field in database
            article.published_at = parsed_date.replace(tzinfo=None) if parsed_date.tzinfo else parsed_date
            print(f"  📅 Updated {source_type} article published_at: {parsed_date}")
        except Exception as e:
            print(f"  ⚠️ Error parsing {source_type} publication date '{pub_date}': {e}")