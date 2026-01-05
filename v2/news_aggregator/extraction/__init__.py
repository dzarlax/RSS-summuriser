"""Content extraction components for RSS Summarizer v2."""

import asyncio
import weakref

from .core_extractor import CoreExtractor
from .extraction_strategies import ExtractionStrategies
from .html_processor import HTMLProcessor
from .date_extractor import DateExtractor
from .metadata_extractor import MetadataExtractor
from .extraction_utils import ExtractionUtils
from .extraction_logger import ExtractionLogger, get_extraction_logger


class ContentExtractor:
    """
    Main content extractor that delegates to specialized components.
    
    This is a facade that provides the same interface as the original
    monolithic ContentExtractor but uses modular components internally.
    """
    
    def __init__(self):
        # Initialize all specialized components
        self.utils = ExtractionUtils()
        self.html_processor = HTMLProcessor(self.utils)
        self.date_extractor = DateExtractor(self.utils)
        self.metadata_extractor = MetadataExtractor(self.utils)
        self.extraction_strategies = ExtractionStrategies(
            self.utils, self.html_processor, self.date_extractor, self.metadata_extractor
        )
        self.core_extractor = CoreExtractor(
            self.utils, self.html_processor, self.extraction_strategies
        )
        _ACTIVE_EXTRACTORS.add(self)
    
    async def __aenter__(self):
        """Async context manager entry."""
        return await self.core_extractor.__aenter__()
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        return await self.core_extractor.__aexit__(exc_type, exc_val, exc_tb)
    
    async def close_browser(self):
        """Close browser if open."""
        return await self.core_extractor.close_browser()
    
    async def extract_article_content_with_metadata(self, url: str, retry_count: int = 3):
        """Extract article content with metadata (main public method)."""
        return await self.core_extractor.extract_article_content_with_metadata(url, retry_count)
    
    async def extract_article_content(self, url: str, retry_count: int = 2):
        """Extract article content (main public method)."""
        return await self.core_extractor.extract_article_content(url, retry_count)


# Factory function for backward compatibility
async def get_content_extractor():
    """Get a ContentExtractor instance (maintains original API)."""
    return ContentExtractor()


async def cleanup_content_extractor():
    """Cleanup resources (maintains original API)."""
    if not _ACTIVE_EXTRACTORS:
        return

    extractors = [extractor for extractor in list(_ACTIVE_EXTRACTORS) if extractor]
    if not extractors:
        return

    await asyncio.gather(
        *(extractor.close_browser() for extractor in extractors),
        return_exceptions=True
    )
    _ACTIVE_EXTRACTORS.clear()


_ACTIVE_EXTRACTORS: "weakref.WeakSet[ContentExtractor]" = weakref.WeakSet()


__all__ = [
    'ContentExtractor',
    'get_content_extractor',
    'cleanup_content_extractor',
    'CoreExtractor',
    'ExtractionStrategies',
    'HTMLProcessor',
    'DateExtractor',
    'MetadataExtractor',
    'ExtractionUtils',
    'ExtractionLogger',
    'get_extraction_logger'
]

