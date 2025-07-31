"""Source registry for managing different source types."""

from typing import Dict, Type, Optional
from .base import BaseSource, SourceType, SourceInfo
from .rss_source import RSSSource
from .generic_source import GenericSource
from .telegram_source import TelegramSource


class SourceRegistry:
    """Registry for news source types."""
    
    def __init__(self):
        self._sources: Dict[SourceType, Type[BaseSource]] = {}
        self._register_default_sources()
    
    def _register_default_sources(self):
        """Register built-in source types."""
        self.register(SourceType.RSS, RSSSource)
        self.register(SourceType.TELEGRAM, TelegramSource)
        self.register(SourceType.REDDIT, GenericSource)
        self.register(SourceType.TWITTER, GenericSource)
        self.register(SourceType.NEWS_API, GenericSource)
        self.register(SourceType.CUSTOM, GenericSource)
    
    def register(self, source_type: SourceType, source_class: Type[BaseSource]):
        """Register a source type."""
        self._sources[source_type] = source_class
    
    def create_source(self, source_info: SourceInfo) -> BaseSource:
        """Create source instance from source info."""
        source_type = SourceType(source_info.source_type)
        
        if source_type not in self._sources:
            raise ValueError(f"Unknown source type: {source_type}")
        
        source_class = self._sources[source_type]
        return source_class(source_info)
    
    def get_supported_types(self) -> list[SourceType]:
        """Get list of supported source types."""
        return list(self._sources.keys())
    
    def is_supported(self, source_type: SourceType) -> bool:
        """Check if source type is supported."""
        return source_type in self._sources


# Global registry instance
_source_registry = SourceRegistry()


def get_source_registry() -> SourceRegistry:
    """Get the global source registry."""
    return _source_registry