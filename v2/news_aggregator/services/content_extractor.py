"""Enhanced content extraction from web articles with AI optimization."""

import re
import json
import asyncio
import time
from typing import Optional, Dict, Any, List, Tuple
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Comment
from readability.readability import Document
from playwright.async_api import async_playwright, Browser, Page
from langdetect import detect
from langdetect.lang_detect_exception import LangDetectException
import textstat
import chardet
import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

from ..core.http_client import get_http_client
from ..core.cache import cached
from ..core.exceptions import ContentExtractionError
from .extraction_memory import get_extraction_memory, ExtractionAttempt
from .domain_stability_tracker import get_stability_tracker
from .ai_extraction_optimizer import get_ai_extraction_optimizer
from .extraction_constants import (
    MAX_CONTENT_LENGTH,
    MIN_CONTENT_LENGTH,
    BROWSER_CONCURRENCY,
    PLAYWRIGHT_TIMEOUT_FIRST_MS,
    PLAYWRIGHT_TIMEOUT_RETRY_MS,
    PLAYWRIGHT_TOTAL_BUDGET_MS,
    MIN_QUALITY_SCORE,
    HTML_CACHE_TTL_SECONDS,
    SELECTOR_CACHE_TTL_SECONDS,
)
import dateutil.parser


class ContentExtractor:
    """Enhanced content extractor with multiple fallback strategies."""
    
    def __init__(self):
        self.max_content_length = MAX_CONTENT_LENGTH
        self.min_content_length = MIN_CONTENT_LENGTH
        self.browser: Optional[Browser] = None
        # Limit concurrent browser pages to reduce resource pressure
        self._browser_semaphore = asyncio.Semaphore(BROWSER_CONCURRENCY)
        # Lightweight in-process caches
        self._html_cache: Dict[str, Tuple[float, str]] = {}
        self._domain_selector_cache: Dict[str, Tuple[float, str]] = {}
        
        # Universal content selectors (ordered by reliability)
        self.content_selectors = [
            # Schema.org microdata
            '[itemtype*="Article"] [itemprop="articleBody"]',
            '[itemtype*="NewsArticle"] [itemprop="articleBody"]',
            '[itemtype*="BlogPosting"] [itemprop="articleBody"]',
            
            # JSON-LD structured data (will be parsed separately)
            'script[type="application/ld+json"]',
            
            # Semantic HTML5 selectors
            'article[role="main"]',
            'main article',
            '[role="main"] article',
            
            # Modern framework patterns (TailwindCSS, Bootstrap, etc.)
            '.prose',  # TailwindCSS typography
            '.prose-lg', '.prose-xl',  # TailwindCSS variants
            '.container .text-base',  # Modern text containers
            '[class*="text-"] div:not([class*="nav"]):not([class*="menu"])',  # TailwindCSS text utilities
            
            # Site-specific patterns (based on popular Russian news sites)
            '.mb-14',  # N+1.ru main content
            '.article__text',  # Common Russian news pattern
            '.news-text', '.news-content',  # News sites
            '.material-text', '.full-text',  # Material content
            '.text-content', '.story-text',  # Story content
            
            # Common CMS patterns (WordPress, Drupal, etc.)
            '.entry-content',
            '.post-content',
            '.article-content',
            '.content-body',
            '.article-body',
            '.story-body',
            '.post-body',
            '.main-content',
            '.article-text',
            '.story-content',
            
            # Generic content containers
            'article',
            'main',
            '.content',
            '#content',
            '#main-content'
        ]
        
        # Unwanted element patterns
        self.unwanted_selectors = [
            # Navigation and UI
            'nav', 'header', 'footer', 'aside', 'sidebar',
            '.navigation', '.menu', '.nav', '.breadcrumb',
            
            # Ads and promotional content
            '.advertisement', '.ads', '.ad', '.promo',
            '.sponsored', '.promotion', '.banner',
            
            # Social and sharing
            '.social', '.share', '.sharing', '.social-media',
            '.facebook', '.twitter', '.instagram',
            
            # Comments and user content
            '.comments', '.comment', '.discussion',
            '.user-comments', '.comment-section',
            
            # Related content
            '.related', '.recommended', '.suggested',
            '.more-stories', '.you-might-like',
            
            # Newsletter and subscription
            '.newsletter', '.subscribe', '.subscription',
            '.email-signup', '.signup-form',
            
            # Tags and metadata (sometimes)
            '.tags', '.categories', '.metadata',
            '.publish-date', '.author-info'
        ]
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close_browser()
    
    async def close_browser(self):
        """Force close the browser and cleanup."""
        if self.browser:
            try:
                await self.browser.close()
            except Exception as e:
                print(f"Warning: Error closing browser: {e}")
            finally:
                self.browser = None
    
    async def extract_article_content_with_metadata(self, url: str, retry_count: int = 3) -> Dict[str, Optional[str]]:
        """
        Extract article content with metadata using AI-enhanced extraction with retry mechanism.
        
        Args:
            url: Article URL
            retry_count: Number of retries if extraction fails (default: 3)
            
        Returns:
            Dictionary with 'content', 'publication_date', and 'full_article_url' keys
        """
        import asyncio
        import random
        
        result = {
            'content': None,
            'publication_date': None,
            'full_article_url': None
        }
        
        if not url:
            return result
        
        # Clean URL from invisible/problematic characters
        url = self._clean_url(url)
        domain = self._extract_domain(url)
        
        print(f"🧠 AI-enhanced extraction with metadata for {domain} (max {retry_count} attempts)")
        
        last_exception = None
        
        for attempt in range(retry_count):
            try:
                if attempt > 0:
                    # Exponential backoff with jitter: 1s, 2s, 4s...
                    wait_time = (2 ** (attempt - 1)) + random.uniform(0.1, 0.5)
                    print(f"  🔄 Retry attempt {attempt + 1}/{retry_count} after {wait_time:.1f}s delay...")
                    await asyncio.sleep(wait_time)
                
                # Main extraction logic
                result = await self._attempt_extraction_with_metadata(url, domain, attempt + 1)
                
                # Check if extraction was successful
                if result.get('content') and len(result['content'].strip()) > 50:
                    if attempt > 0:
                        print(f"  ✅ Extraction succeeded on attempt {attempt + 1}/{retry_count}")
                    # Force close browser to prevent memory leaks after successful extraction
                    await self.close_browser()
                    return result
                else:
                    if attempt == 0:
                        print(f"  ⚠️ Initial extraction failed or insufficient content (got {len(result.get('content', '') or '')} chars)")
                    else:
                        print(f"  ⚠️ Retry {attempt + 1} failed or insufficient content (got {len(result.get('content', '') or '')} chars)")
                    
                    if attempt < retry_count - 1:
                        print(f"  🔄 Will retry with different strategy...")
                    
            except Exception as e:
                last_exception = e
                if attempt == 0:
                    print(f"  ❌ Initial extraction attempt failed: {e}")
                else:
                    print(f"  ❌ Retry attempt {attempt + 1} failed: {e}")
                
                if attempt < retry_count - 1:
                    print(f"  🔄 Will retry after delay...")
        
        # All attempts failed
        print(f"  ❌ All {retry_count} extraction attempts failed for {domain}")
        if last_exception:
            print(f"  ❌ Final error: {last_exception}")
        
        # Force close browser to prevent memory leaks
        await self.close_browser()
        
        return result
    
    async def _attempt_extraction_with_metadata(self, url: str, domain: str, attempt_num: int) -> Dict[str, Optional[str]]:
        """
        Single attempt at extraction with metadata.
        
        Args:
            url: Article URL  
            domain: Domain name
            attempt_num: Current attempt number (1-based)
            
        Returns:
            Dictionary with extraction results
        """
        result = {
            'content': None,
            'publication_date': None, 
            'full_article_url': None
        }
        
        try:
            # First, try to get the page HTML for analysis
            html_content = await self._fetch_html_content(url)
            if not html_content:
                print(f"  ⚠️ Failed to fetch HTML on attempt {attempt_num}, trying direct content extraction strategies...")
                # Skip HTML analysis and go directly to content extraction strategies
                content = await self.extract_article_content(url)
                if content:
                    result['content'] = content
                return result
            
            # Try canonical/AMP alternatives early (non-AI) to reach full article
            try:
                soup_for_links = BeautifulSoup(html_content, 'html.parser')
                alt_links = self._find_alt_article_links(soup_for_links, url)
                for alt_url in alt_links:
                    if alt_url and alt_url != url:
                        print(f"  🔗 Found alternative article link: {alt_url} (attempt {attempt_num})")
                        alt_html = await self._fetch_html_content(alt_url)
                        alt_content = await self._extract_from_html(alt_html)
                        if self._is_good_content(alt_content):
                            result['full_article_url'] = alt_url
                            result['content'] = alt_content
                            return result
            except Exception as e:
                print(f"  ⚠️ Canonical/AMP link follow failed on attempt {attempt_num}: {e}")
            
            # Import AI client dynamically
            from .ai_client import get_ai_client
            ai_client = get_ai_client()
            
            # Phase 1: Try custom parsers first, then AI and CSS selectors
            # Try custom parser for publication date only if enabled
            try:
                from ..config import settings
                if settings.use_custom_parsers:
                    from .custom_parsers import get_custom_parser_manager
                    custom_parser_manager = await get_custom_parser_manager()
                    if custom_parser_manager.can_parse(url):
                        try:
                            custom_result = custom_parser_manager.extract_metadata(html_content, url)
                            custom_date = custom_result.get('publication_date')
                            if custom_date:
                                result['publication_date'] = self._normalize_date(custom_date)
                                print(f"  📅 Custom parser publication date found: {custom_date} (attempt {attempt_num})")
                        except Exception as e:
                            print(f"  ⚠️ Custom parser date extraction failed on attempt {attempt_num}: {e}")
            except Exception:
                pass
            
            # If custom parser didn't find date, try AI and CSS
            if not result.get('publication_date'):
                try:
                    pub_date = await ai_client.extract_publication_date(html_content, url)
                    if pub_date:
                        result['publication_date'] = self._normalize_date(pub_date)
                        print(f"  📅 AI Publication date found: {pub_date} (attempt {attempt_num})")
                    else:
                        # Fallback to CSS selector-based extraction
                        soup = BeautifulSoup(html_content, 'html.parser')
                        css_date = self._extract_publication_date(soup)
                        if css_date:
                            result['publication_date'] = self._normalize_date(css_date)
                            print(f"  📅 CSS Publication date found: {css_date} (attempt {attempt_num})")
                except Exception as e:
                    print(f"  ⚠️ Error extracting publication date with AI on attempt {attempt_num}, trying CSS: {e}")
                    # Fallback to CSS selector-based extraction
                    try:
                        soup = BeautifulSoup(html_content, 'html.parser')
                        css_date = self._extract_publication_date(soup)
                        if css_date:
                            result['publication_date'] = self._normalize_date(css_date)
                            print(f"  📅 CSS Publication date found: {css_date} (attempt {attempt_num})")
                    except Exception as e2:
                        print(f"  ⚠️ Error extracting publication date with CSS on attempt {attempt_num}: {e2}")
            
            # Phase 2: Check if we need to follow a link for full content
            try:
                full_article_url = await ai_client.extract_full_article_link(html_content, url)
                if full_article_url and full_article_url != url:
                    result['full_article_url'] = full_article_url
                    print(f"  🔗 Full article link found: {full_article_url} (attempt {attempt_num})")
                    
                    # Extract content from the full article page
                    content = await self.extract_article_content(full_article_url)
                    if content:
                        result['content'] = content
                        return result
            except Exception as e:
                print(f"  ⚠️ Error extracting full article link on attempt {attempt_num}: {e}")
            
            # Phase 3: Extract content from current page using already fetched HTML first
            content = await self._extract_from_html(html_content)
            if not content:
                # Fallback to full pipeline (may use readability/playwright)
                content = await self.extract_article_content(url)
            result['content'] = content
            
            return result
            
        except Exception as e:
            print(f"  ❌ Error in enhanced extraction for {url} on attempt {attempt_num}: {e}")
            # Re-raise exception so retry logic can handle it
            raise
    
    async def extract_article_content(self, url: str, retry_count: int = 2) -> Optional[str]:
        """
        Extract main article content using AI-optimized strategies with retry mechanism.
        
        Args:
            url: Article URL
            retry_count: Number of retries if extraction fails (default: 2)
            
        Returns:
            Clean article text or None if failed
        """
        import asyncio
        import random
        
        if not url:
            return None
        
        # Clean URL from invisible/problematic characters
        url = self._clean_url(url)
        domain = self._extract_domain(url)
        
        print(f"🧠 AI-optimized extraction for {domain} (max {retry_count} attempts)")
        
        last_exception = None
        
        for attempt in range(retry_count):
            try:
                if attempt > 0:
                    # Shorter wait time for content extraction retry: 0.5s, 1s...
                    wait_time = (0.5 * (attempt)) + random.uniform(0.1, 0.3)
                    print(f"  🔄 Content extraction retry {attempt + 1}/{retry_count} after {wait_time:.1f}s delay...")
                    await asyncio.sleep(wait_time)
                
                # Main extraction logic
                content = await self._attempt_content_extraction(url, domain, attempt + 1)
                
                # Check if extraction was successful
                if content and len(content.strip()) > 50:
                    if attempt > 0:
                        print(f"  ✅ Content extraction succeeded on attempt {attempt + 1}/{retry_count}")
                    return content
                else:
                    if attempt == 0:
                        print(f"  ⚠️ Initial content extraction failed or insufficient content (got {len(content or '')} chars)")
                    else:
                        print(f"  ⚠️ Content extraction retry {attempt + 1} failed or insufficient content (got {len(content or '')} chars)")
                    
                    if attempt < retry_count - 1:
                        print(f"  🔄 Will retry content extraction...")
                    
            except Exception as e:
                last_exception = e
                if attempt == 0:
                    print(f"  ❌ Initial content extraction attempt failed: {e}")
                else:
                    print(f"  ❌ Content extraction retry {attempt + 1} failed: {e}")
                
                if attempt < retry_count - 1:
                    print(f"  🔄 Will retry content extraction after delay...")
        
        # All attempts failed
        print(f"  ❌ All {retry_count} content extraction attempts failed for {domain}")
        if last_exception:
            print(f"  ❌ Final error: {last_exception}")
        
        return None
    
    async def _attempt_content_extraction(self, url: str, domain: str, attempt_num: int) -> Optional[str]:
        """
        Single attempt at content extraction.
        
        Args:
            url: Article URL  
            domain: Domain name
            attempt_num: Current attempt number (1-based)
            
        Returns:
            Extracted content or None
        """
        start_time = time.time()

        # Check if this is a Telegram domain and handle specially
        if domain in ("t.me", "telegram.me", "www.t.me", "www.telegram.me"):
            print(f"  📱 Telegram domain detected - attempting enhanced extraction (attempt {attempt_num})")
            
            # For reprocessing, we should try to extract content from Telegram messages
            # that might contain external links
            try:
                telegram_content = await self._extract_from_telegram_with_links(url)
                if telegram_content and len(telegram_content) > 200:
                    print(f"  ✅ Extracted enhanced Telegram content: {len(telegram_content)} chars (attempt {attempt_num})")
                    return self._finalize_content(telegram_content)
                else:
                    print(f"  ⚠️ Telegram content not sufficient for reprocessing: {len(telegram_content or '')} chars (attempt {attempt_num})")
                    return None
                    
            except Exception as e:
                print(f"  ❌ Telegram enhanced extraction failed on attempt {attempt_num}: {e}")
                return None
        
        try:
            # Get AI services
            memory = await get_extraction_memory()
            stability_tracker = await get_stability_tracker()
            
            # Check if domain should be temporarily skipped due to consecutive failures
            should_skip, skip_reason = stability_tracker.should_skip_domain_temporarily(domain)
            if should_skip:
                print(f"  ⏰ Skipping {domain}: {skip_reason}")
                return None
            
            # Phase 0: Try custom parsers first only if enabled in config
            try:
                from ..config import settings
                if settings.use_custom_parsers:
                    from .custom_parsers import get_custom_parser_manager
                    custom_parser_manager = await get_custom_parser_manager()
                    if custom_parser_manager.can_parse(url):
                        try:
                            html_content = await self._fetch_html_content(url)
                            if html_content:
                                custom_result = custom_parser_manager.extract_metadata(html_content, url)
                                custom_content = custom_result.get('content')
                                if self._is_good_content(custom_content):
                                    await self._record_extraction_success(
                                        url, domain, 'custom_parser', custom_result.get('parser_used', 'unknown'),
                                        custom_content, int((time.time() - start_time) * 1000)
                                    )
                                    return self._finalize_content(custom_content)
                        except Exception as e:
                            print(f"  ⚠️ Custom parser failed for {domain}: {e}")
            except Exception:
                pass

            # Phase 0.25: Dynamic parser built on-the-fly from learned patterns (no domain hardcoding)
            try:
                from .custom_parsers import get_custom_parser_manager
                dyn_mgr = await get_custom_parser_manager()
                dyn_parser = await dyn_mgr.get_dynamic_parser_for_url(url)
                if dyn_parser:
                    html_for_dyn = await self._fetch_html_content(url)
                    if html_for_dyn:
                        soup_dyn = BeautifulSoup(html_for_dyn, 'html.parser')
                        self._remove_unwanted_elements(soup_dyn)
                        dyn_content = dyn_parser.extract_content(soup_dyn, url)
                        if self._is_good_content(dyn_content):
                            await self._record_extraction_success(
                                url, domain, 'dynamic_parser', getattr(dyn_parser, '_content_selectors', None),
                                dyn_content, int((time.time() - start_time) * 1000)
                            )
                            return self._finalize_content(dyn_content)
                        else:
                            # Negative feedback: degrade the first tried selector for this domain
                            try:
                                memory = await get_extraction_memory()
                                tried = getattr(dyn_parser, '_content_selectors', [])
                                if tried:
                                    await memory.degrade_pattern(domain, tried[0], 'dynamic_parser')
                            except Exception:
                                pass
            except Exception as e:
                print(f"  ⚠️ Dynamic parser phase failed: {e}")

            # Phase 0.5: Single HTML fetch to reuse across soup-based strategies
            html_for_soup = await self._fetch_html_content(url)
            if html_for_soup:
                # Try fast soup-based strategies first to avoid extra network requests
                soup = BeautifulSoup(html_for_soup, 'html.parser')
                # Remove unwanted elements once
                self._remove_unwanted_elements(soup)
                # JSON-LD
                content = self._extract_from_json_ld(soup)
                if self._is_good_content(content):
                    await self._record_extraction_success(
                        url, domain, 'json_ld', None, content, int((time.time() - start_time) * 1000)
                    )
                    return self._finalize_content(content)
                # Open Graph
                content = self._extract_from_open_graph(soup)
                if self._is_good_content(content):
                    await self._record_extraction_success(
                        url, domain, 'open_graph', None, content, int((time.time() - start_time) * 1000)
                    )
                    return self._finalize_content(content)
                # Enhanced selectors with A/B exploration: try top learned selector first (if any)
                ab_content = None
                learned_for_ab = await memory.get_best_patterns_for_domain(domain, strategy='css_selectors', limit=1)
                if learned_for_ab:
                    sel = learned_for_ab[0].selector_pattern
                    try:
                        elements = soup.select(sel)
                        if elements:
                            ab_text = elements[0].get_text(separator='\n', strip=True)
                            if ab_text:
                                ab_content = self._clean_text(ab_text)
                    except Exception:
                        ab_content = None
                content = ab_content or self._extract_by_enhanced_selectors(soup)
                if self._is_good_content(content):
                    await self._record_extraction_success(
                        url, domain, 'css_selectors', None, content, int((time.time() - start_time) * 1000)
                    )
                    return self._finalize_content(content)
                # Heuristics with A/B exploration: randomly test one alternative selector and compare
                import random
                heuristic_candidate = None
                alt_selectors = [
                    'article', '.entry-content', '.article-content', '.post-content', '.content-body'
                ]
                random.shuffle(alt_selectors)
                for sel in alt_selectors[:1]:
                    try:
                        el = soup.select_one(sel)
                        if el:
                            txt = el.get_text(separator='\n', strip=True)
                            if txt and len(txt) > self.min_content_length:
                                heuristic_candidate = self._clean_text(txt)
                                break
                    except Exception:
                        continue
                content = heuristic_candidate or self._extract_by_enhanced_heuristics(soup)
                if self._is_good_content(content):
                    await self._record_extraction_success(
                        url, domain, 'heuristics', None, content, int((time.time() - start_time) * 1000)
                    )
                    return self._finalize_content(content)
                
                # If soup-based strategies failed, try canonical/AMP alternatives before other phases
                try:
                    alt_links = self._find_alt_article_links(soup, url)
                    for alt_url in alt_links:
                        if alt_url and alt_url != url:
                            print(f"  🔗 Trying alternative article link: {alt_url}")
                            alt_html = await self._fetch_html_content(alt_url)
                            alt_soup = BeautifulSoup(alt_html, 'html.parser') if alt_html else None
                            if alt_soup:
                                self._remove_unwanted_elements(alt_soup)
                                alt_content = (
                                    self._extract_from_json_ld(alt_soup)
                                    or self._extract_by_enhanced_selectors(alt_soup)
                                    or self._extract_by_enhanced_heuristics(alt_soup)
                                )
                                if self._is_good_content(alt_content):
                                    await self._record_extraction_success(
                                        url, domain, 'alt_link', None, alt_content, int((time.time() - start_time) * 1000)
                                    )
                                    return self._finalize_content(alt_content)
                except Exception as e:
                    print(f"  ⚠️ Alternative link attempt failed: {e}")
            
            # Phase 1: Try learned best patterns first
            learned_patterns = await memory.get_best_patterns_for_domain(domain, limit=3)
            
            for pattern in learned_patterns:
                if pattern.success_rate > 70:  # High confidence patterns
                    print(f"  📚 Trying learned pattern: {pattern.selector_pattern[:40]}... ({pattern.success_rate:.1f}%)")
                    # Use cached HTML with domain selector when possible to avoid extra fetches
                    cached_selector = self._domain_selector_cache.get(domain)
                    if cached_selector and (time.monotonic() - cached_selector[0] <= SELECTOR_CACHE_TTL_SECONDS):
                        sel = cached_selector[1]
                        content = await self._extract_with_css_selector(url, sel)
                    else:
                        content = await self._extract_with_learned_pattern(url, pattern)
                    
                    if self._is_good_content(content):
                        # Record successful extraction
                        await self._record_extraction_success(
                            url, domain, pattern.extraction_strategy, pattern.selector_pattern,
                            content, int((time.time() - start_time) * 1000)
                        )
                        # Cache successful selector for domain
                        if pattern.extraction_strategy != 'playwright':
                            self._domain_selector_cache[domain] = (time.monotonic(), pattern.selector_pattern)
                        return self._finalize_content(content)
            
            # Phase 2: Standard extraction strategies with learning
            # Get the best method for this domain and try it first
            best_method = stability_tracker.get_best_method_for_domain(domain)
            ineffective_methods = stability_tracker.get_ineffective_methods_for_domain(domain, min_attempts=2)
            recently_failed_methods = stability_tracker.get_recently_failed_methods(domain, recent_failures_threshold=1)
            
            # Define all available strategies
            all_strategies = {
                'encoding_aware': self._extract_with_encoding_detection,
                'readability': self._extract_with_readability,
                'html_parsing': self._extract_with_enhanced_selectors,
                'playwright': self._extract_with_browser
            }
            
            # Filter out ineffective and recently failed methods
            methods_to_skip = set(ineffective_methods + recently_failed_methods)
            if methods_to_skip:
                print(f"  ⚠️ Skipping failing methods for {domain}: {', '.join(methods_to_skip)}")
                all_strategies = {name: func for name, func in all_strategies.items() if name not in methods_to_skip}
            
            # Prioritize strategies based on domain history
            if best_method and best_method in all_strategies:
                print(f"  🎯 Prioritizing best method for {domain}: {best_method}")
                # Try best method first
                strategies = [(best_method, all_strategies[best_method])]
                # Add remaining strategies
                remaining_strategies = [(name, func) for name, func in all_strategies.items() if name != best_method]
                strategies.extend(remaining_strategies)
            else:
                # Use available strategies in default order (encoding_aware first)
                default_order = ['encoding_aware', 'readability', 'html_parsing', 'playwright']
                strategies = [(name, all_strategies[name]) for name in default_order if name in all_strategies]
            
            for strategy_name, strategy_func in strategies:
                print(f"  🔧 Trying strategy: {strategy_name}")
                content = await strategy_func(url)
                
                if self._is_good_content(content):
                    # Record successful extraction
                    await self._record_extraction_success(
                        url, domain, strategy_name, None, content,
                        int((time.time() - start_time) * 1000)
                    )
                    return self._finalize_content(content)
                
                # Record failed attempt
                await self._record_extraction_failure(
                    url, domain, strategy_name, int((time.time() - start_time) * 1000)
                )
            
            # Phase 3: AI optimization for struggling domains
            should_optimize, reason = stability_tracker.should_use_ai_optimization(domain)
            if should_optimize:
                print(f"  🤖 Triggering AI optimization: {reason}")
                ai_optimizer = await get_ai_extraction_optimizer()
                success = await ai_optimizer.optimize_domain_extraction(domain, [url])
                
                if success:
                    # Try again with new AI patterns
                    new_patterns = await memory.get_best_patterns_for_domain(domain, limit=2)
                    for pattern in new_patterns:
                        if pattern.discovered_by == 'ai':
                            print(f"  🎯 Trying new AI pattern: {pattern.selector_pattern[:40]}...")
                            # Prefer CSS application when possible; cache result
                            content = await self._extract_with_css_selector(url, pattern.selector_pattern)
                            
                            if self._is_good_content(content):
                                await self._record_extraction_success(
                                    url, domain, pattern.extraction_strategy, pattern.selector_pattern,
                                    content, int((time.time() - start_time) * 1000)
                                )
                                self._domain_selector_cache[domain] = (time.monotonic(), pattern.selector_pattern)
                                return self._finalize_content(content)
            
            # Complete failure - record for exponential backoff
            print(f"  💥 All extraction strategies failed for {domain}")
            stability_tracker.record_all_methods_failure(domain)
            return None
            
        except Exception as e:
            print(f"  ❌ Extraction error for {url}: {e}")
            raise ContentExtractionError(f"Failed to extract content from {url}: {e}")
    
    async def _fetch_html_content(self, url: str) -> Optional[str]:
        """Fetch raw HTML content from URL with Brotli support."""
        try:
            # Serve from cache if fresh
            now = time.monotonic()
            cached = self._html_cache.get(url)
            if cached and (now - cached[0] <= HTML_CACHE_TTL_SECONDS):
                return cached[1]
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',  # Brotli support
                'Connection': 'keep-alive',
                'Cache-Control': 'no-cache',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1',
                'Upgrade-Insecure-Requests': '1'
            }
            
            async with get_http_client() as client:
                response = await client.session.get(url, headers=headers, timeout=15)
                if response.status == 200:
                    # aiohttp should automatically decode Brotli if library is available
                    text = await response.text()
                    # Put to cache
                    self._html_cache[url] = (now, text)
                    return text
                    
            return None
            
        except Exception as e:
            error_msg = str(e)
            
            # Check if it's a Brotli-related error and try fallback
            if 'brotli' in error_msg.lower() or 'br' in error_msg.lower():
                print(f"  🔄 Brotli error detected, trying fallback without br encoding for {url}")
                return await self._fetch_html_content_fallback(url)
            else:
                print(f"  ⚠️ Error fetching HTML from {url}: {e}")
                return None
    
    async def _fetch_html_content_fallback(self, url: str) -> Optional[str]:
        """Fallback fetch without Brotli support."""
        try:
            now = time.monotonic()
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate',  # Without Brotli as fallback
                'Connection': 'keep-alive',
                'Cache-Control': 'no-cache',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1',
                'Upgrade-Insecure-Requests': '1'
            }
            
            async with get_http_client() as client:
                response = await client.session.get(url, headers=headers, timeout=15)
                if response.status == 200:
                    text = await response.text()
                    self._html_cache[url] = (now, text)
                    return text
                    
            return None
            
        except Exception as e:
            print(f"  ❌ Fallback fetch also failed for {url}: {e}")
            return None
    
    async def _extract_with_learned_pattern(self, url: str, pattern) -> Optional[str]:
        """Extract content using a learned pattern."""
        try:
            if pattern.extraction_strategy == 'playwright':
                return await self._extract_with_playwright_selector(url, pattern.selector_pattern)
            else:
                return await self._extract_with_css_selector(url, pattern.selector_pattern)
        except Exception as e:
            print(f"    ❌ Learned pattern failed: {e}")
            return None
    
    async def _extract_with_css_selector(self, url: str, selector: str) -> Optional[str]:
        """Extract content using specific CSS selector."""
        try:
            headers = self._get_headers()
            
            async with get_http_client() as client:
                response = await client.session.get(url, headers=headers)
                response.raise_for_status()
                html = await response.text()
            
            if not html:
                return None
            
            soup = BeautifulSoup(html, 'html.parser')
            self._remove_unwanted_elements(soup)
            
            elements = soup.select(selector)
            if elements:
                text = elements[0].get_text(separator='\n', strip=True)
                return self._clean_text(text) if text else None
                
        except Exception as e:
            print(f"    ❌ CSS selector extraction failed: {e}")
            
        return None
    
    async def _extract_with_playwright_selector(self, url: str, selector: str) -> Optional[str]:
        """Extract content using Playwright with specific selector."""
        try:
            if not self.browser:
                playwright = await async_playwright().start()
                self.browser = await playwright.chromium.launch(
                    headless=True,
                    args=['--no-sandbox', '--disable-dev-shm-usage']
                )
            
            page = await self.browser.new_page()
            await page.set_extra_http_headers(self._get_headers())
            await page.goto(url, wait_until='networkidle', timeout=30000)
            await page.wait_for_timeout(1000)
            
            element = await page.query_selector(selector)
            if element:
                text = await element.inner_text()
                await page.close()
                return self._clean_text(text) if text else None
            
            await page.close()
            
        except Exception as e:
            print(f"    ❌ Playwright selector extraction failed: {e}")
            
        return None
    
    async def _record_extraction_success(
        self, url: str, domain: str, strategy: str, selector: Optional[str],
        content: str, extraction_time_ms: int
    ):
        """Record successful extraction attempt."""
        try:
            memory = await get_extraction_memory()
            stability_tracker = await get_stability_tracker()
            
            attempt = ExtractionAttempt(
                article_url=url,
                domain=domain,
                extraction_strategy=strategy,
                selector_used=selector,
                success=True,
                content_length=len(content),
                quality_score=self._assess_content_quality(content),
                extraction_time_ms=extraction_time_ms
            )
            
            await memory.record_extraction_attempt(attempt)
            
            stability_tracker.update_domain_stats(
                domain=domain,
                success=True,
                extraction_time_ms=extraction_time_ms,
                content_length=len(content),
                quality_score=attempt.quality_score,
                method=strategy
            )
            
        except Exception as e:
            print(f"    ⚠️ Failed to record extraction success: {e}")
    
    async def _record_extraction_failure(
        self, url: str, domain: str, strategy: str, extraction_time_ms: int,
        error_message: str = None
    ):
        """Record failed extraction attempt."""
        try:
            memory = await get_extraction_memory()
            stability_tracker = await get_stability_tracker()
            
            attempt = ExtractionAttempt(
                article_url=url,
                domain=domain,
                extraction_strategy=strategy,
                success=False,
                extraction_time_ms=extraction_time_ms,
                error_message=error_message or "Content extraction failed"
            )
            
            await memory.record_extraction_attempt(attempt)
            
            stability_tracker.update_domain_stats(
                domain=domain,
                success=False,
                extraction_time_ms=extraction_time_ms,
                method=strategy
            )
            
        except Exception as e:
            print(f"    ⚠️ Failed to record extraction failure: {e}")
    
    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL."""
        try:
            parsed = urlparse(url)
            return parsed.netloc.lower()
        except:
            return "unknown"
    
    async def _extract_with_encoding_detection(self, url: str) -> Optional[str]:
        """Extract content using automatic encoding detection for international sites."""
        
        try:
            print(f"    🔍 Trying encoding-aware extraction...")
            
            # Create session with retry logic
            session = requests.Session()
            retry_strategy = Retry(
                total=2,
                backoff_factor=1,
                status_forcelist=[429, 500, 502, 503, 504],
            )
            adapter = HTTPAdapter(max_retries=retry_strategy)
            session.mount("http://", adapter)
            session.mount("https://", adapter)
            
            # Request with no encoding assumption
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5,sr;q=0.3,ru;q=0.3',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
            }
            
            response = session.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            
            # Get raw bytes
            raw_content = response.content
            print(f"    📦 Downloaded {len(raw_content)} bytes")
            
            # Auto-detect encoding
            detected_encoding = chardet.detect(raw_content)
            encoding = detected_encoding.get('encoding', 'utf-8')
            confidence = detected_encoding.get('confidence', 0.0)
            
            print(f"    🔍 Detected encoding: {encoding} (confidence: {confidence:.2f})")
            
            # Try detected encoding first
            try:
                html_content = raw_content.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                print(f"    ⚠️ Failed to decode with {encoding}, trying fallbacks...")
                
                # Fallback encodings for different regions
                fallback_encodings = ['utf-8', 'windows-1251', 'iso-8859-2', 'windows-1252', 'cp1250']
                html_content = None
                
                for fallback_enc in fallback_encodings:
                    try:
                        html_content = raw_content.decode(fallback_enc, errors='ignore')
                        print(f"    ✅ Successfully decoded with {fallback_enc}")
                        encoding = fallback_enc
                        break
                    except (UnicodeDecodeError, LookupError):
                        continue
                
                if not html_content:
                    print(f"    ❌ All encoding attempts failed")
                    return None
            
            print(f"    📄 Decoded HTML: {len(html_content)} characters")
            
            # Parse with BeautifulSoup
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Try multiple content extraction strategies
            content_selectors = [
                'div.content', 'div.article-content', 'div.post-content',
                'article', 'main', 'div.entry-content',
                '.content-body', '.article-body', '.post-body',
                '#content', '#main-content', '#article-content',
                'div[class*="content"]', 'div[class*="article"]',
                'div[class*="text"]', 'div[class*="body"]'
            ]
            
            extracted_text = ""
            for selector in content_selectors:
                elements = soup.select(selector)
                if elements:
                    # Get text from the largest element
                    best_element = max(elements, key=lambda el: len(el.get_text()))
                    text = best_element.get_text(separator='\n', strip=True)
                    if len(text) > len(extracted_text):
                        extracted_text = text
                        print(f"    ✅ Found content with selector: {selector} ({len(text)} chars)")
            
            # Fallback: get all paragraph text
            if len(extracted_text) < 200:
                paragraphs = soup.find_all(['p', 'div'])
                text_parts = []
                for p in paragraphs:
                    text = p.get_text(strip=True)
                    if len(text) > 50:  # Only substantial paragraphs
                        text_parts.append(text)
                
                if text_parts:
                    extracted_text = '\n\n'.join(text_parts)
                    print(f"    📝 Fallback paragraph extraction: {len(extracted_text)} chars")
            
            # Clean and validate content
            if extracted_text:
                # Remove extra whitespace
                extracted_text = re.sub(r'\n{3,}', '\n\n', extracted_text)
                extracted_text = re.sub(r'[ \t]+', ' ', extracted_text)
                extracted_text = extracted_text.strip()
                
                # Validate minimum length
                if len(extracted_text) >= self.min_content_length:
                    print(f"    ✅ Encoding-aware extraction successful: {len(extracted_text)} chars")
                    return extracted_text
                else:
                    print(f"    ⚠️ Content too short: {len(extracted_text)} chars")
            
            return None
            
        except Exception as e:
            print(f"    ❌ Encoding-aware extraction failed: {e}")
            return None
    
    async def _extract_with_readability(self, url: str) -> Optional[str]:
        """Extract content using Mozilla's readability algorithm with retry."""
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                headers = self._get_headers()  # Get fresh headers each attempt
                
                # Add delay between retries
                if attempt > 0:
                    import random
                    delay = random.uniform(1, 3) * (attempt + 1)
                    print(f"  ⏰ Retrying readability extraction in {delay:.1f}s (attempt {attempt + 1}/{max_retries})")
                    await asyncio.sleep(delay)
                
                async with get_http_client() as client:
                    try:
                        # Bypass retry mechanism for content extraction
                        response = await client.session.get(url, headers=headers)
                        response.raise_for_status()
                        html = await response.text()
                    except Exception as fetch_error:
                        print(f"  🔗 HTTP fetch failed (attempt {attempt + 1}): {type(fetch_error).__name__}")
                        if attempt < max_retries - 1:
                            continue
                        raise fetch_error
                
                if not html:
                    if attempt < max_retries - 1:
                        continue
                    return None
                
                # Use readability to extract main content
                doc = Document(html)
                content = doc.summary()
                
                if content:
                    # Parse the readability result
                    soup = BeautifulSoup(content, 'html.parser')
                    text = soup.get_text(separator='\n', strip=True)
                    cleaned_text = self._clean_text(text)
                    
                    if len(cleaned_text) > self.min_content_length:
                        print(f"  ✅ Readability extraction successful on attempt {attempt + 1}")
                        return cleaned_text
                
                if attempt < max_retries - 1:
                    continue
                    
            except Exception as e:
                print(f"  ⚠️ Readability extraction attempt {attempt + 1} failed for {url}: {type(e).__name__}")
                if attempt == max_retries - 1:
                    print(f"  ❌ All readability extraction attempts failed")
                continue
        
        return None
    
    async def _extract_with_enhanced_selectors(self, url: str) -> Optional[str]:
        """Extract content using enhanced CSS selectors and structured data with retry."""
        max_retries = 2
        
        for attempt in range(max_retries):
            try:
                headers = self._get_headers()  # Fresh headers each attempt
                
                if attempt > 0:
                    import random
                    delay = random.uniform(2, 4)
                    print(f"  ⏰ Retrying enhanced extraction in {delay:.1f}s (attempt {attempt + 1}/{max_retries})")
                    await asyncio.sleep(delay)
                
                async with get_http_client() as client:
                    try:
                        # Bypass retry mechanism for content extraction
                        response = await client.session.get(url, headers=headers)
                        response.raise_for_status()
                        html = await response.text()
                    except Exception as fetch_error:
                        print(f"  🔗 HTTP fetch failed (attempt {attempt + 1}): {type(fetch_error).__name__}")
                        if attempt < max_retries - 1:
                            continue
                        raise fetch_error
                
                if not html:
                    if attempt < max_retries - 1:
                        continue
                    return None
                
                soup = BeautifulSoup(html, 'html.parser')
                
                # Remove unwanted elements first
                self._remove_unwanted_elements(soup)
                
                # Try JSON-LD structured data first
                content = self._extract_from_json_ld(soup)
                if content and len(content) > self.min_content_length:
                    print(f"  ✅ JSON-LD extraction successful on attempt {attempt + 1}")
                    return content
                
                # Try Open Graph description
                content = self._extract_from_open_graph(soup)
                if content and len(content) > self.min_content_length:
                    print(f"  ✅ Open Graph extraction successful on attempt {attempt + 1}")
                    return content
                
                # Try enhanced CSS selectors
                content = self._extract_by_enhanced_selectors(soup)
                if content and len(content) > self.min_content_length:
                    print(f"  ✅ CSS selectors extraction successful on attempt {attempt + 1}")
                    return content
                
                # Try content heuristics with quality scoring
                content = self._extract_by_enhanced_heuristics(soup)
                if content and len(content) > self.min_content_length:
                    print(f"  ✅ Heuristics extraction successful on attempt {attempt + 1}")
                    return content
                
                if attempt < max_retries - 1:
                    continue
                    
            except Exception as e:
                print(f"  ⚠️ Enhanced selector extraction attempt {attempt + 1} failed for {url}: {type(e).__name__}")
                if attempt == max_retries - 1:
                    print(f"  ❌ All enhanced extraction attempts failed")
                continue
        
        return None
    
    async def _extract_with_browser(self, url: str) -> Optional[str]:
        """Extract content using browser rendering (for JavaScript-heavy sites)."""
        print(f"  🎭 Browser extraction started for {url}")
        page = None
        # Time budget (in ms) for the whole Playwright strategy
        budget_start = time.monotonic()
        total_budget_ms = PLAYWRIGHT_TOTAL_BUDGET_MS

        def remaining_ms() -> int:
            """Compute remaining milliseconds from the total budget."""
            elapsed = (time.monotonic() - budget_start) * 1000
            return max(0, int(total_budget_ms - elapsed))

        # Limit concurrency of browser pages
        async with self._browser_semaphore:
            try:
                if not self.browser:
                    print(f"  🔧 Launching Playwright browser...")
                    playwright = await async_playwright().start()
                    self.browser = await playwright.chromium.launch(
                        headless=True,
                        args=[
                            '--no-sandbox',
                            '--disable-dev-shm-usage',
                            '--disable-blink-features=AutomationControlled',
                            '--disable-extensions',
                            '--no-first-run',
                            '--disable-default-apps',
                            '--no-zygote',
                            '--disable-background-timer-throttling',
                            '--disable-backgrounding-occluded-windows',
                            '--disable-renderer-backgrounding',
                            '--disable-features=TranslateUI',
                            '--disable-ipc-flooding-protection',
                            '--hide-scrollbars',
                            '--mute-audio',
                            '--no-default-browser-check'
                        ]
                    )
                else:
                    print(f"  🔧 Using existing browser instance...")
                
                page = await self.browser.new_page()
                
                # Block heavy resource types to speed up extraction; allow text/css/js
                async def _route_handler(route):
                    try:
                        if route.request.resource_type in {"image", "media", "font", "stylesheet"}:
                            await route.abort()
                        else:
                            await route.continue_()
                    except Exception:
                        try:
                            await route.continue_()
                        except Exception:
                            pass
                await page.route("**/*", _route_handler)

                # Set realistic viewport and user agent (mobile UA often loads simpler markup)
                import random
                viewports = [
                    {"width": 390, "height": 844},  # iPhone 12/13
                    {"width": 412, "height": 915},  # Android large
                    {"width": 1920, "height": 1080},
                    {"width": 1366, "height": 768},
                    {"width": 1280, "height": 720},
                    {"width": 1440, "height": 900}
                ]
                await page.set_viewport_size(random.choice(viewports))
                await page.set_extra_http_headers(self._get_headers())
                
                # Remove automation indicators
                await page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined,
                });
                
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1, 2, 3, 4, 5],
                });
                
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['en-US', 'en'],
                });
                
                window.chrome = {
                    runtime: {},
                };
            """)
                
                # Load page with longer timeout and retry logic
                max_retries = 2
                for attempt in range(max_retries):
                    # Early stop if budget exhausted
                    if remaining_ms() <= 0:
                        print("  ⏰ Budget exhausted before navigation; stopping browser strategy")
                        raise TimeoutError("playwright_budget_exhausted")
                    try:
                        base_timeout = PLAYWRIGHT_TIMEOUT_FIRST_MS if attempt == 0 else PLAYWRIGHT_TIMEOUT_RETRY_MS
                        timeout = min(base_timeout, max(1000, remaining_ms()))
                        # Prefer faster first paint to avoid long waits on heavy sites
                        wait_until = 'domcontentloaded' if attempt == 0 else 'networkidle'
                        print(f"  🌐 Page load attempt {attempt + 1}/{max_retries} (timeout: {timeout/1000}s, wait: {wait_until})")
                        await page.goto(url, wait_until=wait_until, timeout=timeout)
                        break
                    except Exception as e:
                        print(f"  🔄 Page load attempt {attempt + 1} failed: {e}")
                        if attempt == max_retries - 1:
                            raise
                        # Brief pause before retry (bounded by remaining budget)
                        pause_ms = min(2000, remaining_ms())
                        if pause_ms <= 0:
                            print("  ⏰ Budget exhausted during retry backoff; stopping")
                            raise TimeoutError("playwright_budget_exhausted")
                        await asyncio.sleep(pause_ms / 1000)
                
                # Wait for content to load and simulate human behavior
                human_wait_ms = min(random.randint(2000, 4000), remaining_ms())
                if human_wait_ms > 0:
                    await page.wait_for_timeout(human_wait_ms)
                
                # First try to extract readable text directly from rendered page (try multiple waits)
                print(f"  🔍 Trying direct element extraction from rendered page...")
                
                # Try our specific selectors first (skip JSON-LD)
                content = None
                selectors_to_try = [s for s in self.content_selectors if 'script' not in s]
                
                # Crawl with short micro-waits to allow lazy text to appear
                for selector in selectors_to_try[:20]:
                    if remaining_ms() <= 0:
                        print("  ⏰ Budget exhausted while trying selectors; stop loop")
                        break
                    try:
                        element = await page.query_selector(selector)
                        if element:
                            # brief wait to ensure text is rendered
                            await page.wait_for_timeout(200)
                            text = await element.inner_text()
                            print(f"  📄 Selector '{selector}': {len(text)} chars")
                            if len(text) > self.min_content_length:
                                content = self._clean_text(text)
                                print(f"  ✅ Found good content with '{selector}': {len(content)} chars")
                                # Ensure page is closed before returning
                                try:
                                    await page.close()
                                except Exception:
                                    pass
                                return content
                    except Exception as e:
                        print(f"  ⚠️ Selector '{selector}' failed: {e}")
                        continue
                
                # Fallback to HTML parsing if direct extraction failed
                print(f"  🔍 Fallback to HTML parsing...")
                if remaining_ms() <= 0:
                    print("  ⏰ Budget exhausted before HTML parsing fallback; stopping")
                    raise TimeoutError("playwright_budget_exhausted")
                html_content = await page.content()
                if html_content:
                    soup = BeautifulSoup(html_content, 'html.parser')
                    
                    # Remove unwanted elements first
                    self._remove_unwanted_elements(soup)
                    
                    # Try enhanced selectors on cleaned HTML
                    enhanced_content = self._extract_by_enhanced_selectors(soup)
                    if enhanced_content and len(enhanced_content) > self.min_content_length:
                        try:
                            await page.close()
                        except Exception:
                            pass
                        return enhanced_content
                    
                    # Try JSON-LD as last resort (but it usually doesn't have full text)
                    json_ld_content = self._extract_from_json_ld(soup)
                    if json_ld_content and len(json_ld_content) > self.min_content_length:
                        try:
                            await page.close()
                        except Exception:
                            pass
                        return json_ld_content
                
                # Fallback to direct element extraction
                content = None
                for selector in self.content_selectors[:10]:  # Try top 10 selectors
                    if remaining_ms() <= 0:
                        print("  ⏰ Budget exhausted during final selector attempts; stopping")
                        break
                    try:
                        if 'script' in selector:  # Skip JSON-LD selector
                            continue
                        element = await page.query_selector(selector)
                        if element:
                            text = await element.inner_text()
                            if len(text) > self.min_content_length:
                                content = text
                                break
                    except Exception:
                        continue
                
                if content:
                    try:
                        await page.close()
                    except Exception:
                        pass
                    return self._clean_text(content)
                
            except Exception as e:
                print(f"  ⚠️ Browser extraction failed for {url}: {e}")
            finally:
                if page:
                    try:
                        await page.close()
                    except Exception:
                        pass
        
        return None
    
    async def _extract_simple_direct(self, url: str) -> Optional[str]:
        """Simple direct extraction without retry mechanisms."""
        try:
            print(f"  🔧 Simple direct extraction for {url}")
            headers = self._get_headers()
            
            # Use simple aiohttp session without retry decorators
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status != 200:
                        print(f"  ⚠️ HTTP {response.status}")
                        return None
                        
                    html = await response.text()
                    if not html:
                        print(f"  ⚠️ Empty HTML response")
                        return None
            
            soup = BeautifulSoup(html, 'html.parser')
            self._remove_unwanted_elements(soup)
            
            # Try our enhanced selectors
            content = self._extract_by_enhanced_selectors(soup)
            if content and len(content) > self.min_content_length:
                print(f"  ✅ Simple extraction successful: {len(content)} chars")
                return content
            
            # Try enhanced heuristics
            content = self._extract_by_enhanced_heuristics(soup)
            if content and len(content) > self.min_content_length:
                print(f"  ✅ Simple heuristics successful: {len(content)} chars")
                return content
            
            print(f"  ⚠️ Simple extraction found no suitable content")
            return None
            
        except Exception as e:
            print(f"  ⚠️ Simple extraction failed: {type(e).__name__}: {e}")
            return None
    
    async def _extract_basic_fallback(self, url: str) -> Optional[str]:
        """Basic fallback extraction (original method)."""
        try:
            headers = self._get_headers()
            
            async with get_http_client() as client:
                response = await client.session.get(url, headers=headers)
                response.raise_for_status()
                html = await response.text()
            
            if not html:
                return None
            
            soup = BeautifulSoup(html, 'html.parser')
            self._remove_unwanted_elements(soup)
            
            # Try basic selectors
            for selector in ['article', '.content', '#content', 'main']:
                elements = soup.select(selector)
                if elements:
                    text = elements[0].get_text(separator='\n', strip=True)
                    if len(text) > self.min_content_length:
                        return self._clean_text(text)
            
            # Final fallback: all paragraphs
            paragraphs = soup.find_all('p')
            if paragraphs:
                text_parts = []
                for p in paragraphs:
                    text = p.get_text(separator=' ', strip=True)
                    if len(text) > 50:
                        text_parts.append(text)
                
                if text_parts:
                    return self._clean_text('\n\n'.join(text_parts))
            
        except Exception as e:
            print(f"  ⚠️ Basic fallback extraction failed for {url}: {type(e).__name__}")
        
        return None
    
    def _extract_publication_date(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract publication date from HTML using multiple strategies."""
        try:
            # Strategy 1: JSON-LD structured data
            json_date = self._extract_date_from_json_ld(soup)
            if json_date:
                return json_date
            
            # Strategy 2: Common CSS selectors for publication date
            date_selectors = [
                # Schema.org microdata
                '[itemprop="datePublished"]',
                '[itemprop="publishedTime"]',
                '[itemprop="dateCreated"]',
                
                # Open Graph meta tags
                'meta[property="article:published_time"]',
                'meta[property="article:published"]',
                'meta[name="pubdate"]',
                'meta[name="publishdate"]',
                'meta[name="date"]',
                
                # Common CSS classes and elements
                '.publish-date', '.published-date', '.publication-date',
                '.date-published', '.pub-date', '.article-date',
                '.post-date', '.entry-date', '.timestamp',
                'time[datetime]', 'time[pubdate]',
                '.byline time', '.meta time', '.date time',
                
                # Specific news site patterns
                '.article-meta time', '.story-meta time',
                '.news-meta .date', '.article-header .date',
                '.content-meta time', '.post-meta time'
            ]
            
            for selector in date_selectors:
                elements = soup.select(selector)
                for element in elements:
                    # Try to get datetime attribute first
                    date_text = element.get('datetime') or element.get('content')
                    
                    # If no datetime attribute, get text content
                    if not date_text:
                        date_text = element.get_text(strip=True)
                    
                    if date_text and self._is_valid_date_string(date_text):
                        return date_text
            
            # Strategy 3: Look for date patterns in text
            import re
            from datetime import datetime
            
            # Common date patterns
            date_patterns = [
                r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}',  # ISO format
                r'\d{4}-\d{2}-\d{2}',  # YYYY-MM-DD
                r'\d{1,2}/\d{1,2}/\d{4}',  # MM/DD/YYYY or DD/MM/YYYY
                r'\d{1,2}\.\d{1,2}\.\d{4}',  # DD.MM.YYYY
                r'[A-Za-z]+ \d{1,2}, \d{4}',  # Month DD, YYYY
                r'\d{1,2} [A-Za-z]+ \d{4}'  # DD Month YYYY
            ]
            
            # Search in meta tags and common date containers
            for pattern in date_patterns:
                # Search in meta description or title
                meta_desc = soup.find('meta', attrs={'name': 'description'})
                if meta_desc:
                    content = meta_desc.get('content', '')
                    match = re.search(pattern, content)
                    if match:
                        return match.group(0)
            
            return None
            
        except Exception as e:
            print(f"    ⚠️ Date extraction failed: {e}")
            return None
    
    def _extract_date_from_json_ld(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract publication date from JSON-LD structured data."""
        scripts = soup.find_all('script', type='application/ld+json')
        
        for script in scripts:
            try:
                if not script.string:
                    continue
                    
                data = json.loads(script.string)
                
                # Handle both single objects and arrays
                items = data if isinstance(data, list) else [data]
                
                # Process nested graph structures
                if isinstance(data, dict) and '@graph' in data:
                    items = data['@graph']
                
                for item in items:
                    if not isinstance(item, dict):
                        continue
                        
                    # Look for publication date in various schema.org types
                    item_type = item.get('@type', '')
                    if isinstance(item_type, list):
                        item_type = item_type[0] if item_type else ''
                    
                    if item_type in ['Article', 'NewsArticle', 'BlogPosting', 'WebPage']:
                        # Try various date fields
                        date_fields = ['datePublished', 'publishedTime', 'dateCreated', 'dateModified']
                        for field in date_fields:
                            date_value = item.get(field)
                            if date_value:
                                return str(date_value)
                
            except Exception as e:
                continue
        
        return None
    
    def _is_valid_date_string(self, date_str: str) -> bool:
        """Check if string looks like a valid date."""
        if not date_str or len(date_str) < 8:
            return False
        
        # Common date patterns
        import re
        patterns = [
            r'\d{4}-\d{2}-\d{2}',  # YYYY-MM-DD
            r'\d{4}/\d{2}/\d{2}',  # YYYY/MM/DD
            r'\d{1,2}/\d{1,2}/\d{4}',  # MM/DD/YYYY
            r'\d{1,2}\.\d{1,2}\.\d{4}',  # DD.MM.YYYY
            r'[A-Za-z]{3,} \d{1,2}, \d{4}',  # Month DD, YYYY
            r'\d{1,2} [A-Za-z]{3,} \d{4}'  # DD Month YYYY
        ]
        
        for pattern in patterns:
            if re.search(pattern, date_str):
                return True
        
        return False
    
    def _extract_from_json_ld(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract content from JSON-LD structured data."""
        scripts = soup.find_all('script', type='application/ld+json')
        
        for script in scripts:
            try:
                if not script.string:
                    continue
                    
                data = json.loads(script.string)
                
                # Handle both single objects and arrays
                items = data if isinstance(data, list) else [data]
                
                # Process nested graph structures
                if isinstance(data, dict) and '@graph' in data:
                    items = data['@graph']
                
                for item in items:
                    if not isinstance(item, dict):
                        continue
                        
                    # Look for article body in various schema.org types
                    item_type = item.get('@type', '')
                    if isinstance(item_type, list):
                        item_type = item_type[0] if item_type else ''
                    
                    if item_type in ['Article', 'NewsArticle', 'BlogPosting']:
                        # Try articleBody first
                        article_body = item.get('articleBody')
                        if article_body and len(str(article_body)) > self.min_content_length:
                            return self._clean_text(str(article_body))
                        
                        # Try description
                        description = item.get('description')
                        if description and len(str(description)) > self.min_content_length:
                            return self._clean_text(str(description))
                        
                        # Try text content from nested objects
                        text_content = item.get('text') or item.get('mainEntityOfPage', {}).get('text')
                        if text_content and len(str(text_content)) > self.min_content_length:
                            return self._clean_text(str(text_content))
            
            except (json.JSONDecodeError, AttributeError, TypeError) as e:
                print(f"  ⚠️ JSON-LD parsing error: {e}")
                continue
        
        return None
    
    def _extract_from_open_graph(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract content from Open Graph meta tags."""
        og_description = soup.find('meta', property='og:description')
        if og_description and og_description.get('content'):
            content = og_description['content']
            if len(content) > self.min_content_length:
                return content
        
        # Also try standard meta description
        meta_description = soup.find('meta', attrs={'name': 'description'})
        if meta_description and meta_description.get('content'):
            content = meta_description['content']
            if len(content) > self.min_content_length:
                return content
        
        return None

    def _find_alt_article_links(self, soup: BeautifulSoup, base_url: str) -> List[str]:
        """Find canonical/AMP or obvious 'read more' alternative links.
        Returns list of URLs ordered by preference.
        """
        alt_urls: List[str] = []
        try:
            # Canonical link
            canonical = soup.find('link', rel=lambda v: v and 'canonical' in v)
            if canonical and canonical.get('href'):
                alt_urls.append(urljoin(base_url, canonical['href']))
        except Exception:
            pass
        try:
            # AMP link
            amp = soup.find('link', rel=lambda v: v and 'amphtml' in v)
            if amp and amp.get('href'):
                alt_urls.append(urljoin(base_url, amp['href']))
        except Exception:
            pass
        try:
            # Common "read more" anchors
            candidates = soup.select('a[rel="next"], a.more, a.read-more, a.readmore, a[href*="/amp/"]')
            for a in candidates:
                href = a.get('href')
                if href:
                    alt_urls.append(urljoin(base_url, href))
        except Exception:
            pass
        # Deduplicate while preserving order
        seen: set = set()
        deduped: List[str] = []
        for u in alt_urls:
            if u not in seen:
                seen.add(u)
                deduped.append(u)
        return deduped
    
    def _extract_by_enhanced_selectors(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract using enhanced CSS selectors."""
        for selector in self.content_selectors:
            if 'script' in selector:  # Skip JSON-LD selector
                continue
                
            elements = soup.select(selector)
            if elements:
                text = elements[0].get_text(separator='\n', strip=True)
                if len(text) > self.min_content_length:
                    return text
        
        return None
    
    def _extract_by_enhanced_heuristics(self, soup: BeautifulSoup) -> Optional[str]:
        """Enhanced heuristic extraction with quality scoring and modern CSS patterns."""
        candidates = []
        
        # Strategy 1: Find containers with substantial text content
        for container in soup.find_all(['div', 'section', 'article', 'main']):
            text = container.get_text(separator='\n', strip=True)
            
            if len(text) > self.min_content_length:
                quality_score = self._assess_content_quality(text)
                
                # Boost score for modern CSS patterns
                container_classes = container.get('class', [])
                class_string = ' '.join(container_classes).lower()
                
                # Modern frameworks indicators
                if any(pattern in class_string for pattern in [
                    'prose', 'text-', 'content', 'article', 'story', 'news',
                    'material', 'body', 'main', 'mb-', 'mt-', 'p-', 'mx-',
                    'container', 'wrapper'
                ]):
                    quality_score += 10
                
                # Russian news sites patterns
                if any(pattern in class_string for pattern in [
                    'article', 'news', 'material', 'story', 'text', 'content'
                ]):
                    quality_score += 15
                
                # Tailwind/modern CSS utilities patterns
                if any(pattern in class_string for pattern in [
                    'mb-', 'mt-', 'p-', 'px-', 'py-', 'mx-', 'text-', 'prose'
                ]):
                    quality_score += 8
                
                candidates.append((quality_score, len(text), text, container))
        
        # Strategy 2: Look for containers with many paragraphs
        for container in soup.find_all(['div', 'section']):
            paragraphs = container.find_all('p')
            
            if len(paragraphs) >= 3:  # At least 3 paragraphs
                text = container.get_text(separator='\n', strip=True)
                
                if len(text) > self.min_content_length:
                    quality_score = self._assess_content_quality(text)
                    quality_score += len(paragraphs) * 2  # Bonus for paragraph count
                    candidates.append((quality_score, len(text), text, container))
        
        # Strategy 3: Find largest text blocks that aren't navigation
        text_blocks = []
        for elem in soup.find_all(['div', 'section', 'p']):
            if self._is_likely_content_element(elem):
                text = elem.get_text(separator='\n', strip=True)
                if len(text) > 300:  # Substantial text blocks
                    text_blocks.append((len(text), text))
        
        # Combine largest text blocks if they're substantial
        if text_blocks:
            text_blocks.sort(key=lambda x: x[0], reverse=True)
            combined_text = '\n\n'.join([block[1] for block in text_blocks[:3]])
            if len(combined_text) > self.min_content_length:
                quality_score = self._assess_content_quality(combined_text)
                candidates.append((quality_score, len(combined_text), combined_text, None))
        
        # Sort by quality score, then by length
        if candidates:
            candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
            return candidates[0][2]
        
        return None
    
    def _normalize_date(self, date_str: Optional[str]) -> Optional[str]:
        """Normalize various date strings into UTC ISO format."""
        if not date_str:
            return None
        try:
            dt = dateutil.parser.parse(date_str)
            # If naive, assume UTC; otherwise convert to UTC
            if not dt.tzinfo:
                return dt.isoformat()
            return dt.astimezone(tz=None).isoformat()
        except Exception:
            return date_str

    async def _extract_from_html(self, html: Optional[str]) -> Optional[str]:
        """Extract content from already fetched HTML using soup-based strategies."""
        if not html:
            return None
        try:
            soup = BeautifulSoup(html, 'html.parser')
            self._remove_unwanted_elements(soup)
            # JSON-LD
            content = self._extract_from_json_ld(soup)
            if self._is_good_content(content):
                return self._finalize_content(content)
            # Open Graph
            content = self._extract_from_open_graph(soup)
            if self._is_good_content(content):
                return self._finalize_content(content)
            # Enhanced selectors
            content = self._extract_by_enhanced_selectors(soup)
            if self._is_good_content(content):
                return self._finalize_content(content)
            # Heuristics
            content = self._extract_by_enhanced_heuristics(soup)
            if self._is_good_content(content):
                return self._finalize_content(content)
        except Exception:
            return None
        return None
    
    def _is_likely_content_element(self, element) -> bool:
        """Check if element is likely to contain main content."""
        if not element:
            return False
        
        # Check element classes and IDs for content indicators
        classes = element.get('class', [])
        element_id = element.get('id', '')
        class_string = ' '.join(classes).lower()
        id_string = element_id.lower()
        
        # Positive indicators
        content_indicators = [
            'content', 'article', 'story', 'news', 'text', 'body',
            'material', 'post', 'entry', 'main', 'prose'
        ]
        
        # Negative indicators  
        nav_indicators = [
            'nav', 'menu', 'header', 'footer', 'sidebar', 'aside',
            'comment', 'ad', 'advertisement', 'social', 'share',
            'related', 'recommend', 'tag', 'category', 'meta'
        ]
        
        # Check for content indicators
        has_content_indicator = any(indicator in class_string or indicator in id_string 
                                  for indicator in content_indicators)
        
        # Check for navigation indicators  
        has_nav_indicator = any(indicator in class_string or indicator in id_string
                               for indicator in nav_indicators)
        
        # Exclude if it has navigation indicators
        if has_nav_indicator:
            return False
        
        # Include if it has content indicators
        if has_content_indicator:
            return True
        
        # Default heuristic: check text content ratio
        text = element.get_text(strip=True)
        if len(text) < 50:  # Too short
            return False
        
        # Check if element has reasonable text density
        html_length = len(str(element))
        text_length = len(text)
        
        if html_length > 0:
            text_ratio = text_length / html_length
            return text_ratio > 0.3  # At least 30% text content
        
        return True
    
    def _is_good_content(self, content: str) -> bool:
        """Check if extracted content meets quality standards."""
        if not content or len(content) < self.min_content_length:
            return False
        
        # Check content quality score
        quality_score = self._assess_content_quality(content)
        if quality_score < MIN_QUALITY_SCORE:  # Minimum quality threshold
            return False
        
        # Check for meaningful content (not just navigation/ads)
        meaningful_words = [
            'article', 'story', 'news', 'report', 'analysis',
            'said', 'according', 'study', 'research', 'found'
        ]
        
        content_lower = content.lower()
        meaningful_count = sum(1 for word in meaningful_words if word in content_lower)
        
        if meaningful_count < 2 and len(content) < 1000:
            return False
        
        return True
    
    def _finalize_content(self, content: str) -> str:
        """Final content processing and truncation."""
        if not content:
            return ""
        
        # Smart truncation by sentences
        if len(content) > self.max_content_length:
            content = self._smart_truncate(content, self.max_content_length)
        
        return self._clean_text(content)
    
    def _smart_truncate(self, text: str, max_length: int) -> str:
        """Smart truncation that respects sentence boundaries."""
        if len(text) <= max_length:
            return text
        
        # Find sentence boundaries
        sentences = re.split(r'([.!?]+)', text)
        result = ""
        
        for i in range(0, len(sentences), 2):  # Every other element is a sentence
            sentence = sentences[i]
            punctuation = sentences[i + 1] if i + 1 < len(sentences) else ""
            
            candidate = result + sentence + punctuation
            if len(candidate) > max_length:
                break
            
            result = candidate
        
        # If we couldn't fit even one sentence, do hard truncation
        if not result:
            result = text[:max_length - 3] + "..."
        
        return result.strip()
    
    def _remove_unwanted_elements(self, soup: BeautifulSoup) -> None:
        """Remove unwanted HTML elements."""
        # Remove script, style, and other non-content tags
        unwanted_tags = [
            'script', 'style', 'noscript', 'iframe', 'embed', 
            'object', 'form', 'input', 'button'
        ]
        
        for tag in unwanted_tags:
            for element in soup.find_all(tag):
                element.decompose()
        
        # Remove elements with unwanted classes/IDs
        for selector in self.unwanted_selectors:
            for element in soup.select(selector):
                element.decompose()
        
        # Remove comments
        for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
            comment.extract()
    
    def _clean_text(self, text: str) -> str:
        """Enhanced text cleaning."""
        if not text:
            return ""
        
        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'\n\s*\n', '\n\n', text)
        
        # Remove common unwanted patterns
        unwanted_patterns = [
            r'Subscribe to.*?newsletter',
            r'Follow us on.*?social media',
            r'Share this article',
            r'Related articles?:?',
            r'Advertisement',
            r'Cookie policy',
            r'Privacy policy',
            r'Terms of service',
            r'Sign up for.*?updates',
            r'Click here to.*?',
            r'Read more:?',
            r'Continue reading',
            r'This article was.*?published',
            r'Updated:?\s*\d+',
            r'Published:?\s*\d+'
        ]
        
        for pattern in unwanted_patterns:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)
        
        # Remove excessive punctuation
        text = re.sub(r'[.]{3,}', '...', text)
        text = re.sub(r'[!]{2,}', '!', text)
        text = re.sub(r'[?]{2,}', '?', text)
        
        return text.strip()
    
    def _assess_content_quality(self, text: str) -> float:
        """Assess content quality with a 0-100 score."""
        if not text:
            return 0
        score = 0
        # Length scoring (0-40 points)
        text_length = len(text)
        if text_length > 3000:
            score += 40
        elif text_length > 1500:
            score += 30
        elif text_length > 800:
            score += 20
        elif text_length > 400:
            score += 10
        # Sentence structure scoring (0-20 points)
        sentence_count = len(re.findall(r'[.!?]+', text))
        if sentence_count > 15:
            score += 20
        elif sentence_count > 8:
            score += 15
        elif sentence_count > 4:
            score += 10
        # Word count scoring (0-15 points)
        word_count = len(text.split())
        if word_count > 500:
            score += 15
        elif word_count > 250:
            score += 10
        elif word_count > 100:
            score += 5
        # Paragraph structure (0-10 points)
        paragraph_count = len([p for p in text.split('\n\n') if p.strip()])
        if paragraph_count >= 4:
            score += 10
        elif paragraph_count >= 2:
            score += 5
        # Content indicators (0-10 points)
        content_indicators = [
            r'\b(статья|новость|сообщает|объявил|заявил|отметил)\b',
            r'\b(article|news|reported|announced|stated|noted)\b',
            r'\b(согласно|по данным|как сообщает|по информации)\b',
            r'\b(according to|sources|reports|information)\b'
        ]
        for pattern in content_indicators:
            if re.search(pattern, text, re.IGNORECASE):
                score += 2.5
        # Quality deductions
        if len(text) < 200:
            score -= 20
        words = text.lower().split()
        if len(words) > 50:
            unique_words = len(set(words))
            repetition_ratio = unique_words / len(words)
            if repetition_ratio < 0.3:
                score -= 15
        return max(0, min(100, score))
    
    def _clean_url(self, url: str) -> str:
        """Clean URL from invisible and problematic characters."""
        import unicodedata
        
        # Remove common invisible/problematic characters
        # Including: zero-width space, word joiner, etc.
        problematic_chars = [
            '\u200B',  # Zero Width Space
            '\u200C',  # Zero Width Non-Joiner  
            '\u200D',  # Zero Width Joiner
            '\u2060',  # Word Joiner
            '\uFEFF',  # Zero Width No-Break Space (BOM)
            '\u00A0',  # Non-breaking space
        ]
        
        cleaned_url = url
        for char in problematic_chars:
            cleaned_url = cleaned_url.replace(char, '')
        
        # Normalize unicode characters
        cleaned_url = unicodedata.normalize('NFKC', cleaned_url)
        
        # Strip whitespace
        cleaned_url = cleaned_url.strip()
        
        # Log if URL was modified
        if cleaned_url != url:
            print(f"  🧹 Cleaned URL: {repr(url)} → {repr(cleaned_url)}")
        
        return cleaned_url
    
    def _get_headers(self) -> Dict[str, str]:
        """Get HTTP headers to avoid bot detection with rotation."""
        import random
        
        # Multiple realistic User-Agent strings
        user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0'
        ]
        
        # Accept headers variations
        accept_headers = [
            'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
            'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
        ]
        
        # Language preferences
        languages = [
            'en-US,en;q=0.9',
            'en-US,en;q=0.9,ru;q=0.8',
            'en-GB,en;q=0.9,en-US;q=0.8',
            'ru-RU,ru;q=0.9,en;q=0.8'
        ]
        
        base_headers = {
            'User-Agent': random.choice(user_agents),
            'Accept': random.choice(accept_headers),
            'Accept-Language': random.choice(languages),
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0'
        }
        
        # Randomly add/remove some optional headers
        optional_headers = {
            'Sec-Ch-Ua': f'"Not A(Brand";v="99", "Google Chrome";v="{random.randint(120, 125)}", "Chromium";v="{random.randint(120, 125)}"',
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': f'"{random.choice(["Windows", "macOS", "Linux"])}"',
        }
        
        # Add some optional headers randomly
        for key, value in optional_headers.items():
            if random.random() > 0.3:  # 70% chance to include
                base_headers[key] = value
        
        return base_headers

    async def _extract_from_telegram_with_links(self, telegram_url: str) -> Optional[str]:
        """Extract content from Telegram messages, following external links if present."""
        try:
            # First, get the HTML content of the Telegram message
            html_content = await self._fetch_html_content(telegram_url)
            if not html_content:
                return None
            
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Extract message text from meta tags (modern Telegram structure)
            message_text = ""
            
            # Try og:description first
            og_description = soup.find('meta', property='og:description')
            if og_description:
                message_text = og_description.get('content', '').strip()
                print(f"    📱 Found message in og:description: {len(message_text)} chars")
            
            # Try twitter:description as fallback
            if not message_text:
                twitter_description = soup.find('meta', name='twitter:description')
                if twitter_description:
                    message_text = twitter_description.get('content', '').strip()
                    print(f"    📱 Found message in twitter:description: {len(message_text)} chars")
            
            if not message_text:
                print("    ❌ No message text found in meta tags")
                return None
            
            # Clean the message text (remove @channel mentions at the end)
            import re
            message_text = re.sub(r'\s*@\w+\s*$', '', message_text).strip()
            
            print(f"    📱 Cleaned message text: \"{message_text}\" ({len(message_text)} chars)")
            
            # Look for external links in scripts or data attributes
            external_links = []
            
            # Check scripts for any URLs
            scripts = soup.find_all('script')
            for script in scripts:
                if script.string:
                    # Look for URLs in script content
                    urls = re.findall(r'https?://(?!t\.me)[^\s"\'<>]+', script.string)
                    for url in urls:
                        if not url.startswith('https://t.me/') and not url.endswith(('.js', '.css', '.png', '.jpg')):
                            external_links.append(url.rstrip(',;)'))
            
            # Also look in all href attributes
            all_links = soup.find_all('a', href=True)
            for link in all_links:
                href = link.get('href', '')
                if href and not href.startswith(('https://t.me/', '#', '@', 'tg://')):
                    if href.startswith('http'):
                        external_links.append(href)
            
            # Remove duplicates
            external_links = list(set(external_links))
            print(f"    🔗 Found {len(external_links)} potential external links: {external_links[:3]}")
            
            # If we found external links, try to extract content from them
            best_content = message_text
            best_length = len(message_text)
            
            for link_url in external_links[:2]:  # Try up to 2 links
                try:
                    print(f"    🔍 Extracting from external link: {link_url}")
                    link_content = await self.extract_article_content(link_url)
                    
                    if link_content and len(link_content) > 300:  # Only if we get substantial content
                        print(f"    ✅ Better content from link: {len(link_content)} chars")
                        best_content = f"{message_text}\n\n--- Полный текст из ссылки ---\n\n{link_content}"
                        best_length = len(best_content)
                        break  # Use the first successful extraction
                        
                except Exception as e:
                    print(f"    ⚠️ Link extraction failed for {link_url}: {e}")
                    continue
            
            return best_content if best_length > len(message_text) else None
            
        except Exception as e:
            print(f"    ❌ Telegram message parsing failed: {e}")
            return None


# Создаем глобальный экземпляр для использования
_extractor_instance = None

async def get_content_extractor() -> ContentExtractor:
    """Get or create enhanced content extractor instance with proper cleanup."""
    global _extractor_instance
    if _extractor_instance is None:
        _extractor_instance = ContentExtractor()
    return _extractor_instance

async def cleanup_content_extractor():
    """Cleanup global content extractor instance and close browsers."""
    global _extractor_instance
    if _extractor_instance is not None:
        if _extractor_instance.browser:
            await _extractor_instance.browser.close()
            _extractor_instance.browser = None
        _extractor_instance = None