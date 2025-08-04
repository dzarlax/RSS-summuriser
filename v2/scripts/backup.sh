#!/bin/bash

# RSS Summarizer v2 - Backup Script
# Создает полное резервное копирование всех данных для переноса сервиса

set -e

BACKUP_DIR="./backups/$(date +%Y%m%d_%H%M%S)"
CONTAINER_NAME="v2-postgres-1"

echo "🗄️ RSS Summarizer v2 - Backup Starting..."
echo "📁 Backup directory: $BACKUP_DIR"

# Создаем директорию для бэкапа
mkdir -p "$BACKUP_DIR"

# 1. Database Backup
echo "📊 Backing up PostgreSQL database..."
if docker ps --format 'table {{.Names}}' | grep -q "$CONTAINER_NAME"; then
    docker exec $CONTAINER_NAME pg_dump -U newsuser -d newsdb --data-only --column-inserts --rows-per-insert=1 > "$BACKUP_DIR/database.sql"
    echo "✅ Database backup completed"
else
    echo "⚠️ Warning: PostgreSQL container not running, skipping database backup"
fi

# 2. Configuration Backup
echo "⚙️ Backing up configuration..."
if [ -f ".env" ]; then
    cp .env "$BACKUP_DIR/"
    echo "✅ .env copied"
else
    echo "⚠️ Warning: .env file not found"
fi

cp docker-compose.yml "$BACKUP_DIR/" 2>/dev/null || echo "⚠️ Warning: docker-compose.yml not found"

if [ -d "db/" ]; then
    cp -r db/ "$BACKUP_DIR/"
    echo "✅ Database migrations copied"
else
    echo "⚠️ Warning: db/ directory not found"
fi

# 3. Application Data Backup
echo "📂 Backing up application data..."
if [ -d "./data" ]; then
    cp -r ./data "$BACKUP_DIR/"
    echo "✅ Application data copied"
fi

if [ -d "./logs" ]; then
    cp -r ./logs "$BACKUP_DIR/"
    echo "✅ Logs copied"
fi

# 4. Создаем метаданные резервной копии
echo "📋 Creating backup metadata..."
cat > "$BACKUP_DIR/backup_info.txt" << EOF
RSS Summarizer v2 - Backup Information
======================================
Backup Date: $(date)
Database: newsdb
Container: $CONTAINER_NAME
Version: v2.0
Host: $(hostname)

Contents:
- database.sql: Full PostgreSQL dump
- .env: Environment configuration
- docker-compose.yml: Docker configuration
- db/: Database migrations and init scripts
- data/: Application data files
- logs/: Application logs

Restore Command:
./scripts/restore.sh $BACKUP_DIR
EOF

# 5. Создаем архив
echo "📦 Creating backup archive..."
ARCHIVE_NAME="news_aggregator_backup_$(date +%Y%m%d_%H%M%S).tar.gz"
cd ./backups
tar -czf "$ARCHIVE_NAME" "$(basename $BACKUP_DIR)"
cd ..

echo "✅ Backup completed successfully!"
echo "📁 Backup location: $BACKUP_DIR"
echo "📦 Archive created: ./backups/$ARCHIVE_NAME"
echo ""
echo "📋 To restore on another server:"
echo "   1. Copy archive to new server"
echo "   2. Run: ./scripts/restore.sh ./backups/$ARCHIVE_NAME" 