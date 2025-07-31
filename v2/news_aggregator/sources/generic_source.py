"""Generic source implementation for non-RSS sources."""

from typing import AsyncGenerator, Optional
from .base import BaseSource, Article, SourceInfo


class GenericSource(BaseSource):
    """Generic source implementation for Telegram, Reddit, Twitter, etc."""
    
    async def fetch_articles(self, limit: Optional[int] = None) -> AsyncGenerator[Article, None]:
        """
        Generic sources don't actively fetch articles.
        Articles are expected to be added manually or via other mechanisms.
        """
        # Return empty generator - no automatic fetching for generic sources
        return
        yield  # This makes it a generator but yields nothing
    
    async def test_connection(self) -> bool:
        """
        Test connection for generic sources.
        For generic sources, we just validate the URL format.
        """
        try:
            if not self.url or len(self.url.strip()) < 5:
                return False
            
            # Basic URL validation
            url = self.url.lower()
            
            # Validate based on source type
            source_type = self.source_info.source_type.value
            
            if source_type == "telegram":
                return "t.me/" in url or "telegram.me/" in url
            elif source_type == "reddit":
                return "reddit.com" in url or "www.reddit.com" in url
            elif source_type == "twitter":
                return "twitter.com" in url or "x.com" in url
            elif source_type == "news_api":
                return "http" in url  # Basic HTTP URL check
            elif source_type == "custom":
                return "http" in url  # Basic HTTP URL check
            else:
                return True  # Allow other types
                
        except Exception:
            return False