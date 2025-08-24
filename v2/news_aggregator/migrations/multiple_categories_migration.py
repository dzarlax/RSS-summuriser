"""
Migration for multiple categories support.
"""

import logging
from typing import Dict, Any
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .base_migration import BaseMigration

logger = logging.getLogger(__name__)


class MultipleCategoriesMigration(BaseMigration):
    """Migration to add support for multiple categories per article."""
    
    def __init__(self):
        super().__init__(
            migration_id='002_multiple_categories',
            description='Add support for multiple categories per article',
            version='2.0.0'
        )
    
    async def check_needed(self, db: AsyncSession) -> bool:
        """Check if multiple categories migration is needed."""
        try:
            # Check if categories table exists by trying to query it
            try:
                await db.execute(text("SELECT 1 FROM categories LIMIT 1"))
                await db.execute(text("SELECT 1 FROM article_categories LIMIT 1"))
            except Exception as e:
                logger.info("📋 Categories tables not found - migration needed")
                # Important: rollback the transaction after failed queries
                await db.rollback()
                return True
            
            # Check if we have any composite categories to migrate
            result = await db.execute(text("""
                SELECT COUNT(*) FROM articles 
                WHERE category IS NOT NULL 
                AND (
                    category LIKE '%|%' OR 
                    category LIKE '%/%' OR 
                    category LIKE '%,%' OR 
                    category LIKE '% and %' OR 
                    category LIKE '% & %'
                )
            """))
            
            composite_count = result.scalar()
            
            # Check if we have articles with categories but no article_categories entries
            result = await db.execute(text("""
                SELECT COUNT(*) FROM articles a
                WHERE a.category IS NOT NULL 
                AND NOT EXISTS (
                    SELECT 1 FROM article_categories ac 
                    WHERE ac.article_id = a.id
                )
            """))
            
            unmigrated_count = result.scalar()
            
            if composite_count > 0:
                logger.info(f"📊 Found {composite_count} composite categories to migrate")
                return True
                
            if unmigrated_count > 0:
                logger.info(f"📊 Found {unmigrated_count} unmigrated articles")
                return True
            
            logger.info("✅ Multiple categories migration not needed")
            return False
            
        except Exception as e:
            logger.warning(f"Could not check migration status: {e}")
            # If we can't check, assume migration is needed for safety
            return True
    
    async def execute(self, db: AsyncSession) -> Dict[str, Any]:
        """Execute multiple categories migration."""
        migration_result = {
            'schema_created': False,
            'simple_categories_migrated': 0,
            'composite_categories_migrated': 0,
            'total_relationships_created': 0,
            'errors': []
        }
        
        try:
            logger.info("🔧 Creating schema for multiple categories...")
            
            # Step 1: Create schema
            await self._create_schema(db)
            migration_result['schema_created'] = True
            
            # Step 2: Insert default categories
            await self._insert_default_categories(db)
            
            # Step 3: Migrate simple categories
            simple_count = await self._migrate_simple_categories(db)
            migration_result['simple_categories_migrated'] = simple_count
            
            # Step 4: Migrate composite categories
            composite_result = await self._migrate_composite_categories(db)
            migration_result['composite_categories_migrated'] = composite_result['processed']
            migration_result['total_relationships_created'] += composite_result['relationships_created']
            
            # Step 5: Get final statistics
            try:
                result = await db.execute(text("SELECT COUNT(*) FROM article_categories"))
                migration_result['total_relationships_created'] = result.scalar()
            except Exception as e:
                logger.warning(f"Statistics collection warning: {e}")
                migration_result['total_relationships_created'] = 0
            
            logger.info(f"🎉 Migration completed successfully!")
            logger.info(f"   Simple categories: {migration_result['simple_categories_migrated']}")
            logger.info(f"   Composite categories: {migration_result['composite_categories_migrated']}")
            logger.info(f"   Total relationships: {migration_result['total_relationships_created']}")
            
            return migration_result
            
        except Exception as e:
            error_msg = f"Migration failed: {str(e)}"
            logger.error(error_msg)
            migration_result['errors'].append(error_msg)
            await db.rollback()
            raise
    
    async def _create_schema(self, db: AsyncSession):
        """Create database schema for multiple categories."""
        
        # Create tables with single transaction approach
        try:
            # Create categories table
            await db.execute(text("""
                CREATE TABLE IF NOT EXISTS categories (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(50) NOT NULL UNIQUE,
                    display_name VARCHAR(100) NOT NULL,
                    description TEXT,
                    color VARCHAR(7) DEFAULT '#6c757d',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            logger.info("✅ Created categories table")
            
            # Create article_categories table
            await db.execute(text("""
                CREATE TABLE IF NOT EXISTS article_categories (
                    id SERIAL PRIMARY KEY,
                    article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
                    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
                    confidence FLOAT DEFAULT 1.0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(article_id, category_id)
                )
            """))
            logger.info("✅ Created article_categories table")
            
            # Create indexes
            await db.execute(text("CREATE INDEX IF NOT EXISTS idx_article_categories_article_id ON article_categories(article_id)"))
            await db.execute(text("CREATE INDEX IF NOT EXISTS idx_article_categories_category_id ON article_categories(category_id)"))
            await db.execute(text("CREATE INDEX IF NOT EXISTS idx_article_categories_confidence ON article_categories(confidence)"))
            logger.info("✅ Created indexes")
            
            # Commit all changes at once
            await db.commit()
            logger.info("✅ Schema creation completed successfully")
            
        except Exception as e:
            error_msg = f"Failed to create schema: {e}"
            logger.error(error_msg)
            await db.rollback()
            raise Exception(error_msg)
    
    async def _insert_default_categories(self, db: AsyncSession):
        """Insert default categories."""
        try:
            # First check if categories table exists
            await db.execute(text("SELECT 1 FROM categories LIMIT 1"))
            
            # Table exists, insert default categories
            await db.execute(text("""
                INSERT INTO categories (name, display_name, description, color) VALUES
                    ('Business', 'Бизнес', 'Экономика, финансы, компании, инвестиции', '#28a745'),
                    ('Tech', 'Технологии', 'IT, софтвер, инновации, стартапы', '#007bff'),
                    ('Science', 'Наука', 'Исследования, медицина, открытия', '#6f42c1'),
                    ('Serbia', 'Сербия', 'Новости Сербии, политика, общество', '#dc3545'),
                    ('Other', 'Прочее', 'Остальные новости', '#6c757d')
                ON CONFLICT (name) DO NOTHING
            """))
            await db.commit()
            logger.info("✅ Default categories inserted")
        except Exception as e:
            logger.warning(f"Default categories insertion warning (table may not exist): {e}")
            await db.rollback()
    
    async def _migrate_simple_categories(self, db: AsyncSession) -> int:
        """Migrate simple (non-composite) categories."""
        try:
            # First check if both tables exist
            await db.execute(text("SELECT 1 FROM categories LIMIT 1"))
            await db.execute(text("SELECT 1 FROM article_categories LIMIT 1"))
            
            result = await db.execute(text("""
                INSERT INTO article_categories (article_id, category_id, confidence)
                SELECT 
                    a.id as article_id,
                    c.id as category_id,
                    1.0 as confidence
                FROM articles a
                JOIN categories c ON c.name = a.category
                WHERE a.category IS NOT NULL
                  AND a.category NOT LIKE '%|%'
                  AND a.category NOT LIKE '%/%'
                  AND a.category NOT LIKE '%,%'
                  AND a.category NOT LIKE '% and %'
                  AND a.category NOT LIKE '% & %'
                  AND NOT EXISTS (
                      SELECT 1 FROM article_categories ac 
                      WHERE ac.article_id = a.id
                  )
                ON CONFLICT (article_id, category_id) DO NOTHING
            """))
            
            count = result.rowcount
            await db.commit()
            logger.info(f"✅ Migrated {count} simple categories")
            return count
        except Exception as e:
            logger.warning(f"Simple categories migration warning (tables may not exist): {e}")
            await db.rollback()
            return 0
    
    async def _migrate_composite_categories(self, db: AsyncSession) -> Dict[str, int]:
        """Migrate composite categories (e.g., 'Business|Tech')."""
        logger.info("🔀 Migrating composite categories...")
        
        # Find composite categories
        result = await db.execute(text("""
            SELECT id, category, title 
            FROM articles 
            WHERE category IS NOT NULL 
            AND (
                category LIKE '%|%' OR 
                category LIKE '%/%' OR 
                category LIKE '%,%' OR 
                category LIKE '% and %' OR 
                category LIKE '% & %'
            )
            ORDER BY id
        """))
        
        composite_articles = result.fetchall()
        logger.info(f"🔍 Found {len(composite_articles)} composite categories")
        
        if not composite_articles:
            return {'processed': 0, 'relationships_created': 0}
        
        # Get valid categories - check if table exists first
        try:
            cat_result = await db.execute(text("SELECT name, id FROM categories"))
            valid_categories = {name: cat_id for name, cat_id in cat_result.fetchall()}
        except Exception as e:
            logger.warning(f"Could not get categories (table may not exist): {e}")
            # If categories table doesn't exist, we can't migrate composite categories
            return {'processed': 0, 'relationships_created': 0}
        
        stats = {'processed': 0, 'relationships_created': 0}
        
        for article_id, composite_category, title in composite_articles:
            try:
                # Parse composite category
                categories_to_assign = []
                separators = ['|', '/', ',', ' and ', ' & ']
                parts = [composite_category]
                
                for sep in separators:
                    if sep in composite_category:
                        parts = [p.strip() for p in composite_category.split(sep)]
                        break
                
                # Find valid categories
                for part in parts:
                    clean_part = part.strip()
                    if clean_part in valid_categories:
                        categories_to_assign.append((clean_part, valid_categories[clean_part]))
                
                if not categories_to_assign and 'Other' in valid_categories:
                    categories_to_assign.append(('Other', valid_categories['Other']))
                
                # Remove existing relationships for this article
                await db.execute(
                    text("DELETE FROM article_categories WHERE article_id = :article_id"),
                    {'article_id': article_id}
                )
                
                # Add new relationships
                for cat_name, cat_id in categories_to_assign:
                    await db.execute(text("""
                        INSERT INTO article_categories (article_id, category_id, confidence)
                        VALUES (:article_id, :category_id, 1.0)
                        ON CONFLICT (article_id, category_id) DO NOTHING
                    """), {
                        'article_id': article_id,
                        'category_id': cat_id
                    })
                    stats['relationships_created'] += 1
                
                # Update the legacy category field to the first assigned category
                if categories_to_assign:
                    first_category = categories_to_assign[0][0]
                    await db.execute(text("""
                        UPDATE articles SET category = :category WHERE id = :article_id
                    """), {
                        'category': first_category,
                        'article_id': article_id
                    })
                
                stats['processed'] += 1
                
                # Commit every 100 articles to avoid long transactions
                if stats['processed'] % 100 == 0:
                    await db.commit()
                    logger.info(f"   Processed {stats['processed']} composite categories...")
                
            except Exception as article_error:
                logger.warning(f"Failed to migrate article {article_id}: {article_error}")
                await db.rollback()
                continue
        
        await db.commit()
        logger.info(f"✅ Composite categories migration completed: {stats['processed']} articles, {stats['relationships_created']} relationships")
        
        return stats
