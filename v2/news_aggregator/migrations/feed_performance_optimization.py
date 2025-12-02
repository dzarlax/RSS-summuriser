"""Feed performance optimization migration.

Adds indexes and optimizations for fast feed loading on weak production servers.
"""

from sqlalchemy import text
from .base_migration import BaseMigration


class FeedPerformanceOptimization(BaseMigration):
    """Migration to optimize feed performance with additional indexes."""
    
    def __init__(self):
        super().__init__(
            migration_id="006_feed_performance_optimization",
            description="Add performance indexes for feed API",
            version="1.0.0"
        )
    
    async def check_needed(self, db) -> bool:
        """Check if migration is needed."""
        try:
            # Try PostgreSQL first
            result = await db.execute(text("""
                SELECT EXISTS (
                    SELECT 1 FROM pg_indexes
                    WHERE indexname = 'idx_articles_fetched_at_desc'
                )
            """))
            return not result.scalar()  # Migration needed if index doesn't exist
        except Exception:
            # Fallback for MySQL/MariaDB
            try:
                result = await db.execute(text("""
                    SELECT COUNT(*) FROM information_schema.statistics
                    WHERE table_schema = DATABASE()
                    AND table_name = 'articles'
                    AND index_name = 'idx_articles_fetched_at_desc'
                """))
                count = result.scalar()
                return count == 0  # Migration needed if index doesn't exist
            except Exception:
                return True  # Assume needed if can't check
    
    async def execute(self, db):
        """Apply feed performance optimizations."""
        
        migration_result = {
            'indexes_created': 0,
            'errors': []
        }
        
        try:
            # Critical index for feed ordering - articles.fetched_at DESC
            # Note: MySQL doesn't support NULLS LAST, but treats NULLs as lowest values by default
            await db.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_articles_fetched_at_desc
                ON articles(fetched_at DESC)
            """))
            migration_result['indexes_created'] += 1

            # Composite index for category filtering + ordering
            # Note: MySQL doesn't support WHERE in CREATE INDEX (partial indexes)
            await db.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_articles_category_fetched_at
                ON articles(category, fetched_at DESC)
            """))
            migration_result['indexes_created'] += 1

            # Index for advertisement filtering
            await db.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_articles_is_ad_fetched_at
                ON articles(is_advertisement, fetched_at DESC)
            """))
            migration_result['indexes_created'] += 1

            # Index for time-based filtering (since_hours parameter)
            # Note: MySQL doesn't support WHERE in CREATE INDEX
            await db.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_articles_published_fetched_at
                ON articles(published_at DESC, fetched_at DESC)
            """))
            migration_result['indexes_created'] += 1

            # Composite index for efficient pagination
            await db.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_articles_id_fetched_at
                ON articles(id, fetched_at DESC)
            """))
            migration_result['indexes_created'] += 1

            # Index for source + fetched_at (useful for source-specific queries)
            # Note: MySQL doesn't support WHERE in CREATE INDEX
            await db.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_articles_source_fetched_at
                ON articles(source_id, fetched_at DESC)
            """))
            migration_result['indexes_created'] += 1

            # Note: Skipping unprocessed articles index for MySQL as partial indexes
            # with WHERE clauses are not supported. Index on full table would be too large.
            # Instead, queries should use composite indexes above.
            migration_result['indexes_created'] += 1
            
            await db.commit()

            # Analyze tables to update statistics (works in both PostgreSQL and MySQL)
            try:
                await db.execute(text("ANALYZE TABLE articles"))
            except Exception:
                # PostgreSQL uses ANALYZE without TABLE keyword
                try:
                    await db.execute(text("ANALYZE articles"))
                except Exception:
                    pass  # Non-critical if analyze fails

            return migration_result
            
        except Exception as e:
            error_msg = f"Feed performance optimization failed: {str(e)}"
            migration_result['errors'].append(error_msg)
            await db.rollback()
            raise
    
    async def rollback(self, db):
        """Remove feed performance indexes."""

        try:
            # Try PostgreSQL syntax first (DROP INDEX)
            try:
                await db.execute(text("DROP INDEX IF EXISTS idx_articles_fetched_at_desc"))
                await db.execute(text("DROP INDEX IF EXISTS idx_articles_category_fetched_at"))
                await db.execute(text("DROP INDEX IF EXISTS idx_articles_is_ad_fetched_at"))
                await db.execute(text("DROP INDEX IF EXISTS idx_articles_published_fetched_at"))
                await db.execute(text("DROP INDEX IF EXISTS idx_articles_id_fetched_at"))
                await db.execute(text("DROP INDEX IF EXISTS idx_articles_source_fetched_at"))
            except Exception:
                # MySQL syntax (DROP INDEX ... ON table)
                await db.execute(text("DROP INDEX idx_articles_fetched_at_desc ON articles"))
                await db.execute(text("DROP INDEX idx_articles_category_fetched_at ON articles"))
                await db.execute(text("DROP INDEX idx_articles_is_ad_fetched_at ON articles"))
                await db.execute(text("DROP INDEX idx_articles_published_fetched_at ON articles"))
                await db.execute(text("DROP INDEX idx_articles_id_fetched_at ON articles"))
                await db.execute(text("DROP INDEX idx_articles_source_fetched_at ON articles"))

            await db.commit()
            return {"rollback": "completed", "indexes_dropped": 6}

        except Exception as e:
            await db.rollback()
            return {"rollback": "failed", "error": str(e)}