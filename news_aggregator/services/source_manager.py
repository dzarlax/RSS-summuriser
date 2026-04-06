import logging
"""Source manager for handling multiple news sources."""

import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from ..models import Source, Article
from ..sources import get_source_registry, BaseSource, SourceInfo, SourceType
from ..core.exceptions import SourceError

logger = logging.getLogger(__name__)


class SourceManager:
    """Manager for news sources."""
    
    def __init__(self):
        self.source_registry = get_source_registry()
        self._source_instances: Dict[int, BaseSource] = {}
    
    async def create_source(self, db: AsyncSession, name: str, source_type: str, 
                           url: str, config: Optional[Dict[str, Any]] = None) -> Source:
        """Create new source in database."""
        try:
            # Validate source type
            source_type_enum = SourceType(source_type)
            if not self.source_registry.is_supported(source_type_enum):
                raise SourceError(f"Unsupported source type: {source_type}")
            
            # Create source record
            source = Source(
                name=name,
                source_type=source_type,
                url=url,
                config=config or {},
                enabled=True
            )
            
            db.add(source)
            await db.commit()
            await db.refresh(source)
            
            # Test connection
            source_instance = self._create_source_instance(source)
            if not await source_instance.test_connection():
                source.enabled = False
                source.last_error = "Failed connection test"
                source.error_count = 1
                await db.commit()
            
            return source
        
        except Exception as e:
            await db.rollback()
            raise SourceError(f"Failed to create source: {e}")
    
    async def get_sources(self, db: AsyncSession, enabled_only: bool = False) -> List[Source]:
        """Get all sources from database."""
        query = select(Source)
        if enabled_only:
            query = query.where(Source.enabled == True)
        
        result = await db.execute(query)
        return result.scalars().all()
    
    async def get_source_by_id(self, db: AsyncSession, source_id: int) -> Optional[Source]:
        """Get source by ID."""
        result = await db.execute(select(Source).where(Source.id == source_id))
        return result.scalar_one_or_none()
    
    async def update_source(self, db: AsyncSession, source_id: int, **updates) -> Optional[Source]:
        """Update source."""
        try:
            source = await self.get_source_by_id(db, source_id)
            if not source:
                return None
            for key, value in updates.items():
                if hasattr(source, key):
                    setattr(source, key, value)
            source.updated_at = datetime.utcnow()
            await db.commit()
            await db.refresh(source)
            if source_id in self._source_instances:
                del self._source_instances[source_id]
            return source
        except Exception as e:
            await db.rollback()
            raise SourceError(f"Failed to update source {source_id}: {e}")
    
    async def delete_source(self, db: AsyncSession, source_id: int, delete_articles: bool = False) -> bool:
        """
        Delete source and optionally its articles.
        
        Args:
            db: Database session
            source_id: ID of source to delete
            delete_articles: Whether to delete associated articles
        """
        try:
            source = await self.get_source_by_id(db, source_id)
            if not source:
                return False
                
            # Check if source has articles
            from ..models import Article
            from sqlalchemy import select, func, delete
            
            # If delete_articles is requested, remove them first
            if delete_articles:
                await db.execute(delete(Article).where(Article.source_id == source_id))
            
            # Delete source
            await db.delete(source)
            await db.commit()
            
            # Cleanup in-memory instance
            if source_id in self._source_instances:
                del self._source_instances[source_id]
                
            return True
        except Exception as e:
            await db.rollback()
            raise SourceError(f"Failed to delete source {source_id}: {e}")
    
    def _create_source_instance(self, source: Source) -> BaseSource:
        """Create source instance from database record."""
        source_info = SourceInfo(
            name=source.name,
            source_type=SourceType(source.source_type),
            url=source.url,
            description=f"Source: {source.name}",
            enabled=source.enabled,
            config=source.config
        )
        
        return self.source_registry.create_source(source_info)
    
    async def get_source_instance(self, source: Source) -> BaseSource:
        """Get cached source instance."""
        if source.id not in self._source_instances:
            self._source_instances[source.id] = self._create_source_instance(source)
        
        return self._source_instances[source.id]
    
    async def test_source_connection(self, db: AsyncSession, source_id: int) -> bool:
        """Test source connection."""
        source = await self.get_source_by_id(db, source_id)
        if not source:
            return False
        
        try:
            source_instance = await self.get_source_instance(source)
            is_connected = await source_instance.test_connection()
            
            # Update source status
            if is_connected:
                source.last_success = datetime.utcnow()
                source.error_count = 0
                source.last_error = None
            else:
                source.error_count += 1
                source.last_error = "Connection test failed"
            
            try:
                await db.commit()
            except Exception as e:
                await db.rollback()
                raise SourceError(f"Failed to update source status {source_id}: {e}")
            return is_connected
        
        except Exception as e:
            source.error_count += 1
            source.last_error = str(e)
            try:
                await db.commit()
            except Exception:
                await db.rollback()
            return False
    
    async def get_sources_from_db(self) -> List[Source]:
        """Quick fetch of enabled sources from database."""
        from sqlalchemy import select
        from ..database_helpers import fetch_all

        # Define query
        query = select(Source).where(Source.enabled == True)

        # Fetch using database queue
        return await fetch_all(query)

    async def fetch_from_all_sources_no_db(self, sources: List[Source],
                                           max_concurrent: int = 5) -> Dict[str, List[Article]]:
        """
        Fetch articles from sources via HTTP - NO DATABASE ACCESS.
        This is purely I/O bound HTTP fetching, no semaphore locks.
        """
        results = {}

        # Create semaphore to limit concurrent fetches
        semaphore = asyncio.Semaphore(max_concurrent)

        async def fetch_source_raw(source: Source):
            """Fetch articles from source without DB access."""
            async with semaphore:
                try:
                    source_instance = await self.get_source_instance(source)
                    articles = []

                    async for article in source_instance.fetch_articles():
                        articles.append(article)

                    return source.name, articles
                except Exception as e:
                    logger.info(f"Error fetching from {source.name}: {e}")
                    return source.name, []

        # Execute fetches concurrently (HTTP only, no DB lock)
        tasks = [fetch_source_raw(source) for source in sources]
        fetch_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        for result in fetch_results:
            if isinstance(result, Exception):
                logger.info(f"Fetch task failed: {result}")
                continue

            source_name, articles = result
            results[source_name] = articles

        return results

    @staticmethod
    def _collect_candidate_urls(article) -> List[str]:
        """Build URL list from article.url + raw_data telegram/original links."""
        urls = [article.url]
        try:
            raw = getattr(article, 'raw_data', None)
            if raw:
                telegram_url = raw.get('telegram_url') or raw.get('message_url')
                original_link = raw.get('original_link')
                for u in (telegram_url, original_link):
                    if u and u not in urls:
                        urls.append(u)
        except Exception as e:
            logger.debug(f"Error collecting candidate URLs: {e}")
        return urls

    @staticmethod
    def _is_batch_duplicate(urls: List[str], title: str,
                            seen_urls: set, seen_titles: set) -> bool:
        """Check in-memory batch-level dedup by URLs and title."""
        if any(u in seen_urls for u in urls if u):
            return True
        if title and title in seen_titles:
            return True
        return False

    @staticmethod
    async def _check_db_duplicate(db: AsyncSession, urls: List[str]) -> Optional[Article]:
        """Check if any of the candidate URLs already exist in DB."""
        result = await db.execute(
            select(Article).where(Article.url.in_(urls)).limit(1)
        )
        return result.scalars().first()

    @staticmethod
    async def _check_title_duplicate(db: AsyncSession, source_id: int, title: str) -> bool:
        """Check for near-duplicate by title within the same source (7-day window)."""
        if not title:
            return False
        try:
            cutoff = datetime.utcnow() - timedelta(days=7)
            result = await db.execute(
                select(Article.id).where(
                    and_(
                        Article.source_id == source_id,
                        func.lower(Article.title) == title,
                        Article.fetched_at >= cutoff,
                    )
                ).limit(1)
            )
            return result.scalars().first() is not None
        except Exception as e:
            logger.debug(f"Error checking title duplicate: {e}")
            return False

    @staticmethod
    def _apply_raw_data_fields(db_article: Article, raw_data) -> None:
        """Apply ad detection and metadata from raw_data to article."""
        try:
            if isinstance(raw_data, dict):
                if 'advertising_detection' in raw_data or 'is_advertisement' in raw_data:
                    db_article.is_advertisement = bool(raw_data.get('is_advertisement', False))
                    if 'ad_confidence' in raw_data:
                        db_article.ad_confidence = float(raw_data.get('ad_confidence') or 0.0)
                    if 'ad_type' in raw_data:
                        db_article.ad_type = raw_data.get('ad_type')
                    if 'ad_reasoning' in raw_data:
                        db_article.ad_reasoning = raw_data.get('ad_reasoning')
                    if 'ad_markers' in raw_data:
                        db_article.ad_markers = raw_data.get('ad_markers')
                    db_article.ad_processed = True
        except Exception as e:
            logger.debug(f"Error applying raw_data fields: {e}")

    @staticmethod
    def _record_in_seen_sets(urls: List[str], title: str,
                             seen_urls: set, seen_titles: set) -> None:
        """Record URLs and title into batch dedup sets."""
        for u in urls:
            if u:
                seen_urls.add(u)
        if title:
            seen_titles.add(title)

    async def save_fetched_articles_with_sources(self, raw_articles: Dict[str, List[Article]],
                                                  source_map: Dict[str, Source], db: AsyncSession) -> Dict[str, List[Article]]:
        """
        Save fetched articles to database using provided source mapping.
        This is pure DB writes, no HTTP fetching.
        """
        results = {}

        for source_name, articles in raw_articles.items():
            try:
                source = source_map.get(source_name)
                if not source:
                    logger.info(f"Source {source_name} not found in mapping, skipping save")
                    results[source_name] = []
                    continue

                source.last_fetch = datetime.utcnow()
                saved_articles = []
                seen_urls: set[str] = set()
                seen_titles: set[str] = set()

                for article in articles:
                    urls = self._collect_candidate_urls(article)
                    normalized_title = (article.title or "").strip().lower()

                    # In-memory batch dedup
                    if self._is_batch_duplicate(urls, normalized_title, seen_urls, seen_titles):
                        logger.warning(f"  [DEDUP] Batch duplicate skipped: {normalized_title[:60]}")
                        continue

                    # DB URL dedup
                    existing = await self._check_db_duplicate(db, urls)
                    if existing is not None:
                        if existing.summary and existing.processed:
                            logger.warning(f"  [DEDUP] DB URL duplicate skipped: {existing.url[:80]} (title: {normalized_title[:60]})")
                            continue

                        # Update existing unprocessed article
                        logger.info(f"  🔄 Updating existing unprocessed article: {existing.url[:50]}...")
                        existing.title = article.title or existing.title
                        existing.content = article.content or existing.content
                        existing.url = article.url or existing.url
                        existing.image_url = article.image_url or existing.image_url
                        existing.published_at = article.published_at or existing.published_at
                        existing.hash_content = self._calculate_content_hash(article) or existing.hash_content
                        saved_articles.append(existing)
                        self._record_in_seen_sets(urls, normalized_title, seen_urls, seen_titles)
                        continue

                    # DB title dedup (same source, 7-day window)
                    if await self._check_title_duplicate(db, source.id, normalized_title):
                        logger.warning(f"  [DEDUP] Title duplicate skipped: {normalized_title[:60]}")
                        continue

                    # Create new article
                    db_article = Article(
                        source_id=source.id,
                        title=article.title,
                        url=article.url,
                        content=article.content,
                        summary=article.summary,
                        image_url=article.image_url,
                        media_files=article.media_files or [],
                        published_at=article.published_at,
                        processed=False,
                        hash_content=self._calculate_content_hash(article)
                    )
                    self._apply_raw_data_fields(db_article, getattr(article, 'raw_data', None))

                    db.add(db_article)
                    saved_articles.append(db_article)
                    self._record_in_seen_sets(urls, normalized_title, seen_urls, seen_titles)

                results[source_name] = saved_articles

            except Exception as e:
                logger.info(f"Error saving articles for {source_name}: {e}")
                results[source_name] = []

        return results

    def _calculate_content_hash(self, article) -> str:
        """Calculate hash for article content (for deduplication)."""
        import hashlib
        
        content = f"{article.title}:{article.url}"
        return hashlib.sha256(content.encode()).hexdigest()
    
    async def get_source_stats(self, db: AsyncSession) -> Dict[str, Any]:
        """Get statistics about sources."""
        # Get all sources
        all_sources = await self.get_sources(db)
        enabled_sources = [s for s in all_sources if s.enabled]
        
        # Get article counts
        from sqlalchemy import func
        article_counts = await db.execute(
            select(Source.name, func.count(Article.id).label('count'))
            .outerjoin(Article)
            .group_by(Source.id, Source.name)
        )
        
        source_article_counts = {name: count for name, count in article_counts}
        
        return {
            'total_sources': len(all_sources),
            'enabled_sources': len(enabled_sources),
            'disabled_sources': len(all_sources) - len(enabled_sources),
            'sources_with_errors': len([s for s in all_sources if s.error_count > 0]),
            'article_counts_by_source': source_article_counts,
            'supported_source_types': [t.value for t in self.source_registry.get_supported_types()]
        }