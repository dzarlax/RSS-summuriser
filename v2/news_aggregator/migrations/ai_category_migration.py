"""Migration to add ai_category column to article_categories table."""

from .base_migration import BaseMigration
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)


class AiCategoryMigration(BaseMigration):
    """Migration to add ai_category column to article_categories."""
    
    def __init__(self):
        super().__init__(
            migration_id="006_add_ai_category_column",
            description="Add ai_category column to article_categories table",
            version="1.0"
        )
    
    async def check_needed(self, db: AsyncSession) -> bool:
        """Check if this migration is needed."""
        try:
            # Try to query the ai_category column
            result = await db.execute(text("SELECT ai_category FROM article_categories LIMIT 1"))
            return False  # Column exists, migration not needed
        except Exception:
            return True  # Column doesn't exist, migration needed
    
    async def execute(self, db: AsyncSession) -> Dict[str, Any]:
        """Execute the migration."""
        logger.info("🔄 Adding ai_category column to article_categories table...")
        
        try:
            # Add ai_category column
            await db.execute(text("ALTER TABLE article_categories ADD COLUMN ai_category VARCHAR(100)"))
            await db.commit()
            
            logger.info("✅ Successfully added ai_category column")
            return {"success": True, "message": "Added ai_category column"}
            
        except Exception as e:
            await db.rollback()
            logger.error(f"❌ Failed to add ai_category column: {e}")
            raise
    
    async def rollback(self, db: AsyncSession) -> Dict[str, Any]:
        """Rollback the migration."""
        logger.info("🔄 Removing ai_category column from article_categories table...")
        
        try:
            await db.execute(text("ALTER TABLE article_categories DROP COLUMN IF EXISTS ai_category"))
            await db.commit()
            
            logger.info("✅ Successfully removed ai_category column")
            return {"success": True, "message": "Removed ai_category column"}
            
        except Exception as e:
            await db.rollback()
            logger.error(f"❌ Failed to remove ai_category column: {e}")
            raise