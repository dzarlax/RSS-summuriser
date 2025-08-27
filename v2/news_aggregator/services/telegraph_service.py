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
            # Step 1: Collect valid categories and count articles
            valid_categories = []
            category_stats = {}
            
            for category, articles in articles_by_category.items():
                if articles:  # Only categories with articles
                    valid_categories.append(category)
                    category_stats[category] = len(articles)
            
            if not valid_categories:
                logging.warning("No valid categories for Telegraph page")
                return None
            
            # Step 2: Create table of contents
            content_html = self._create_table_of_contents(valid_categories, category_stats)
            content_html += "<hr>\n\n"  # Separator line
            
            # Step 3: Create category content with anchors
            categories_processed = 0
            
            for category in valid_categories:
                articles = articles_by_category[category]
                
                try:
                    # Category header (Telegraph doesn't support id attributes)
                    content_html += f'<h3>{category}</h3>\n'
                    
                    # Add articles from this category
                    for article in articles:
                        # Use headline/description like old version
                        headline = article.get('headline', '')
                        description = article.get('description', '')
                        links = article.get('links', [])
                        image_url = article.get('image_url', '')
                        
                        if headline:
                            content_html += f"<h4>{self._escape_html(headline)}</h4>\n"
                        
                        # Add image if available
                        if image_url and self._is_valid_image_url(image_url):
                            content_html += f'<img src="{image_url}" alt="{self._escape_html(headline[:100])}">\n'
                        
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
            
            logging.info(f"Processed {categories_processed} categories for Telegraph page with table of contents")
            
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
    
    def _is_valid_image_url(self, url: str) -> bool:
        """Check if URL looks like a valid image URL."""
        if not url or not isinstance(url, str):
            return False
        
        url = url.lower()
        
        # Check if URL starts with http/https
        if not url.startswith(('http://', 'https://')):
            return False
        
        # Check for image file extensions
        image_extensions = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.svg')
        if any(url.endswith(ext) for ext in image_extensions):
            return True
        
        # Check for known image CDN patterns
        image_cdns = [
            'telegram.space/file/',  # Telegram CDN
            'cdn.telegram',
            'imgur.com/',
            'i.imgur.com/',
            'images.',
            'img.',
            'static.',
            'media.',
            'photo'
        ]
        
        return any(pattern in url for pattern in image_cdns)
    
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
    
    def _create_table_of_contents(self, categories: List[str], category_stats: Dict[str, int]) -> str:
        """Create table of contents with working Telegraph anchor links."""
        if not categories:
            return ""
        
        toc_html = "<h3>📋 Содержание</h3>\n"
        toc_html += "<blockquote>\n<p>"
        
        # Create compact list without extra paragraph spacing
        toc_lines = []
        for category in categories:
            article_count = category_stats.get(category, 0)
            # Create Telegraph-compatible anchor link (spaces become dashes)
            category_anchor = self._create_telegraph_anchor(category)
            
            # Create clickable link with article count
            toc_lines.append(f'<a href="#{category_anchor}">{category}</a> — {article_count} новостей')
        
        # Join all category lines with <br> for compact display
        toc_html += "<br>\n".join(toc_lines)
        
        # Add total count on separate line
        total_articles = sum(category_stats.values())
        toc_html += f'<br><br><em>Всего: {total_articles} новостей в {len(categories)} категориях</em>'
        
        toc_html += "</p>\n</blockquote>\n"
        return toc_html
    
    def _create_telegraph_anchor(self, category: str) -> str:
        """Create Telegraph-compatible anchor from category name.
        
        Telegraph anchor format: spaces become dashes, preserve case.
        For "Tech News" -> "Tech-News"
        """
        if not category:
            return "category"
        
        # Replace spaces with dashes, keep original case
        anchor = category.replace(' ', '-')
        
        # Remove any problematic characters but keep case
        import re
        anchor = re.sub(r'[^\w\s-]', '', anchor)
        anchor = re.sub(r'[-\s]+', '-', anchor)  # Multiple dashes/spaces to single dash
        anchor = anchor.strip('-')  # Remove leading/trailing dashes
        
        # Ensure non-empty result
        if not anchor:
            anchor = "category"
        
        return anchor
    
