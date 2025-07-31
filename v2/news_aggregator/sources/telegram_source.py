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
        """Fetch messages from public Telegram channel with multiple fallbacks."""
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
        
        # Sort by date and yield
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
        
        if not messages:
            # Try to find any div with text content as fallback
            print("No standard message containers found, trying fallback...")
            return []
        
        for message in messages:
            try:
                article = self._parse_message_element(message, base_url)
                if article:
                    articles.append(article)
            except Exception as e:
                print(f"Error parsing message: {e}")
                continue
        
        return articles
    
    def _parse_message_element(self, message_div, base_url: str) -> Optional[Article]:
        """Parse message div element into Article."""
        try:
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
                    # Use separator to preserve spaces between elements
                    content = text_element.get_text(separator=' ', strip=True)
                    break
            
            # If no specific text element, try to get all text
            if not content:
                content = message_div.get_text(separator=' ', strip=True)
            
            if len(content) < 10:
                return None
            
            # Extract message URL
            message_url = self._extract_message_url(message_div, base_url)
            
            # Extract date
            published_at = self._extract_date(message_div)
            
            # Extract image and media info
            image_url = self._extract_image_url(message_div)
            media_info = self._extract_media_info(message_div)
            
            # Extract title
            title = self._extract_title(content)
            
            return Article(
                title=title,
                url=message_url,
                content=content,
                published_at=published_at,
                source_type="telegram",
                source_name=self.name,
                image_url=image_url,
                raw_data={
                    "channel": self.channel_username,
                    "access_method": base_url,
                    "content_length": len(content),
                    "media_info": media_info,
                    "has_media": bool(image_url or media_info.get('video_url') or media_info.get('document_url'))
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
    
    def _extract_image_url(self, message_div) -> Optional[str]:
        """Extract image URL from message div with enhanced media support."""
        # Enhanced image selectors
        img_selectors = [
            'img[src]',                    # Standard images
            '.media img',                  # Media container images
            '.photo img',                  # Photo-specific images
            '.video-thumb img',            # Video thumbnails
            '.document-thumb img',         # Document thumbnails
            'a[style*="background-image"] img',  # Background image links
            '.attachment img',             # Attachment images
            '.preview img'                 # Preview images
        ]
        
        image_urls = []
        
        for selector in img_selectors:
            imgs = message_div.select(selector)
            for img in imgs:
                src = img.get('src') or img.get('data-src') or img.get('data-lazy-src')
                if src:
                    # Clean and normalize URL
                    if src.startswith('http'):
                        image_urls.append(src)
                    elif src.startswith('//'):
                        image_urls.append(f"https:{src}")
                    elif src.startswith('/'):
                        image_urls.append(f"https://t.me{src}")
        
        # Also check for background-image in style attributes
        style_elements = message_div.select('[style*="background-image"]')
        for element in style_elements:
            style = element.get('style', '')
            # Extract URL from background-image: url(...)
            import re
            bg_matches = re.findall(r'background-image:\s*url\(["\']?(.*?)["\']?\)', style)
            for match in bg_matches:
                if match.startswith('http'):
                    image_urls.append(match)
                elif match.startswith('//'):
                    image_urls.append(f"https:{match}")
        
        # Return the first valid high-quality image
        for url in image_urls:
            # Prefer full-size images over thumbnails
            if 'thumb' not in url.lower() and 'preview' not in url.lower():
                return url
        
        # Fallback to any image
        return image_urls[0] if image_urls else None
    
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
                media_info['video_url'] = self._normalize_url(video['src'])
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
                media_info['document_url'] = self._normalize_url(doc_link['href'])
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
                media_info['audio_url'] = self._normalize_url(audio['src'])
                media_info['media_type'] = 'audio'
                if audio.get('duration'):
                    media_info['duration'] = audio['duration']
                break
        
        # Sticker extraction
        sticker = message_div.select_one('.sticker img, .animated-sticker img')
        if sticker and sticker.get('src'):
            media_info['sticker_url'] = self._normalize_url(sticker['src'])
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
    
    def _normalize_url(self, url: str) -> str:
        """Normalize URL to absolute format."""
        if url.startswith('http'):
            return url
        elif url.startswith('//'):
            return f"https:{url}"
        elif url.startswith('/'):
            return f"https://t.me{url}"
        else:
            return url
    
    def _extract_title(self, text: str) -> str:
        """Extract title from message text."""
        lines = text.split('\n')
        first_line = lines[0].strip()
        
        # Remove common Telegram emojis and formatting
        first_line = re.sub(r'^[📰📢🔥⚡️💥🎯📊📈📉🚀🗞️📡⭐️✨🎉🎊💫🌟]+\s*', '', first_line)
        first_line = re.sub(r'^(BREAKING|NEWS|UPDATE|URGENT):\s*', '', first_line, flags=re.IGNORECASE)
        
        if len(first_line) > 15:
            return first_line[:120] + ("..." if len(first_line) > 120 else "")
        else:
            # Use full text if first line is too short
            cleaned_text = re.sub(r'^[📰📢🔥⚡️💥🎯📊📈📉🚀🗞️📡⭐️✨🎉🎊💫🌟]+\s*', '', text)
            return cleaned_text[:120] + ("..." if len(cleaned_text) > 120 else "")
    
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