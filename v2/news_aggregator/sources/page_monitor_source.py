"""Adaptive page monitor source for websites without RSS feeds."""

import re
import json
import hashlib
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Set, Tuple, Any
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

try:
    from playwright.async_api import async_playwright, Browser, Page
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    async_playwright = None
    Browser = None
    Page = None

from bs4 import BeautifulSoup

from .base import BaseSource, SourceInfo, Article, SourceType
from ..core.http_client import get_http_client
from ..core.exceptions import SourceError


@dataclass
class PageSnapshot:
    """Snapshot of page content for change detection."""
    url: str
    content_hash: str
    article_hashes: Set[str]
    extracted_items: List[Dict[str, Any]]
    timestamp: datetime
    selectors_used: List[str]


@dataclass 
class PageMonitorConfig:
    """Configuration for page monitoring."""
    url: str
    name: str
    
    # Content detection settings
    article_selectors: List[str] = None
    title_selectors: List[str] = None
    date_selectors: List[str] = None
    link_selectors: List[str] = None
    
    # Update frequency
    check_interval_minutes: int = 30
    
    # Content filtering
    min_title_length: int = 10
    max_articles_per_check: int = 20
    
    # Browser settings
    use_browser: bool = True
    wait_for_js: bool = True
    wait_timeout_ms: int = 30000
    
    # AI optimization
    enable_ai_analysis: bool = True
    reanalyze_after_failures: int = 5
    
    def __post_init__(self):
        if self.article_selectors is None:
            self.article_selectors = [
                # Common article/news item patterns
                'article', '.article', '.news-item', '.post', '.entry',
                '.changelog-item', '.update-item', '.release-note',
                
                # List items that might contain news
                '.content li', '.main li', 'ul.updates li', 'ul.news li',
                
                # Generic content containers
                '.content > div', '.main > div', '.updates > div',
                '[class*="item"]', '[class*="post"]', '[class*="article"]',
                
                # Headings that might indicate news items
                'h2, h3, h4', '.title', '.headline', '.heading'
            ]
        
        if self.title_selectors is None:
            self.title_selectors = [
                'h1', 'h2', 'h3', 'h4', '.title', '.headline', '.heading',
                'a[href]', '.link', '.post-title', '.article-title'
            ]
        
        if self.date_selectors is None:
            self.date_selectors = [
                # Standard HTML5 time elements
                'time', 'time[datetime]', '[datetime]',
                
                # Common date classes
                '.date', '.timestamp', '.published', '.created', '.updated',
                '.publish-date', '.published-date', '.creation-date', '.post-date',
                '.article-date', '.news-date', '.entry-date', '.blog-date',
                
                # Meta information
                '.meta .date', '.meta time', '.metadata .date', '.info .date',
                '.post-meta .date', '.article-meta .date', '.entry-meta .date',
                
                # GitHub/Changelog specific
                '.commit-date', '.release-date', '.version-date', '.update-date',
                '.changelog-date', '.timeline .date', 
                
                # Blog specific
                '.byline .date', '.author-date', '.publish-info .date',
                
                # Generic patterns
                '[class*="date"]', '[class*="time"]', '[class*="publish"]',
                '[id*="date"]', '[id*="time"]'
            ]
        
        if self.link_selectors is None:
            self.link_selectors = [
                'a[href]', '.link', '.read-more', '.permalink'
            ]


class PageMonitorSource(BaseSource):
    """Adaptive source for monitoring pages without RSS feeds."""
    
    def __init__(self, config: PageMonitorConfig):
        info = SourceInfo(
            name=config.name,
            source_type=SourceType.CUSTOM,
            url=config.url,
            description=f"Page monitor for {config.url}"
        )
        super().__init__(info)
        
        self.config = config
        self.browser: Optional[Browser] = None
        self.last_snapshot: Optional[PageSnapshot] = None
        self.failure_count = 0
        self.ai_analysis_count = 0
        
        # Dynamic selectors learned through AI analysis
        self.learned_selectors: Dict[str, float] = {}  # selector -> confidence
        
        # Content patterns for intelligent extraction
        self.content_patterns = {
            'changelog': [
                r'(?i)\b(version|v\d+|\d+\.\d+)',
                r'(?i)\b(released?|updated?|fixed?|added?|improved?)',
                r'(?i)\b(feature|bug|improvement|enhancement)'
            ],
            'news': [
                r'(?i)\b(breaking|urgent|announced?|launched?)',
                r'(?i)\b(today|yesterday|this week|latest)',
                r'(?i)\b(update|news|press|release)'
            ],
            'blog': [
                r'(?i)\b(posted|published|written|authored)',
                r'(?i)\b(tutorial|guide|how.?to|tips)',
                r'(?i)\b(learn|understand|master)'
            ]
        }
    
    async def __aenter__(self):
        """Initialize browser if needed."""
        if self.config.use_browser and not self.browser:
            playwright = await async_playwright().start()
            self.browser = await playwright.chromium.launch(
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-blink-features=AutomationControlled',
                    '--disable-web-security',
                    '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'
                ]
            )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Close browser."""
        if self.browser:
            await self.browser.close()
            self.browser = None
    
    async def fetch_articles(self) -> List[Article]:
        """Fetch new articles by monitoring page changes."""
        try:
            print(f"🔍 Monitoring page: {self.config.url}")
            
            # Get current page snapshot
            current_snapshot = await self._take_page_snapshot()
            
            if not current_snapshot:
                self.failure_count += 1
                print(f"❌ Failed to take snapshot (failures: {self.failure_count})")
                
                # Trigger AI analysis after repeated failures
                if (self.failure_count >= self.config.reanalyze_after_failures and 
                    self.config.enable_ai_analysis):
                    await self._trigger_ai_analysis()
                
                return []
            
            # Reset failure count on success
            self.failure_count = 0
            
            # Compare with last snapshot to find new content
            new_articles = []
            if self.last_snapshot:
                new_articles = await self._detect_new_content(
                    self.last_snapshot, current_snapshot
                )
            else:
                print("📸 First snapshot taken, treating all extracted items as new")
                # On first run, return all extracted items as new articles
                new_articles = await self._convert_extracted_to_articles(current_snapshot.extracted_items)
            
            # Update last snapshot
            self.last_snapshot = current_snapshot
            
            print(f"📊 Found {len(new_articles)} new articles")
            return new_articles
            
        except Exception as e:
            self.failure_count += 1
            print(f"❌ Error monitoring page: {e}")
            raise SourceError(f"Failed to monitor {self.config.url}: {e}")
    
    async def _take_page_snapshot(self) -> Optional[PageSnapshot]:
        """Take a snapshot of the current page state."""
        try:
            if self.config.use_browser:
                return await self._take_browser_snapshot()
            else:
                return await self._take_http_snapshot()
        except Exception as e:
            print(f"⚠️ Snapshot failed: {e}")
            return None
    
    async def _take_browser_snapshot(self) -> Optional[PageSnapshot]:
        """Take snapshot using browser rendering."""
        if not self.browser:
            await self.__aenter__()
        
        page = None
        try:
            page = await self.browser.new_page()
            
            # Set realistic headers
            await page.set_extra_http_headers({
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1'
            })
            
            # Navigate to page
            print(f"  🌐 Loading page: {self.config.url}")
            await page.goto(self.config.url, wait_until='networkidle', timeout=self.config.wait_timeout_ms)
            
            if self.config.wait_for_js:
                await page.wait_for_timeout(2000)  # Let JS finish
            
            # Get page content
            html = await page.content()
            
            # Extract articles using various selectors
            articles = await self._extract_articles_from_html(html, page)
            
            # Create content hash
            content_hash = hashlib.md5(html.encode()).hexdigest()
            article_hashes = {self._hash_article(article) for article in articles}
            
            return PageSnapshot(
                url=self.config.url,
                content_hash=content_hash,
                article_hashes=article_hashes,
                extracted_items=articles,
                timestamp=datetime.utcnow(),
                selectors_used=list(self.learned_selectors.keys()) or self.config.article_selectors[:5]
            )
            
        finally:
            if page:
                await page.close()
    
    async def _take_http_snapshot(self) -> Optional[PageSnapshot]:
        """Take snapshot using HTTP requests."""
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate',
            'DNT': '1',
            'Connection': 'keep-alive'
        }
        
        async with get_http_client() as client:
            response = await client.session.get(self.config.url, headers=headers)
            response.raise_for_status()
            html = await response.text()
        
        articles = await self._extract_articles_from_html(html)
        
        content_hash = hashlib.md5(html.encode()).hexdigest()
        article_hashes = {self._hash_article(article) for article in articles}
        
        return PageSnapshot(
            url=self.config.url,
            content_hash=content_hash,
            article_hashes=article_hashes,
            extracted_items=articles,
            timestamp=datetime.utcnow(),
            selectors_used=self.config.article_selectors[:5]
        )
    
    async def _extract_articles_from_html(self, html: str, page: Optional[Page] = None) -> List[Dict[str, Any]]:
        """Extract articles from HTML using intelligent selectors."""
        soup = BeautifulSoup(html, 'html.parser')
        articles = []
        
        # Try learned selectors first (if any)
        if self.learned_selectors:
            sorted_selectors = sorted(
                self.learned_selectors.items(), 
                key=lambda x: x[1], 
                reverse=True
            )
            for selector, confidence in sorted_selectors[:3]:
                if confidence > 0.7:
                    print(f"  🎯 Trying learned selector: {selector} (confidence: {confidence:.2f})")
                    articles.extend(await self._extract_with_selector(soup, selector, page))
                    if articles:
                        break
        
        # If no articles found, try configured selectors
        if not articles:
            for selector in self.config.article_selectors:
                print(f"  🔍 Trying selector: {selector}")
                new_articles = await self._extract_with_selector(soup, selector, page)
                articles.extend(new_articles)
                
                if len(articles) >= self.config.max_articles_per_check:
                    break
        
        # Filter and enhance articles
        articles = await self._filter_and_enhance_articles(articles)
        
        print(f"  📋 Extracted {len(articles)} potential articles")
        return articles[:self.config.max_articles_per_check]
    
    async def _extract_with_selector(self, soup: BeautifulSoup, selector: str, page: Optional[Page] = None) -> List[Dict[str, Any]]:
        """Extract articles using a specific selector."""
        articles = []
        
        try:
            elements = soup.select(selector)
            
            for element in elements:
                article = await self._extract_article_from_element(element, soup)
                if article:
                    articles.append(article)
                    
        except Exception as e:
            print(f"    ❌ Selector '{selector}' failed: {e}")
        
        return articles
    
    async def _extract_article_from_element(self, element, soup: BeautifulSoup) -> Optional[Dict[str, Any]]:
        """Extract article data from a DOM element."""
        article = {}
        
        # Extract title
        title = await self._extract_title(element)
        if not title or len(title) < self.config.min_title_length:
            return None
        
        article['title'] = title
        
        # Extract link
        link = await self._extract_link(element)
        if link:
            article['link'] = urljoin(self.config.url, link)
        else:
            article['link'] = self.config.url  # Fallback to main page
        
        # Extract date
        date = await self._extract_date(element)
        article['published'] = date or datetime.utcnow()
        
        # Extract content/description
        content = await self._extract_content(element)
        article['description'] = content
        
        # Extract additional metadata
        article['source'] = self.config.name
        article['source_url'] = self.config.url
        
        # Content classification
        article['content_type'] = await self._classify_content(title, content)
        
        return article
    
    async def _extract_title(self, element) -> Optional[str]:
        """Extract title from element."""
        # Try title selectors
        for selector in self.config.title_selectors:
            try:
                title_elem = element.select_one(selector)
                if title_elem:
                    title = title_elem.get_text(strip=True)
                    if title:
                        return title
            except:
                continue
        
        # Fallback to element text
        text = element.get_text(strip=True)
        if text:
            # Take first line/sentence as title
            lines = text.split('\n')
            for line in lines:
                line = line.strip()
                if len(line) >= self.config.min_title_length:
                    return line[:200]  # Limit title length
        
        return None
    
    async def _extract_link(self, element) -> Optional[str]:
        """Extract link from element."""
        # Try to find link in element or parent
        link_elem = element.find('a', href=True)
        if not link_elem:
            # Check if element itself is a link
            if element.name == 'a' and element.get('href'):
                link_elem = element
            else:
                # Check parent elements
                parent = element.parent
                while parent and parent.name != 'html':
                    if parent.name == 'a' and parent.get('href'):
                        link_elem = parent
                        break
                    parent = parent.parent
        
        if link_elem:
            href = link_elem.get('href')
            if href and not href.startswith('#'):
                return href
        
        return None
    
    async def _extract_date(self, element) -> Optional[datetime]:
        """Extract date from element."""
        for selector in self.config.date_selectors:
            try:
                date_elem = element.select_one(selector)
                if date_elem:
                    # Try datetime attribute first
                    datetime_attr = date_elem.get('datetime')
                    if datetime_attr:
                        parsed_date = self._parse_datetime(datetime_attr)
                        if parsed_date:
                            return parsed_date
                    
                    # Try text content
                    date_text = date_elem.get_text(strip=True)
                    if date_text:
                        parsed_date = self._parse_datetime(date_text)
                        if parsed_date:
                            return parsed_date
            except Exception as e:
                continue
        
        # If no date found, fallback to checking element's own text for date patterns
        element_text = element.get_text(strip=True)[:300]  # First 300 chars
        if element_text:
            # Look for date patterns in the text with improved regex
            import re
            date_patterns = [
                # Standard formats with word boundaries
                r'\b(\d{4})-(\d{2})-(\d{2})\b',  # 2025-07-31
                r'\b(\w+)\s+(\d{1,2}),?\s+(\d{4})\b',  # July 31, 2025
                r'\b(\d{1,2})\s+(\w+)\s+(\d{4})\b',  # 31 July 2025
                
                # More flexible patterns for embedded dates (like in Cursor changelog)
                r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})',  # July 29, 2025
                r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2}),?\s+(\d{4})',  # Jul 29, 2025  
                r'(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})',  # 29 July 2025
                r'(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{4})',  # 29 Jul 2025
                
                # Numeric formats
                r'(\d{1,2})/(\d{1,2})/(\d{4})',  # 7/29/2025
                r'(\d{1,2})-(\d{1,2})-(\d{4})',  # 7-29-2025
                r'(\d{4})/(\d{1,2})/(\d{1,2})',  # 2025/7/29
            ]
            
            for pattern in date_patterns:
                match = re.search(pattern, element_text, re.IGNORECASE)
                if match:
                    # Reconstruct full match text for complex patterns
                    if len(match.groups()) == 3:
                        # Pattern with groups - reconstruct full date string
                        groups = match.groups()
                        if pattern.startswith(r'(January|February'):  # Month Day, Year
                            date_candidate = f"{groups[0]} {groups[1]}, {groups[2]}"
                        elif pattern.startswith(r'(Jan|Feb'):  # Abbreviated month
                            date_candidate = f"{groups[0]} {groups[1]}, {groups[2]}"
                        elif 'January|February' in pattern and pattern.endswith(r')'):  # Day Month Year
                            date_candidate = f"{groups[0]} {groups[1]} {groups[2]}"
                        elif 'Jan|Feb' in pattern and pattern.endswith(r')'):  # Day abbreviated month Year
                            date_candidate = f"{groups[0]} {groups[1]} {groups[2]}"
                        else:
                            date_candidate = match.group(0)
                    else:
                        date_candidate = match.group(0)
                    
                    parsed_date = self._parse_datetime(date_candidate)
                    if parsed_date:
                        return parsed_date
        
        return None
    
    def _parse_datetime(self, date_str: str) -> Optional[datetime]:
        """Parse datetime from string."""
        if not date_str:
            return None
            
        date_str = date_str.strip()
        
        # Extended datetime patterns for various sites
        patterns = [
            # ISO formats
            '%Y-%m-%d',
            '%Y-%m-%dT%H:%M:%S',
            '%Y-%m-%dT%H:%M:%SZ',
            '%Y-%m-%dT%H:%M:%S.%fZ',
            '%Y-%m-%d %H:%M:%S',
            '%Y/%m/%d',
            '%Y/%m/%d %H:%M:%S',
            
            # US formats
            '%B %d, %Y',
            '%b %d, %Y',
            '%m/%d/%Y',
            '%m-%d-%Y',
            
            # European formats
            '%d %B %Y',
            '%d %b %Y',
            '%d/%m/%Y',
            '%d.%m.%Y',
            '%d-%m-%Y',
            
            # Relative formats (handle common ones)
            '%Y-%m-%d %H:%M',
            '%d.%m.%Y %H:%M',
            
            # Changelog specific
            '%B %Y',  # "July 2025"
            '%Y-%m',   # "2025-07"
        ]
        
        # Try parsing with each pattern
        for pattern in patterns:
            try:
                parsed_date = datetime.strptime(date_str, pattern)
                
                # If only month/year provided, set to first day
                if pattern in ['%B %Y', '%Y-%m']:
                    parsed_date = parsed_date.replace(day=1)
                
                # Don't accept dates too far in the future (more than 1 day)
                if parsed_date > datetime.utcnow() + timedelta(days=1):
                    continue
                    
                # Don't accept dates older than 2 years
                if parsed_date < datetime.utcnow() - timedelta(days=730):
                    continue
                    
                return parsed_date
                
            except ValueError:
                continue
        
        # Try parsing relative dates like "2 days ago", "yesterday"
        parsed_relative = self._parse_relative_date(date_str)
        if parsed_relative:
            return parsed_relative
        
        return None
    
    def _parse_relative_date(self, date_str: str) -> Optional[datetime]:
        """Parse relative dates like '2 days ago', 'yesterday', etc."""
        import re
        
        date_str = date_str.lower().strip()
        now = datetime.utcnow()
        
        # Handle "X days ago", "X hours ago", etc.
        relative_pattern = r'(\d+)\s+(second|minute|hour|day|week|month|year)s?\s+ago'
        match = re.search(relative_pattern, date_str)
        if match:
            number = int(match.group(1))
            unit = match.group(2)
            
            if unit == 'second':
                return now - timedelta(seconds=number)
            elif unit == 'minute':
                return now - timedelta(minutes=number)
            elif unit == 'hour':
                return now - timedelta(hours=number)
            elif unit == 'day':
                return now - timedelta(days=number)
            elif unit == 'week':
                return now - timedelta(weeks=number)
            elif unit == 'month':
                return now - timedelta(days=number * 30)  # Approximate
            elif unit == 'year':
                return now - timedelta(days=number * 365)  # Approximate
        
        # Handle common words
        if 'yesterday' in date_str:
            return now - timedelta(days=1)
        elif 'today' in date_str or 'just now' in date_str:
            return now
        elif 'last week' in date_str:
            return now - timedelta(weeks=1)
        elif 'last month' in date_str:
            return now - timedelta(days=30)
        
        return None
    
    async def _extract_content(self, element) -> str:
        """Extract content/description from element."""
        # Get text content, but clean it up
        text = element.get_text(separator=' ', strip=True)
        
        # Remove excessive whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        
        # Limit length
        if len(text) > 500:
            text = text[:500] + '...'
        
        return text
    
    async def _classify_content(self, title: str, content: str) -> str:
        """Classify content type based on patterns."""
        text = f"{title} {content}".lower()
        
        for content_type, patterns in self.content_patterns.items():
            matches = sum(1 for pattern in patterns if re.search(pattern, text))
            if matches >= 2:  # Need at least 2 pattern matches
                return content_type
        
        return 'general'
    
    async def _filter_and_enhance_articles(self, articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Filter and enhance extracted articles."""
        filtered = []
        seen_titles = set()
        
        for article in articles:
            title = article.get('title', '').strip()
            
            # Skip if no title or too short
            if not title or len(title) < self.config.min_title_length:
                continue
            
            # Skip duplicates
            title_lower = title.lower()
            if title_lower in seen_titles:
                continue
            seen_titles.add(title_lower)
            
            # Enhance article
            article['id'] = hashlib.md5(f"{title}{article.get('link', '')}".encode()).hexdigest()
            
            filtered.append(article)
        
        return filtered
    
    async def _detect_new_content(self, old_snapshot: PageSnapshot, new_snapshot: PageSnapshot) -> List[Article]:
        """Detect new content by comparing snapshots."""
        new_articles = []
        
        # Find articles with new hashes
        new_hashes = new_snapshot.article_hashes - old_snapshot.article_hashes
        
        for article_data in new_snapshot.extracted_items:
            article_hash = self._hash_article(article_data)
            
            if article_hash in new_hashes:
                # Convert to Article object
                article = Article(
                    title=article_data.get('title', ''),
                    url=article_data.get('link', ''),
                    content=article_data.get('description', ''),
                    published_at=article_data.get('published', datetime.utcnow()),
                    source_name=self.config.name
                )
                new_articles.append(article)
        
        return new_articles
    
    async def _convert_extracted_to_articles(self, extracted_items: List[Dict[str, Any]]) -> List[Article]:
        """Convert extracted items to Article objects (for first run)."""
        articles = []
        
        for article_data in extracted_items:
            # Convert to Article object
            article = Article(
                title=article_data.get('title', ''),
                url=article_data.get('link', ''),
                content=article_data.get('description', ''),
                published_at=article_data.get('published', datetime.utcnow()),
                source_name=self.config.name
            )
            articles.append(article)
        
        return articles
    
    def _hash_article(self, article_data: Dict[str, Any]) -> str:
        """Create hash for article to detect changes."""
        key_data = {
            'title': article_data.get('title', ''),
            'link': article_data.get('link', ''),
            'description': article_data.get('description', '')[:100]  # First 100 chars
        }
        return hashlib.md5(json.dumps(key_data, sort_keys=True).encode()).hexdigest()
    
    async def _trigger_ai_analysis(self):
        """Trigger AI analysis to improve selectors."""
        try:
            print(f"🤖 Triggering AI analysis for {self.config.url}")
            
            # This would integrate with the AI extraction optimizer
            # For now, we'll implement a simple heuristic improvement
            
            self.ai_analysis_count += 1
            
            # Add some smart selectors based on domain analysis
            domain = urlparse(self.config.url).netloc.lower()
            
            if 'changelog' in self.config.url.lower() or 'changelog' in domain:
                self.learned_selectors.update({
                    '.changelog-entry': 0.9,
                    '.release-note': 0.8,
                    '.version-info': 0.8,
                    'li[data-version]': 0.7,
                    '.update-item': 0.7
                })
            
            if 'blog' in domain or 'news' in domain:
                self.learned_selectors.update({
                    '.post-item': 0.9,
                    '.news-item': 0.9,
                    'article.post': 0.8,
                    '.blog-entry': 0.8
                })
            
            print(f"  🎯 Added {len(self.learned_selectors)} learned selectors")
            
        except Exception as e:
            print(f"  ❌ AI analysis failed: {e}")
    
    async def test_connection(self) -> bool:
        """Test if the page can be accessed."""
        try:
            print(f"🔗 Testing connection to {self.config.url}")
            
            if self.config.use_browser:
                # Test with browser
                if not self.browser:
                    await self.__aenter__()
                
                page = await self.browser.new_page()
                try:
                    await page.goto(self.config.url, wait_until='networkidle', timeout=30000)
                    print("✅ Browser connection successful")
                    return True
                except Exception as e:
                    print(f"❌ Browser connection failed: {e}")
                    return False
                finally:
                    await page.close()
            else:
                # Test with HTTP
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'
                }
                
                async with get_http_client() as client:
                    response = await client.session.get(self.config.url, headers=headers)
                    response.raise_for_status()
                    print("✅ HTTP connection successful")
                    return True
                    
        except Exception as e:
            print(f"❌ Connection test failed: {e}")
            return False


async def create_page_monitor_source(url: str, name: str, **config_kwargs) -> PageMonitorSource:
    """Create and configure a page monitor source."""
    config = PageMonitorConfig(
        url=url,
        name=name,
        **config_kwargs
    )
    
    return PageMonitorSource(config)