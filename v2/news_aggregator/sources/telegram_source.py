"""Telegram source for reading public channels with Cloudflare bypass."""

import re
import random
from datetime import datetime, timedelta
import logging
import pytz
from typing import AsyncGenerator, Optional, Dict, List, Any
from bs4 import BeautifulSoup
import asyncio

from .base import BaseSource, Article
from ..core.http_client import get_http_client
from ..core.exceptions import SourceError

try:
    from playwright.async_api import async_playwright, Browser, Page
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


class TelegramSource(BaseSource):
    """Telegram public channel source with multiple access methods."""
    
    # Real browser headers to bypass Cloudflare
    BROWSER_HEADERS = [
        {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9,ru;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Ch-Ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': '"Windows"',
        },
        {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }
    ]
    
    def __init__(self, source_info):
        super().__init__(source_info)
        self.channel_username = self._extract_channel_username()
        self.browser: Optional[Browser] = None
        
        # Multiple access URLs to try
        self.access_urls = [
            f"https://t.me/s/{self.channel_username}",  # Standard preview
            f"https://telegram.me/s/{self.channel_username}",  # Alternative domain
        ]
        
        # Retry configuration
        self.max_retries = 3
        self.base_delay = 2.0
        self.max_delay = 30.0
    
    def _extract_channel_username(self) -> str:
        """Extract channel username from URL."""
        url = self.url.lower().strip()
        
        # Remove protocol
        url = re.sub(r'^https?://', '', url)
        
        # Handle different formats
        if "t.me/" in url:
            username = url.split("t.me/")[-1].split("?")[0].split("/")[0]
        elif "telegram.me/" in url:
            username = url.split("telegram.me/")[-1].split("?")[0].split("/")[0]
        elif url.startswith("@"):
            username = url.replace("@", "")
        else:
            # Assume it's just the username
            username = url.split("/")[0]
        
        # Clean username
        username = re.sub(r'[^a-zA-Z0-9_]', '', username)
        
        if not username:
            raise SourceError(f"Could not extract channel username from: {self.url}")
        
        return username
    
    async def fetch_articles(self, limit: Optional[int] = None) -> AsyncGenerator[Article, None]:
        """Fetch messages from public Telegram channel with multiple fallbacks and advertising detection."""
        articles_found = []
        
        # Strategy 1: Try HTTP requests with smart retry
        for url in self.access_urls:
            try:
                print(f"📡 Trying HTTP request: {url}")
                articles = await self._fetch_with_http_retry(url, limit)
                articles_found.extend(articles)
                
                if articles_found:
                    print(f"✅ HTTP method successful: {len(articles_found)} articles")
                    break
                    
            except Exception as e:
                print(f"⚠️ HTTP failed for {url}: {e}")
                continue
        
        # Strategy 2: Fallback to Playwright if HTTP failed and available
        if not articles_found and PLAYWRIGHT_AVAILABLE:
            try:
                print(f"🎭 Fallback to browser rendering...")
                for url in self.access_urls:
                    try:
                        articles = await self._fetch_with_browser(url, limit)
                        articles_found.extend(articles)
                        
                        if articles_found:
                            print(f"✅ Browser method successful: {len(articles_found)} articles")
                            break
                    except Exception as e:
                        print(f"⚠️ Browser failed for {url}: {e}")
                        continue
                        
            except Exception as e:
                print(f"⚠️ Browser fallback failed: {e}")
        
        if not articles_found:
            method_info = "HTTP + Browser" if PLAYWRIGHT_AVAILABLE else "HTTP only"
            raise SourceError(f"All access methods ({method_info}) failed for channel: {self.channel_username}")
        
        # ============================================================================
        # DISABLED: Advertising detection moved to combined analysis in orchestrator
        # ============================================================================
        # Advertising detection is now handled by analyze_article_complete() in the
        # orchestrator along with summarization and categorization for efficiency.
        # This eliminates duplicate AI calls and reduces API usage by ~75%.
        #
        # Old code: articles_with_ad_detection = await self._apply_advertising_detection(articles_found)
        # ============================================================================
        
        # Sort by date and yield (no ad detection here anymore)
        articles_found.sort(key=lambda x: x.published_at or datetime.min, reverse=True)
        
        for i, article in enumerate(articles_found):
            if limit and i >= limit:
                break
            yield article
    
    async def _fetch_with_http_retry(self, url: str, limit: Optional[int] = None) -> List[Article]:
        """Fetch with smart retry logic for Cloudflare and other blocks."""
        last_exception = None
        
        for attempt in range(self.max_retries):
            try:
                # Exponential backoff with jitter
                if attempt > 0:
                    delay = min(self.base_delay * (2 ** (attempt - 1)), self.max_delay)
                    jitter = random.uniform(0.1, 0.5) * delay
                    total_delay = delay + jitter
                    print(f"  ⏰ Retry {attempt + 1}/{self.max_retries} after {total_delay:.1f}s delay")
                    await asyncio.sleep(total_delay)
                
                # Rotate headers for each attempt
                headers = random.choice(self.BROWSER_HEADERS).copy()
                
                # Add additional anti-detection headers on retries
                if attempt > 0:
                    headers.update({
                        'Cache-Control': 'no-cache',
                        'Pragma': 'no-cache',
                        'Sec-Fetch-User': '?1',
                        'X-Requested-With': 'XMLHttpRequest' if attempt == 2 else None
                    })
                    headers = {k: v for k, v in headers.items() if v is not None}
                
                async with get_http_client() as client:
                    # Random human delay
                    await asyncio.sleep(random.uniform(1, 4))
                    
                    response = await client.get(url, headers=headers)
                    async with response:
                        if response.status == 200:
                            html = await response.text()
                            return self._parse_html(html, url)
                        elif response.status == 403:
                            print(f"  🚫 Access denied (attempt {attempt + 1})")
                            if attempt < self.max_retries - 1:
                                continue  # Retry with different headers
                            raise SourceError("Access denied after all retries")
                        elif response.status == 404:
                            raise SourceError("Channel not found or private")
                        elif response.status in [429, 503, 502, 504]:
                            print(f"  🔄 Rate limited/server error {response.status} (attempt {attempt + 1})")
                            if attempt < self.max_retries - 1:
                                continue  # Retry after delay
                            raise SourceError(f"Server error {response.status} after all retries")
                        else:
                            raise SourceError(f"HTTP {response.status}")
                            
            except SourceError:
                raise  # Don't retry SourceErrors
            except Exception as e:
                last_exception = e
                print(f"  ⚠️ Request failed (attempt {attempt + 1}): {e}")
                if attempt < self.max_retries - 1:
                    continue
        
        raise SourceError(f"All HTTP retry attempts failed: {last_exception}")

    def _normalize_external_url(self, url: str) -> Optional[str]:
        """Normalize external article URL to reduce duplicates (strip tracking params, anchors)."""
        if not url or not isinstance(url, str):
            return None
        try:
            from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
            parsed = urlparse(url)
            if not parsed.scheme or not parsed.netloc:
                return url
            scheme = parsed.scheme.lower()
            netloc = parsed.netloc.lower()
            path = parsed.path or '/'
            # Remove common tracking params
            tracking = {
                'utm_source','utm_medium','utm_campaign','utm_term','utm_content','utm_id',
                'gclid','fbclid','yclid','mc_cid','mc_eid','ref','ref_src','igshid',
                'mkt_tok','vero_conv','vero_id','_hsenc','_hsmi','si','s','feature','spm'
            }
            query_pairs = [(k,v) for k,v in parse_qsl(parsed.query, keep_blank_values=False) if k not in tracking]
            query = urlencode(query_pairs, doseq=True)
            # Drop fragments
            fragment = ''
            normalized = urlunparse((scheme, netloc, path, '', query, fragment))
            # Remove trailing slash duplication (but keep root '/')
            if normalized.endswith('/') and path != '/':
                normalized = normalized[:-1]
            return normalized
        except Exception:
            return url
    
    async def _fetch_with_browser(self, url: str, limit: Optional[int] = None) -> List[Article]:
        """Fetch using Playwright browser for JS-heavy or protected channels."""
        if not PLAYWRIGHT_AVAILABLE:
            raise SourceError("Playwright not available for browser fallback")
        
        page = None
        try:
            # Initialize browser if needed
            if not self.browser:
                print(f"  🔧 Launching browser...")
                playwright = await async_playwright().start()
                self.browser = await playwright.chromium.launch(
                    headless=True,
                    args=[
                        '--no-sandbox',
                        '--disable-dev-shm-usage',
                        '--disable-blink-features=AutomationControlled',
                        '--disable-extensions',
                        '--no-first-run'
                    ]
                )
            
            page = await self.browser.new_page()
            
            # Set realistic browser environment
            await page.set_viewport_size({"width": 1366, "height": 768})
            
            # Set headers to match real browser
            headers = random.choice(self.BROWSER_HEADERS)
            await page.set_extra_http_headers(headers)
            
            # Navigate with realistic timing
            print(f"  🌐 Loading page with browser...")
            await page.goto(url, wait_until='networkidle', timeout=30000)
            
            # Wait for content to load and simulate human behavior
            await page.wait_for_timeout(random.uniform(2000, 5000))
            
            # Scroll to load more content if needed
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(1000)
            
            # Extract HTML and parse
            html = await page.content()
            return self._parse_html(html, url)
            
        except Exception as e:
            print(f"  🎭 Browser extraction failed: {e}")
            raise SourceError(f"Browser extraction failed: {e}")
        finally:
            if page:
                try:
                    await page.close()
                except:
                    pass
    
    async def _fetch_from_url(self, url: str, limit: Optional[int] = None) -> List[Article]:
        """Legacy method - kept for compatibility."""
        return await self._fetch_with_http_retry(url, limit)
    
    def _parse_html(self, html: str, base_url: str) -> List[Article]:
        """Parse HTML and extract articles."""
        soup = BeautifulSoup(html, 'html.parser')
        articles = []
        
        # Try different selectors for different page layouts
        message_selectors = [
            'div.tgme_widget_message',  # Standard preview
            'div.message',              # Alternative layout
            'div[data-post]',           # Web client format
        ]
        
        messages = []
        for selector in message_selectors:
            messages = soup.select(selector)
            if messages:
                break

        # Exclude Telegram service/system messages (pin, join, etc.)
        if messages:
            filtered = []
            for m in messages:
                classes = m.get('class') or []
                if isinstance(classes, list) and any('tgme_widget_message_service' in c for c in classes):
                    continue
                filtered.append(m)
            messages = filtered
        
        if not messages:
            # Try to find any div with text content as fallback
            print("No standard message containers found, trying fallback...")
            return []
        
        seen_message_ids = set()
        for message in messages:
            try:
                article = self._parse_message_element(message, base_url)
                if article:
                    # Deduplicate by Telegram message_id if available
                    try:
                        mid = None
                        if hasattr(article, 'raw_data') and article.raw_data:
                            mid = article.raw_data.get('message_id')
                        if mid and mid in seen_message_ids:
                            continue
                        if mid:
                            seen_message_ids.add(mid)
                    except Exception:
                        pass
                    articles.append(article)
            except Exception as e:
                print(f"Error parsing message: {e}")
                continue
        
        return articles
    
    def _parse_message_element(self, message_div, base_url: str) -> Optional[Article]:
        """Parse message div element into Article."""
        try:
            # Remove quoted original from replies to avoid mixing it into the reply content
            try:
                for reply in message_div.select('.tgme_widget_message_reply'):
                    reply.decompose()
            except Exception:
                pass
            
            # Extract message text - try multiple selectors
            text_selectors = [
                '.tgme_widget_message_text',
                '.message-text',
                '.text',
                'div[dir="ltr"]'
            ]
            
            content = ""
            for selector in text_selectors:
                text_element = message_div.select_one(selector)
                if text_element:
                    # Preserve line breaks between blocks for better readability
                    content = text_element.get_text(separator='\n', strip=True)
                    break
            
            # If no specific text element, try to get all text
            if not content:
                content = message_div.get_text(separator='\n', strip=True)
            
            # Clean up content from HTML artifacts and weird characters
            content = self._clean_message_content(content)
            
            if len(content) < 10:
                return None
            
            # Extract message URL and id
            message_url = self._extract_message_url(message_div, base_url)
            message_id = None
            try:
                data_post = message_div.get('data-post')
                if data_post and '/' in data_post:
                    message_id = data_post.split('/')[-1]
                elif message_url and message_url.rsplit('/', 1):
                    tail = message_url.rsplit('/', 1)[-1]
                    if tail.isdigit():
                        message_id = tail
            except Exception:
                message_id = None
            
            # Extract date
            published_at = self._extract_date(message_div)
            
            # Extract image and media info
            image_url = self._extract_image_url(message_div)
            media_files = self._extract_media_files(message_div)
            media_info = self._extract_media_info(message_div)

            # Extract external links (buttons/previews) that are not Telegram links
            external_links = []
            original_link = None
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
                    # Normalize to prevent duplicate URLs by tracking params/fragments
                    external_links.append(self._normalize_external_url(href))
                # Deduplicate while preserving order
                seen = set()
                external_links = [x for x in external_links if not (x in seen or seen.add(x))][:5]
                # Pick original link by simple heuristics (avoid socials)
                blacklist = ('facebook.com', 'twitter.com', 'x.com', 'instagram.com', 'vk.com', 'ok.ru', 'youtube.com', 'youtu.be', 't.me', 'telegram.me')
                for link in external_links:
                    from urllib.parse import urlparse
                    try:
                        host = urlparse(link).netloc.lower()
                        if not any(b in host for b in blacklist):
                            original_link = self._normalize_external_url(link)
                            break
                    except Exception:
                        continue
            except Exception:
                external_links = []
            
            # Extract title
            title = self._extract_title(content)

            # Forwarded info
            forwarded_from = None
            try:
                fwd = message_div.select_one('.tgme_widget_message_forwarded_from')
                if fwd:
                    forwarded_from = fwd.get_text(strip=True)
            except Exception:
                forwarded_from = None
            
            # Extract hashtags from content for downstream features
            hashtags = []
            try:
                import re as _re
                hashtags = [_re.sub(r'[^\w_]+', '', h).lower() for h in _re.findall(r'(?:(?<=\s)|^)#(\w+)', content)]
                # Deduplicate
                seen_ht = set()
                hashtags = [h for h in hashtags if h and not (h in seen_ht or seen_ht.add(h))][:20]
            except Exception:
                hashtags = []

            # Prefer original external link as canonical URL; keep Telegram URL separately
            final_url = (self._normalize_external_url(original_link) if original_link else None) or message_url

            return Article(
                title=title,
                url=final_url,
                content=content,
                published_at=published_at,
                source_type="telegram",
                source_name=self.name,
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
                # Try datetime attribute
                datetime_str = time_element.get('datetime')
                if datetime_str:
                    try:
                        # Parse ISO format and convert to naive UTC
                        dt = datetime.fromisoformat(datetime_str.replace('Z', '+00:00'))
                        if dt.tzinfo is not None:
                            dt = dt.astimezone(pytz.UTC).replace(tzinfo=None)
                        return dt
                    except:
                        pass
                
                # Try data-time attribute
                time_str = time_element.get('data-time')
                if time_str:
                    try:
                        # Convert timestamp to naive UTC datetime
                        return datetime.utcfromtimestamp(int(time_str))
                    except:
                        pass
        
        # Fallback to current time (naive UTC)
        return datetime.utcnow()
    
    def _extract_media_files(self, message_div) -> List[Dict[str, Any]]:
        """Extract all media files from message div with enhanced media support, excluding channel avatars."""
        media_files = []
        
        # Enhanced media selectors
        media_selectors = {
            'image': [
                '.media img',                  # Media container images (content)
                '.photo img',                  # Photo-specific images (content)
                '.attachment img',             # Attachment images (content)
                '.message_media img',          # Message media (content)
                '.tgme_widget_message_photo img',  # Telegram preview photos (content)
            ],
            'video': [
                '.video-thumb img',            # Video thumbnails (content)
                '.tgme_widget_message_video',  # Video containers
                'video',                       # Direct video elements
            ],
            'document': [
                '.document-thumb img',         # Document thumbnails (content)
                '.tgme_widget_message_document', # Document containers
            ]
        }
        
        # Avatar/profile selectors to exclude
        avatar_selectors = [
            '.tgme_widget_message_user_photo img',  # User profile photos
            '.tgme_widget_message_owner_photo img', # Channel owner photos
            '.message_author_photo img',            # Author photos
            '.avatar img',                          # Generic avatars
            '.profile img',                         # Profile images
            '.channel_photo img'                    # Channel photos
        ]
        
        # First, collect avatar URLs to exclude them
        avatar_urls = set()
        for selector in avatar_selectors:
            avatar_imgs = message_div.select(selector)
            for img in avatar_imgs:
                src = img.get('src') or img.get('data-src') or img.get('data-lazy-src')
                if src:
                    avatar_urls.add(src)
        
        # Extract images
        for selector in media_selectors['image']:
            imgs = message_div.select(selector)
            for img in imgs:
                src = img.get('src') or img.get('data-src') or img.get('data-lazy-src')
                if src and src not in avatar_urls:
                    normalized_url = self._normalize_image_url(src)
                    if normalized_url and self._is_content_image(normalized_url):
                        media_files.append({
                            'url': normalized_url,
                            'type': 'image',
                            'thumbnail': normalized_url  # For images, thumbnail is the same as URL
                        })
        
        # Extract videos
        for selector in media_selectors['video']:
            elements = message_div.select(selector)
            for element in elements:
                if element.name == 'video':
                    # Direct video element
                    src = element.get('src')
                    poster = element.get('poster')
                    if src:
                        media_files.append({
                            'url': self._normalize_image_url(src),
                            'type': 'video',
                            'thumbnail': self._normalize_image_url(poster) if poster else None
                        })
                else:
                    # Video container - look for thumbnail and video URL
                    thumb_img = element.select_one('img')
                    if thumb_img:
                        thumb_src = thumb_img.get('src') or thumb_img.get('data-src')
                        if thumb_src and thumb_src not in avatar_urls:
                            # For video containers, we might not have direct video URL
                            # but we can use the thumbnail and mark it as video
                            normalized_thumb = self._normalize_image_url(thumb_src)
                            if normalized_thumb:
                                media_files.append({
                                    'url': normalized_thumb,  # Use thumbnail as URL for now
                                    'type': 'video',
                                    'thumbnail': normalized_thumb
                                })
        
        # Extract documents
        for selector in media_selectors['document']:
            elements = message_div.select(selector)
            for element in elements:
                thumb_img = element.select_one('img')
                if thumb_img:
                    thumb_src = thumb_img.get('src') or thumb_img.get('data-src')
                    if thumb_src and thumb_src not in avatar_urls:
                        normalized_thumb = self._normalize_image_url(thumb_src)
                        if normalized_thumb:
                            media_files.append({
                                'url': normalized_thumb,  # Use thumbnail as URL for now
                                'type': 'document',
                                'thumbnail': normalized_thumb
                            })
        
        # Check for background images in style attributes
        for element in message_div.select('[style*="background-image"]'):
            style = element.get('style', '')
            import re
            bg_matches = re.findall(r'background-image:\s*url\(["\']?(.*?)["\']?\)', style)
            for match in bg_matches:
                if match not in avatar_urls:
                    normalized_url = self._normalize_image_url(match)
                    if normalized_url and self._is_content_image(normalized_url):
                        media_files.append({
                            'url': normalized_url,
                            'type': 'image',
                            'thumbnail': normalized_url
                        })
        
        # Remove duplicates based on URL
        seen_urls = set()
        unique_media = []
        for media in media_files:
            if media['url'] not in seen_urls:
                seen_urls.add(media['url'])
                unique_media.append(media)
        
        return unique_media
    
    def _extract_image_url(self, message_div) -> Optional[str]:
        """Extract single image URL for backward compatibility."""
        media_files = self._extract_media_files(message_div)
        
        # Return first image URL for backward compatibility
        for media in media_files:
            if media.get('type') == 'image':
                # Prefer full-size images over thumbnails
                url = media.get('url', '')
                if 'thumb' not in url.lower() and 'preview' not in url.lower():
                    return url
        
        # Fallback to any image
        for media in media_files:
            if media.get('type') == 'image':
                return media.get('url')
        
        return None
    
    def _normalize_image_url(self, url: str) -> Optional[str]:
        """Normalize image URL to absolute format."""
        if not url:
            return None
            
        if url.startswith('http'):
            return url
        elif url.startswith('//'):
            return f"https:{url}"
        elif url.startswith('/'):
            return f"https://t.me{url}"
        else:
            return None
    
    def _is_content_image(self, url: str) -> bool:
        """Check if URL is likely a content image (not avatar/profile)."""
        if not url:
            return False
            
        url_lower = url.lower()
        
        # Exclude known avatar/profile patterns
        avatar_patterns = [
            '/userpic/',           # User profile pictures
            '/profile/',           # Profile images
            '/avatar/',            # Avatar images
            '/channel_photo/',     # Channel photos
            '/user_photo/',        # User photos
            '_userpic.',           # Userpic files
            '_avatar.',            # Avatar files
            '_profile.',           # Profile files
        ]
        
        for pattern in avatar_patterns:
            if pattern in url_lower:
                return False
        
        # Check for content image indicators
        content_patterns = [
            '/file/',              # General file storage
            '/photo/',             # Photo files
            '/media/',             # Media files
            '/document/',          # Document files
            '/video/',             # Video files
        ]
        
        for pattern in content_patterns:
            if pattern in url_lower:
                return True
        
        # If no specific pattern matches, assume it's content if it's from telegram CDN
        return 'cdn' in url_lower and 'telegram' in url_lower
    
    def _clean_message_content(self, content: str) -> str:
        """Clean message content from HTML artifacts and weird characters."""
        if not content:
            return ""
        
        import re
        
        # Remove HTML entities
        content = content.replace('&nbsp;', ' ')
        content = content.replace('&amp;', '&')
        content = content.replace('&lt;', '<')
        content = content.replace('&gt;', '>')
        content = content.replace('&quot;', '"')
        content = content.replace('&#39;', "'")
        
        # Remove weird characters and HTML artifacts (keep punctuation incl. dots)
        content = re.sub(r'[^\w\s\.\,\!\?\;\:\-\(\)\[\]\"\'а-яА-ЯёЁ\d\+\=\#\@\%\&\*\/\\\|]', '', content, flags=re.UNICODE)
        
        # Remove specific patterns that cause issues
        content = re.sub(r'!!!"?>', '', content)  # Remove the specific artifact seen in screenshot
        content = re.sub(r'<[^>]*>', '', content)  # Remove any remaining HTML tags
        # Normalize whitespace but preserve paragraph breaks
        content = content.replace('\r\n', '\n')
        content = re.sub(r'\n{3,}', '\n\n', content)
        content = re.sub(r'[ \t]+', ' ', content)
        
        # Fix numeric ranges that got split across lines (e.g., "15\n20%" -> "15-20%")
        content = re.sub(r'(\d+)\s*\n\s*(\d+%)', r'\1-\2', content)
        content = re.sub(r'(\d+)\s*\n\s*(\d+)', r'\1-\2', content)  # General number-number pairs
        content = re.sub(r'(\d+)\s*\n\s*-\s*(\d+)', r'\1-\2', content)  # Cases with existing dash
        
        # Remove navigation text
        content = re.sub(r'Please open Telegram to view this post.*?VIEW IN TELEGRAM', '', content, flags=re.IGNORECASE)
        content = re.sub(r'\d+\s+views?\s+\d{2}:\d{2}', '', content)  # Remove "X views XX:XX"
        
        return content.strip()
    
    def _extract_media_info(self, message_div) -> Dict[str, Any]:
        """Extract comprehensive media information from message."""
        media_info = {
            'video_url': None,
            'document_url': None,
            'audio_url': None,
            'sticker_url': None,
            'poll_data': None,
            'location_data': None,
            'media_type': None,
            'duration': None,
            'file_size': None,
            'file_name': None
        }
        
        # Video extraction
        video_selectors = [
            'video[src]',
            '.video-message video',
            '.media-video video',
            'source[src]'
        ]
        
        for selector in video_selectors:
            video = message_div.select_one(selector)
            if video and video.get('src'):
                media_info['video_url'] = self._normalize_image_url(video['src'])
                media_info['media_type'] = 'video'
                if video.get('duration'):
                    media_info['duration'] = video['duration']
                break
        
        # Document/file extraction
        doc_selectors = [
            'a[href*="/file/"]',
            '.document a[href]',
            '.attachment a[href]',
            '.file-download a[href]'
        ]
        
        for selector in doc_selectors:
            doc_link = message_div.select_one(selector)
            if doc_link and doc_link.get('href'):
                media_info['document_url'] = self._normalize_image_url(doc_link['href'])
                media_info['media_type'] = 'document'
                
                # Try to extract file name
                file_name_element = doc_link.select_one('.file-name, .document-name')
                if file_name_element:
                    media_info['file_name'] = file_name_element.get_text(strip=True)
                
                # Try to extract file size
                file_size_element = message_div.select_one('.file-size, .document-size')
                if file_size_element:
                    media_info['file_size'] = file_size_element.get_text(strip=True)
                break
        
        # Audio extraction
        audio_selectors = [
            'audio[src]',
            '.audio-message audio',
            '.voice-message audio'
        ]
        
        for selector in audio_selectors:
            audio = message_div.select_one(selector)
            if audio and audio.get('src'):
                media_info['audio_url'] = self._normalize_image_url(audio['src'])
                media_info['media_type'] = 'audio'
                if audio.get('duration'):
                    media_info['duration'] = audio['duration']
                break
        
        # Sticker extraction
        sticker = message_div.select_one('.sticker img, .animated-sticker img')
        if sticker and sticker.get('src'):
            media_info['sticker_url'] = self._normalize_image_url(sticker['src'])
            media_info['media_type'] = 'sticker'
        
        # Poll extraction
        poll = message_div.select_one('.poll, .quiz')
        if poll:
            poll_question = poll.select_one('.poll-question, .quiz-question')
            poll_options = poll.select('.poll-option, .quiz-option')
            
            if poll_question:
                media_info['poll_data'] = {
                    'question': poll_question.get_text(strip=True),
                    'options': [opt.get_text(strip=True) for opt in poll_options],
                    'type': 'quiz' if 'quiz' in poll.get('class', []) else 'poll'
                }
                media_info['media_type'] = 'poll'
        
        # Location extraction
        location = message_div.select_one('.location, .venue')
        if location:
            location_text = location.get_text(strip=True)
            # Try to extract coordinates from data attributes or href
            location_link = location.select_one('a[href*="maps.google.com"], a[href*="openstreetmap.org"]')
            
            media_info['location_data'] = {
                'text': location_text,
                'url': location_link['href'] if location_link else None
            }
            media_info['media_type'] = 'location'
        
        return media_info
    
    def _extract_title(self, text: str) -> str:
        """Extract title from message text."""
        lines = [ln.strip() for ln in text.split('\n') if ln.strip()]
        first_line = lines[0].strip()
        
        # Remove common Telegram emojis and formatting
        first_line = re.sub(r'^[📰📢🔥⚡️💥🎯📊📈📉🚀🗞️📡⭐️✨🎉🎊💫🌟]+\s*', '', first_line)
        first_line = re.sub(r'^(BREAKING|NEWS|UPDATE|URGENT):\s*', '', first_line, flags=re.IGNORECASE)
        
        # Prefer first informative line, otherwise fallback to combined short text
        if len(first_line) >= 20:
            return self._smart_truncate_title(first_line)
        
        # Try next lines to avoid too-short titles
        for ln in lines[1:3]:
            if len(ln) >= 20:
                return self._smart_truncate_title(ln)
        
        cleaned_text = re.sub(r'^[📰📢🔥⚡️💥🎯📊📈📉🚀🗞️📡⭐️✨🎉🎊💫🌟]+\s*', '', ' '.join(lines))
        return self._smart_truncate_title(cleaned_text)
    
    def _smart_truncate_title(self, title: str) -> str:
        """Smart title truncation that preserves readability."""
        if not title:
            return title
        
        # Find first sentence (ends with period, exclamation, or question mark)
        first_sentence_match = re.search(r'^[^.!?]*[.!?]', title)
        if first_sentence_match:
            first_sentence = first_sentence_match.group(0).strip()
            # If first sentence is reasonable length (at least 20 chars), use it
            if len(first_sentence) >= 20:
                return first_sentence
        
        # If no sentence boundary or too short, return full title
        # (most Telegram titles are single sentences anyway)
        return title
    
    async def test_connection(self) -> bool:
        """Test Telegram channel connection."""
        try:
            headers = random.choice(self.BROWSER_HEADERS)
            
            for url in self.access_urls:
                try:
                    async with get_http_client() as client:
                        response = await client.get(url, headers=headers)
                        async with response:
                            if response.status == 200:
                                return True
                except:
                    continue
            
            return False
                    
        except Exception:
            return False
    
    # ============================================================================
    # DEPRECATED: _apply_advertising_detection() - Replaced by combined analysis
    # ============================================================================
    # This method has been replaced by the combined analysis approach in orchestrator
    # which does advertising detection along with summarization and categorization
    # in a single AI API call, reducing requests by ~75%.
    #
    # async def _apply_advertising_detection(self, articles: List[Article]) -> List[Article]:
    #     """DEPRECATED: Use combined analysis in orchestrator instead."""
    #     # Method body commented out - was doing separate AI advertising detection
    #     # Now handled by analyze_article_complete() in orchestrator
    #     pass

    async def cleanup(self):
        """Clean up resources (browser, etc.)."""
        if self.browser:
            try:
                await self.browser.close()
                self.browser = None
                print("🧹 Browser cleaned up successfully")
            except Exception as e:
                print(f"⚠️ Error cleaning up browser: {e}")
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.cleanup() 