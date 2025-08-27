"""
Remove legacy category field migration.
This migration removes the legacy 'category' column from articles table
since all category data is now stored in the new categories/article_categories system.
"""

from .base_migration import BaseMigration
from ..database import AsyncSessionLocal
from sqlalchemy import text
import logging


class RemoveLegacyCategoryMigration(BaseMigration):
    """Migration to remove legacy category field from articles table."""
    
    def __init__(self):
        super().__init__(
            migration_id="004_remove_legacy_category",
            description="Remove legacy category field from articles table",
            version="2.0.0"
        )
    
    async def check_needed(self, db) -> bool:
        """Check if migration is needed."""
        try:
            # Check if category column exists
            result = await db.execute(text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'articles' 
                AND column_name = 'category'
            """))
            
            columns = result.fetchall()
            return len(columns) > 0  # Migration needed if column exists
            
        except Exception as e:
            logging.error(f"Error checking if legacy category migration is needed: {e}")
            return False
    
    async def execute(self, db) -> dict:
        """Execute the migration."""
        try:
            # Remove the legacy category column
            await db.execute(text("ALTER TABLE articles DROP COLUMN IF EXISTS category"))
            
            # Add comment explaining the change
            await db.execute(text("""
                COMMENT ON TABLE articles IS 
                'Articles table - categories now stored in article_categories relationship'
            """))
            
            await db.commit()
            
            logging.info("✅ Legacy category column removed from articles table")
            return {"success": True, "message": "Legacy category column removed"}
            
        except Exception as e:
            logging.error(f"❌ Failed to remove legacy category column: {e}")
            await db.rollback()
            return {"success": False, "error": str(e)}
    
    async def rollback(self, db) -> dict:
        """Rollback the migration (re-add category column)."""
        try:
            # Re-add the category column
            await db.execute(text("""
                ALTER TABLE articles 
                ADD COLUMN IF NOT EXISTS category VARCHAR(50)
            """))
            
            await db.commit()
            
            logging.info("✅ Legacy category column restored to articles table")
            return {"success": True, "message": "Legacy category column restored"}
            
        except Exception as e:
            logging.error(f"❌ Failed to restore legacy category column: {e}")
            await db.rollback()
            return {"success": False, "error": str(e)}