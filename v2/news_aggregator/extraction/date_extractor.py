"""Date extraction and normalization for content extraction."""

import json
import re
from typing import Optional
from bs4 import BeautifulSoup
import dateutil.parser

from .extraction_utils import ExtractionUtils


class DateExtractor:
    """Extract and normalize publication dates from web content."""
    
    def __init__(self, utils: ExtractionUtils):
        self.utils = utils
    
    def extract_publication_date(self, soup: BeautifulSoup) -> tuple[Optional[str], Optional[str]]:
        """
        Extract publication date from HTML using multiple strategies.
        
        Returns:
            Tuple of (normalized_date, successful_selector)
        """
        try:
            # Strategy 1: JSON-LD structured data
            json_date, json_selector = self._extract_date_from_json_ld(soup)
            if json_date:
                return json_date, json_selector
            
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
                '.date-time', '.datetime', '.timestamp',
                '.entry-date', '.post-date', '.news-date',
                
                # Time elements
                'time[datetime]',
                'time[pubdate]',
                'time',
                
                # Common tag structures
                '.byline .date', '.meta .date', '.info .date',
                'header .date', '.article-header .date',
                '.article-meta time', '.entry-meta time'
            ]
            
            for selector in date_selectors:
                elements = soup.select(selector)
                for element in elements:
                    # Get date from various attributes
                    date_value = (
                        element.get('datetime') or 
                        element.get('content') or 
                        element.get('value') or
                        element.get_text(strip=True)
                    )
                    
                    if date_value and self._is_valid_date_string(date_value):
                        normalized_date = self.normalize_date(date_value)
                        if normalized_date:
                            return normalized_date, selector
            
            # Strategy 3: Text pattern matching
            text_content = soup.get_text()
            date_patterns = [
                # Various text-based date patterns
                (r'Published:?\s*([A-Za-z]+\s+\d{1,2},?\s+\d{4})', 'text_pattern_published'),
                (r'Date:?\s*([A-Za-z]+\s+\d{1,2},?\s+\d{4})', 'text_pattern_date'),
                (r'(\d{1,2}\s+[A-Za-z]+\s+\d{4})', 'text_pattern_dd_month_yyyy'),
                (r'([A-Za-z]+\s+\d{1,2},?\s+\d{4})', 'text_pattern_month_dd_yyyy'),
                (r'(\d{4}-\d{2}-\d{2})', 'text_pattern_yyyy_mm_dd'),
                (r'(\d{2}/\d{2}/\d{4})', 'text_pattern_mm_dd_yyyy'),
                (r'(\d{1,2}/\d{1,2}/\d{4})', 'text_pattern_m_d_yyyy')
            ]
            
            for pattern, pattern_name in date_patterns:
                matches = re.finditer(pattern, text_content, re.IGNORECASE)
                for match in matches:
                    date_str = match.group(1)
                    if self._is_valid_date_string(date_str):
                        normalized_date = self.normalize_date(date_str)
                        if normalized_date:
                            return normalized_date, pattern_name
            
            return None, None
            
        except Exception as e:
            return None
    
    def _extract_date_from_json_ld(self, soup: BeautifulSoup) -> tuple[Optional[str], Optional[str]]:
        """
        Extract publication date from JSON-LD structured data.
        
        Returns:
            Tuple of (date, json_path/field)
        """
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
                                return str(date_value), f"json_ld_{field}"
                
            except Exception as e:
                continue
        
        return None, None
    
    def _is_valid_date_string(self, date_str: str) -> bool:
        """Check if string looks like a valid date."""
        if not date_str or len(date_str) < 8:
            return False
        
        # Common date patterns
        patterns = [
            r'\d{4}-\d{2}-\d{2}',  # YYYY-MM-DD
            r'\d{4}/\d{2}/\d{2}',  # YYYY/MM/DD
            r'\d{2}/\d{2}/\d{4}',  # MM/DD/YYYY
            r'\d{1,2}/\d{1,2}/\d{4}',  # M/D/YYYY
            r'[A-Za-z]+\s+\d{1,2},?\s+\d{4}',  # Month DD, YYYY
            r'\d{1,2}\s+[A-Za-z]+\s+\d{4}',  # DD Month YYYY
            r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}',  # ISO format
        ]
        
        for pattern in patterns:
            if re.search(pattern, date_str):
                return True
        
        return False
    
    def normalize_date(self, date_str: Optional[str]) -> Optional[str]:
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

