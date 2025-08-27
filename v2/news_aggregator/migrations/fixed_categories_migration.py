"""
Migration to consolidate all categories into 7 fixed categories.
Migrates existing articles to the new category system.
"""

from typing import Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, text
from .base_migration import BaseMigration


class FixedCategoriesMigration(BaseMigration):
    """Migration to limit categories to 7 fixed ones and migrate existing data."""
    
    def __init__(self):
        super().__init__(
            migration_id="fixed_categories_migration",
            version="2025.08.27.002",
            description="Consolidate all categories into 7 fixed categories"
        )
        
        # Fixed list of 7 allowed categories
        self.FIXED_CATEGORIES = {
            'Serbia': 'Сербия',
            'Tech': 'Технологии', 
            'Business': 'Бизнес',
            'Science': 'Наука',
            'Politics': 'Политика',
            'International': 'Международные',
            'Other': 'Прочее'
        }
        
        # Mapping of existing categories to fixed categories
        self.CATEGORY_MIGRATION_MAP = {
            # Keep as-is
            'Serbia': 'Serbia',
            'Tech': 'Tech',
            'Business': 'Business',
            'Science': 'Science',
            'Other': 'Other',
            
            # Politics
            'Politics': 'Politics',
            'Government': 'Politics',
            'Legal': 'Politics',
            'Human Rights': 'Politics',
            'Security': 'Politics',
            
            # International
            'International Relations': 'International',
            'Russia': 'International',
            'Europe': 'International',
            'European Union': 'International',
            
            # Science
            'Nature': 'Science',
            'Health': 'Science',
            
            # Other
            'News': 'Other',
            'Events': 'Other',
            'Culture': 'Other',
            'Society': 'Other',
            'Entertainment': 'Other',
            'Lifestyle': 'Other',
        }

    async def execute(self, session: AsyncSession) -> bool:
        """Execute the migration."""
        try:
            print("🔄 Starting fixed categories migration...")
            
            # Step 1: Create/update fixed categories
            print("  📝 Ensuring fixed categories exist...")
            category_id_map = {}
            
            for category_name, display_name in self.FIXED_CATEGORIES.items():
                # Check if category exists
                result = await session.execute(
                    text("SELECT id FROM categories WHERE name = :name"),
                    {"name": category_name}
                )
                category_row = result.fetchone()
                
                if category_row:
                    category_id = category_row[0]
                    # Update display name if needed
                    await session.execute(
                        text("UPDATE categories SET display_name = :display_name WHERE id = :id"),
                        {"id": category_id, "display_name": display_name}
                    )
                    print(f"    ✅ Updated category '{category_name}' (ID: {category_id})")
                else:
                    # Create new category
                    result = await session.execute(
                        text("""
                            INSERT INTO categories (name, display_name, description, color, created_at) 
                            VALUES (:name, :display_name, :description, '#6c757d', NOW()) 
                            RETURNING id
                        """),
                        {
                            "name": category_name,
                            "display_name": display_name,
                            "description": f"Fixed category: {display_name}"
                        }
                    )
                    category_id = result.fetchone()[0]
                    print(f"    ➕ Created category '{category_name}' (ID: {category_id})")
                
                category_id_map[category_name] = category_id
            
            # Step 2: Migrate article categories
            print("  🔄 Migrating article categories...")
            
            # Get all existing article-category relationships
            existing_relations = await session.execute(
                text("""
                    SELECT ac.article_id, ac.confidence, c.name as old_category_name
                    FROM article_categories ac
                    JOIN categories c ON ac.category_id = c.id
                """)
            )
            
            migration_stats = {}
            articles_to_migrate = {}
            
            for row in existing_relations.fetchall():
                article_id, confidence, old_category_name = row
                
                # Map to new category
                new_category_name = self.CATEGORY_MIGRATION_MAP.get(old_category_name, 'Other')
                
                # Track stats
                migration_key = f"{old_category_name} → {new_category_name}"
                migration_stats[migration_key] = migration_stats.get(migration_key, 0) + 1
                
                # Group by article for batch processing
                if article_id not in articles_to_migrate:
                    articles_to_migrate[article_id] = []
                
                articles_to_migrate[article_id].append({
                    'new_category_name': new_category_name,
                    'confidence': confidence
                })
            
            # Step 3: Clear existing article-category relationships
            print("  🗑️ Clearing existing article-category relationships...")
            await session.execute(text("DELETE FROM article_categories"))
            
            # Step 4: Create new relationships
            print("  ➕ Creating new article-category relationships...")
            total_articles = len(articles_to_migrate)
            processed = 0
            
            for article_id, category_mappings in articles_to_migrate.items():
                # Group by category and keep highest confidence
                category_confidences = {}
                for mapping in category_mappings:
                    category_name = mapping['new_category_name']
                    confidence = mapping['confidence']
                    
                    if category_name not in category_confidences:
                        category_confidences[category_name] = confidence
                    else:
                        category_confidences[category_name] = max(category_confidences[category_name], confidence)
                
                # Create relationships for this article
                for category_name, confidence in category_confidences.items():
                    category_id = category_id_map[category_name]
                    await session.execute(
                        text("""
                            INSERT INTO article_categories (article_id, category_id, confidence, created_at) 
                            VALUES (:article_id, :category_id, :confidence, NOW())
                        """),
                        {
                            "article_id": article_id,
                            "category_id": category_id,
                            "confidence": confidence
                        }
                    )
                
                processed += 1
                if processed % 100 == 0:
                    print(f"    📊 Processed {processed}/{total_articles} articles...")
            
            # Step 5: Remove old categories
            print("  🗑️ Removing old categories...")
            categories_to_remove = []
            
            all_categories = await session.execute(text("SELECT id, name FROM categories"))
            for row in all_categories.fetchall():
                category_id, category_name = row
                if category_name not in self.FIXED_CATEGORIES:
                    categories_to_remove.append((category_id, category_name))
            
            for category_id, category_name in categories_to_remove:
                await session.execute(text("DELETE FROM categories WHERE id = :id"), {"id": category_id})
                print(f"    🗑️ Removed category '{category_name}' (ID: {category_id})")
            
            await session.commit()
            
            # Print migration statistics
            print("  📊 Migration statistics:")
            for migration, count in migration_stats.items():
                print(f"    - {migration}: {count} assignments")
            
            print(f"✅ Fixed categories migration completed!")
            print(f"   📊 Migrated {total_articles} articles")
            print(f"   🏷️ Created {len(self.FIXED_CATEGORIES)} fixed categories")
            print(f"   🗑️ Removed {len(categories_to_remove)} old categories")
            
            return True
            
        except Exception as e:
            print(f"❌ Fixed categories migration failed: {e}")
            await session.rollback()
            raise

    async def check_needed(self, session: AsyncSession) -> bool:
        """Check if migration is needed."""
        try:
            # Check if we have more than 7 categories or any auto-created categories
            result = await session.execute(
                text("""
                    SELECT COUNT(*) as total_categories,
                           COUNT(CASE WHEN description LIKE '%Auto-created%' THEN 1 END) as auto_created
                    FROM categories
                """)
            )
            row = result.fetchone()
            total_categories, auto_created = row
            
            # Migration needed if we have auto-created categories or more than 7 categories
            return auto_created > 0 or total_categories > 7
            
        except Exception as e:
            print(f"⚠️ Error checking if migration is needed: {e}")
            return True  # Run migration if uncertain

    async def rollback(self, session: AsyncSession) -> bool:
        """Rollback the migration (restore original categories)."""
        try:
            print("🔄 Rolling back fixed categories migration...")
            # This is complex to rollback, so we'll just log a warning
            print("⚠️ Rollback not implemented - manual database restore required")
            return False
        except Exception as e:
            print(f"❌ Rollback failed: {e}")
            return False