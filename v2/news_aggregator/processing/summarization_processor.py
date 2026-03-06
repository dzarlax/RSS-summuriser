import logging
"""Summarization processor for articles based on source type."""

from datetime import datetime
from typing import Dict, Any
from urllib.parse import urlparse

from ..models import Article
from ..services.ai_client import get_ai_client

logger = logging.getLogger(__name__)


class SummarizationProcessor:
    """Handles article summarization based on source type."""
    
    def __init__(self):
        self.ai_client = None
    
    async def _ensure_ai_client(self):
        """Ensure AI client is initialized."""
        if not self.ai_client:
            self.ai_client = get_ai_client()
    
    async def get_summary_by_source_type(self, article: Article, source_type: str, stats: Dict[str, Any]) -> Dict[str, Any]:
        """Get article summary (and optimized title) based on source type.

        Returns a dict with keys:
          - 'summary': str  — the generated summary
          - 'optimized_title': str | None  — AI-optimized title if available
        """
        await self._ensure_ai_client()

        try:
            if source_type == 'rss':
                return await self._process_rss_summary(article, stats)
            elif source_type == 'telegram':
                return await self._process_telegram_summary(article, stats)
            else:
                return await self._process_custom_summary(article, source_type, stats)

        except Exception as e:
            logger.warning(f"  ⚠️ Error getting summary by source type: {e}")
            return {'summary': article.content or article.title, 'optimized_title': None}
    
    async def _process_rss_summary(self, article: Article, stats: Dict[str, Any]) -> Dict[str, Any]:
        """Process RSS source summary."""
        ai_result = await self.ai_client.get_article_summary_with_metadata(article.url)
        stats['api_calls_made'] += 1

        ai_summary = ai_result.get('summary')
        pub_date = ai_result.get('publication_date')
        self._update_article_publication_date(article, pub_date, 'RSS')

        return {
            'summary': ai_summary or article.content or article.title,
            'optimized_title': ai_result.get('optimized_title'),
        }
    
    async def _process_telegram_summary(self, article: Article, stats: Dict[str, Any]) -> Dict[str, Any]:
        """Process Telegram source summary."""
        original_link = None
        try:
            if hasattr(article, 'raw_data') and article.raw_data:
                original_link = article.raw_data.get('original_link')
        except Exception:
            original_link = None

        if original_link and not self._is_telegram_domain(original_link):
            try:
                ai_result = await self.ai_client.get_article_summary_with_metadata(original_link)
                self._update_article_publication_date(article, ai_result.get('publication_date'), 'Telegram')
                ai_summary = ai_result.get('summary')
                if ai_summary:
                    return {
                        'summary': ai_summary,
                        'optimized_title': ai_result.get('optimized_title'),
                    }
            except Exception as e:
                logger.warning(f"  ⚠️ Skipping Telegram AI extraction (external link failed): {e}")

        return {'summary': article.content or article.title, 'optimized_title': None}
    
    async def _process_custom_summary(self, article: Article, source_type: str, stats: Dict[str, Any]) -> Dict[str, Any]:
        """Process custom or unknown source summary."""
        ai_result = await self.ai_client.get_article_summary_with_metadata(article.url)
        stats['api_calls_made'] += 1

        ai_summary = ai_result.get('summary')
        self._update_article_publication_date(article, ai_result.get('publication_date'), source_type)

        return {
            'summary': ai_summary or article.content or article.title,
            'optimized_title': ai_result.get('optimized_title'),
        }
    
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
            logger.info(f"  📅 Updated {source_type} article published_at: {parsed_date}")
        except Exception as e:
            logger.warning(f"  ⚠️ Error parsing {source_type} publication date '{pub_date}': {e}")