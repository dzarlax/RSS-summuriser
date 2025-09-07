"""Metadata extraction from web content."""

import json
from typing import Optional, List
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from .extraction_utils import ExtractionUtils


class MetadataExtractor:
    """Extract metadata and structured data from web content."""
    
    def __init__(self, utils: ExtractionUtils):
        self.utils = utils
    
    def extract_from_json_ld(self, soup: BeautifulSoup) -> Optional[str]:
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
                        # Try various content fields
                        content_fields = ['articleBody', 'text', 'description']
                        for field in content_fields:
                            content = item.get(field)
                            if content and isinstance(content, str) and len(content) > self.utils.min_content_length:
                                return content
                
            except Exception as e:
                continue
        
        return None
    
    def extract_from_open_graph(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract content from Open Graph meta tags."""
        og_description = soup.find('meta', property='og:description')
        if og_description and og_description.get('content'):
            content = og_description['content']
            if len(content) > self.utils.min_content_length:
                return content
        
        # Also try standard meta description
        meta_description = soup.find('meta', attrs={'name': 'description'})
        if meta_description and meta_description.get('content'):
            content = meta_description['content']
            if len(content) > self.utils.min_content_length:
                return content
        
        return None
    
    def find_alt_article_links(self, soup: BeautifulSoup, base_url: str) -> List[str]:
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
            # AMP version link
            amp_link = soup.find('link', rel=lambda v: v and 'amphtml' in v)
            if amp_link and amp_link.get('href'):
                alt_urls.append(urljoin(base_url, amp_link['href']))
        except Exception:
            pass
        try:
            # Look for obvious "read more" or "full article" links
            for link in soup.find_all('a', href=True):
                text = link.get_text(strip=True).lower()
                if any(phrase in text for phrase in [
                    'read more', 'full article', 'continue reading', 
                    'read full', 'view full', 'more details'
                ]):
                    full_url = urljoin(base_url, link['href'])
                    if full_url not in alt_urls:
                        alt_urls.append(full_url)
        except Exception:
            pass
        
        return alt_urls
    
    def extract_meta_title(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract page title from various sources."""
        # Try Open Graph title first
        og_title = soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return og_title['content'].strip()
        
        # Try Twitter card title
        twitter_title = soup.find('meta', attrs={'name': 'twitter:title'})
        if twitter_title and twitter_title.get('content'):
            return twitter_title['content'].strip()
        
        # Try standard HTML title
        title_tag = soup.find('title')
        if title_tag and title_tag.get_text():
            return title_tag.get_text().strip()
        
        # Try h1 as fallback
        h1 = soup.find('h1')
        if h1 and h1.get_text():
            return h1.get_text().strip()
        
        return None
    
    def extract_meta_description(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract meta description from various sources."""
        # Try Open Graph description first
        og_desc = soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return og_desc['content'].strip()
        
        # Try Twitter card description
        twitter_desc = soup.find('meta', attrs={'name': 'twitter:description'})
        if twitter_desc and twitter_desc.get('content'):
            return twitter_desc['content'].strip()
        
        # Try standard meta description
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return meta_desc['content'].strip()
        
        return None
    
    def extract_author_info(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract author information from various sources."""
        # Try schema.org microdata
        author_selectors = [
            '[itemprop="author"]',
            '[rel="author"]',
            '.author',
            '.byline',
            '.author-name',
            '.writer',
            '.journalist'
        ]
        
        for selector in author_selectors:
            elements = soup.select(selector)
            for element in elements:
                author_text = element.get_text(strip=True)
                if author_text and len(author_text) < 100:  # Reasonable author name length
                    return author_text
        
        # Try meta tags
        author_meta = soup.find('meta', attrs={'name': 'author'})
        if author_meta and author_meta.get('content'):
            return author_meta['content'].strip()
        
        return None

