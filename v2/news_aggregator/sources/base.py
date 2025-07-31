"""Base classes for news sources."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import AsyncGenerator, Dict, Any, Optional
from enum import Enum


class SourceType(str, Enum):
    """Source types."""
    RSS = "rss"
    TELEGRAM = "telegram" 
    REDDIT = "reddit"
    TWITTER = "twitter"
    NEWS_API = "news_api"
    CUSTOM = "custom"


@dataclass
class Article:
    """Article data structure."""
    title: str
    url: str
    content: Optional[str] = None
    summary: Optional[str] = None
    image_url: Optional[str] = None
    published_at: Optional[datetime] = None
    source_type: str = ""
    source_name: str = ""
    raw_data: Optional[Dict[str, Any]] = None


@dataclass
class SourceInfo:
    """Source information."""
    name: str
    source_type: SourceType
    url: str
    description: str
    enabled: bool = True
    config: Optional[Dict[str, Any]] = None


class BaseSource(ABC):
    """Base class for all news sources."""
    
    def __init__(self, source_info: SourceInfo):
        self.source_info = source_info
        self.name = source_info.name
        self.url = source_info.url
        self.config = source_info.config or {}
    
    @abstractmethod
    async def fetch_articles(self, limit: Optional[int] = None) -> AsyncGenerator[Article, None]:
        """
        Fetch articles from the source.
        
        Args:
            limit: Maximum number of articles to fetch
            
        Yields:
            Article objects
        """
        pass
    
    @abstractmethod
    async def test_connection(self) -> bool:
        """
        Test if the source is accessible.
        
        Returns:
            True if connection is successful
        """
        pass
    
    async def get_source_info(self) -> SourceInfo:
        """Get source information."""
        return self.source_info
    
    def __str__(self) -> str:
        return f"{self.__class__.__name__}({self.name})"
    
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name='{self.name}', url='{self.url}')"