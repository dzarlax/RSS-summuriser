"""Content extraction from web articles."""

import re
from typing import Optional
from bs4 import BeautifulSoup, Comment

from ..core.http_client import get_http_client
from ..core.cache import cached


class ContentExtractor:
    """Extract main content from web articles."""
    
    def __init__(self):
        self.max_content_length = 8000  # Characters limit for AI
    
    @cached(ttl=86400, key_prefix="article_content")
    async def extract_article_content(self, url: str) -> Optional[str]:
        """
        Extract main article content from URL.
        
        Args:
            url: Article URL
            
        Returns:
            Clean article text or None if failed
        """
        if not url:
            return None
            
        try:
            # Add headers to avoid bot detection
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1'
            }
            
            async with get_http_client() as client:
                html = await client.fetch_text(url, headers=headers)
            
            if not html:
                return None
                
            # Parse HTML
            soup = BeautifulSoup(html, 'html.parser')
            
            # Remove unwanted elements
            self._remove_unwanted_elements(soup)
            
            # Try different content extraction strategies
            content = (
                self._extract_by_common_selectors(soup) or
                self._extract_by_article_tag(soup) or
                self._extract_by_content_heuristics(soup)
            )
            
            if content:
                # Clean and limit content
                content = self._clean_text(content)
                if len(content) > self.max_content_length:
                    content = content[:self.max_content_length] + "..."
                return content
                
            return None
            
        except Exception as e:
            print(f"  ⚠️ Error extracting content from {url}: {e}")
            return None
    
    def _remove_unwanted_elements(self, soup: BeautifulSoup) -> None:
        """Remove unwanted HTML elements."""
        unwanted_tags = [
            'script', 'style', 'nav', 'header', 'footer', 'aside',
            'noscript', 'iframe', 'embed', 'object', 'form'
        ]
        
        unwanted_classes = [
            'advertisement', 'ads', 'sidebar', 'menu', 'navigation',
            'comments', 'social', 'share', 'related', 'recommended'
        ]
        
        # Remove unwanted tags
        for tag in unwanted_tags:
            for element in soup.find_all(tag):
                element.decompose()
        
        # Remove elements with unwanted classes
        for class_name in unwanted_classes:
            for element in soup.find_all(class_=re.compile(class_name, re.I)):
                element.decompose()
        
        # Remove comments
        for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
            comment.extract()
    
    def _extract_by_common_selectors(self, soup: BeautifulSoup) -> Optional[str]:
        """Try common article selectors."""
        selectors = [
            'article',
            '[role="main"]',
            '.post-content',
            '.article-content',
            '.entry-content',
            '.content',
            '.post-body',
            '.story-body',
            '.article-body'
        ]
        
        for selector in selectors:
            elements = soup.select(selector)
            if elements:
                # Take the first matching element
                return elements[0].get_text(separator='\n', strip=True)
        
        return None
    
    def _extract_by_article_tag(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract using HTML5 article tag."""
        article = soup.find('article')
        if article:
            return article.get_text(separator='\n', strip=True)
        return None
    
    def _extract_by_content_heuristics(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract using content heuristics (paragraph count, text length)."""
        # Find all paragraph containers
        candidates = []
        
        # Check divs and sections with many paragraphs
        for container in soup.find_all(['div', 'section']):
            paragraphs = container.find_all('p')
            if len(paragraphs) >= 3:  # At least 3 paragraphs
                text = container.get_text(separator='\n', strip=True)
                if len(text) > 500:  # At least 500 characters
                    candidates.append((len(text), text))
        
        # Return the longest candidate
        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            return candidates[0][1]
        
        # Fallback: get all paragraphs from body
        body = soup.find('body')
        if body:
            paragraphs = body.find_all('p')
            if paragraphs:
                text_parts = []
                for p in paragraphs:
                    text = p.get_text(separator=' ', strip=True)
                    if len(text) > 50:  # Skip short paragraphs
                        text_parts.append(text)
                
                if text_parts:
                    return '\n\n'.join(text_parts)
        
        return None
    
    def _clean_text(self, text: str) -> str:
        """Clean extracted text."""
        if not text:
            return ""
        
        # Remove excessive whitespace
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'\n\s*\n', '\n\n', text)
        
        # Remove common unwanted patterns
        patterns = [
            r'Subscribe to.*?newsletter',
            r'Follow us on.*?social media',
            r'Share this article',
            r'Related articles?:?',
            r'Advertisement',
            r'Cookie policy',
        ]
        
        for pattern in patterns:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)
        
        return text.strip()