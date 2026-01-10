"""Category cache service for managing valid categories from database."""

from typing import List, Optional
import asyncio
import time

from ..database import AsyncSessionLocal
from ..models import Category
from sqlalchemy import select


class CategoryCache:
    """
    Thread-safe cache for valid categories with automatic refresh.
    Categories are cached for 5 minutes to balance freshness and performance.
    """

    def __init__(self, ttl: int = 300):
        """
        Initialize category cache.

        Args:
            ttl: Time to live for cache in seconds (default: 5 minutes)
        """
        self._cache: Optional[List[str]] = None
        self._cache_time: Optional[float] = None
        self._ttl = ttl
        self._lock = asyncio.Lock()

    async def get_categories(self, force_refresh: bool = False) -> List[str]:
        """
        Get valid categories from cache or database.

        Args:
            force_refresh: Force cache refresh even if not expired

        Returns:
            List of category names
        """
        async with self._lock:
            # Check if cache is valid
            if not force_refresh and self._is_cache_valid():
                return self._cache

            # Refresh from database
            categories = await self._load_from_db()

            if categories:
                self._cache = categories
                self._cache_time = time.time()
                return categories
            else:
                # Return cached values even if expired if DB load fails
                if self._cache:
                    return self._cache
                # Ultimate fallback to hardcoded list
                return self._get_fallback_categories()

    def _is_cache_valid(self) -> bool:
        """Check if cache is still valid."""
        if self._cache is None:
            return False

        if self._cache_time is None:
            return False

        age = time.time() - self._cache_time
        return age < self._ttl

    async def _load_from_db(self) -> Optional[List[str]]:
        """Load categories from database."""
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(Category.name).order_by(Category.name)
                )
                categories = [row[0] for row in result.all()]

                if categories:
                    print(f"  📋 Loaded {len(categories)} categories from database: {categories}")

                return categories
        except Exception as e:
            print(f"  ⚠️ Failed to load categories from database: {e}")
            return None

    def _get_fallback_categories(self) -> List[str]:
        """Get fallback hardcoded categories."""
        categories = ['AI', 'Serbia', 'Tech', 'Business', 'Science', 'Nature', 'Marketing', 'Other']
        print(f"  ⚠️ Using hardcoded fallback categories (DB unavailable): {categories}")
        return categories

    async def invalidate(self):
        """Invalidate cache (force reload on next access)."""
        async with self._lock:
            self._cache = None
            self._cache_time = None


# Global singleton instance
_category_cache: Optional[CategoryCache] = None


def get_category_cache() -> CategoryCache:
    """Get global category cache instance."""
    global _category_cache
    if _category_cache is None:
        _category_cache = CategoryCache()
    return _category_cache
