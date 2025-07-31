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
        
        # Multiple access URLs to try
        self.access_urls = [
            f"https://t.me/s/{self.channel_username}",  # Standard preview
            f"https://telegram.me/s/{self.channel_username}",  # Alternative domain
        ]
    
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
        
        for url in self.access_urls:
            try:
                print(f"Trying URL: {url}")
                articles = await self._fetch_from_url(url, limit)
                articles_found.extend(articles)
                
                if articles_found:
                    break  # Success, no need to try other URLs
                    
            except Exception as e:
                print(f"Failed to fetch from {url}: {e}")
                continue
        
        if not articles_found:
            raise SourceError(f"All access methods failed for channel: {self.channel_username}")
        
        # Sort by date and yield
        articles_found.sort(key=lambda x: x.published_at or datetime.min, reverse=True)
        
        for i, article in enumerate(articles_found):
            if limit and i >= limit:
                break
            yield article
    
    async def _fetch_from_url(self, url: str, limit: Optional[int] = None) -> List[Article]:
        """Fetch articles from specific URL."""
        headers = random.choice(self.BROWSER_HEADERS)
        
        async with get_http_client() as client:
            # Add random delay to look more human
            await asyncio.sleep(random.uniform(1, 3))
            
            response = await client.get(url, headers=headers)
            async with response:
                if response.status == 403:
                    raise SourceError("Access denied (Cloudflare blocked)")
                elif response.status == 404:
                    raise SourceError("Channel not found or private")
                elif response.status != 200:
                    raise SourceError(f"HTTP {response.status}")
                
                html = await response.text()
                return self._parse_html(html, url)
    
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
            
            # Extract image
            image_url = self._extract_image_url(message_div)
            
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
                    "content_length": len(content)
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
        """Extract image URL from message div."""
        img_selectors = [
            'img[src]',
            '.media img',
            '.photo img'
        ]
        
        for selector in img_selectors:
            img = message_div.select_one(selector)
            if img and img.get('src'):
                src = img['src']
                if src.startswith('http'):
                    return src
                elif src.startswith('//'):
                    return f"https:{src}"
        
        return None
    
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