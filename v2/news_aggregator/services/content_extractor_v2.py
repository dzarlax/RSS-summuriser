"""Enhanced content extraction with AI-powered optimization."""

import re
import json
import asyncio
import time
from typing import Optional, Dict, Any, List, Tuple, NamedTuple
from urllib.parse import urljoin, urlparse
from dataclasses import dataclass

from bs4 import BeautifulSoup, Comment
from readability.readability import Document
from playwright.async_api import async_playwright, Browser, Page

from ..core.http_client import get_http_client
from ..core.exceptions import ContentExtractionError


@dataclass
class ExtractionResult:
    """Result of content extraction attempt."""
    content: Optional[str]
    method: str
    success: bool
    quality_score: float = 0.0
    extraction_time_ms: int = 0
    error_message: Optional[str] = None
    selectors_tried: List[str] = None
    
    def __post_init__(self):
        if self.selectors_tried is None:
            self.selectors_tried = []


@dataclass
class DomainStats:
    """Statistics for domain extraction patterns."""
    domain: str
    successful_methods: Dict[str, int]
    failed_methods: Dict[str, int]
    best_selectors: Dict[str, float]  # selector -> success_rate
    last_updated: float
    
    def get_best_method(self) -> Optional[str]:
        """Get the most successful method for this domain."""
        if not self.successful_methods:
            return None
        return max(self.successful_methods.items(), key=lambda x: x[1])[0]


class ContentExtractorV2:
    """Enhanced content extractor with AI-powered optimization."""
    
    def __init__(self):
        self.max_content_length = 8000
        self.min_content_length = 200
        self.browser: Optional[Browser] = None
        
        # Domain learning storage (in production this would be a database)
        self.domain_stats: Dict[str, DomainStats] = {}
        
        # Base content selectors organized by type
        self.readability_selectors = [
            # Schema.org microdata
            '[itemtype*="Article"] [itemprop="articleBody"]',
            '[itemtype*="NewsArticle"] [itemprop="articleBody"]',
            '[itemtype*="BlogPosting"] [itemprop="articleBody"]',
        ]
        
        self.html_parsing_selectors = [
            # Modern framework patterns
            '.prose', '.prose-lg', '.prose-xl',  # TailwindCSS
            '.container .text-base',
            
            # Site-specific patterns
            '.mb-14',  # N+1.ru
            '.article__text',  # Common Russian news
            '.news-text', '.news-content',
            '.material-text', '.full-text',
            '.text-content', '.story-text',
            
            # CMS patterns
            '.entry-content', '.post-content', '.article-content',
            '.content-body', '.article-body', '.story-body',
            '.post-body', '.main-content', '.article-text',
            
            # Semantic HTML5
            'article[role="main"]', 'main article', '[role="main"] article',
            'article', 'main', '.content', '#content', '#main-content'
        ]
        
        self.playwright_selectors = [
            # Dynamic content selectors (for JS-heavy sites)
            '[data-testid*="content"]', '[data-cy*="content"]',
            '[class*="text-"] div:not([class*="nav"]):not([class*="menu"])',
            '.dynamic-content', '.loaded-content', '.rendered-content'
        ]
        
        # AI learning parameters
        self.learning_enabled = True
        self.min_samples_for_learning = 3
        self.selector_success_threshold = 0.7
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.browser:
            await self.browser.close()
            self.browser = None
    
    async def extract_article_content(self, url: str) -> Optional[str]:
        """
        Extract content using AI-optimized method selection.
        
        Architecture:
        1. Check domain learning data
        2. Try learned best method first
        3. Fallback to all methods with learning
        4. Update learning data
        """
        if not url:
            return None
        
        url = self._clean_url(url)
        domain = self._extract_domain(url)
        start_time = time.time()
        
        print(f"🧠 AI-optimized extraction for {domain}")
        
        try:
            # Phase 1: Try learned best method first
            best_method = self._get_learned_best_method(domain)
            if best_method:
                print(f"  📚 Trying learned best method: {best_method}")
                result = await self._extract_with_method(url, best_method, domain)
                if result.success:
                    await self._record_extraction_result(domain, result)
                    return result.content
            
            # Phase 2: Try all methods with learning
            methods = ['readability', 'html_parsing', 'playwright']
            results = []
            
            for method in methods:
                if method == best_method:  # Skip already tried method
                    continue
                    
                print(f"  🔧 Trying method: {method}")
                result = await self._extract_with_method(url, method, domain)
                results.append(result)
                
                if result.success:
                    await self._record_extraction_result(domain, result)
                    return result.content
            
            # Phase 3: AI-powered selector discovery (if enabled)
            if self.learning_enabled and self._should_try_ai_discovery(domain):
                print(f"  🤖 AI selector discovery for {domain}")
                result = await self._ai_discover_selectors(url, domain)
                if result and result.success:
                    await self._record_extraction_result(domain, result)
                    return result.content
            
            # Record complete failure
            await self._record_complete_failure(domain, int((time.time() - start_time) * 1000))
            return None
            
        except Exception as e:
            raise ContentExtractionError(f"Failed to extract content from {url}: {e}")
    
    async def _extract_with_method(self, url: str, method: str, domain: str) -> ExtractionResult:
        """Extract content using specific method."""
        start_time = time.time()
        
        try:
            if method == 'readability':
                content = await self._extract_readability(url)
            elif method == 'html_parsing':
                content = await self._extract_html_parsing(url, domain)
            elif method == 'playwright':
                content = await self._extract_playwright(url, domain)
            else:
                raise ValueError(f"Unknown extraction method: {method}")
            
            extraction_time = int((time.time() - start_time) * 1000)
            
            if content and self._is_good_content(content):
                quality_score = self._assess_content_quality(content)
                return ExtractionResult(
                    content=content,
                    method=method,
                    success=True,
                    quality_score=quality_score,
                    extraction_time_ms=extraction_time
                )
            else:
                return ExtractionResult(
                    content=None,
                    method=method,
                    success=False,
                    extraction_time_ms=extraction_time,
                    error_message="Content quality insufficient"
                )
                
        except Exception as e:
            extraction_time = int((time.time() - start_time) * 1000)
            return ExtractionResult(
                content=None,
                method=method,
                success=False,
                extraction_time_ms=extraction_time,
                error_message=str(e)
            )
    
    # === CORE EXTRACTION METHODS ===
    
    async def _extract_readability(self, url: str) -> Optional[str]:
        """Pure Mozilla Readability extraction."""
        print(f"    📖 Readability extraction")
        
        try:
            headers = self._get_headers()
            
            async with get_http_client() as client:
                response = await client.session.get(url, headers=headers)
                response.raise_for_status()
                html = await response.text()
            
            if not html:
                return None
            
            # Use readability algorithm
            doc = Document(html)
            content = doc.summary()
            
            if content:
                soup = BeautifulSoup(content, 'html.parser')
                text = soup.get_text(separator='\n', strip=True)
                cleaned_text = self._clean_text(text)
                
                if len(cleaned_text) > self.min_content_length:
                    print(f"    ✅ Readability success: {len(cleaned_text)} chars")
                    return cleaned_text
            
            return None
            
        except Exception as e:
            print(f"    ❌ Readability failed: {type(e).__name__}")
            return None
    
    async def _extract_html_parsing(self, url: str, domain: str) -> Optional[str]:
        """Smart HTML parsing with learned selectors."""
        print(f"    🔍 HTML parsing extraction")
        
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
            
            # Try learned selectors first
            learned_selectors = self._get_learned_selectors(domain)
            if learned_selectors:
                for selector, success_rate in learned_selectors:
                    if success_rate > self.selector_success_threshold:
                        print(f"      🎯 Trying learned selector: {selector[:40]}... ({success_rate:.1%})")
                        content = self._try_selector(soup, selector)
                        if content:
                            print(f"      ✅ Learned selector success!")
                            return content
            
            # Try base selectors
            for selector in self.html_parsing_selectors:
                content = self._try_selector(soup, selector)
                if content:
                    print(f"    ✅ HTML parsing success with: {selector[:40]}...")
                    # Record this selector for learning
                    await self._record_selector_success(domain, selector)
                    return content
            
            # Try structured data extraction
            content = self._extract_structured_data(soup)
            if content:
                print(f"    ✅ Structured data success")
                return content
            
            return None
            
        except Exception as e:
            print(f"    ❌ HTML parsing failed: {type(e).__name__}")
            return None
    
    async def _extract_playwright(self, url: str, domain: str) -> Optional[str]:
        """Playwright browser rendering for JS-heavy sites."""
        print(f"    🎭 Playwright extraction")
        
        page = None
        try:
            if not self.browser:
                playwright = await async_playwright().start()
                self.browser = await playwright.chromium.launch(
                    headless=True,
                    args=[
                        '--no-sandbox',
                        '--disable-dev-shm-usage',
                        '--disable-blink-features=AutomationControlled'
                    ]
                )
            
            page = await self.browser.new_page()
            await page.set_extra_http_headers(self._get_headers())
            
            # Load page
            await page.goto(url, wait_until='networkidle', timeout=45000)
            await page.wait_for_timeout(2000)  # Let JS finish
            
            # Try learned selectors first
            learned_selectors = self._get_learned_selectors(domain, method='playwright')
            if learned_selectors:
                for selector, success_rate in learned_selectors:
                    if success_rate > self.selector_success_threshold:
                        try:
                            element = await page.query_selector(selector)
                            if element:
                                text = await element.inner_text()
                                if len(text) > self.min_content_length:
                                    content = self._clean_text(text)
                                    print(f"      ✅ Learned Playwright selector success!")
                                    return content
                        except:
                            continue
            
            # Try base selectors
            all_selectors = self.playwright_selectors + self.html_parsing_selectors
            for selector in all_selectors:
                try:
                    element = await page.query_selector(selector)
                    if element:
                        text = await element.inner_text()
                        if len(text) > self.min_content_length:
                            content = self._clean_text(text)
                            print(f"    ✅ Playwright success with: {selector[:40]}...")
                            # Record for learning
                            await self._record_selector_success(domain, selector, method='playwright')
                            return content
                except:
                    continue
            
            return None
            
        except Exception as e:
            print(f"    ❌ Playwright failed: {type(e).__name__}")
            return None
        finally:
            if page:
                try:
                    await page.close()
                except:
                    pass
    
    # === AI OPTIMIZATION METHODS ===
    
    async def _ai_discover_selectors(self, url: str, domain: str) -> Optional[ExtractionResult]:
        """AI-powered selector discovery for difficult sites."""
        print(f"      🤖 AI selector discovery")
        
        try:
            # This would integrate with your AI service
            # For now, we'll implement a smart heuristic approach
            
            headers = self._get_headers()
            async with get_http_client() as client:
                response = await client.session.get(url, headers=headers)
                response.raise_for_status()
                html = await response.text()
            
            soup = BeautifulSoup(html, 'html.parser')
            
            # AI-like heuristic: find elements with most text that look like content
            content_candidates = []
            
            for element in soup.find_all(['div', 'section', 'article', 'main']):
                if not element.get('class') and not element.get('id'):
                    continue  # Skip elements without identifiers
                
                text = element.get_text(separator=' ', strip=True)
                if len(text) < 300:  # Too short to be main content
                    continue
                
                # Score based on content indicators
                score = 0
                classes = ' '.join(element.get('class', [])).lower()
                element_id = element.get('id', '').lower()
                
                # Positive indicators
                for indicator in ['content', 'article', 'story', 'text', 'body', 'main']:
                    if indicator in classes or indicator in element_id:
                        score += 10
                
                # Modern CSS framework indicators
                for indicator in ['prose', 'container', 'wrapper']:
                    if indicator in classes:
                        score += 5
                
                # Negative indicators
                for indicator in ['nav', 'menu', 'sidebar', 'ad', 'social']:
                    if indicator in classes or indicator in element_id:
                        score -= 10
                
                if score > 0:
                    # Generate CSS selector for this element
                    selector = self._generate_css_selector(element)
                    if selector:
                        content_candidates.append((score, selector, text))
            
            # Try best candidates
            content_candidates.sort(key=lambda x: x[0], reverse=True)
            
            for score, selector, text in content_candidates[:3]:  # Try top 3
                if len(text) > self.min_content_length:
                    cleaned_content = self._clean_text(text)
                    if self._is_good_content(cleaned_content):
                        print(f"      ✅ AI discovered selector: {selector}")
                        # Record this AI-discovered selector
                        await self._record_selector_success(domain, selector, method='ai_discovered')
                        
                        return ExtractionResult(
                            content=cleaned_content,
                            method='ai_discovered',
                            success=True,
                            quality_score=self._assess_content_quality(cleaned_content),
                            selectors_tried=[selector]
                        )
            
            return None
            
        except Exception as e:
            print(f"      ❌ AI discovery failed: {e}")
            return None
    
    # === LEARNING AND OPTIMIZATION ===
    
    def _get_learned_best_method(self, domain: str) -> Optional[str]:
        """Get the best extraction method for this domain based on learning."""
        if domain not in self.domain_stats:
            return None
        
        stats = self.domain_stats[domain]
        return stats.get_best_method()
    
    def _get_learned_selectors(self, domain: str, method: str = None) -> List[Tuple[str, float]]:
        """Get learned selectors for domain, optionally filtered by method."""
        if domain not in self.domain_stats:
            return []
        
        stats = self.domain_stats[domain]
        selectors = []
        
        for selector, success_rate in stats.best_selectors.items():
            if method and not selector.startswith(f"{method}:"):
                continue
            selectors.append((selector.replace(f"{method}:", ""), success_rate))
        
        # Sort by success rate
        selectors.sort(key=lambda x: x[1], reverse=True)
        return selectors[:5]  # Return top 5
    
    async def _record_extraction_result(self, domain: str, result: ExtractionResult):
        """Record extraction result for learning."""
        if domain not in self.domain_stats:
            self.domain_stats[domain] = DomainStats(
                domain=domain,
                successful_methods={},
                failed_methods={},
                best_selectors={},
                last_updated=time.time()
            )
        
        stats = self.domain_stats[domain]
        
        if result.success:
            stats.successful_methods[result.method] = stats.successful_methods.get(result.method, 0) + 1
            print(f"  📈 Recorded success: {result.method} for {domain}")
        else:
            stats.failed_methods[result.method] = stats.failed_methods.get(result.method, 0) + 1
            print(f"  📉 Recorded failure: {result.method} for {domain}")
        
        stats.last_updated = time.time()
    
    async def _record_selector_success(self, domain: str, selector: str, method: str = 'html_parsing'):
        """Record successful selector for learning."""
        if domain not in self.domain_stats:
            self.domain_stats[domain] = DomainStats(
                domain=domain,
                successful_methods={},
                failed_methods={},
                best_selectors={},
                last_updated=time.time()
            )
        
        stats = self.domain_stats[domain]
        selector_key = f"{method}:{selector}"
        
        # Simple success rate calculation (in production, this would be more sophisticated)
        current_rate = stats.best_selectors.get(selector_key, 0.0)
        new_rate = min(1.0, current_rate + 0.1)  # Increment by 10%
        stats.best_selectors[selector_key] = new_rate
        
        print(f"  🎯 Recorded selector success: {selector[:40]}... ({new_rate:.1%})")
        stats.last_updated = time.time()
    
    async def _record_complete_failure(self, domain: str, extraction_time_ms: int):
        """Record complete extraction failure."""
        print(f"  💥 Complete failure for {domain} ({extraction_time_ms}ms)")
    
    def _should_try_ai_discovery(self, domain: str) -> bool:
        """Determine if AI discovery should be attempted for this domain."""
        if not self.learning_enabled:
            return False
        
        if domain not in self.domain_stats:
            return True  # Try AI for unknown domains
        
        stats = self.domain_stats[domain]
        total_attempts = sum(stats.successful_methods.values()) + sum(stats.failed_methods.values())
        
        # Try AI if we have few successful extractions
        success_rate = sum(stats.successful_methods.values()) / max(1, total_attempts)
        return success_rate < 0.3 and total_attempts >= self.min_samples_for_learning
    
    # === UTILITY METHODS ===
    
    def _try_selector(self, soup: BeautifulSoup, selector: str) -> Optional[str]:
        """Try CSS selector on soup."""
        try:
            elements = soup.select(selector)
            if elements:
                text = elements[0].get_text(separator='\n', strip=True)
                if len(text) > self.min_content_length:
                    return self._clean_text(text)
        except:
            pass
        return None
    
    def _extract_structured_data(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract from JSON-LD and other structured data."""
        # JSON-LD extraction
        scripts = soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                if not script.string:
                    continue
                data = json.loads(script.string)
                items = data if isinstance(data, list) else [data]
                
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    
                    item_type = item.get('@type', '')
                    if isinstance(item_type, list):
                        item_type = item_type[0] if item_type else ''
                    
                    if item_type in ['Article', 'NewsArticle', 'BlogPosting']:
                        article_body = item.get('articleBody')
                        if article_body and len(str(article_body)) > self.min_content_length:
                            return self._clean_text(str(article_body))
            except:
                continue
        
        return None
    
    def _generate_css_selector(self, element) -> Optional[str]:
        """Generate CSS selector for element."""
        try:
            # Simple selector generation
            if element.get('id'):
                return f"#{element['id']}"
            
            if element.get('class'):
                classes = element['class']
                if len(classes) == 1:
                    return f".{classes[0]}"
                # For multiple classes, pick the most specific looking one
                for cls in classes:
                    if any(word in cls.lower() for word in ['content', 'article', 'story', 'text']):
                        return f".{cls}"
                return f".{classes[0]}"
            
            # Fallback to tag + nth-child
            return f"{element.name}:nth-child({len(list(element.previous_siblings)) + 1})"
            
        except:
            return None
    
    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL."""
        try:
            parsed = urlparse(url)
            return parsed.netloc.lower()
        except:
            return "unknown"
    
    def _clean_url(self, url: str) -> str:
        """Clean URL from problematic characters."""
        import unicodedata
        problematic_chars = ['\u200B', '\u200C', '\u200D', '\u2060', '\uFEFF', '\u00A0']
        cleaned_url = url
        for char in problematic_chars:
            cleaned_url = cleaned_url.replace(char, '')
        return unicodedata.normalize('NFKC', cleaned_url).strip()
    
    def _get_headers(self) -> Dict[str, str]:
        """Get realistic HTTP headers."""
        import random
        user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        ]
        
        return {
            'User-Agent': random.choice(user_agents),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }
    
    def _remove_unwanted_elements(self, soup: BeautifulSoup) -> None:
        """Remove unwanted HTML elements."""
        unwanted_tags = ['script', 'style', 'noscript', 'iframe', 'embed', 'object', 'form']
        for tag in unwanted_tags:
            for element in soup.find_all(tag):
                element.decompose()
        
        unwanted_selectors = [
            'nav', 'header', 'footer', 'aside', '.navigation', '.menu',
            '.advertisement', '.ads', '.ad', '.social', '.share',
            '.comments', '.comment', '.related', '.recommended'
        ]
        for selector in unwanted_selectors:
            for element in soup.select(selector):
                element.decompose()
    
    def _clean_text(self, text: str) -> str:
        """Clean extracted text."""
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
        ]
        
        for pattern in unwanted_patterns:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)
        
        return text.strip()
    
    def _is_good_content(self, content: str) -> bool:
        """Check if content meets quality standards."""
        if not content or len(content) < self.min_content_length:
            return False
        
        quality_score = self._assess_content_quality(content)
        return quality_score >= 30
    
    def _assess_content_quality(self, text: str) -> float:
        """Assess content quality."""
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
        
        # Sentence count
        sentences = len(re.findall(r'[.!?]+', text))
        if sentences > 10:
            score += 20
        elif sentences > 5:
            score += 15
        
        # Word count
        words = len(text.split())
        if words > 300:
            score += 15
        elif words > 150:
            score += 10
        
        return score


# Global instance
_extractor_instance = None

async def get_content_extractor_v2() -> ContentExtractorV2:
    """Get or create enhanced content extractor instance."""
    global _extractor_instance
    if _extractor_instance is None:
        _extractor_instance = ContentExtractorV2()
    return _extractor_instance