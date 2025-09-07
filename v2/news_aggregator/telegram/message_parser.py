"""Message parsing logic for Telegram sources."""

import re
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from urllib.parse import urlparse
from bs4 import BeautifulSoup

from ..sources.base import Article
from .media_extractor import MediaExtractor


class MessageParser:
    """Parse Telegram message elements into Article objects."""
    
    def __init__(self, source_name: str, channel_username: str):
        """Initialize parser with source information."""
        self.source_name = source_name
        self.channel_username = channel_username
        self.media_extractor = MediaExtractor()
        
        # Text extraction selectors
        self.text_selectors = [
            '.tgme_widget_message_text',
            '.message-text', 
            '.text',
            'div[dir="ltr"]',
            '.tgme_widget_message_text_wrapper',
            '.message_text',
            '.post-content',
        ]
    
    async def parse_message_element(self, message_div, base_url: str, soup=None) -> Optional[Article]:
        """Parse message div element into Article."""
        try:
            # Clean up message div first
            self._cleanup_message_div(message_div)
            
            # Extract content
            content = self._extract_message_content(message_div, base_url)
            if len(content) < 10:
                return None
            
            # Extract basic message info
            message_url = self._extract_message_url(message_div, base_url)
            message_id = self._extract_message_id(message_div, message_url)
            published_at = self._extract_date(message_div)
            
            # Extract media information
            image_url = self.media_extractor.extract_image_url(message_div)
            media_files = self.media_extractor.extract_media_files(message_div)
            media_info = self.media_extractor.extract_media_info(message_div)
            
            # Extract Open Graph image if no media found and soup is available
            if not image_url and not media_files and soup:
                og_image_url = self._extract_opengraph_image(soup)
                if og_image_url:
                    image_url = og_image_url
                    # Add to media_files as well
                    media_files = [{
                        'url': og_image_url,
                        'type': 'image',
                        'thumbnail': og_image_url,
                        'source': 'opengraph'
                    }]
            
            # Extract links and metadata
            external_links = self._extract_external_links(message_div)
            original_link = self._find_original_link(external_links)
            
            # Try to extract full content from external link if Telegram content is short
            if original_link and len(content) < 200:
                full_content = await self._try_extract_full_content(original_link, content)
                if full_content:
                    content = full_content
                    print(f"  🎯 Using full content from external source ({len(content)} chars)")
            
            title = self._extract_title(content)
            forwarded_from = self._extract_forwarded_info(message_div)
            hashtags = self._extract_hashtags(content)
            
            # Determine final URL (prefer external original link)
            final_url = (self._normalize_external_url(original_link) if original_link else None) or message_url
            
            return Article(
                title=title,
                url=final_url,
                content=content,
                published_at=published_at,
                source_type="telegram",
                source_name=self.source_name,
                image_url=image_url,
                media_files=media_files,
                raw_data={
                    "channel": self.channel_username,
                    "access_method": base_url,
                    "content_length": len(content),
                    "media_info": media_info,
                    "has_media": bool(image_url or media_info.get('video_url') or media_info.get('document_url') or media_files),
                    "media_count": len(media_files) if media_files else 0,
                    "external_links": external_links,
                    "hashtags": hashtags,
                    "original_link": original_link,
                    "forwarded_from": forwarded_from,
                    "message_id": message_id,
                    "telegram_url": message_url
                }
            )
            
        except Exception as e:
            print(f"Error parsing Telegram message: {e}")
            return None
    
    async def _try_extract_full_content(self, external_link: str, short_content: str) -> Optional[str]:
        """
        Try to extract full content from external link if Telegram content is short.
        
        Args:
            external_link: External URL to extract content from
            short_content: Short content from Telegram message
            
        Returns:
            Full content if extraction successful, None otherwise
        """
        # Only try full extraction if content is very short (likely just title + @channel)
        if len(short_content) > 200:  # Content already substantial
            return None
            
        # Skip non-news domains to avoid processing promotional links
        news_domains = [
            'euronews.rs', 'blic.rs', 'rts.rs', 'b92.net', 'danas.rs', 
            'politika.rs', 'novosti.rs', 'telegraf.rs', 'alo.rs',
            'kurir.rs', 'n1info.rs', 'beta.rs', 'tanjug.rs',
            'balkaninsight.com', 'balkaninfo.rs'
        ]
        
        if not any(domain in external_link.lower() for domain in news_domains):
            print(f"  ⏭️  Skipping non-news domain: {external_link}")
            return None
            
        try:
            print(f"  🔗 Trying to extract full content from: {external_link}")
            
            # Lazy import to avoid circular import
            from ..extraction import ContentExtractor
            
            async with ContentExtractor() as content_extractor:
                # Extract full content from external link
                result = await content_extractor.extract_article_content_with_metadata(external_link)
                
                if result and result.get('content'):
                    full_content = result['content']
                    if len(full_content) > len(short_content) * 2:  # Significant improvement
                        print(f"  ✅ Extracted full content: {len(full_content)} chars vs {len(short_content)} chars")
                        return full_content
                    else:
                        print(f"  ⚠️  External content not much longer than Telegram content")
                else:
                    print(f"  ❌ No content extracted from external link")
                    
        except Exception as e:
            print(f"  ⚠️  Full content extraction failed: {e}")
            
        return None
    
    def _cleanup_message_div(self, message_div) -> None:
        """Remove quoted original from replies to avoid mixing content."""
        try:
            for reply in message_div.select('.tgme_widget_message_reply'):
                reply.decompose()
        except Exception:
            pass
    
    def _extract_message_content(self, message_div, base_url: str) -> str:
        """Extract message text content using multiple strategies."""
        content = ""
        
        # Strategy 1: Try specific text selectors
        for selector in self.text_selectors:
            text_element = message_div.select_one(selector)
            if text_element:
                content = text_element.get_text(separator='\n', strip=True)
                break
        
        # Strategy 2: If no specific text element, try to get all text from message
        if not content:
            # Remove navigation elements first
            for elem in message_div.select('.tgme_widget_message_footer, .tgme_widget_message_info, .tgme_widget_message_date'):
                elem.decompose()
            content = message_div.get_text(separator='\n', strip=True)
        
        # Strategy 3: Fallback to meta tags for very short content
        if len(content) < 20:
            meta_content = self._extract_from_meta_tags(message_div, base_url)
            if meta_content and len(meta_content) > len(content):
                print(f"  📝 Using meta fallback for very short content: {len(content)} → {len(meta_content)}")
                content = meta_content
        
        # Clean up content
        return self._clean_message_content(content)
    
    def _extract_message_url(self, message_div, base_url: str) -> str:
        """Extract message URL from div."""
        # Try to find link to specific message
        link_selectors = [
            'a.tgme_widget_message_date',
            'a[href*="/"]',
            '.message-link'
        ]
        
        for selector in link_selectors:
            link = message_div.select_one(selector)
            if link and link.get('href'):
                href = link['href']
                if href.startswith('http'):
                    return href
                elif href.startswith('/'):
                    return f"https://t.me{href}"
        
        # Fallback to channel URL
        return f"https://t.me/{self.channel_username}"
    
    def _extract_message_id(self, message_div, message_url: str) -> Optional[str]:
        """Extract message ID from data attributes or URL."""
        try:
            data_post = message_div.get('data-post')
            if data_post and '/' in data_post:
                return data_post.split('/')[-1]
            elif message_url and message_url.rsplit('/', 1):
                tail = message_url.rsplit('/', 1)[-1]
                if tail.isdigit():
                    return tail
        except Exception:
            pass
        return None
    
    def _extract_date(self, message_div) -> Optional[datetime]:
        """Extract date from message div."""
        # Try multiple date selectors
        time_selectors = [
            'time[datetime]',
            '.datetime',
            '.date',
            '[data-time]'
        ]
        
        for selector in time_selectors:
            time_element = message_div.select_one(selector)
            if time_element:
                # Try datetime attribute first
                datetime_str = time_element.get('datetime')
                if datetime_str:
                    try:
                        dt = datetime.fromisoformat(datetime_str.replace('Z', '+00:00'))
                        # Convert to naive UTC for database compatibility
                        return dt.astimezone(timezone.utc).replace(tzinfo=None)
                    except ValueError:
                        pass
                
                # Try data-time attribute
                data_time = time_element.get('data-time')
                if data_time:
                    try:
                        dt = datetime.fromtimestamp(float(data_time), tz=timezone.utc)
                        # Convert to naive UTC for database compatibility
                        return dt.replace(tzinfo=None)
                    except (ValueError, TypeError):
                        pass
        
        # Fallback to current time (naive UTC for database compatibility)
        return datetime.now(timezone.utc).replace(tzinfo=None)
    
    def _extract_external_links(self, message_div) -> List[str]:
        """Extract external links from message (not Telegram links)."""
        external_links = []
        
        try:
            # Prefer preview links
            preview_selectors = [
                '.tgme_widget_message_link_preview a[href]',
                '.link_preview a[href]',
                '.tgme_widget_message_forwarded_from a[href]'
            ]
            
            link_candidates = []
            for sel in preview_selectors:
                link_candidates.extend(message_div.select(sel))
            
            # Fallback to any links
            if not link_candidates:
                link_candidates = message_div.select('a[href]')
            
            for a in link_candidates:
                href = a.get('href')
                if not href or not href.startswith(('http://', 'https://')):
                    continue
                if 't.me' in href or 'telegram.me' in href:
                    continue
                
                # Normalize to prevent duplicate URLs
                external_links.append(self._normalize_external_url(href))
            
            # Deduplicate while preserving order
            seen = set()
            external_links = [x for x in external_links if x and not (x in seen or seen.add(x))][:5]
            
        except Exception:
            external_links = []
        
        return external_links
    
    def _find_original_link(self, external_links: List[str]) -> Optional[str]:
        """Find the most likely original link by excluding social media."""
        blacklist = (
            'facebook.com', 'twitter.com', 'x.com', 'instagram.com', 
            'vk.com', 'ok.ru', 'youtube.com', 'youtu.be', 't.me', 'telegram.me'
        )
        
        for link in external_links:
            try:
                host = urlparse(link).netloc.lower()
                if not any(b in host for b in blacklist):
                    return self._normalize_external_url(link)
            except Exception:
                continue
        
        return None
    
    def _extract_title(self, text: str) -> str:
        """Extract title from message text."""
        if not text:
            return "Telegram Post"
        
        # Split into lines and find the first substantial line
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        
        if not lines:
            return "Telegram Post"
        
        # Use first line as title, but smart truncate if too long
        title = lines[0]
        
        # Remove common Telegram artifacts
        title = re.sub(r'^(Forwarded from|Reply to|@\w+:?\s*)', '', title, flags=re.IGNORECASE)
        title = re.sub(r'^\s*[🔗📎📷🎥📄]\s*', '', title)  # Remove emoji artifacts
        
        # Smart truncate 
        return self._smart_truncate_title(title)
    
    def _extract_forwarded_info(self, message_div) -> Optional[str]:
        """Extract forwarded message information."""
        try:
            fwd = message_div.select_one('.tgme_widget_message_forwarded_from')
            if fwd:
                return fwd.get_text(strip=True)
        except Exception:
            pass
        return None
    
    def _extract_hashtags(self, content: str) -> List[str]:
        """Extract hashtags from content."""
        try:
            hashtags = [re.sub(r'[^\w_]+', '', h).lower() for h in re.findall(r'(?:(?<=\s)|^)#(\w+)', content)]
            # Deduplicate and limit
            seen_ht = set()
            hashtags = [h for h in hashtags if h and not (h in seen_ht or seen_ht.add(h))][:20]
            return hashtags
        except Exception:
            return []
    
    def _extract_from_meta_tags(self, message_div, base_url: str = None) -> Optional[str]:
        """Extract content from meta tags as fallback."""
        try:
            # Look for Open Graph or Twitter meta tags
            meta_selectors = [
                'meta[property="og:description"]',
                'meta[name="description"]',
                'meta[name="twitter:description"]'
            ]
            
            for selector in meta_selectors:
                meta_tag = message_div.select_one(selector)
                if meta_tag and meta_tag.get('content'):
                    content = meta_tag['content'].strip()
                    if len(content) > 20:
                        return content
        except Exception as e:
            print(f"  ⚠️ Meta extraction failed: {e}")
        
        return None
    
    def _extract_opengraph_image(self, soup) -> Optional[str]:
        """Extract Open Graph image from meta tags."""
        try:
            # Look for Open Graph image meta tags
            og_image_selectors = [
                'meta[property="og:image"]',
                'meta[property="og:image:url"]',
                'meta[name="twitter:image"]',
                'meta[name="twitter:image:src"]'
            ]
            
            for selector in og_image_selectors:
                meta_tag = soup.select_one(selector)
                if meta_tag and meta_tag.get('content'):
                    image_url = meta_tag['content'].strip()
                    if image_url.startswith(('http://', 'https://')):
                        print(f"    🖼️ Found Open Graph image: {image_url[:80]}...")
                        return image_url
                    elif image_url.startswith('//'):
                        image_url = f"https:{image_url}"
                        print(f"    🖼️ Found Open Graph image: {image_url[:80]}...")
                        return image_url
        except Exception as e:
            print(f"  ⚠️ Open Graph image extraction failed: {e}")
        
        return None
    
    def _clean_message_content(self, content: str) -> str:
        """Clean up message content from HTML artifacts and weird characters."""
        if not content:
            return ""
        
        # Remove excessive whitespace
        content = re.sub(r'\s+', ' ', content)
        content = re.sub(r'\n\s*\n', '\n\n', content)  # Clean up multiple newlines
        
        # Remove invisible/control characters (except newlines and tabs)
        content = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', content)
        
        # Clean up common Telegram artifacts
        content = re.sub(r'\s*\n\s*View in Telegram\s*$', '', content, flags=re.IGNORECASE)
        content = re.sub(r'\s*\n\s*Open in Telegram\s*$', '', content, flags=re.IGNORECASE)
        
        return content.strip()
    
    def _smart_truncate_title(self, title: str) -> str:
        """Intelligently truncate title to reasonable length."""
        if len(title) <= 120:
            return title
        
        # Find good break points
        break_chars = ['. ', '! ', '? ', ': ', ' - ', ' – ', ' — ']
        for char in break_chars:
            pos = title[:120].rfind(char)
            if pos > 60:  # Ensure we don't cut too short
                return title[:pos + 1].strip()
        
        # Fallback: word boundary
        words = title[:120].split()
        if len(words) > 1:
            return ' '.join(words[:-1]) + '...'
        
        return title[:117] + '...'
    
    def _normalize_external_url(self, url: str) -> Optional[str]:
        """Normalize external URL for consistency."""
        if not url:
            return None
        
        try:
            # Remove tracking parameters
            parsed = urlparse(url)
            if parsed.scheme and parsed.netloc:
                # Remove common tracking params
                clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                if parsed.query:
                    # Keep important query params, remove tracking ones
                    from urllib.parse import parse_qs, urlencode
                    params = parse_qs(parsed.query)
                    
                    # Common tracking parameters to remove
                    tracking_params = {
                        'utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term',
                        'fbclid', 'gclid', '_ga', 'mc_cid', 'mc_eid'
                    }
                    
                    clean_params = {k: v for k, v in params.items() if k not in tracking_params}
                    if clean_params:
                        clean_url += '?' + urlencode(clean_params, doseq=True)
                
                return clean_url
            
        except Exception:
            pass
        
        return url if url.startswith(('http://', 'https://')) else None
