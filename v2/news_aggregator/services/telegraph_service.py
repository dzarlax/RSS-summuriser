"""Telegraph service for creating news pages."""

import logging
from datetime import datetime
from typing import Dict, List, Optional
from telegraph import Telegraph

from ..config import settings


class TelegraphService:
    """Service for creating Telegraph pages."""
    
    def __init__(self):
        self.access_token = getattr(settings, 'telegraph_access_token', None)
        if not self.access_token:
            # Try from environment
            import os
            self.access_token = os.getenv('TELEGRAPH_ACCESS_TOKEN')
        
        if self.access_token:
            self.telegraph = Telegraph(access_token=self.access_token)
        else:
            self.telegraph = None
            logging.warning("Telegraph access token not configured")
    
    async def create_news_page(self, articles_by_category: Dict[str, List]) -> Optional[str]:
        """
        Create Telegraph page with full news content (like old version).
        
        Args:
            articles_by_category: Dictionary with categories and their articles (like old version format)
            
        Returns:
            Telegraph page URL or None if failed
        """
        if not self.telegraph:
            logging.warning("Telegraph not configured")
            return None
        
        if not articles_by_category:
            logging.warning("No data for Telegraph page")
            return None
        
        try:
            # Prepare content
            content_html = ""
            categories_processed = 0
            
            for category, articles in articles_by_category.items():
                if not articles:
                    continue
                    
                try:
                    # Category header
                    content_html += f"<h3>{category}</h3>\n"
                    
                    # Add articles from this category (like old version)
                    for article in articles:
                        # Use headline/description like old version
                        headline = article.get('headline', '')
                        description = article.get('description', '')
                        links = article.get('links', [])
                        
                        if headline:
                            content_html += f"<h4>{self._escape_html(headline)}</h4>\n"
                        
                        if description:
                            # Clean and format description
                            cleaned_description = self._clean_summary_for_telegraph(description)
                            content_html += f"<p>{cleaned_description}</p>\n"
                        
                        # Add links like old version
                        if links:
                            links_html = []
                            for link in links[:3]:  # Max 3 links
                                if link and link.startswith(('http://', 'https://')):
                                    try:
                                        domain = self._extract_domain(link)
                                        if domain:
                                            links_html.append(f'<a href="{link}">{domain}</a>')
                                    except Exception:
                                        continue
                            if links_html:
                                content_html += f"<p>Источники: {' | '.join(links_html)}</p>\n"
                        
                        content_html += "<br>\n"
                    
                    categories_processed += 1
                    
                except Exception as e:
                    logging.warning(f"Error processing category {category}: {e}")
                    continue
            
            logging.info(f"Processed {categories_processed} categories for Telegraph page")
            
            # Sanitize HTML content
            content_html = self._sanitize_html_for_telegraph(content_html)
            
            if not content_html.strip():
                logging.warning("No valid content for Telegraph page")
                return None
            
            # Create page
            current_date = datetime.utcnow().strftime("%d.%m.%Y")
            page_title = f"Новости за {current_date}"
            
            logging.info(f"Creating Telegraph page: {page_title}")
            
            response = self.telegraph.create_page(
                title=page_title,
                html_content=content_html,
                author_name="RSS Summarizer",
                author_url="https://dzarlax.dev"
            )
            
            telegraph_url = response.get('url')
            if telegraph_url:
                logging.info(f"Telegraph page created: {telegraph_url}")
                return telegraph_url
            else:
                logging.error("Telegraph API returned no URL")
                return None
                
        except Exception as e:
            logging.error(f"Failed to create Telegraph page: {e}")
            return None
    
    def _escape_html(self, text: str) -> str:
        """Escape HTML special characters."""
        if not text:
            return ""
        return (text.replace('&', '&amp;')
                   .replace('<', '&lt;')
                   .replace('>', '&gt;')
                   .replace('"', '&quot;')
                   .replace("'", '&#x27;'))
    
    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL."""
        try:
            from urllib.parse import urlparse
            return urlparse(url).netloc.lower()
        except Exception:
            return "unknown"
    
    def _clean_summary_for_telegraph(self, summary: str) -> str:
        """Clean summary text for Telegraph."""
        if not summary:
            return ""
        
        # Remove HTML tags except allowed ones
        import re
        # Keep basic formatting but remove complex HTML
        summary = re.sub(r'<(?!/?[biu]>|/?strong>|/?em>)[^>]*>', '', summary)
        
        # Remove "Читать оригинал" links
        summary = re.sub(r'<a href=.*?>Читать оригинал</a>', '', summary)
        
        # Clean up whitespace
        summary = ' '.join(summary.split())
        
        return self._escape_html(summary)
    
    def _sanitize_html_for_telegraph(self, html_content: str) -> str:
        """
        Remove HTML tags not allowed by Telegraph API.
        Telegraph allows: a, aside, b, blockquote, br, code, em, figcaption, figure, h3, h4, hr, i, iframe, img, li, ol, p, pre, s, strong, u, ul, video
        """
        if not html_content:
            return ""
            
        try:
            from bs4 import BeautifulSoup
            
            # List of forbidden tags
            forbidden_tags = [
                'script', 'style', 'meta', 'link', 'head', 'title', 
                'body', 'html', 'div', 'span', 'table', 'tr', 'td', 'th',
                'h1', 'h2', 'h5', 'h6', 'form', 'input', 'button', 'select'
            ]
            
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Remove forbidden tags but keep content
            for tag_name in forbidden_tags:
                for tag in soup.find_all(tag_name):
                    tag.unwrap()
            
            # Remove scripts and styles completely
            for script in soup.find_all(['script', 'style']):
                script.decompose()
            
            # Convert to string and clean up
            cleaned_html = str(soup)
            
            # Remove empty lines
            lines = [line.strip() for line in cleaned_html.split('\n') if line.strip()]
            return '\n'.join(lines)
            
        except Exception as e:
            logging.warning(f"Error sanitizing HTML: {e}")
            return html_content