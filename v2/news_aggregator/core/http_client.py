"""Async HTTP client with connection pooling and rate limiting."""

import asyncio
import hashlib
import time
from typing import Dict, Optional, Any
from contextlib import asynccontextmanager

import aiohttp
from aiohttp import ClientTimeout, ClientError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from ..config import settings


class RateLimiter:
    """Rate limiter for API calls."""
    
    def __init__(self, max_calls: int, time_window: float = 1.0):
        self.max_calls = max_calls
        self.time_window = time_window
        self.calls = []
        self.lock = asyncio.Lock()
    
    async def acquire(self):
        """Acquire permission to make a call."""
        async with self.lock:
            now = time.time()
            # Remove old calls outside the time window
            self.calls = [call_time for call_time in self.calls if now - call_time < self.time_window]
            
            if len(self.calls) >= self.max_calls:
                # Wait until we can make another call
                sleep_time = self.time_window - (now - self.calls[0])
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
                    return await self.acquire()
            
            self.calls.append(now)


class AsyncHTTPClient:
    """Async HTTP client with rate limiting and connection pooling."""
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.rate_limiter = RateLimiter(max_calls=settings.api_rate_limit, time_window=1.0)
        
        # Connection configuration
        self.timeout = ClientTimeout(total=30, connect=10)
        self.connector = aiohttp.TCPConnector(
            limit=20,  # Total connection pool size
            limit_per_host=5,  # Connections per host
            ttl_dns_cache=300,  # DNS cache TTL
            use_dns_cache=True,
        )
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self.start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
    
    async def start(self):
        """Start the HTTP client session."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                connector=self.connector,
                timeout=self.timeout,
                headers={
                    'User-Agent': 'RSS-Summarizer-v2/2.0.0',
                }
            )
    
    async def close(self):
        """Close the HTTP client session."""
        if self.session and not self.session.closed:
            await self.session.close()
        if self.connector:
            await self.connector.close()
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((ClientError, asyncio.TimeoutError))
    )
    async def get(self, url: str, headers: Optional[Dict[str, str]] = None, **kwargs) -> aiohttp.ClientResponse:
        """Make GET request with retries."""
        if not self.session or self.session.closed:
            await self.start()
        
        return await self.session.get(url, headers=headers, **kwargs)
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((ClientError, asyncio.TimeoutError))
    )
    async def post(self, url: str, data: Any = None, json: Any = None, 
                   headers: Optional[Dict[str, str]] = None, **kwargs) -> aiohttp.ClientResponse:
        """Make POST request with retries."""
        if not self.session or self.session.closed:
            await self.start()
        
        # Apply rate limiting for POST requests (usually API calls)
        await self.rate_limiter.acquire()
        
        return await self.session.post(url, data=data, json=json, headers=headers, **kwargs)
    
    async def fetch_text(self, url: str, **kwargs) -> str:
        """Fetch URL and return text content."""
        async with await self.get(url, **kwargs) as response:
            response.raise_for_status()
            return await response.text()
    
    async def fetch_json(self, url: str, **kwargs) -> Dict[str, Any]:
        """Fetch URL and return JSON content."""
        async with await self.get(url, **kwargs) as response:
            response.raise_for_status()
            return await response.json()


# Global HTTP client instance
http_client = None


@asynccontextmanager
async def get_http_client():
    """Get HTTP client context manager."""
    global http_client
    
    if http_client is None:
        http_client = AsyncHTTPClient()
    
    if not http_client.session or http_client.session.closed:
        await http_client.start()
    try:
        yield http_client
    finally:
        # Don't close here - let it be reused
        pass