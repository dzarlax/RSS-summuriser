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
        source = await self.get_source_by_id(db, source_id)
        if not source:
            return None
        
        for key, value in updates.items():
            if hasattr(source, key):
                setattr(source, key, value)
        
        source.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(source)
        
        # Clear cached instance
        if source_id in self._source_instances:
            del self._source_instances[source_id]
        
        return source
    
    async def delete_source(self, db: AsyncSession, source_id: int) -> bool:
        """Delete source."""
        source = await self.get_source_by_id(db, source_id)
        if not source:
            return False
        
        await db.delete(source)
        await db.commit()
        
        # Clear cached instance
        if source_id in self._source_instances:
            del self._source_instances[source_id]
        
        return True
    
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
            
            await db.commit()
            return is_connected
        
        except Exception as e:
            source.error_count += 1
            source.last_error = str(e)
            await db.commit()
            return False
    
    async def fetch_from_source(self, db: AsyncSession, source: Source, 
                               limit: Optional[int] = None) -> List[Article]:
        """Fetch articles from a single source."""
        try:
            source_instance = await self.get_source_instance(source)
            articles = []
            
            # Update fetch time
            source.last_fetch = datetime.utcnow()
            
            async for article in source_instance.fetch_articles(limit=limit):
                # Check if article already exists
                existing = await db.execute(
                    select(Article).where(Article.url == article.url)
                )
                if existing.scalar_one_or_none():
                    continue  # Skip existing articles
                
                # Create article record
                db_article = Article(
                    source_id=source.id,
                    title=article.title,
                    url=article.url,
                    content=article.content,
                    summary=article.summary,
                    image_url=article.image_url,
                    published_at=article.published_at,
                    processed=False,
                    hash_content=self._calculate_content_hash(article)
                )
                
                db.add(db_article)
                articles.append(db_article)
            
            # Update source success status
            source.last_success = datetime.utcnow()
            source.error_count = 0
            source.last_error = None
            
            await db.commit()
            return articles
        
        except Exception as e:
            # Update source error status
            source.error_count += 1
            source.last_error = str(e)
            await db.commit()
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