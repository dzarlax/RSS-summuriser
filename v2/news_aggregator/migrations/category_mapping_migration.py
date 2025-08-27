"""
Migration to create category_mapping table for web-based category mapping management.
"""

from typing import Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from .base_migration import BaseMigration


class CategoryMappingMigration(BaseMigration):
    """Migration to create category_mapping table."""
    
    def __init__(self):
        super().__init__(
            migration_id="category_mapping_migration",
            version="2025.08.27.003",
            description="Create category_mapping table for web-based mapping management"
        )

    async def execute(self, session: AsyncSession) -> bool:
        """Execute the migration."""
        try:
            print("🔄 Creating category_mapping table...")
            
            # Create category_mapping table
            await session.execute(text("""
                CREATE TABLE IF NOT EXISTS category_mapping (
                    id SERIAL PRIMARY KEY,
                    ai_category VARCHAR(100) NOT NULL UNIQUE,
                    fixed_category VARCHAR(50) NOT NULL,
                    confidence_threshold FLOAT DEFAULT 0.0,
                    description TEXT,
                    created_by VARCHAR(100) DEFAULT 'system',
                    usage_count INTEGER DEFAULT 0,
                    last_used TIMESTAMP,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            
            # Create indexes
            await session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_category_mapping_ai_category 
                ON category_mapping(ai_category)
            """))
            
            await session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_category_mapping_fixed_category 
                ON category_mapping(fixed_category)
            """))
            
            await session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_category_mapping_is_active 
                ON category_mapping(is_active)
            """))
            
            # Insert default mappings from hardcoded mapping
            default_mappings = [
                # International relations
                ('Russia', 'International', 'Maps Russia-related content to International category'),
                ('Europe', 'International', 'Maps Europe-related content to International category'),
                ('International Relations', 'International', 'Maps international relations content'),
                ('World', 'International', 'Maps world news to International category'),
                ('Global', 'International', 'Maps global content to International category'),
                ('Foreign', 'International', 'Maps foreign news to International category'),
                
                # Health/Medical -> Science
                ('Health', 'Science', 'Maps health content to Science category'),
                ('Medical', 'Science', 'Maps medical content to Science category'),
                ('Medicine', 'Science', 'Maps medicine content to Science category'),
                ('Healthcare', 'Science', 'Maps healthcare content to Science category'),
                
                # Events/Society -> Other
                ('Events', 'Other', 'Maps event announcements to Other category'),
                ('Society', 'Other', 'Maps society content to Other category'),
                ('Culture', 'Other', 'Maps cultural content to Other category'),
                ('Lifestyle', 'Other', 'Maps lifestyle content to Other category'),
                ('Entertainment', 'Other', 'Maps entertainment content to Other category'),
                ('Sports', 'Other', 'Maps sports content to Other category'),
                
                # Security/Legal -> Politics
                ('Security', 'Politics', 'Maps security content to Politics category'),
                ('Legal', 'Politics', 'Maps legal content to Politics category'),
                ('Law', 'Politics', 'Maps law content to Politics category'),
                ('Government', 'Politics', 'Maps government content to Politics category'),
                ('Human Rights', 'Politics', 'Maps human rights content to Politics category'),
                
                # Nature/Environment -> Science
                ('Nature', 'Science', 'Maps nature content to Science category'),
                ('Environment', 'Science', 'Maps environmental content to Science category'),
                ('Climate', 'Science', 'Maps climate content to Science category'),
                ('Ecology', 'Science', 'Maps ecology content to Science category'),
                
                # Generic news -> Other
                ('News', 'Other', 'Maps generic news to Other category'),
                ('General', 'Other', 'Maps general content to Other category'),
            ]
            
            print("  📝 Inserting default category mappings...")
            for ai_category, fixed_category, description in default_mappings:
                await session.execute(text("""
                    INSERT INTO category_mapping 
                    (ai_category, fixed_category, description, created_by)
                    VALUES (:ai_category, :fixed_category, :description, 'system')
                    ON CONFLICT (ai_category) DO NOTHING
                """), {
                    "ai_category": ai_category,
                    "fixed_category": fixed_category,
                    "description": description
                })
            
            await session.commit()
            
            print(f"✅ Category mapping migration completed!")
            print(f"   📋 Created category_mapping table")
            print(f"   📊 Inserted {len(default_mappings)} default mappings")
            
            return True
            
        except Exception as e:
            print(f"❌ Category mapping migration failed: {e}")
            await session.rollback()
            raise

    async def check_needed(self, session: AsyncSession) -> bool:
        """Check if migration is needed."""
        try:
            # Check if category_mapping table exists
            result = await session.execute(text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name = 'category_mapping'
                )
            """))
            table_exists = result.scalar()
            
            # Migration needed if table doesn't exist
            return not table_exists
            
        except Exception as e:
            print(f"⚠️ Error checking if migration is needed: {e}")
            return True  # Run migration if uncertain

    async def rollback(self, session: AsyncSession) -> bool:
        """Rollback the migration."""
        try:
            print("🔄 Rolling back category mapping migration...")
            
            # Drop the table
            await session.execute(text("DROP TABLE IF EXISTS category_mapping"))
            await session.commit()
            
            print("✅ Category mapping migration rolled back")
            return True
            
        except Exception as e:
            print(f"❌ Rollback failed: {e}")
            await session.rollback()
            return False