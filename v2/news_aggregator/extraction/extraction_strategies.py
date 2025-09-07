"""Different strategies for content extraction from web pages."""

import asyncio
import time
from typing import Optional, Dict, Any, List
from urllib.parse import urljoin

import aiohttp
import chardet
from bs4 import BeautifulSoup
from readability.readability import Document
from playwright.async_api import async_playwright, Browser, Page

from ..core.http_client import get_http_client
from ..core.exceptions import ContentExtractionError
from ..services.extraction_memory import get_extraction_memory, ExtractionAttempt
from ..services.domain_stability_tracker import get_stability_tracker
from ..services.ai_extraction_optimizer import get_ai_extraction_optimizer
from ..services.extraction_constants import (
    BROWSER_CONCURRENCY,
    PLAYWRIGHT_TIMEOUT_FIRST_MS,
    PLAYWRIGHT_TIMEOUT_RETRY_MS,
    PLAYWRIGHT_TOTAL_BUDGET_MS,
)

from .extraction_utils import ExtractionUtils
from .html_processor import HTMLProcessor
from .date_extractor import DateExtractor
from .metadata_extractor import MetadataExtractor


class ExtractionStrategies:
    """Various strategies for extracting content from web pages."""
    
    def __init__(self, utils: ExtractionUtils, html_processor: HTMLProcessor, 
                 date_extractor: DateExtractor, metadata_extractor: MetadataExtractor):
        self.utils = utils
        self.html_processor = html_processor
        self.date_extractor = date_extractor
        self.metadata_extractor = metadata_extractor
        
        # Browser management
        self.browser: Optional[Browser] = None
        self._browser_semaphore = asyncio.Semaphore(BROWSER_CONCURRENCY)
    
    def _is_high_quality_content(self, content: str, title: str = "", url: str = "") -> bool:
        """Check if extracted content passes quality checks using Smart Filter."""
        if not content or not content.strip():
            return False
        
        try:
            from ..services.smart_filter import get_smart_filter
            smart_filter = get_smart_filter()
            
            # Use Smart Filter to check content quality
            # We use allow_extraction=False to get strict quality assessment
            should_process, reason = smart_filter.should_process_with_ai(
                title=title or "Extracted Content",
                content=content,
                url=url,
                source_type='extraction',
                allow_extraction=False
            )
            
            if not should_process and "Metadata/low-quality content detected" in reason:
                print(f"    ❌ Content failed quality check: {reason}")
                return False
            
            return True
            
        except Exception as e:
            print(f"    ⚠️ Quality check failed: {e}, assuming content is valid")
            return True  # Fail open - if quality check fails, assume content is OK
    
    async def attempt_extraction_with_metadata(self, url: str, domain: str, attempt_num: int) -> Dict[str, Optional[str]]:
        """Attempt content extraction with comprehensive metadata extraction."""
        print(f"    🔄 Extraction attempt #{attempt_num} for domain: {domain}")
        
        result = {
            'content': None,
            'title': None,
            'publication_date': None,
            'author': None,
            'description': None,
            'method_used': None
        }
        
        # Strategy 1: Try learned patterns first (fastest)
        extraction_memory = await get_extraction_memory()
        learned_pattern = await extraction_memory.get_successful_pattern(domain)
        
        if learned_pattern:
            print(f"    📚 Trying learned pattern for {domain}")
            try:
                content = await self.extract_with_learned_pattern(url, learned_pattern)
                if content and self.utils.is_good_content(content) and self._is_high_quality_content(content, url=url):
                    result['content'] = content
                    result['method_used'] = f"learned_pattern_{learned_pattern.get('method', 'unknown')}"
                    
                    # Try to extract metadata with quick HTML fetch
                    try:
                        html = await self.fetch_html_content(url)
                        if html:
                            soup = BeautifulSoup(html, 'html.parser')
                            result['title'] = self.metadata_extractor.extract_meta_title(soup)
                            result['publication_date'] = self.date_extractor.extract_publication_date(soup)
                            result['author'] = self.metadata_extractor.extract_author_info(soup)
                            result['description'] = self.metadata_extractor.extract_meta_description(soup)
                    except Exception as e:
                        print(f"    ⚠️ Metadata extraction failed: {e}")
                    
                    return result
            except Exception as e:
                print(f"    ❌ Learned pattern failed: {e}")
        
        # Strategy 2: Readability with HTML fetch
        try:
            print(f"    📖 Trying readability extraction")
            content = await self.extract_with_readability(url)
            if content and self.utils.is_good_content(content) and self._is_high_quality_content(content, url=url):
                result['content'] = content
                result['method_used'] = 'readability'
                
                # Extract metadata from the same HTML
                try:
                    html = await self.fetch_html_content(url)
                    if html:
                        soup = BeautifulSoup(html, 'html.parser')
                        result['title'] = self.metadata_extractor.extract_meta_title(soup)
                        result['publication_date'] = self.date_extractor.extract_publication_date(soup)
                        result['author'] = self.metadata_extractor.extract_author_info(soup)
                        result['description'] = self.metadata_extractor.extract_meta_description(soup)
                except Exception as e:
                    print(f"    ⚠️ Metadata extraction failed: {e}")
                
                return result
        except Exception as e:
            print(f"    ❌ Readability extraction failed: {e}")
        
        # Strategy 3: Enhanced HTML selectors
        try:
            print(f"    🎯 Trying enhanced selectors")
            html = await self.fetch_html_content(url)
            if html:
                soup = BeautifulSoup(html, 'html.parser')
                content = self.html_processor.extract_by_enhanced_selectors(soup)
                
                if content and self.utils.is_good_content(content) and self._is_high_quality_content(content, url=url):
                    result['content'] = content
                    result['method_used'] = 'enhanced_selectors'
                    result['title'] = self.metadata_extractor.extract_meta_title(soup)
                    result['publication_date'] = self.date_extractor.extract_publication_date(soup)
                    result['author'] = self.metadata_extractor.extract_author_info(soup)
                    result['description'] = self.metadata_extractor.extract_meta_description(soup)
                    return result
        except Exception as e:
            print(f"    ❌ Enhanced selectors failed: {e}")
        
        # Strategy 4: Browser rendering (more expensive)
        try:
            print(f"    🎭 Trying browser rendering")
            content = await self.extract_with_browser(url)
            if content and self.utils.is_good_content(content) and self._is_high_quality_content(content, url=url):
                result['content'] = content
                result['method_used'] = 'browser_rendering'
                
                # Try to get metadata through browser as well
                try:
                    async with self._browser_semaphore:
                        if not self.browser:
                            playwright = await async_playwright().start()
                            self.browser = await playwright.chromium.launch(headless=True)
                        
                        context = await self.browser.new_context()
                        page = await context.new_page()
                        await page.goto(url, timeout=PLAYWRIGHT_TIMEOUT_FIRST_MS)
                        
                        # Extract metadata through browser
                        title = await page.title()
                        if title:
                            result['title'] = title
                        
                        # Get HTML for further metadata extraction
                        html_content = await page.content()
                        if html_content:
                            soup = BeautifulSoup(html_content, 'html.parser')
                            result['publication_date'] = self.date_extractor.extract_publication_date(soup)
                            result['author'] = self.metadata_extractor.extract_author_info(soup)
                            result['description'] = self.metadata_extractor.extract_meta_description(soup)
                        
                        await context.close()
                        
                except Exception as e:
                    print(f"    ⚠️ Browser metadata extraction failed: {e}")
                
                return result
        except Exception as e:
            print(f"    ❌ Browser rendering failed: {e}")
        
        # Strategy 5: Fallback to basic text extraction
        try:
            print(f"    🔄 Trying fallback extraction")
            html = await self.fetch_html_content_fallback(url)
            if html:
                soup = BeautifulSoup(html, 'html.parser')
                
                # Try multiple extraction methods
                content = (
                    self.metadata_extractor.extract_from_json_ld(soup) or
                    self.metadata_extractor.extract_from_open_graph(soup) or
                    self.html_processor.extract_by_enhanced_heuristics(soup)
                )
                
                if content and len(content) > 100:
                    result['content'] = content
                    result['method_used'] = 'fallback_extraction'
                    result['title'] = self.metadata_extractor.extract_meta_title(soup)
                    result['publication_date'] = self.date_extractor.extract_publication_date(soup)
                    result['author'] = self.metadata_extractor.extract_author_info(soup)
                    result['description'] = self.metadata_extractor.extract_meta_description(soup)
                    return result
        except Exception as e:
            print(f"    ❌ Fallback extraction failed: {e}")
        
        return result
    
    async def attempt_content_extraction(self, url: str, domain: str, attempt_num: int) -> Optional[str]:
        """Attempt content extraction using various strategies."""
        print(f"    🔄 Content extraction attempt #{attempt_num} for domain: {domain}")
        
        # Strategy 1: Try learned patterns first
        extraction_memory = await get_extraction_memory()
        learned_pattern = await extraction_memory.get_successful_pattern(domain)
        
        if learned_pattern:
            print(f"    📚 Trying learned pattern")
            try:
                content = await self.extract_with_learned_pattern(url, learned_pattern)
                if content and self.utils.is_good_content(content) and self._is_high_quality_content(content, url=url):
                    return content
            except Exception as e:
                print(f"    ❌ Learned pattern failed: {e}")
        
        # Strategy 2: Enhanced selectors with HTML fetch
        try:
            print(f"    🎯 Trying enhanced selectors")
            content = await self.extract_with_enhanced_selectors(url)
            if content and self.utils.is_good_content(content) and self._is_high_quality_content(content, url=url):
                return content
        except Exception as e:
            print(f"    ❌ Enhanced selectors failed: {e}")
        
        # Strategy 3: Readability
        try:
            print(f"    📖 Trying readability")
            content = await self.extract_with_readability(url)
            if content and self.utils.is_good_content(content) and self._is_high_quality_content(content, url=url):
                return content
        except Exception as e:
            print(f"    ❌ Readability failed: {e}")
        
        # Strategy 4: Browser rendering
        try:
            print(f"    🎭 Trying browser rendering")
            content = await self.extract_with_browser(url)
            if content and self.utils.is_good_content(content) and self._is_high_quality_content(content, url=url):
                return content
        except Exception as e:
            print(f"    ❌ Browser failed: {e}")
        
        # Strategy 5: Encoding detection
        try:
            print(f"    🔤 Trying encoding detection")
            content = await self.extract_with_encoding_detection(url)
            if content and self.utils.is_good_content(content) and self._is_high_quality_content(content, url=url):
                return content
        except Exception as e:
            print(f"    ❌ Encoding detection failed: {e}")
        
        # Strategy 6: Simple direct extraction
        try:
            print(f"    📄 Trying simple extraction")
            content = await self.extract_simple_direct(url)
            if content and len(content) > 50:
                return content
        except Exception as e:
            print(f"    ❌ Simple extraction failed: {e}")
        
        return None
    
    async def extract_with_learned_pattern(self, url: str, pattern) -> Optional[str]:
        """Extract content using a learned CSS selector pattern."""
        if not pattern or 'selector' not in pattern:
            return None
        
        try:
            html = await self.fetch_html_content(url)
            if not html:
                return None
            
            soup = BeautifulSoup(html, 'html.parser')
            return await self.extract_with_css_selector(url, pattern['selector'])
        except Exception as e:
            raise ContentExtractionError(f"Learned pattern extraction failed: {e}")
    
    async def extract_with_css_selector(self, url: str, selector: str) -> Optional[str]:
        """Extract content using a specific CSS selector."""
        try:
            html = await self.fetch_html_content(url)
            if not html:
                return None
            
            soup = BeautifulSoup(html, 'html.parser')
            elements = soup.select(selector)
            
            if elements:
                content = elements[0].get_text(separator=' ', strip=True)
                return self.html_processor.clean_text(content)
                
        except Exception as e:
            raise ContentExtractionError(f"CSS selector extraction failed: {e}")
        
        return None
    
    async def extract_with_playwright_selector(self, url: str, selector: str) -> Optional[str]:
        """Extract content using Playwright with CSS selector."""
        async with self._browser_semaphore:
            try:
                if not self.browser:
                    playwright = await async_playwright().start()
                    self.browser = await playwright.chromium.launch(headless=True)
                
                context = await self.browser.new_context()
                page = await context.new_page()
                
                await page.goto(url, timeout=PLAYWRIGHT_TIMEOUT_FIRST_MS)
                
                # Wait for selector and extract content
                await page.wait_for_selector(selector, timeout=5000)
                element = await page.query_selector(selector)
                
                if element:
                    content = await element.inner_text()
                    return self.html_processor.clean_text(content) if content else None
                
                await context.close()
                
            except Exception as e:
                raise ContentExtractionError(f"Playwright extraction failed: {e}")
        
        return None
    
    async def extract_with_encoding_detection(self, url: str) -> Optional[str]:
        """Extract content using automatic encoding detection for international sites."""
        try:
            import aiohttp
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self.utils.get_headers()) as response:
                    if response.status != 200:
                        return None
                    
                    # Get raw bytes
                    content_bytes = await response.read()
                    
                    # Detect encoding
                    encoding_info = chardet.detect(content_bytes)
                    encoding = encoding_info.get('encoding', 'utf-8')
                    confidence = encoding_info.get('confidence', 0)
                    
                    print(f"    🔤 Detected encoding: {encoding} (confidence: {confidence:.2f})")
                    
                    # Decode with detected or fallback encoding
                    html = None
                    if confidence < 0.7:  # Low confidence, try common encodings
                        for fallback_encoding in ['utf-8', 'cp1252', 'iso-8859-1']:
                            try:
                                html = content_bytes.decode(fallback_encoding)
                                break
                            except UnicodeDecodeError:
                                continue
                        if not html:
                            return None
                    else:
                        try:
                            html = content_bytes.decode(encoding)
                        except UnicodeDecodeError:
                            html = content_bytes.decode('utf-8', errors='ignore')
                    
                    # Parse and extract
                    soup = BeautifulSoup(html, 'html.parser')
                    content = (
                        self.html_processor.extract_by_enhanced_selectors(soup) or
                        self.html_processor.extract_by_enhanced_heuristics(soup)
                    )
                    
                    return content
                
        except Exception as e:
            raise ContentExtractionError(f"Encoding detection extraction failed: {e}")
    
    async def extract_with_readability(self, url: str) -> Optional[str]:
        """Extract content using Python readability library."""
        try:
            html = await self.fetch_html_content(url)
            if not html:
                return None
            
            doc = Document(html)
            content = doc.summary()
            
            if content:
                # Parse the readability output and extract text
                soup = BeautifulSoup(content, 'html.parser')
                text_content = soup.get_text(separator=' ', strip=True)
                return self.html_processor.clean_text(text_content)
                
        except Exception as e:
            raise ContentExtractionError(f"Readability extraction failed: {e}")
        
        return None
    
    async def extract_with_enhanced_selectors(self, url: str) -> Optional[str]:
        """Extract content using enhanced CSS selectors."""
        try:
            html = await self.fetch_html_content(url)
            if not html:
                return None
            
            soup = BeautifulSoup(html, 'html.parser')
            return self.html_processor.extract_by_enhanced_selectors(soup)
            
        except Exception as e:
            raise ContentExtractionError(f"Enhanced selectors extraction failed: {e}")
    
    async def extract_with_browser(self, url: str) -> Optional[str]:
        """Extract content using browser rendering for JavaScript-heavy sites."""
        print(f"      🎭 Starting browser extraction for: {url[:80]}...")
        budget_start = time.time()
        
        async with self._browser_semaphore:
            try:
                if not self.browser:
                    print(f"      🚀 Launching Playwright browser...")
                    playwright = await async_playwright().start()
                    self.browser = await playwright.chromium.launch(
                        headless=True,
                        args=['--no-sandbox', '--disable-setuid-sandbox']  # Docker compatibility
                    )
                    print(f"      ✅ Browser launched successfully")
                
                context = await self.browser.new_context(
                    user_agent='Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                )
                page = await context.new_page()
                
                # Set up route handler for resource blocking
                async def route_handler(route):
                    if route.request.resource_type in ["image", "media", "font"]:
                        await route.abort()
                    else:
                        await route.continue_()
                
                await page.route("**/*", route_handler)
                
                # Navigate with timeout
                def remaining_ms() -> int:
                    elapsed_s = time.time() - budget_start
                    remaining_s = max(0, PLAYWRIGHT_TOTAL_BUDGET_MS / 1000 - elapsed_s)
                    return int(remaining_s * 1000)
                
                timeout_ms = min(PLAYWRIGHT_TIMEOUT_FIRST_MS, remaining_ms())
                print(f"      🌐 Navigating to URL (timeout: {timeout_ms}ms)...")
                await page.goto(url, timeout=timeout_ms)
                print(f"      ✅ Page loaded successfully")
                
                # Wait for content to load - improved for SPA sites
                print(f"      ⏳ Waiting for content to load...")
                try:
                    # Wait for network to be idle (initial load)
                    print(f"      🌐 Waiting for network idle...")
                    await page.wait_for_load_state('networkidle', timeout=min(5000, remaining_ms()))
                    print(f"      ✅ Network idle achieved")
                    
                    # For SPA sites, wait for content to actually appear
                    print(f"      📝 Waiting for substantial content (>500 chars)...")
                    await page.wait_for_function(
                        "() => document.body.innerText.length > 500", 
                        timeout=min(10000, remaining_ms())
                    )
                    print(f"      ✅ Substantial content detected")
                except Exception as e:
                    print(f"      ⚠️ Content detection failed: {e}")
                    # If SPA detection fails, try waiting for common content selectors
                    try:
                        print(f"      🎯 Waiting for content selectors...")
                        await page.wait_for_selector(
                            'article, main, .content, #content, p', 
                            timeout=min(8000, remaining_ms())
                        )
                        print(f"      ✅ Content selector found")
                        # Give additional time for dynamic content to load
                        await asyncio.sleep(min(2, remaining_ms() / 1000))
                    except Exception as e2:
                        print(f"      ⚠️ Content selector wait failed: {e2}")
                        pass  # Continue even if content detection times out
                
                # Extract content using multiple strategies
                content = None
                
                # First, let's see what we're working with
                print(f"      📊 Analyzing page content...")
                try:
                    body_text_length = await page.evaluate("() => document.body.innerText.length")
                    print(f"      📏 Total body text length: {body_text_length} chars")
                except:
                    print(f"      ⚠️ Could not measure body text length")
                
                # Strategy 1: Look for article/main content - comprehensive selectors
                print(f"      🎯 Trying content selectors...")
                article_selectors = [
                    # Semantic HTML5
                    'article', 'main', '[role="main"]',
                    # Common content containers
                    '.content', '#content', '.post-content', '.article-content',
                    '.entry-content', '.story-content', '.news-content',
                    # Generic content wrappers
                    '.container .content', '.wrapper .content',
                    # Try multiple paragraphs as content
                    'div:has(> p:nth-child(3))',  # Divs with multiple paragraphs
                ]
                
                for i, selector in enumerate(article_selectors):
                    try:
                        print(f"        🔍 [{i+1}/{len(article_selectors)}] Trying selector: {selector}")
                        element = await page.query_selector(selector)
                        if element:
                            text = await element.inner_text()
                            text_len = len(text.strip()) if text else 0
                            print(f"        📝 Found element with {text_len} chars")
                            if text and text_len > 200:
                                content = self.html_processor.clean_text(text)
                                if self.utils.is_good_content(content) and self._is_high_quality_content(content, url=url):
                                    print(f"        ✅ Content accepted from selector: {selector}")
                                    break
                                else:
                                    print(f"        ❌ Content quality insufficient")
                        else:
                            print(f"        ❌ Selector not found: {selector}")
                    except Exception as e:
                        print(f"        ❌ Selector failed: {selector} - {e}")
                        continue
                
                # Strategy 1.5: Collect paragraphs if main content not found
                if not content:
                    print(f"      📝 Collecting paragraphs...")
                    try:
                        # Find all meaningful paragraphs
                        paragraphs = await page.query_selector_all('p')
                        print(f"        📊 Found {len(paragraphs)} paragraphs")
                        if paragraphs and len(paragraphs) >= 3:
                            paragraph_texts = []
                            for i, p in enumerate(paragraphs):
                                text = await p.inner_text()
                                text_len = len(text.strip()) if text else 0
                                if text and text_len > 50:  # Meaningful paragraph
                                    paragraph_texts.append(text.strip())
                                    print(f"        📝 P{i+1}: {text_len} chars - '{text[:60]}...'")
                            
                            print(f"        📊 Collected {len(paragraph_texts)} meaningful paragraphs")
                            if len(paragraph_texts) >= 3:
                                combined_text = '\n\n'.join(paragraph_texts)
                                print(f"        📏 Combined text length: {len(combined_text)} chars")
                                if len(combined_text) > 500:
                                    content = self.html_processor.clean_text(combined_text)
                                    if content:
                                        quality_score = self.utils.assess_content_quality(content)
                                        print(f"        📊 Content quality score: {quality_score:.2f} (min: 0.30)")
                                        if self.utils.is_good_content(content) and self._is_high_quality_content(content, url=url):
                                            print(f"        ✅ Paragraph collection successful!")
                                        else:
                                            print(f"        ❌ Combined paragraph quality insufficient (score: {quality_score:.2f})")
                    except Exception as e:
                        print(f"        ❌ Paragraph collection failed: {e}")

                # Strategy 2: Fallback to body content
                if not content:
                    print(f"      🚑 Fallback to body content...")
                    try:
                        body = await page.query_selector('body')
                        if body:
                            raw_content = await body.inner_text()
                            content_len = len(raw_content) if raw_content else 0
                            print(f"        📏 Body text length: {content_len} chars")
                            if raw_content and content_len > 200:
                                content = self.html_processor.clean_text(raw_content)
                                if content and self.utils.is_good_content(content) and self._is_high_quality_content(content, url=url):
                                    print(f"        ✅ Body content accepted (cleaned: {len(content)} chars)")
                                else:
                                    print(f"        ❌ Body content quality insufficient")
                                    content = None
                            else:
                                print(f"        ❌ Body content too short")
                        else:
                            print(f"        ❌ Body element not found")
                    except Exception as e:
                        print(f"        ❌ Body extraction failed: {e}")
                
                await context.close()
                return content
                
            except Exception as e:
                raise ContentExtractionError(f"Browser extraction failed: {e}")
    
    async def extract_simple_direct(self, url: str) -> Optional[str]:
        """Simple direct extraction as last resort."""
        try:
            html = await self.fetch_html_content_fallback(url)
            if not html:
                return None
            
            soup = BeautifulSoup(html, 'html.parser')
            
            # Remove unwanted elements
            self.html_processor.remove_unwanted_elements(soup)
            
            # Get all text
            text = soup.get_text(separator=' ', strip=True)
            return self.html_processor.clean_text(text)
            
        except Exception as e:
            raise ContentExtractionError(f"Simple extraction failed: {e}")
    
    async def fetch_html_content(self, url: str) -> Optional[str]:
        """Fetch HTML content using HTTP client."""
        try:
            # Use aiohttp directly to avoid async generator issues
            import aiohttp
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self.utils.get_headers()) as response:
                    if response.status == 200:
                        return await response.text()
                    else:
                        print(f"    ⚠️ HTTP {response.status} for {url}")
                        return None
                    
        except Exception as e:
            print(f"    ❌ HTML fetch failed: {e}")
            return None
    
    async def fetch_html_content_fallback(self, url: str) -> Optional[str]:
        """Fallback HTML fetching using requests library."""
        try:
            import requests
            from requests.adapters import HTTPAdapter
            from requests.packages.urllib3.util.retry import Retry
            
            session = requests.Session()
            retry_strategy = Retry(
                total=2,
                backoff_factor=1,
                status_forcelist=[429, 500, 502, 503, 504],
            )
            session.mount("http://", HTTPAdapter(max_retries=retry_strategy))
            session.mount("https://", HTTPAdapter(max_retries=retry_strategy))
            
            response = session.get(url, headers=self.utils.get_headers(), timeout=10)
            
            if response.status_code == 200:
                return response.text
            else:
                return None
                
        except Exception as e:
            print(f"    ❌ Fallback fetch failed: {e}")
            return None
    
    async def record_extraction_success(
        self,
        domain: str,
        method: str,
        selector: Optional[str] = None,
        content_length: int = 0,
        extraction_time: float = 0
    ):
        """Record successful extraction for learning."""
        try:
            extraction_memory = await get_extraction_memory()
            attempt = ExtractionAttempt(
                domain=domain,
                method=method,
                selector=selector,
                success=True,
                content_length=content_length,
                extraction_time=extraction_time,
                error=None
            )
            
            await extraction_memory.record_attempt(attempt)
            
        except Exception as e:
            print(f"    ⚠️ Failed to record success: {e}")
    
    async def record_extraction_failure(
        self,
        domain: str,
        method: str,
        error: str,
        selector: Optional[str] = None
    ):
        """Record failed extraction for learning."""
        try:
            extraction_memory = await get_extraction_memory()
            attempt = ExtractionAttempt(
                article_url="unknown",
                domain=domain,
                extraction_strategy=method,
                selector_used=selector,
                success=False,
                content_length=0,
                extraction_time_ms=0,
                error_message=error
            )
            
            await extraction_memory.record_attempt(attempt)
            
        except Exception as e:
            print(f"    ⚠️ Failed to record failure: {e}")
    
    async def close_browser(self):
        """Close browser if open."""
        if self.browser:
            await self.browser.close()
            self.browser = None
