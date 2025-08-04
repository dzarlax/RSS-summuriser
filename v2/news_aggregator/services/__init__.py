"""Services module."""

from .ai_client import AIClient, get_ai_client
from .source_manager import SourceManager
from .content_extractor import ContentExtractor, get_content_extractor
from .extraction_memory import ExtractionMemoryService, get_extraction_memory
from .domain_stability_tracker import DomainStabilityTracker, get_stability_tracker
from .ai_extraction_optimizer import AIExtractionOptimizer, get_ai_extraction_optimizer

__all__ = [
    'AIClient',
    'get_ai_client',
    'SourceManager',
    'ContentExtractor',
    'get_content_extractor',
    'ExtractionMemoryService',
    'get_extraction_memory',
    'DomainStabilityTracker',
    'get_stability_tracker',
    'AIExtractionOptimizer',
    'get_ai_extraction_optimizer'
]