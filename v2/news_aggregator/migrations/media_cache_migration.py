"""Migration for adding media cache support."""

import logging
from typing import Dict, Any
from .base_migration import TableExistsMigration

logger = logging.getLogger(__name__)


class MediaCacheMigration(TableExistsMigration):
    """Migration to add media_files_cache table for caching media files."""
    
    def __init__(self):
        # SQL statements to create the media cache table
        sql_statements = [
            """
            CREATE TABLE IF NOT EXISTS media_files_cache (
                id SERIAL PRIMARY KEY,
                article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
                
                -- Original media data
                original_url TEXT NOT NULL,
                media_type VARCHAR(20) NOT NULL,
                filename VARCHAR(255),
                mime_type VARCHAR(100),
                file_size INTEGER,
                
                -- Cached file paths (relative to media_cache_dir)
                cached_original_path VARCHAR(500),
                cached_thumbnail_path VARCHAR(500),
                cached_optimized_path VARCHAR(500),
                
                -- Media metadata
                width INTEGER,
                height INTEGER,
                duration REAL,
                
                -- Cache status and error tracking
                cache_status VARCHAR(20) DEFAULT 'pending' NOT NULL,
                cache_attempts INTEGER DEFAULT 0,
                last_cache_attempt TIMESTAMP,
                cache_error TEXT,
                
                -- Usage tracking for LRU cleanup
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
                accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
            )
            """,
            
            # Indexes for performance
            "CREATE INDEX IF NOT EXISTS idx_media_files_cache_article_id ON media_files_cache(article_id)",
            "CREATE INDEX IF NOT EXISTS idx_media_files_cache_original_url ON media_files_cache(original_url)",
            "CREATE INDEX IF NOT EXISTS idx_media_files_cache_media_type ON media_files_cache(media_type)",
            "CREATE INDEX IF NOT EXISTS idx_media_files_cache_status ON media_files_cache(cache_status)",
            "CREATE INDEX IF NOT EXISTS idx_media_files_cache_created_at ON media_files_cache(created_at)",
            "CREATE INDEX IF NOT EXISTS idx_media_files_cache_accessed_at ON media_files_cache(accessed_at)",
            
            # Add comments for documentation
            """
            COMMENT ON TABLE media_files_cache IS 'Cache table for media files with optimized versions'
            """,
            """
            COMMENT ON COLUMN media_files_cache.cache_status IS 'Status: pending, processing, cached, failed'
            """,
            """
            COMMENT ON COLUMN media_files_cache.media_type IS 'Type: image, video, document'
            """,
            """
            COMMENT ON COLUMN media_files_cache.cached_original_path IS 'Path relative to media_cache_dir'
            """,
            """
            COMMENT ON COLUMN media_files_cache.accessed_at IS 'Last access time for LRU cleanup'
            """
        ]
        
        super().__init__(
            migration_id="006_add_media_cache_support",
            description="Add media cache table for storing cached media files with optimized versions",
            version="2.2.0",
            required_tables=["media_files_cache"],
            sql_statements=sql_statements
        )
    
    async def verify_success(self, db_session) -> bool:
        """Verify that media cache table was created successfully."""
        try:
            # Check if table exists and has expected columns
            result = await db_session.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'media_files_cache' 
                AND column_name IN ('id', 'article_id', 'original_url', 'cache_status')
            """)
            
            columns = [row[0] for row in result.fetchall()]
            expected_columns = ['id', 'article_id', 'original_url', 'cache_status']
            
            if all(col in columns for col in expected_columns):
                logger.info("✅ Media cache table created successfully with all required columns")
                return True
            else:
                logger.error(f"❌ Missing columns in media_files_cache table. Found: {columns}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Could not verify media cache table creation: {e}")
            return False


# Migration instance
media_cache_migration = MediaCacheMigration()

