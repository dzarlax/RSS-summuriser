"""Source manager for handling multiple news sources."""

import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from ..models import Source, Article
from ..sources import get_source_registry, BaseSource, SourceInfo, SourceType
from ..core.exceptions import SourceError
from ..database import get_db


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
    
    async def fetch_from_source(self, db: AsyncSession, source: Source, 
                               limit: Optional[int] = None) -> List[Article]:
        """Fetch articles from a single source."""
        try:
            source_instance = await self.get_source_instance(source)
            articles = []
            # In-memory deduplication for current batch
            seen_urls_in_batch: set[str] = set()
            seen_titles_in_batch: set[str] = set()
            
            # Update fetch time
            source.last_fetch = datetime.utcnow()
            
            async for article in source_instance.fetch_articles(limit=limit):
                # Check if article already exists
                urls_to_check = [article.url]
                try:
                    if getattr(article, 'raw_data', None):
                        telegram_url = article.raw_data.get('telegram_url') or article.raw_data.get('message_url')
                        original_link = article.raw_data.get('original_link')
                        for u in (telegram_url, original_link):
                            if u and u not in urls_to_check:
                                urls_to_check.append(u)
                except Exception:
                    pass

                # Fast in-memory batch-level dedup by URLs
                if any(u in seen_urls_in_batch for u in urls_to_check if u):
                    continue

                # Fast in-memory batch-level dedup by normalized title per source
                normalized_title = (article.title or "").strip().lower()
                if normalized_title and normalized_title in seen_titles_in_batch:
                    continue

                # Check existence safely across multiple candidate URLs
                existing = await db.execute(
                    select(Article.id).where(Article.url.in_(urls_to_check)).limit(1)
                )
                if existing.scalars().first() is not None:
                    continue  # Skip existing articles

                # Additional near-duplicate guard for Telegram: same source + same title (case-insensitive) in recent window
                try:
                    from sqlalchemy import func, and_
                    recent_window_days = 7
                    normalized_title = (article.title or "").strip().lower()
                    if normalized_title:
                        title_dup_q = select(Article.id).where(
                            and_(
                                Article.source_id == source.id,
                                func.lower(Article.title) == normalized_title,
                            )
                        ).limit(1)
                        title_dup = await db.execute(title_dup_q)
                        if title_dup.scalars().first() is not None:
                            continue  # Skip near-duplicate by title within same source
                except Exception:
                    pass
                
                # Create article record
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

                # If source already performed advertising detection (e.g., Telegram), persist it now
                try:
                    raw = getattr(article, 'raw_data', None)
                    if isinstance(raw, dict):
                        if 'advertising_detection' in raw or 'is_advertisement' in raw:
                            db_article.is_advertisement = bool(raw.get('is_advertisement', False))
                            if 'ad_confidence' in raw:
                                db_article.ad_confidence = float(raw.get('ad_confidence') or 0.0)
                            if 'ad_type' in raw:
                                db_article.ad_type = raw.get('ad_type')
                            if 'ad_reasoning' in raw:
                                db_article.ad_reasoning = raw.get('ad_reasoning')
                            if 'ad_markers' in raw:
                                db_article.ad_markers = raw.get('ad_markers')
                            db_article.ad_processed = True
                except Exception:
                    pass
                
                db.add(db_article)
                articles.append(db_article)

                # Record into batch dedup sets
                for u in urls_to_check:
                    if u:
                        seen_urls_in_batch.add(u)
                if normalized_title:
                    seen_titles_in_batch.add(normalized_title)
            
            # Update source success status
            source.last_success = datetime.utcnow()
            source.error_count = 0
            source.last_error = None
            
            try:
                await db.commit()
            except Exception as e:
                await db.rollback()
                raise SourceError(f"Failed to store fetched articles for source {source.name}: {e}")
            return articles
        
        except Exception as e:
            # Update source error status
            source.error_count += 1
            source.last_error = str(e)
            try:
                await db.commit()
            except Exception:
                await db.rollback()
            raise SourceError(f"Failed to fetch from source {source.name}: {e}")
    
    async def fetch_from_all_sources(self, db: AsyncSession, 
                                   max_concurrent: int = 5) -> Dict[str, List[Article]]:
        """Fetch articles from all enabled sources concurrently."""
        sources = await self.get_sources(db, enabled_only=True)
        results = {}
        
        # Create semaphore to limit concurrent fetches
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def fetch_source(source: Source):
            async with semaphore:
                try:
                    # Create a new session for each concurrent task
                    from ..database import AsyncSessionLocal
                    async with AsyncSessionLocal() as task_db:
                        # Get fresh source instance with new session
                        fresh_source = await task_db.get(Source, source.id)
                        if not fresh_source:
                            return source.name, []
                        
                        articles = await self.fetch_from_source(task_db, fresh_source)
                        return source.name, articles
                except Exception as e:
                    print(f"Error fetching from {source.name}: {e}")
                    return source.name, []
        
        # Execute fetches concurrently
        tasks = [fetch_source(source) for source in sources]
        fetch_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results
        for result in fetch_results:
            if isinstance(result, Exception):
                print(f"Fetch task failed: {result}")
                continue
            
            source_name, articles = result
            results[source_name] = articles
        
        return results
    
    def _calculate_content_hash(self, article) -> str:
        """Calculate hash for article content (for deduplication)."""
        import hashlib
        
        content = f"{article.title}:{article.url}"
        return hashlib.sha256(content.encode()).hexdigest()
    
    async def get_sources_due_for_fetch(self, db: AsyncSession) -> List[Source]:
        """Get sources that are due for fetching based on their intervals."""
        now = datetime.utcnow()
        
        query = select(Source).where(
            Source.enabled == True,
            (Source.last_fetch.is_(None)) |
            (Source.last_fetch < now - timedelta(seconds=Source.fetch_interval))
        )
        
        result = await db.execute(query)
        return result.scalars().all()
    
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