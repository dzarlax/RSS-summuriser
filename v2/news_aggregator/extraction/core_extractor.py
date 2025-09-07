"""Core content extractor - main coordinator for all extraction strategies."""

import asyncio
import time
from typing import Optional, Dict, Any, List
from urllib.parse import urljoin

from ..core.cache import cached
from ..services.extraction_memory import get_extraction_memory, ExtractionAttempt
from ..services.domain_stability_tracker import get_stability_tracker
from ..services.ai_extraction_optimizer import get_ai_extraction_optimizer
from ..services.extraction_constants import HTML_CACHE_TTL_SECONDS, SELECTOR_CACHE_TTL_SECONDS

from .extraction_utils import ExtractionUtils
from .html_processor import HTMLProcessor
from .extraction_strategies import ExtractionStrategies


class CoreExtractor:
    """Core content extractor that coordinates all extraction strategies."""
    
    def __init__(self, utils: ExtractionUtils, html_processor: HTMLProcessor, strategies: ExtractionStrategies):
        self.utils = utils
        self.html_processor = html_processor
        self.strategies = strategies
        
        # Lightweight in-process caches
        self._html_cache: Dict[str, Any] = {}
        self._selector_cache: Dict[str, Any] = {}
        
        # Browser management (delegated to strategies)
        self.browser = None  # Will be managed by strategies
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close_browser()
    
    async def close_browser(self):
        """Close browser if open."""
        await self.strategies.close_browser()
    
    async def extract_article_content_with_metadata(self, url: str, retry_count: int = 3) -> Dict[str, Optional[str]]:
        """
        Extract article content along with metadata (title, publication date, author).
        
        Args:
            url: URL to extract from
            retry_count: Number of retry attempts
            
        Returns:
            Dict with content, title, publication_date, author, description, method_used
        """
        if not url:
            return {'content': None, 'title': None, 'publication_date': None, 
                   'author': None, 'description': None, 'method_used': None}
        
        # Clean URL first
        clean_url = self.utils.clean_url(url)
        domain = self.utils.extract_domain(clean_url)
        
        print(f"🔍 Extracting content with metadata from: {domain}")
        print(f"  🔗 URL: {clean_url[:100]}{'...' if len(clean_url) > 100 else ''}")
        
        extraction_start = time.time()
        last_exception = None
        
        for attempt in range(1, retry_count + 1):
            try:
                print(f"  📝 Extraction attempt {attempt}/{retry_count}")
                
                # Use comprehensive extraction with metadata
                result = await self.strategies.attempt_extraction_with_metadata(clean_url, domain, attempt)
                
                if result.get('content') and self.utils.is_good_content(result['content']):
                    extraction_time = time.time() - extraction_start
                    content_length = len(result['content'])
                    
                    print(f"  ✅ Extraction successful!")
                    print(f"     Method: {result.get('method_used', 'unknown')}")
                    print(f"     Content length: {content_length} characters")
                    print(f"     Time taken: {extraction_time:.2f}s")
                    
                    # Record success for learning
                    try:
                        extraction_memory = await get_extraction_memory()
                        attempt = ExtractionAttempt(
                            article_url=url,
                            domain=domain,
                            extraction_strategy=result.get('method_used', 'unknown'),
                            success=True,
                            content_length=content_length,
                            extraction_time_ms=int(extraction_time * 1000)
                        )
                        await extraction_memory.record_extraction_attempt(attempt)
                    except Exception as e:
                        print(f"  ⚠️ Failed to record success: {e}")
                    
                    # Update domain stability
                    try:
                        stability_tracker = await get_stability_tracker()
                        stability_tracker.update_domain_stats(
                            domain=domain,
                            success=True,
                            extraction_time_ms=int(extraction_time * 1000),
                            content_length=content_length,
                            quality_score=0.8,  # Default quality score for successful extraction
                            method=result.get('method_used', 'unknown')
                        )
                    except Exception as e:
                        print(f"  ⚠️ Failed to update domain stability: {e}")
                    
                    # Finalize content
                    result['content'] = self.utils.finalize_content(result['content'])
                    
                    return result
                    
                else:
                    print(f"  ❌ Attempt {attempt} failed - content quality insufficient")
                    if attempt < retry_count:
                        await asyncio.sleep(1)  # Brief delay before retry
                        
            except Exception as e:
                last_exception = e
                print(f"  ❌ Attempt {attempt} failed with error: {e}")
                
                # Record failure for learning
                try:
                    extraction_memory = await get_extraction_memory()
                    attempt_obj = ExtractionAttempt(
                        article_url=url,
                        domain=domain,
                        extraction_strategy=f"attempt_{attempt}",
                        success=False,
                        error_message=str(e)
                    )
                    await extraction_memory.record_extraction_attempt(attempt_obj)
                    
                    # Update domain stability for failure
                    stability_tracker = await get_stability_tracker()
                    stability_tracker.update_domain_stats(
                        domain=domain,
                        success=False,
                        method=f"attempt_{attempt}"
                    )
                except Exception as record_error:
                    print(f"  ⚠️ Failed to record failure: {record_error}")
                
                if attempt < retry_count:
                    await asyncio.sleep(1)
        
        # All attempts failed
        extraction_time = time.time() - extraction_start
        print(f"  💀 All extraction attempts failed after {extraction_time:.2f}s")
        
        # Try alternative URLs if available
        try:
            html = await self.strategies.fetch_html_content(clean_url)
            if html:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html, 'html.parser')
                alt_urls = self.strategies.metadata_extractor.find_alt_article_links(soup, clean_url)
                
                for alt_url in alt_urls[:2]:  # Try up to 2 alternative URLs
                    print(f"  🔄 Trying alternative URL: {alt_url}")
                    try:
                        alt_result = await self.strategies.attempt_extraction_with_metadata(alt_url, domain, 1)
                        if alt_result.get('content') and self.utils.is_good_content(alt_result['content']):
                            print(f"  ✅ Alternative URL successful!")
                            alt_result['content'] = self.utils.finalize_content(alt_result['content'])
                            return alt_result
                    except Exception as e:
                        print(f"  ❌ Alternative URL failed: {e}")
                        continue
        except Exception as e:
            print(f"  ⚠️ Failed to try alternative URLs: {e}")
        
        return {'content': None, 'title': None, 'publication_date': None,
               'author': None, 'description': None, 'method_used': 'failed'}
    
    async def extract_article_content(self, url: str, retry_count: int = 2) -> Optional[str]:
        """
        Extract article content (main public method for backward compatibility).
        
        Args:
            url: URL to extract from
            retry_count: Number of retry attempts
            
        Returns:
            Extracted content or None if extraction failed
        """
        if not url:
            return None
        
        # Clean URL first
        clean_url = self.utils.clean_url(url)
        domain = self.utils.extract_domain(clean_url)
        
        print(f"🔍 Extracting content from: {domain}")
        print(f"  🔗 URL: {clean_url[:100]}{'...' if len(clean_url) > 100 else ''}")
        
        extraction_start = time.time()
        last_exception = None
        
        for attempt in range(1, retry_count + 1):
            try:
                print(f"  📝 Extraction attempt {attempt}/{retry_count}")
                
                content = await self.strategies.attempt_content_extraction(clean_url, domain, attempt)
                
                if content and self.utils.is_good_content(content):
                    extraction_time = time.time() - extraction_start
                    content_length = len(content)
                    
                    print(f"  ✅ Extraction successful!")
                    print(f"     Content length: {content_length} characters")
                    print(f"     Time taken: {extraction_time:.2f}s")
                    
                    # Record success for learning
                    await self.strategies.record_extraction_success(
                        domain=domain,
                        method="content_extraction",
                        content_length=content_length,
                        extraction_time=extraction_time
                    )
                    
                    # Update domain stability
                    try:
                        stability_tracker = await get_stability_tracker()
                        await stability_tracker.record_success(domain, "content_extraction")
                    except Exception as e:
                        print(f"  ⚠️ Failed to update domain stability: {e}")
                    
                    return self.utils.finalize_content(content)
                    
                else:
                    print(f"  ❌ Attempt {attempt} failed - content quality insufficient")
                    if attempt < retry_count:
                        await asyncio.sleep(0.5)  # Brief delay before retry
                        
            except Exception as e:
                last_exception = e
                print(f"  ❌ Attempt {attempt} failed with error: {e}")
                
                # Record failure for learning
                await self.strategies.record_extraction_failure(
                    domain=domain,
                    method=f"content_attempt_{attempt}",
                    error=str(e)
                )
                
                if attempt < retry_count:
                    await asyncio.sleep(0.5)
        
        # All attempts failed
        extraction_time = time.time() - extraction_start
        print(f"  💀 All content extraction attempts failed after {extraction_time:.2f}s")
        
        # Try alternative URLs if available
        try:
            html = await self.strategies.fetch_html_content(clean_url)
            if html:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html, 'html.parser')
                alt_urls = self.strategies.metadata_extractor.find_alt_article_links(soup, clean_url)
                
                for alt_url in alt_urls[:1]:  # Try 1 alternative URL for content-only extraction
                    print(f"  🔄 Trying alternative URL: {alt_url}")
                    try:
                        alt_content = await self.strategies.attempt_content_extraction(alt_url, domain, 1)
                        if alt_content and self.utils.is_good_content(alt_content):
                            print(f"  ✅ Alternative URL successful!")
                            return self.utils.finalize_content(alt_content)
                    except Exception as e:
                        print(f"  ❌ Alternative URL failed: {e}")
                        continue
        except Exception as e:
            print(f"  ⚠️ Failed to try alternative URLs: {e}")
        
        return None
    
    @cached(ttl=HTML_CACHE_TTL_SECONDS)
    async def _extract_from_html(self, html: str) -> Optional[str]:
        """Extract content from already fetched HTML using soup-based strategies."""
        if not html:
            return None
        
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, 'html.parser')
            
            # Try multiple extraction methods in order of preference
            content = (
                self.strategies.metadata_extractor.extract_from_json_ld(soup) or
                self.html_processor.extract_by_enhanced_selectors(soup) or
                self.strategies.metadata_extractor.extract_from_open_graph(soup) or
                self.html_processor.extract_by_enhanced_heuristics(soup)
            )
            
            if content and self.utils.is_good_content(content):
                return self.utils.finalize_content(content)
                
        except Exception as e:
            print(f"HTML extraction failed: {e}")
        
        return None
    
    def get_extraction_stats(self) -> Dict[str, Any]:
        """Get extraction performance statistics."""
        return {
            'html_cache_size': len(self._html_cache),
            'selector_cache_size': len(self._selector_cache),
            'browser_active': self.browser is not None
        }

