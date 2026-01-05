"""Modern modular Telegram source using specialized components."""

import re
import random
from datetime import datetime, timedelta
import logging
import pytz
import asyncio
from typing import AsyncGenerator, Optional, Dict, List, Any
from bs4 import BeautifulSoup

from ..sources.base import BaseSource, Article
from ..core.http_client import get_http_client
from ..core.exceptions import SourceError
from .message_parser import MessageParser
from .media_extractor import MediaExtractor

try:
    from playwright.async_api import async_playwright, Browser, Page
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


class TelegramSource(BaseSource):
    """Modern Telegram public channel source with modular architecture."""
    
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
        self._playwright = None
        
        # Initialize modular components
        self.message_parser = MessageParser(self.name, self.channel_username)
        self.media_extractor = MediaExtractor()
        
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
        
        # Remove protocol and common prefixes
        url = re.sub(r'^https?://', '', url)
        url = re.sub(r'^(www\.)?', '', url)
        
        # Extract username from different URL patterns
        patterns = [
            r't\.me/s/([^/?]+)',        # t.me/s/username
            r't\.me/([^/?]+)',          # t.me/username
            r'telegram\.me/s/([^/?]+)', # telegram.me/s/username
            r'telegram\.me/([^/?]+)',   # telegram.me/username
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                username = match.group(1)
                # Clean username
                username = username.split('?')[0]  # Remove query params
                username = username.split('#')[0]  # Remove fragments
                return username
        
        # If no pattern matches, assume the entire cleaned URL is the username
        username = url.split('/')[0].split('?')[0].split('#')[0]
        return username
    
    async def fetch_articles(self, limit: Optional[int] = None) -> AsyncGenerator[Article, None]:
        """Fetch articles from Telegram channel using multiple methods."""
        print(f"🔍 Fetching from Telegram: @{self.channel_username} (limit: {limit})")
        
        articles_found = 0
        last_error = None
        
        # Try browser first for better media extraction (JS widgets)
        if PLAYWRIGHT_AVAILABLE:
            try:
                print("  🎭 Trying browser access for comprehensive media extraction...")
                async for article in self._fetch_with_browser():
                    articles_found += 1
                    yield article
                    if limit and articles_found >= limit:
                        break
                
                if articles_found > 0:
                    print(f"  ✅ Browser method successful - found {articles_found} articles")
                    return
                    
            except Exception as e:
                last_error = e
                print(f"  ❌ Browser method failed: {e}")
        
        # Try HTTP as fallback
        try:
            print("  📡 Trying HTTP access as fallback...")
            async for article in self._fetch_with_http():
                articles_found += 1
                yield article
                if limit and articles_found >= limit:
                    break
            
            if articles_found > 0:
                print(f"  ✅ HTTP method successful - found {articles_found} articles")
                return
                
        except Exception as e:
            last_error = e
            print(f"  ❌ HTTP method failed: {e}")
        
        if articles_found == 0:
            error_msg = f"All access methods failed for @{self.channel_username}"
            if last_error:
                error_msg += f". Last error: {last_error}"
            raise SourceError(error_msg)
    
    async def _fetch_with_http(self) -> AsyncGenerator[Article, None]:
        """Fetch articles using HTTP requests."""
        import aiohttp
        
        async with aiohttp.ClientSession() as session:
            for url in self.access_urls:
                try:
                    headers = random.choice(self.BROWSER_HEADERS)
                    
                    async with session.get(url, headers=headers, timeout=30) as response:
                        if response.status == 200:
                            html = await response.text()
                            articles = await self._parse_html(html, url)
                            
                            for article in articles:
                                yield article
                            
                            if articles:
                                return  # Success with this URL
                        else:
                            print(f"  ⚠️ HTTP {response.status} for {url}")
                            
                except Exception as e:
                    print(f"  ❌ HTTP error for {url}: {e}")
                    continue
        
        raise SourceError("All HTTP methods failed")
    
    async def _fetch_with_browser(self) -> AsyncGenerator[Article, None]:
        """Fetch articles using browser automation."""
        if not PLAYWRIGHT_AVAILABLE:
            raise SourceError("Playwright not available for browser access")
        
        try:
            if not self.browser:
                self._playwright = await async_playwright().start()
                self.browser = await self._playwright.chromium.launch(headless=True)
            
            context = await self.browser.new_context()
            page = await context.new_page()
            
            for url in self.access_urls:
                try:
                    await page.goto(url, timeout=30000)
                    
                    # Wait for content to load
                    await page.wait_for_selector('.tgme_widget_message', timeout=10000)
                    
                    # Enhanced scrolling strategy to load fresh messages
                    try:
                        print("  🔄 Enhanced scrolling to load latest messages...")
                        
                        # First scroll to bottom to trigger loading more recent messages
                        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        await asyncio.sleep(3)
                        
                        # Scroll to top (most recent messages)
                        await page.evaluate("window.scrollTo(0, 0)")
                        await asyncio.sleep(2)
                        
                        # Multiple cycles of scrolling to ensure we get latest content
                        for i in range(3):
                            await page.evaluate("window.scrollBy(0, -1000)")  # Scroll up
                            await asyncio.sleep(1)
                            await page.evaluate("window.scrollTo(0, 0)")      # Back to top
                            await asyncio.sleep(1)
                        
                        print("  ✅ Enhanced scrolling completed")
                    except Exception as scroll_error:
                        print(f"  ⚠️ Scrolling failed: {scroll_error}")
                        pass
                    
                    # Get HTML content
                    html = await page.content()
                    articles = await self._parse_html(html, url)
                    
                    for article in articles:
                        yield article
                    
                    if articles:
                        await context.close()
                        return  # Success with this URL
                        
                except Exception as e:
                    print(f"  ❌ Browser error for {url}: {e}")
                    continue
            
            await context.close()
            raise SourceError("All browser methods failed")
            
        except Exception as e:
            if self.browser:
                await self.browser.close()
                self.browser = None
            if self._playwright:
                await self._playwright.stop()
                self._playwright = None
            raise SourceError(f"Browser access failed: {e}")
    
    async def _parse_html(self, html: str, base_url: str) -> List[Article]:
        """Parse HTML content and extract articles using modular components."""
        soup = BeautifulSoup(html, 'html.parser')
        articles = []
        
        # Find message containers
        message_selectors = [
            '.tgme_widget_message',
            '.message',
            '[data-post]'
        ]
        
        messages = []
        for selector in message_selectors:
            messages = soup.select(selector)
            if messages:
                break
        
        if not messages:
            print(f"  ⚠️ No messages found in HTML")
            return articles
        
        print(f"  📊 Found {len(messages)} messages to parse")
        
        for i, message_div in enumerate(messages):
            try:
                # Use modular message parser with soup for Open Graph extraction
                article = await self.message_parser.parse_message_element(message_div, base_url, soup)
                if article:
                    articles.append(article)
                    if len(articles) % 5 == 0:  # Progress indicator
                        print(f"  ✅ Parsed {len(articles)} articles...")
            except Exception as e:
                print(f"  ⚠️ Error parsing message {i+1}: {e}")
                continue
        
        print(f"  🎯 Successfully parsed {len(articles)}/{len(messages)} messages")
        return articles
    
    def _normalize_external_url(self, url: str) -> Optional[str]:
        """Normalize external URL (delegated to message parser)."""
        return self.message_parser._normalize_external_url(url)
    
    async def test_connection(self) -> bool:
        """Test Telegram channel connection."""
        try:
            headers = random.choice(self.BROWSER_HEADERS)
            
            import aiohttp
            
            async with aiohttp.ClientSession() as session:
                for url in self.access_urls:
                    try:
                        async with session.get(url, headers=headers) as response:
                            if response.status == 200:
                                return True
                    except:
                        continue
            
            return False
                    
        except Exception:
            return False
    
    async def close(self):
        """Clean up resources."""
        if self.browser:
            try:
                await self.browser.close()
            except Exception as e:
                print(f"Error closing browser: {e}")
            finally:
                self.browser = None
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception as e:
                print(f"Error stopping Playwright: {e}")
            finally:
                self._playwright = None
