"""File-based caching system."""

import json
import hashlib
import time
import asyncio
from pathlib import Path
from typing import Any, Optional, Union
import aiofiles

from ..config import settings


class FileCache:
    """File-based cache with TTL support."""
    
    def __init__(self, cache_dir: Union[str, Path] = None, default_ttl: int = None):
        self.cache_dir = Path(cache_dir or settings.cache_dir)
        self.default_ttl = default_ttl or settings.cache_ttl
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
    
    def _get_cache_path(self, key: str) -> Path:
        """Get cache file path for key."""
        key_hash = hashlib.md5(key.encode()).hexdigest()
        return self.cache_dir / f"{key_hash}.json"
    
    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        cache_path = self._get_cache_path(key)
        
        if not cache_path.exists():
            return None
        
        try:
            async with aiofiles.open(cache_path, 'r', encoding='utf-8') as f:
                content = await f.read()
                data = json.loads(content)
            
            # Check TTL
            if time.time() > data.get('expires_at', 0):
                # Cache expired, remove file
                try:
                    cache_path.unlink()
                except FileNotFoundError:
                    pass
                return None
            
            return data.get('value')
        
        except (json.JSONDecodeError, KeyError, FileNotFoundError):
            # Corrupted or missing cache file
            try:
                cache_path.unlink()
            except FileNotFoundError:
                pass
            return None
    
    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Set value in cache."""
        cache_path = self._get_cache_path(key)
        expires_at = time.time() + (ttl or self.default_ttl)
        
        data = {
            'value': value,
            'created_at': time.time(),
            'expires_at': expires_at,
            'key': key  # For debugging
        }
        
        async with self._lock:
            try:
                # Write to temporary file first, then rename (atomic operation)
                temp_path = cache_path.with_suffix('.tmp')
                async with aiofiles.open(temp_path, 'w', encoding='utf-8') as f:
                    await f.write(json.dumps(data, ensure_ascii=False, indent=2))
                
                temp_path.rename(cache_path)
            except Exception as e:
                # Clean up temporary file if it exists
                try:
                    temp_path.unlink()
                except FileNotFoundError:
                    pass
                raise e
    
    async def delete(self, key: str) -> bool:
        """Delete key from cache."""
        cache_path = self._get_cache_path(key)
        try:
            cache_path.unlink()
            return True
        except FileNotFoundError:
            return False
    
    async def clear(self) -> int:
        """Clear all cache files."""
        count = 0
        for cache_file in self.cache_dir.glob("*.json"):
            try:
                cache_file.unlink()
                count += 1
            except FileNotFoundError:
                pass
        return count
    
    async def cleanup_expired(self) -> int:
        """Remove expired cache files."""
        count = 0
        current_time = time.time()
        
        for cache_file in self.cache_dir.glob("*.json"):
            try:
                async with aiofiles.open(cache_file, 'r', encoding='utf-8') as f:
                    content = await f.read()
                    data = json.loads(content)
                
                if current_time > data.get('expires_at', 0):
                    cache_file.unlink()
                    count += 1
            except (json.JSONDecodeError, KeyError, FileNotFoundError):
                # Corrupted file, remove it
                try:
                    cache_file.unlink()
                    count += 1
                except FileNotFoundError:
                    pass
        
        return count
    
    async def get_stats(self) -> dict:
        """Get cache statistics."""
        total_files = 0
        expired_files = 0
        total_size = 0
        current_time = time.time()
        
        for cache_file in self.cache_dir.glob("*.json"):
            total_files += 1
            total_size += cache_file.stat().st_size
            
            try:
                async with aiofiles.open(cache_file, 'r', encoding='utf-8') as f:
                    content = await f.read()
                    data = json.loads(content)
                
                if current_time > data.get('expires_at', 0):
                    expired_files += 1
            except (json.JSONDecodeError, KeyError, FileNotFoundError):
                expired_files += 1
        
        return {
            'total_files': total_files,
            'expired_files': expired_files,
            'active_files': total_files - expired_files,
            'total_size_bytes': total_size,
            'total_size_mb': round(total_size / (1024 * 1024), 2),
            'cache_dir': str(self.cache_dir)
        }


# Global cache instance
file_cache = FileCache()


def cache_key_builder(prefix: str, *args, **kwargs) -> str:
    """Build cache key from arguments."""
    key_parts = [prefix]
    key_parts.extend(str(arg) for arg in args)
    key_parts.extend(f"{k}:{v}" for k, v in sorted(kwargs.items()))
    return ":".join(key_parts)


def cached(ttl: Optional[int] = None, key_prefix: str = "default"):
    """Decorator for caching function results."""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            # Build cache key
            cache_key = cache_key_builder(key_prefix, func.__name__, *args, **kwargs)
            
            # Try to get from cache
            cached_result = await file_cache.get(cache_key)
            if cached_result is not None:
                return cached_result
            
            # Execute function and cache result
            result = await func(*args, **kwargs)
            await file_cache.set(cache_key, result, ttl)
            return result
        
        return wrapper
    return decorator