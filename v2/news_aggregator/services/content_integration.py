"""Integration wrapper for enhanced content extraction."""

import asyncio
from typing import Optional, Dict, Any
from contextlib import asynccontextmanager

from .content_extractor import ContentExtractor, get_content_extractor
from ..core.exceptions import ContentExtractionError


class ContentExtractionService:
    """Service for content extraction."""
    
    def __init__(self):
        self._extractor = None
    
    async def extract_content(self, url: str) -> Optional[str]:
        """
        Extract content from URL using enhanced extractor.
        
        Args:
            url: Article URL
            
        Returns:
            Extracted content or None
        """
        if not url:
            return None
        
        try:
            if not self._extractor:
                self._extractor = await get_content_extractor()
            
            return await self._extractor.extract_article_content(url)
        
        except Exception as e:
            print(f"  ⚠️ Content extraction failed for {url}: {e}")
            return None
    
    async def batch_extract(self, urls: list[str], max_concurrent: int = 5) -> Dict[str, Optional[str]]:
        """
        Extract content from multiple URLs concurrently.
        
        Args:
            urls: List of URLs to process
            max_concurrent: Maximum concurrent extractions
            
        Returns:
            Dictionary mapping URLs to extracted content
        """
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def extract_single(url: str) -> tuple[str, Optional[str]]:
            async with semaphore:
                content = await self.extract_content(url)
                return url, content
        
        tasks = [extract_single(url) for url in urls if url]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results
        content_map = {}
        for result in results:
            if isinstance(result, Exception):
                print(f"  ⚠️ Batch extraction error: {result}")
                continue
            
            url, content = result
            content_map[url] = content
        
        return content_map
    
    async def get_extraction_stats(self) -> Dict[str, Any]:
        """Get extraction statistics (if available)."""
        stats = {
            "extractor_active": self._extractor is not None
        }
        
        return stats
    
    async def cleanup(self):
        """Cleanup resources."""
        if self._extractor and hasattr(self._extractor, 'browser'):
            if self._extractor.browser:
                await self._extractor.browser.close()


# Global service instance
_content_service = None

async def get_content_service() -> ContentExtractionService:
    """Get or create content extraction service."""
    global _content_service
    if _content_service is None:
        _content_service = ContentExtractionService()
    return _content_service

@asynccontextmanager
async def content_extraction_context():
    """Context manager for content extraction service."""
    service = ContentExtractionService()
    try:
        yield service
    finally:
        await service.cleanup()