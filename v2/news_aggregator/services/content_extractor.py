"""Enhanced content extraction from web articles with AI optimization."""

import re
import json
import asyncio
import time
from typing import Optional, Dict, Any, List, Tuple
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Comment
from readability import Document
from playwright.async_api import async_playwright, Browser, Page
from langdetect import detect
from langdetect.lang_detect_exception import LangDetectException
import textstat

from ..core.http_client import get_http_client
from ..core.cache import cached
from ..core.exceptions import ContentExtractionError
from .extraction_memory import get_extraction_memory, ExtractionAttempt
from .domain_stability_tracker import get_stability_tracker
from .ai_extraction_optimizer import get_ai_extraction_optimizer


class ContentExtractor:
    """Enhanced content extractor with multiple fallback strategies."""
    
    def __init__(self):
        self.max_content_length = 8000  # Characters limit for AI
        self.min_content_length = 200   # Minimum viable content
        self.browser: Optional[Browser] = None
        
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
        if self.browser:
            await self.browser.close()
            self.browser = None
    
    async def extract_article_content_with_metadata(self, url: str) -> Dict[str, Optional[str]]:
        """
        Extract article content with metadata using AI-enhanced extraction.
        
        Args:
            url: Article URL
            
        Returns:
            Dictionary with 'content', 'publication_date', and 'full_article_url' keys
        """
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
        
        print(f"🧠 AI-enhanced extraction with metadata for {domain}")
        
        try:
            # First, get the page HTML for analysis
            html_content = await self._fetch_html_content(url)
            if not html_content:
                return result
            
            # Import AI client dynamically
            from .ai_client import get_ai_client
            ai_client = get_ai_client()
            
            # Phase 1: Try to extract publication date with AI
            try:
                pub_date = await ai_client.extract_publication_date(html_content, url)
                if pub_date:
                    result['publication_date'] = pub_date
                    print(f"  📅 Publication date found: {pub_date}")
            except Exception as e:
                print(f"  ⚠️ Error extracting publication date: {e}")
            
            # Phase 2: Check if we need to follow a link for full content
            try:
                full_article_url = await ai_client.extract_full_article_link(html_content, url)
                if full_article_url and full_article_url != url:
                    result['full_article_url'] = full_article_url
                    print(f"  🔗 Full article link found: {full_article_url}")
                    
                    # Extract content from the full article page
                    content = await self.extract_article_content(full_article_url)
                    if content:
                        result['content'] = content
                        return result
            except Exception as e:
                print(f"  ⚠️ Error extracting full article link: {e}")
            
            # Phase 3: Extract content from current page
            content = await self.extract_article_content(url)
            result['content'] = content
            
            return result
            
        except Exception as e:
            print(f"  ❌ Error in enhanced extraction for {url}: {e}")
            return result
    
    async def extract_article_content(self, url: str) -> Optional[str]:
        """
        Extract main article content using AI-optimized strategies.
        
        Args:
            url: Article URL
            
        Returns:
            Clean article text or None if failed
        """
        if not url:
            return None
        
        # Clean URL from invisible/problematic characters
        url = self._clean_url(url)
        domain = self._extract_domain(url)
        start_time = time.time()
        
        print(f"🧠 AI-optimized extraction for {domain}")
        
        try:
            # Get AI services
            memory = await get_extraction_memory()
            stability_tracker = await get_stability_tracker()
            
            # Phase 1: Try learned best patterns first
            learned_patterns = await memory.get_best_patterns_for_domain(domain, limit=3)
            
            for pattern in learned_patterns:
                if pattern.success_rate > 70:  # High confidence patterns
                    print(f"  📚 Trying learned pattern: {pattern.selector_pattern[:40]}... ({pattern.success_rate:.1f}%)")
                    content = await self._extract_with_learned_pattern(url, pattern)
                    
                    if self._is_good_content(content):
                        # Record successful extraction
                        await self._record_extraction_success(
                            url, domain, pattern.extraction_strategy, pattern.selector_pattern,
                            content, int((time.time() - start_time) * 1000)
                        )
                        return self._finalize_content(content)
            
            # Phase 2: Standard extraction strategies with learning
            # Get the best method for this domain and try it first
            best_method = stability_tracker.get_best_method_for_domain(domain)
            ineffective_methods = stability_tracker.get_ineffective_methods_for_domain(domain, min_attempts=2)
            recently_failed_methods = stability_tracker.get_recently_failed_methods(domain, recent_failures_threshold=1)
            
            # Define all available strategies
            all_strategies = {
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
                # Use available strategies in default order
                default_order = ['readability', 'html_parsing', 'playwright']
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
                            content = await self._extract_with_learned_pattern(url, pattern)
                            
                            if self._is_good_content(content):
                                await self._record_extraction_success(
                                    url, domain, pattern.extraction_strategy, pattern.selector_pattern,
                                    content, int((time.time() - start_time) * 1000)
                                )
                                return self._finalize_content(content)
            
            # Complete failure
            print(f"  💥 All extraction strategies failed for {domain}")
            return None
            
        except Exception as e:
            print(f"  ❌ Extraction error for {url}: {e}")
            raise ContentExtractionError(f"Failed to extract content from {url}: {e}")
    
    async def _fetch_html_content(self, url: str) -> Optional[str]:
        """Fetch raw HTML content from URL."""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive'
            }
            
            async with get_http_client() as client:
                response = await client.session.get(url, headers=headers, timeout=15)
                if response.status == 200:
                    return await response.text()
            
            return None
        except Exception as e:
            print(f"  ⚠️ Error fetching HTML from {url}: {e}")
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
            
            # Set realistic viewport and user agent
            import random
            viewports = [
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
                try:
                    timeout = 45000 if attempt == 0 else 60000  # 45s first try, 60s retry
                    wait_until = 'networkidle' if attempt == 0 else 'domcontentloaded'
                    
                    print(f"  🌐 Page load attempt {attempt + 1}/{max_retries} (timeout: {timeout/1000}s, wait: {wait_until})")
                    await page.goto(url, wait_until=wait_until, timeout=timeout)
                    break
                except Exception as e:
                    print(f"  🔄 Page load attempt {attempt + 1} failed: {e}")
                    if attempt == max_retries - 1:
                        raise
                    await asyncio.sleep(2)  # Brief pause before retry
            
            # Wait for content to load and simulate human behavior
            await page.wait_for_timeout(random.randint(2000, 4000))
            
            # First try to extract readable text directly from rendered page
            print(f"  🔍 Trying direct element extraction from rendered page...")
            
            # Try our specific selectors first (skip JSON-LD)
            content = None
            selectors_to_try = [s for s in self.content_selectors if 'script' not in s]
            
            for selector in selectors_to_try[:15]:  # Try top 15 selectors
                try:
                    element = await page.query_selector(selector)
                    if element:
                        text = await element.inner_text()
                        print(f"  📄 Selector '{selector}': {len(text)} chars")
                        if len(text) > self.min_content_length:
                            content = self._clean_text(text)
                            print(f"  ✅ Found good content with '{selector}': {len(content)} chars")
                            return content
                except Exception as e:
                    print(f"  ⚠️ Selector '{selector}' failed: {e}")
                    continue
            
            # Fallback to HTML parsing if direct extraction failed
            print(f"  🔍 Fallback to HTML parsing...")
            html_content = await page.content()
            if html_content:
                soup = BeautifulSoup(html_content, 'html.parser')
                
                # Remove unwanted elements first
                self._remove_unwanted_elements(soup)
                
                # Try enhanced selectors on cleaned HTML
                enhanced_content = self._extract_by_enhanced_selectors(soup)
                if enhanced_content and len(enhanced_content) > self.min_content_length:
                    return enhanced_content
                
                # Try JSON-LD as last resort (but it usually doesn't have full text)
                json_ld_content = self._extract_from_json_ld(soup)
                if json_ld_content and len(json_ld_content) > self.min_content_length:
                    return json_ld_content
            
            # Fallback to direct element extraction
            content = None
            for selector in self.content_selectors[:10]:  # Try top 10 selectors
                try:
                    if 'script' in selector:  # Skip JSON-LD selector
                        continue
                    element = await page.query_selector(selector)
                    if element:
                        text = await element.inner_text()
                        if len(text) > self.min_content_length:
                            content = text
                            break
                except:
                    continue
            
            if content:
                return self._clean_text(content)
            
        except Exception as e:
            print(f"  ⚠️ Browser extraction failed for {url}: {e}")
        finally:
            if page:
                try:
                    await page.close()
                except:
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
    
    def _assess_content_quality(self, text: str) -> float:
        """Assess content quality using various metrics."""
        if not text:
            return 0
        
        score = 0
        
        # Length scoring
        if len(text) > 2000:
            score += 40
        elif len(text) > 1000:
            score += 30
        elif len(text) > 500:
            score += 20
        else:
            score += 10
        
        # Sentence count
        sentences = len(re.findall(r'[.!?]+', text))
        if sentences > 10:
            score += 20
        elif sentences > 5:
            score += 15
        elif sentences > 2:
            score += 10
        
        # Word count
        words = len(text.split())
        if words > 300:
            score += 15
        elif words > 150:
            score += 10
        elif words > 50:
            score += 5
        
        # Text composition quality
        if text:
            letters = sum(c.isalpha() for c in text)
            letter_ratio = letters / len(text)
            
            if letter_ratio > 0.7:
                score += 15
            elif letter_ratio > 0.6:
                score += 10
            elif letter_ratio > 0.5:
                score += 5
        
        # Penalty for low-quality indicators
        low_quality_patterns = [
            r'click here', r'subscribe', r'advertisement',
            r'sponsored', r'cookie policy', r'privacy policy'
        ]
        
        for pattern in low_quality_patterns:
            if re.search(pattern, text.lower()):
                score -= 5
        
        return max(0, score)
    
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
        if quality_score < 30:  # Minimum quality threshold
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
        
        # Check for excessive repetition
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


# Создаем глобальный экземпляр для использования
_extractor_instance = None

async def get_content_extractor() -> ContentExtractor:
    """Get or create enhanced content extractor instance."""
    global _extractor_instance
    if _extractor_instance is None:
        _extractor_instance = ContentExtractor()
    return _extractor_instance