"""Migration for adding media files support to articles."""

import logging
from typing import Dict, Any
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .base_migration import BaseMigration

logger = logging.getLogger(__name__)


class MediaFilesMigration(BaseMigration):
    """Migration to add media_files column to articles table."""
    
    def __init__(self):
        super().__init__(
            migration_id="003_add_media_files_support",
            description="Add support for multiple media files per article",
            version="2.1.0"
        )
    
    async def check_needed(self, db_session) -> bool:
        """Check if media_files column exists in articles table."""
        try:
            # Check if media_files column exists
            result = await db_session.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'articles' 
                AND column_name = 'media_files'
            """)
            
            column_exists = result.fetchone() is not None
            return not column_exists
            
        except Exception as e:
            # If we can't check, assume migration is needed
            print(f"Could not check media_files column: {e}")
            return True
    
    async def verify_success(self, db_session) -> bool:
        """Verify that media_files column was added successfully."""
        try:
            # Check if media_files column exists and has correct type
            result = await db_session.execute("""
                SELECT column_name, data_type, column_default
                FROM information_schema.columns 
                WHERE table_name = 'articles' 
                AND column_name = 'media_files'
            """)
            
            column_info = result.fetchone()
            if not column_info:
                return False
            
            # Verify it's a JSON column with default empty array
            return (column_info[1] == 'json' and 
                    "'[]'::json" in str(column_info[2]))
            
        except Exception as e:
            print(f"Could not verify media_files column: {e}")
            return False
    
    async def execute(self, db: AsyncSession) -> Dict[str, Any]:
        """Execute the media files migration."""
        migration_result = {
            'statements_executed': 0,
            'column_added': False,
            'errors': []
        }
        
        try:
            # Add media_files column to articles table
            sql_statement = """
                ALTER TABLE articles 
                ADD COLUMN IF NOT EXISTS media_files JSON DEFAULT '[]'
            """
            
            await db.execute(text(sql_statement))
            migration_result['statements_executed'] += 1
            migration_result['column_added'] = True
            
            # Add comment to the column
            comment_sql = """
                COMMENT ON COLUMN articles.media_files IS 
                'List of media files: [{"url": "...", "type": "image|video|document", "thumbnail": "..."}]'
            """
            
            await db.execute(text(comment_sql))
            migration_result['statements_executed'] += 1
            
            logger.info("✅ Successfully added media_files column to articles table")
            
        except Exception as e:
            error_msg = f"Failed to add media_files column: {e}"
            logger.error(error_msg)
            migration_result['errors'].append(error_msg)
            raise
        
        return migration_result
