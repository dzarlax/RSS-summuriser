#!/bin/bash

# RSS Summarizer v2 - Backup Script (MariaDB version)
# Создает полное резервное копирование всех данных для переноса сервиса

set -e

BACKUP_DIR="./backups/$(date +%Y%m%d_%H%M%S)"
CONTAINER_NAME="v2-app-1"

# MariaDB connection settings (from docker-compose.yml)
DB_HOST="192.168.50.5"
DB_PORT="3306"
DB_USER="dzarlax"
DB_PASS=""
DB_NAME_PROD="newsdb"
DB_NAME_DEV="newsdbdev"

echo "🗄️ RSS Summarizer v2 - Backup Starting..."
echo "📁 Backup directory: $BACKUP_DIR"

# Создаем директорию для бэкапа
mkdir -p "$BACKUP_DIR"

# Determine which database to backup
if docker exec $CONTAINER_NAME printenv DATABASE_URL | grep -q "newsdbdev"; then
    DB_NAME="$DB_NAME_DEV"
    echo "📊 Backing up MariaDB database (DEV): $DB_NAME"
else
    DB_NAME="$DB_NAME_PROD"
    echo "📊 Backing up MariaDB database (PROD): $DB_NAME"
fi

# 1. Database Backup using mysqldump from container
if docker ps --format 'table {{.Names}}' | grep -q "$CONTAINER_NAME"; then
    docker exec $CONTAINER_NAME mysqldump \
        -h "$DB_HOST" \
        -P "$DB_PORT" \
        -u "$DB_USER" \
        -p"$DB_PASS" \
        --single-transaction \
        --routines \
        --triggers \
        --events \
        "$DB_NAME" > "$BACKUP_DIR/database.sql"
    echo "✅ Database backup completed"
else
    echo "⚠️ Warning: Application container not running, skipping database backup"
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
Database: $DB_NAME (MariaDB @ $DB_HOST:$DB_PORT)
Container: $CONTAINER_NAME
Version: v2.0 (MariaDB)
Host: $(hostname)

Contents:
- database.sql: Full MariaDB dump (mysqldump format)
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