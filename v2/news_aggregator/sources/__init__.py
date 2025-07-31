"""News sources module."""

from .base import BaseSource, Article, SourceInfo, SourceType
from .rss_source import RSSSource
from .registry import SourceRegistry, get_source_registry

__all__ = [
    'BaseSource',
    'Article', 
    'SourceInfo',
    'SourceType',
    'RSSSource',
    'SourceRegistry',
    'get_source_registry'
]