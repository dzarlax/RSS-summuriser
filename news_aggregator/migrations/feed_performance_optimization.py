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
            result = await db.execute(text("""
                SELECT EXISTS (
                    SELECT 1 FROM pg_indexes
                    WHERE indexname = 'idx_articles_fetched_at_desc'
                )
            """))
            return not result.scalar()
        except Exception:
            return True
    
    async def execute(self, db):
        """Apply feed performance optimizations."""
        
        migration_result = {
            'indexes_created': 0,
            'errors': []
        }
        
        try:
            # Critical index for feed ordering
            await db.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_articles_fetched_at_desc
                ON articles(fetched_at DESC NULLS LAST)
            """))
            migration_result['indexes_created'] += 1

            # Composite index for category filtering + ordering
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

            # Index for time-based filtering
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

            # Index for source + fetched_at
            await db.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_articles_source_fetched_at
                ON articles(source_id, fetched_at DESC)
            """))
            migration_result['indexes_created'] += 1

            # Partial index for unprocessed articles
            await db.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_articles_unprocessed
                ON articles(fetched_at DESC) WHERE NOT summary_processed
            """))
            migration_result['indexes_created'] += 1
            
            await db.commit()

            try:
                await db.execute(text("ANALYZE articles"))
            except Exception:
                pass

            return migration_result
            
        except Exception as e:
            error_msg = f"Feed performance optimization failed: {str(e)}"
            migration_result['errors'].append(error_msg)
            await db.rollback()
            raise
    
    async def rollback(self, db):
        """Remove feed performance indexes."""

        try:
            await db.execute(text("DROP INDEX IF EXISTS idx_articles_fetched_at_desc"))
            await db.execute(text("DROP INDEX IF EXISTS idx_articles_category_fetched_at"))
            await db.execute(text("DROP INDEX IF EXISTS idx_articles_is_ad_fetched_at"))
            await db.execute(text("DROP INDEX IF EXISTS idx_articles_published_fetched_at"))
            await db.execute(text("DROP INDEX IF EXISTS idx_articles_id_fetched_at"))
            await db.execute(text("DROP INDEX IF EXISTS idx_articles_source_fetched_at"))
            await db.execute(text("DROP INDEX IF EXISTS idx_articles_unprocessed"))

            await db.commit()
            return {"rollback": "completed", "indexes_dropped": 6}

        except Exception as e:
            await db.rollback()
            return {"rollback": "failed", "error": str(e)}