"""Custom parsers for specific domains with enhanced metadata extraction."""

import re
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
from datetime import datetime
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from .extraction_memory import get_extraction_memory
import dateutil.parser


class BaseCustomParser(ABC):
    """Base class for custom domain-specific parsers."""
    
    def __init__(self, domain: str):
        self.domain = domain
    
    @abstractmethod
    def can_parse(self, url: str) -> bool:
        """Check if this parser can handle the given URL."""
        pass
    
    @abstractmethod
    def extract_content(self, soup: BeautifulSoup, url: str) -> Optional[str]:
        """Extract main article content from BeautifulSoup object."""
        pass
    
    @abstractmethod
    def extract_publication_date(self, soup: BeautifulSoup, url: str) -> Optional[str]:
        """Extract publication date from BeautifulSoup object."""
        pass
    
    def extract_metadata(self, soup: BeautifulSoup, url: str) -> Dict[str, Any]:
        """Extract all metadata including content and publication date."""
        return {
            'content': self.extract_content(soup, url),
            'publication_date': self.extract_publication_date(soup, url),
            'parser_used': self.__class__.__name__
        }
    
    def _clean_text(self, text: str) -> str:
        """Clean extracted text."""
        if not text:
            return ""
        
        # Remove extra whitespace
        text = re.sub(r'\s+', ' ', text)
        text = text.strip()
        
        # Remove common artifacts
        text = re.sub(r'\n+', '\n', text)
        text = re.sub(r'[\r\t]+', ' ', text)
        
        return text


class BalkanInsightParser(BaseCustomParser):
    """Custom parser for balkaninsight.com."""
    
    def can_parse(self, url: str) -> bool:
        """Check if URL is from Balkan Insight."""
        return 'balkaninsight.com' in url.lower()
    
    def extract_content(self, soup: BeautifulSoup, url: str) -> Optional[str]:
        """Extract content from Balkan Insight articles."""
        # Try multiple selectors specific to Balkan Insight
        # BI часто использует WordPress-подобные структуры и блоки Gutenberg
        content_selectors = [
            'article .entry-content',
            'article .post-content',
            'article .article-content',
            '.single-post .entry-content',
            '.content-area article .entry-content',
            'div[class*="content"] p',
            '.post-body',
            'article .post-body',
        ]
        
        for selector in content_selectors:
            elements = soup.select(selector)
            if elements:
                # Get text from all matching elements
                content_parts = []
                for elem in elements:
                    text = elem.get_text(separator='\n', strip=True)
                    if text and len(text) > 50:  # Only substantial content
                        content_parts.append(text)
                
                if content_parts:
                    content = '\n\n'.join(content_parts)
                    return self._clean_text(content)
        
        # Fallback: combine paragraphs inside article if present
        article = soup.select_one('article')
        if article:
            paragraphs = [p.get_text(separator=' ', strip=True) for p in article.find_all('p')]
            paragraphs = [p for p in paragraphs if len(p) > 50]
            if paragraphs:
                return self._clean_text('\n\n'.join(paragraphs))
        
        return None
    
    def extract_publication_date(self, soup: BeautifulSoup, url: str) -> Optional[str]:
        """Extract publication date from Balkan Insight."""
        # Balkan Insight specific date selectors
        date_selectors = [
            '.post-meta time',
            '.entry-date',
            '.published',
            'time[datetime]',
            '.date-published'
        ]
        
        for selector in date_selectors:
            elements = soup.select(selector)
            for element in elements:
                # Try datetime attribute first
                date_str = element.get('datetime') or element.get('content')
                
                # If no datetime attribute, get text
                if not date_str:
                    date_str = element.get_text(strip=True)
                
                if date_str and self._is_valid_date(date_str):
                    return date_str
        
        # Try JSON-LD datePublished
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                import json
                data = json.loads(script.string or '{}')
                items = data if isinstance(data, list) else [data]
                if isinstance(data, dict) and '@graph' in data:
                    items = data['@graph']
                for item in items:
                    if isinstance(item, dict):
                        dt = item.get('datePublished') or item.get('dateCreated') or item.get('dateModified')
                        if dt and self._is_valid_date(dt):
                            return dt
            except Exception:
                continue

        # Try meta tags
        meta_selectors = [
            'meta[property="article:published_time"]',
            'meta[name="publishdate"]',
            'meta[name="pubdate"]'
        ]
        
        for selector in meta_selectors:
            meta = soup.select_one(selector)
            if meta:
                date_str = meta.get('content')
                if date_str and self._is_valid_date(date_str):
                    return date_str
        
        return None
    
    def _is_valid_date(self, date_str: str) -> bool:
        """Check if string is a valid date."""
        try:
            dateutil.parser.parse(date_str)
            return True
        except:
            return False


class RTSParser(BaseCustomParser):
    """Custom parser for rts.rs (Radio Television of Serbia)."""
    
    def can_parse(self, url: str) -> bool:
        """Check if URL is from RTS."""
        return 'rts.rs' in url.lower()
    
    def extract_content(self, soup: BeautifulSoup, url: str) -> Optional[str]:
        """Extract content from RTS articles."""
        content_selectors = [
            '.article-text',
            '.content-text', 
            '.news-content',
            '.article-body',
            'div[class*="text"] p'
        ]
        
        for selector in content_selectors:
            elements = soup.select(selector)
            if elements:
                content_parts = []
                for elem in elements:
                    text = elem.get_text(separator='\n', strip=True)
                    if text and len(text) > 30:
                        content_parts.append(text)
                
                if content_parts:
                    return self._clean_text('\n\n'.join(content_parts))
        
        return None
    
    def extract_publication_date(self, soup: BeautifulSoup, url: str) -> Optional[str]:
        """Extract publication date from RTS."""
        # RTS specific patterns
        date_selectors = [
            '.article-date',
            '.news-date',
            '.date-time',
            'time',
            '.published-date'
        ]
        
        for selector in date_selectors:
            elements = soup.select(selector)
            for element in elements:
                date_str = element.get('datetime') or element.get_text(strip=True)
                if date_str and self._is_valid_date(date_str):
                    return date_str
        
        return None
    
    def _is_valid_date(self, date_str: str) -> bool:
        """Check if string is a valid date."""
        try:
            dateutil.parser.parse(date_str)
            return True
        except:
            return False


class B92Parser(BaseCustomParser):
    """Custom parser for b92.net."""
    
    def can_parse(self, url: str) -> bool:
        """Check if URL is from B92."""
        return 'b92.net' in url.lower()
    
    def extract_content(self, soup: BeautifulSoup, url: str) -> Optional[str]:
        """Extract content from B92 articles."""
        content_selectors = [
            '.article-content',
            '.news-text',
            '.content-body',
            'div[class*="content"] p',
            '.article-text'
        ]
        
        for selector in content_selectors:
            elements = soup.select(selector)
            if elements:
                content_parts = []
                for elem in elements:
                    text = elem.get_text(separator='\n', strip=True)
                    if text and len(text) > 30:
                        content_parts.append(text)
                
                if content_parts:
                    return self._clean_text('\n\n'.join(content_parts))
        
        return None
    
    def extract_publication_date(self, soup: BeautifulSoup, url: str) -> Optional[str]:
        """Extract publication date from B92."""
        date_selectors = [
            '.article-info time',
            '.date-published',
            '.news-date',
            'time[datetime]'
        ]
        
        for selector in date_selectors:
            elements = soup.select(selector)
            for element in elements:
                date_str = element.get('datetime') or element.get_text(strip=True)
                if date_str and self._is_valid_date(date_str):
                    return date_str
        
        return None
    
    def _is_valid_date(self, date_str: str) -> bool:
        """Check if string is a valid date."""
        try:
            dateutil.parser.parse(date_str)
            return True
        except:
            return False


class CustomParserManager:
    """Manager for custom domain-specific parsers."""
    
    def __init__(self):
        self.parsers = [
            BalkanInsightParser('balkaninsight.com'),
            RTSParser('rts.rs'),
            B92Parser('b92.net')
        ]
        self._dynamic_cache: Dict[str, BaseCustomParser] = {}
    
    def get_parser_for_url(self, url: str) -> Optional[BaseCustomParser]:
        """Get appropriate parser for the given URL."""
        for parser in self.parsers:
            if parser.can_parse(url):
                return parser
        return None
    
    def can_parse(self, url: str) -> bool:
        """Check if any parser can handle the URL."""
        return self.get_parser_for_url(url) is not None
    
    def extract_metadata(self, html_content: str, url: str) -> Dict[str, Any]:
        """Extract metadata using appropriate custom parser."""
        parser = self.get_parser_for_url(url)
        if not parser:
            return {'content': None, 'publication_date': None}
        
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            result = parser.extract_metadata(soup, url)
            print(f"  🎯 Custom parser {parser.__class__.__name__} extracted metadata")
            return result
        except Exception as e:
            print(f"  ⚠️ Custom parser error for {url}: {e}")
            return {'content': None, 'publication_date': None}

    async def get_dynamic_parser_for_url(self, url: str) -> Optional[BaseCustomParser]:
        """Build a dynamic parser for the domain from learned patterns in memory."""
        try:
            domain = urlparse(url).netloc.lower()
        except Exception:
            return None
        
        # Return cached dynamic parser if exists
        if domain in self._dynamic_cache:
            return self._dynamic_cache[domain]
        
        try:
            memory = await get_extraction_memory()
            patterns = await memory.get_best_patterns_for_domain(domain, limit=5)
            selectors: List[str] = []
            for p in patterns:
                if p.extraction_strategy in ("css_selectors", "html_parsing", "heuristics") and p.selector_pattern:
                    selectors.append(p.selector_pattern)
            # Minimal threshold: need at least one selector
            if not selectors:
                return None
            parser = _DynamicDomainParser(domain=domain, content_selectors=selectors)
            self._dynamic_cache[domain] = parser
            return parser
        except Exception:
            return None


class _DynamicDomainParser(BaseCustomParser):
    """Dynamic domain parser built from learned selector patterns."""
    
    def __init__(self, domain: str, content_selectors: List[str]):
        super().__init__(domain)
        self._content_selectors = content_selectors
        # Generic date selectors; will be extended with learned ones per domain
        self._date_selectors = [
            '[itemprop="datePublished"]', 'meta[property="article:published_time"]',
            'time[datetime]', '.published-date', '.entry-date', '.post-date', '.article-date',
        ]
        self._learned_date_selectors: List[str] = []
    
    def can_parse(self, url: str) -> bool:
        try:
            return self.domain in urlparse(url).netloc.lower()
        except Exception:
            return False
    
    def extract_content(self, soup: BeautifulSoup, url: str) -> Optional[str]:
        for selector in self._content_selectors[:5]:
            try:
                elements = soup.select(selector)
                if elements:
                    parts = []
                    for elem in elements:
                        text = elem.get_text(separator='\n', strip=True)
                        if text and len(text) > 50:
                            parts.append(text)
                    if parts:
                        return self._clean_text('\n\n'.join(parts))
            except Exception:
                continue
        return None
    
    def extract_publication_date(self, soup: BeautifulSoup, url: str) -> Optional[str]:
        # Try learned selectors first (higher priority)
        for selector in self._learned_date_selectors + self._date_selectors:
            try:
                for el in soup.select(selector):
                    val = el.get('datetime') or el.get('content') or el.get_text(strip=True)
                    if val and self._is_valid_date(val):
                        # Positive feedback for date selector
                        try:
                            import asyncio
                            asyncio.create_task(self._record_date_selector_feedback(url, selector, success=True))
                        except Exception:
                            pass
                        return val
            except Exception:
                continue
        # Fallback to JSON-LD within page
        try:
            import json
            for script in soup.find_all('script', type='application/ld+json'):
                data = json.loads(script.string or '{}')
                items = data if isinstance(data, list) else [data]
                if isinstance(data, dict) and '@graph' in data:
                    items = data['@graph']
                for item in items:
                    if isinstance(item, dict):
                        dt = item.get('datePublished') or item.get('dateCreated') or item.get('dateModified')
                        if dt and self._is_valid_date(dt):
                            return dt
        except Exception:
            pass
        # Negative feedback: we could not find a date
        try:
            import asyncio
            for sel in self._learned_date_selectors:
                asyncio.create_task(self._record_date_selector_feedback(url, sel, success=False))
        except Exception:
            pass
        return None

    async def load_learned_date_selectors(self):
        """Load best learned date selectors for this domain from memory."""
        try:
            memory = await get_extraction_memory()
            patterns = await memory.get_best_date_selectors_for_domain(self.domain, limit=5)
            self._learned_date_selectors = [p.selector_pattern for p in patterns]
        except Exception:
            self._learned_date_selectors = []

    async def _record_date_selector_feedback(self, url: str, selector: str, success: bool) -> None:
        try:
            from urllib.parse import urlparse
            domain = urlparse(url).netloc.lower()
            memory = await get_extraction_memory()
            if success:
                await memory.record_date_selector_success(domain, selector)
            else:
                await memory.record_date_selector_failure(domain, selector)
        except Exception:
            pass


# Global instance
_custom_parser_manager = None


async def get_custom_parser_manager() -> CustomParserManager:
    """Get global custom parser manager instance."""
    global _custom_parser_manager
    if _custom_parser_manager is None:
        _custom_parser_manager = CustomParserManager()
    return _custom_parser_manager


# Dynamic manager accessor (alias for clarity)
get_dynamic_parser_manager = get_custom_parser_manager