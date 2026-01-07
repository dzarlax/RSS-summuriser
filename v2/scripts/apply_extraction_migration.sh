#!/bin/bash

# Evening News v2 - Apply Extraction Learning Migration
# Применяет миграцию для добавления таблиц AI-enhanced extraction learning

set -e

CONTAINER_NAME="v2-postgres-1"
MIGRATION_FILE="./db/migrations/001_add_extraction_learning_tables.sql"

echo "🔧 Evening News v2 - Applying Extraction Learning Migration..."
echo "📄 Migration: $MIGRATION_FILE"

# Проверяем наличие файла миграции
if [ ! -f "$MIGRATION_FILE" ]; then
    echo "❌ Error: Migration file not found: $MIGRATION_FILE"
    exit 1
fi

echo "🔍 Checking PostgreSQL container status..."

# Проверяем, запущен ли контейнер PostgreSQL
if docker ps --format 'table {{.Names}}' | grep -q "$CONTAINER_NAME"; then
    echo "✅ PostgreSQL container is running"
    
    # Применяем миграцию
    echo "🚀 Applying migration to database..."
    docker exec -i $CONTAINER_NAME psql -U newsuser -d newsdb < "$MIGRATION_FILE"
    
    if [ $? -eq 0 ]; then
        echo "✅ Migration applied successfully!"
        
        # Проверяем созданные таблицы
        echo "🔍 Verifying created tables..."
        docker exec $CONTAINER_NAME psql -U newsuser -d newsdb -c "
            SELECT 
                schemaname,
                tablename,
                tableowner
            FROM pg_tables 
            WHERE tablename IN ('extraction_patterns', 'domain_stability', 'extraction_attempts', 'ai_usage_tracking')
            ORDER BY tablename;
        "
        
        # Проверяем созданные views
        echo "📊 Verifying created views..."
        docker exec $CONTAINER_NAME psql -U newsuser -d newsdb -c "
            SELECT 
                schemaname,
                viewname,
                viewowner
            FROM pg_views 
            WHERE viewname LIKE '%extraction%' OR viewname LIKE '%ai_usage%'
            ORDER BY viewname;
        "
        
        # Проверяем начальные данные
        echo "📈 Checking initial data..."
        docker exec $CONTAINER_NAME psql -U newsuser -d newsdb -c "
            SELECT 
                'extraction_patterns' as table_name,
                COUNT(*) as records_count
            FROM extraction_patterns
            UNION ALL
            SELECT 
                'domain_stability' as table_name,
                COUNT(*) as records_count
            FROM domain_stability
            ORDER BY table_name;
        "
        
        # Проверяем индексы
        echo "🔗 Verifying indexes..."
        docker exec $CONTAINER_NAME psql -U newsuser -d newsdb -c "
            SELECT 
                schemaname,
                tablename,
                indexname
            FROM pg_indexes 
            WHERE tablename IN ('extraction_patterns', 'domain_stability', 'extraction_attempts', 'ai_usage_tracking')
            ORDER BY tablename, indexname;
        " | head -20
        
        echo ""
        echo "🎉 Extraction Learning Migration completed successfully!"
        echo "📋 Summary:"
        echo "   ✅ Created 4 new tables"
        echo "   ✅ Created 4 analytical views"  
        echo "   ✅ Added indexes for performance"
        echo "   ✅ Inserted test data for popular domains"
        echo "   ✅ Added documentation comments"
        echo ""
        echo "🚀 System is ready for AI-enhanced extraction learning!"
        
    else
        echo "❌ Migration failed!"
        exit 1
    fi
    
else
    echo "⚠️ Error: PostgreSQL container '$CONTAINER_NAME' is not running"
    echo "💡 Please start the services first:"
    echo "   docker-compose up -d"
    exit 1
fi

# Создаем backup point после успешной миграции
echo "💾 Creating backup point after migration..."
BACKUP_DIR="./backups/post_migration_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"
docker exec $CONTAINER_NAME pg_dump -U newsuser -d newsdb > "$BACKUP_DIR/database_with_extraction_learning.sql"
echo "✅ Backup created: $BACKUP_DIR"

echo "🔧 Migration completed successfully! System ready for AI-enhanced extraction."