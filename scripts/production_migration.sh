#!/bin/bash

# Production Migration Script for Multiple Categories Support
# This script handles the complete migration including composite categories

set -e  # Exit on any error

echo "🚀 Starting production migration to multiple categories..."
echo "=================================================="

# Configuration
BACKUP_DIR="./backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/backup_before_categories_${TIMESTAMP}.sql"

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_DIR"

echo "📋 Migration Plan:"
echo "1. Create database backup"
echo "2. Apply schema migration (tables, indexes)"
echo "3. Migrate simple categories"
echo "4. Migrate composite categories (Business|Tech, etc.)"
echo "5. Verify results"
echo ""

# Step 1: Create backup
echo "💾 Step 1: Creating database backup..."
if docker exec production-db pg_dump -U postgres news_aggregator > "$BACKUP_FILE"; then
    echo "✅ Backup created: $BACKUP_FILE"
    echo "   Size: $(du -h "$BACKUP_FILE" | cut -f1)"
else
    echo "❌ Backup failed! Aborting migration."
    exit 1
fi

# Step 2: Apply schema migration
echo ""
echo "🔧 Step 2: Applying schema migration..."
docker exec production-app python -c "
import asyncio
from news_aggregator.database import AsyncSessionLocal
from sqlalchemy import text

async def apply_schema_migration():
    migration_sql = '''
-- Create categories table to store all available categories
CREATE TABLE IF NOT EXISTS categories (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE,
    display_name VARCHAR(100) NOT NULL,
    description TEXT,
    color VARCHAR(7) DEFAULT '#6c757d',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create junction table for many-to-many relationship
CREATE TABLE IF NOT EXISTS article_categories (
    id SERIAL PRIMARY KEY,
    article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    confidence FLOAT DEFAULT 1.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(article_id, category_id)
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_article_categories_article_id ON article_categories(article_id);
CREATE INDEX IF NOT EXISTS idx_article_categories_category_id ON article_categories(category_id);
CREATE INDEX IF NOT EXISTS idx_article_categories_confidence ON article_categories(confidence);

-- Insert default categories
INSERT INTO categories (name, display_name, description, color) VALUES
    (\'Business\', \'Бизнес\', \'Экономика, финансы, компании, инвестиции\', \'#28a745\'),
    (\'Tech\', \'Технологии\', \'IT, софтвер, инновации, стартапы\', \'#007bff\'),
    (\'Science\', \'Наука\', \'Исследования, медицина, открытия\', \'#6f42c1\'),
    (\'Serbia\', \'Сербия\', \'Новости Сербии, политика, общество\', \'#dc3545\'),
    (\'Other\', \'Прочее\', \'Остальные новости\', \'#6c757d\')
ON CONFLICT (name) DO NOTHING;
    '''
    
    async with AsyncSessionLocal() as db:
        statements = [stmt.strip() for stmt in migration_sql.split(';') if stmt.strip()]
        for stmt in statements:
            if stmt.strip():
                await db.execute(text(stmt))
        await db.commit()
        print('✅ Schema migration completed')

asyncio.run(apply_schema_migration())
"

if [ $? -eq 0 ]; then
    echo "✅ Schema migration completed"
else
    echo "❌ Schema migration failed! Check logs."
    exit 1
fi

# Step 3: Migrate simple categories
echo ""
echo "📦 Step 3: Migrating simple categories..."
docker exec production-app python -c "
import asyncio
from news_aggregator.database import AsyncSessionLocal
from sqlalchemy import text

async def migrate_simple_categories():
    async with AsyncSessionLocal() as db:
        # Migrate simple categories (non-composite)
        result = await db.execute(text('''
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
            ON CONFLICT (article_id, category_id) DO NOTHING
        '''))
        
        await db.commit()
        print(f'✅ Migrated simple categories')

asyncio.run(migrate_simple_categories())
"

if [ $? -eq 0 ]; then
    echo "✅ Simple categories migrated"
else
    echo "❌ Simple categories migration failed!"
    exit 1
fi

# Step 4: Migrate composite categories
echo ""
echo "🔀 Step 4: Migrating composite categories..."
docker exec production-app python -c "
import asyncio
from sqlalchemy import text
from news_aggregator.database import AsyncSessionLocal

async def migrate_composite_categories():
    async with AsyncSessionLocal() as db:
        # Find composite categories
        result = await db.execute(text('''
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
        '''))
        
        composite_articles = result.fetchall()
        print(f'🔍 Found {len(composite_articles)} articles with composite categories')
        
        if len(composite_articles) == 0:
            print('✅ No composite categories to migrate')
            return
        
        # Get valid categories
        cat_result = await db.execute(text('SELECT name, id FROM categories'))
        valid_categories = {name: cat_id for name, cat_id in cat_result.fetchall()}
        
        stats = {'processed': 0, 'categories_assigned': 0}
        
        for article_id, composite_category, title in composite_articles:
            print(f'📄 Article {article_id}: {composite_category}')
            
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
            
            # Remove existing relationships
            await db.execute(
                text('DELETE FROM article_categories WHERE article_id = :article_id'),
                {'article_id': article_id}
            )
            
            # Add new relationships
            for cat_name, cat_id in categories_to_assign:
                await db.execute(text('''
                    INSERT INTO article_categories (article_id, category_id, confidence)
                    VALUES (:article_id, :category_id, 1.0)
                    ON CONFLICT (article_id, category_id) DO NOTHING
                '''), {
                    'article_id': article_id,
                    'category_id': cat_id
                })
                stats['categories_assigned'] += 1
                print(f'  ✅ {cat_name}')
            
            stats['processed'] += 1
            await db.commit()
        
        print(f'📊 Composite migration stats:')
        print(f'   Processed: {stats[\"processed\"]} articles')
        print(f'   Assigned: {stats[\"categories_assigned\"]} categories')

asyncio.run(migrate_composite_categories())
"

if [ $? -eq 0 ]; then
    echo "✅ Composite categories migrated"
else
    echo "❌ Composite categories migration failed!"
    exit 1
fi

# Step 5: Verify results
echo ""
echo "🔍 Step 5: Verifying migration results..."
docker exec production-app python -c "
import asyncio
from sqlalchemy import text
from news_aggregator.database import AsyncSessionLocal

async def verify_migration():
    async with AsyncSessionLocal() as db:
        # Total relationships
        result = await db.execute(text('SELECT COUNT(*) FROM article_categories'))
        total_relationships = result.scalar()
        
        # Articles with multiple categories
        result = await db.execute(text('''
            SELECT COUNT(*) FROM (
                SELECT article_id 
                FROM article_categories 
                GROUP BY article_id 
                HAVING COUNT(*) > 1
            ) as multi_cat_articles
        '''))
        multi_category_articles = result.scalar()
        
        # Category distribution
        result = await db.execute(text('''
            SELECT c.display_name, COUNT(ac.article_id) as article_count
            FROM categories c
            LEFT JOIN article_categories ac ON c.id = ac.category_id
            GROUP BY c.id, c.display_name
            ORDER BY article_count DESC
        '''))
        
        print(f'📊 Migration Results:')
        print(f'   Total article-category relationships: {total_relationships}')
        print(f'   Articles with multiple categories: {multi_category_articles}')
        print(f'   Category distribution:')
        
        for display_name, count in result.fetchall():
            print(f'     {display_name}: {count} articles')

asyncio.run(verify_migration())
"

echo ""
echo "🎉 Migration completed successfully!"
echo "=================================================="
echo "📋 Next steps:"
echo "1. Restart application containers: docker compose restart"
echo "2. Test API endpoints: curl http://localhost:8000/api/v1/categories"
echo "3. Check web interface for multiple categories display"
echo ""
echo "💾 Backup location: $BACKUP_FILE"
echo "🔄 To rollback if needed: psql -U postgres news_aggregator < $BACKUP_FILE"
