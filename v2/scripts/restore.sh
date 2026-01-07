#!/bin/bash

# Evening News v2 - Restore Script
# Восстанавливает данные из резервной копии

set -e

if [ -z "$1" ]; then
    echo "❌ Usage: ./scripts/restore.sh <backup_directory_or_archive>"
    echo "📂 Example: ./scripts/restore.sh ./backups/20241231_120000"
    echo "📦 Example: ./scripts/restore.sh ./backups/backup.tar.gz"
    exit 1
fi

BACKUP_SOURCE="$1"
TEMP_DIR=""

# Если это архив, распаковываем
if [[ "$BACKUP_SOURCE" == *.tar.gz ]]; then
    echo "📦 Extracting backup archive..."
    TEMP_DIR="./temp_restore_$(date +%s)"
    mkdir -p "$TEMP_DIR"
    tar -xzf "$BACKUP_SOURCE" -C "$TEMP_DIR"
    BACKUP_DIR="$TEMP_DIR/$(ls $TEMP_DIR | head -n1)"
else
    BACKUP_DIR="$BACKUP_SOURCE"
fi

echo "🔄 Evening News v2 - Restore Starting..."
echo "📁 Restore from: $BACKUP_DIR"

# Проверяем что директория с бэкапом существует
if [ ! -d "$BACKUP_DIR" ]; then
    echo "❌ Backup directory not found: $BACKUP_DIR"
    exit 1
fi

# Показываем информацию о бэкапе
if [ -f "$BACKUP_DIR/backup_info.txt" ]; then
    echo "📋 Backup Information:"
    cat "$BACKUP_DIR/backup_info.txt"
    echo ""
    read -p "Continue with restore? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "❌ Restore cancelled"
        exit 1
    fi
fi

# Определяем compose файл
COMPOSE_FILE="docker-compose.yml"
if [ -f "docker-compose.production.yml" ] && [ -n "${USE_PRODUCTION:-}" ]; then
    COMPOSE_FILE="docker-compose.production.yml"
    echo "🏭 Using production configuration"
fi

# Останавливаем контейнеры
echo "⏹️ Stopping containers..."
docker-compose -f "$COMPOSE_FILE" down || true

# 1. Configuration - НЕ ВОССТАНАВЛИВАЕТСЯ
echo "ℹ️  Note: Using repository files (docker-compose.yml, db/init.sql)"
echo "ℹ️  Note: Backup contains only data, not configuration"

# 2. Restore Application Data
echo "📂 Restoring application data..."
if [ -d "$BACKUP_DIR/data" ]; then
    if [ -d "./data" ]; then
        rm -rf ./data.backup.$(date +%s) 2>/dev/null || true
        mv ./data ./data.backup.$(date +%s) 2>/dev/null || true
    fi
    cp -r "$BACKUP_DIR/data" .
    echo "✅ Application data restored"
fi

if [ -d "$BACKUP_DIR/logs" ]; then
    if [ -d "./logs" ]; then
        rm -rf ./logs.backup.$(date +%s) 2>/dev/null || true
        mv ./logs ./logs.backup.$(date +%s) 2>/dev/null || true
    fi
    cp -r "$BACKUP_DIR/logs" .
    echo "✅ Logs restored"
fi

# 3. Start Application Container (Database is external MariaDB)
echo "🐳 Starting application container..."
docker-compose -f "$COMPOSE_FILE" up -d app
echo "⏳ Waiting for application to be ready..."
sleep 10

# MariaDB connection settings (from docker-compose.yml)
DB_HOST="192.168.50.5"
DB_PORT="3306"
DB_USER="dzarlax"
DB_PASS=""

# Determine which database to restore to
CONTAINER_NAME="v2-app-1"
if docker exec $CONTAINER_NAME printenv DATABASE_URL | grep -q "newsdbdev"; then
    DB_NAME="newsdbdev"
    echo "📊 Restoring to MariaDB database (DEV): $DB_NAME"
else
    DB_NAME="newsdb"
    echo "📊 Restoring to MariaDB database (PROD): $DB_NAME"
fi

# Проверяем что MariaDB доступна
RETRIES=0
MAX_RETRIES=30
while ! docker exec $CONTAINER_NAME mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PASS" -e "SELECT 1" > /dev/null 2>&1; do
    RETRIES=$((RETRIES + 1))
    if [ $RETRIES -eq $MAX_RETRIES ]; then
        echo "❌ MariaDB failed to connect after $MAX_RETRIES attempts"
        exit 1
    fi
    echo "⏳ Waiting for MariaDB... ($RETRIES/$MAX_RETRIES)"
    sleep 2
done

# 4. Restore Database
echo "📊 Restoring database..."
if [ -f "$BACKUP_DIR/database.sql" ]; then
    echo "⚠️  Warning: This will overwrite all data in $DB_NAME database"
    read -p "Continue? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "❌ Restore cancelled"
        exit 1
    fi

    echo "📥 Importing database dump..."
    docker exec -i $CONTAINER_NAME mysql \
        -h "$DB_HOST" \
        -P "$DB_PORT" \
        -u "$DB_USER" \
        -p"$DB_PASS" \
        "$DB_NAME" < "$BACKUP_DIR/database.sql"
    echo "✅ Database restored"
else
    echo "⚠️ database.sql not found, starting with fresh database"
    echo "🔧 Running database migrations..."
    docker exec v2-postgres-1 psql -U newsuser -d newsdb -f /docker-entrypoint-initdb.d/01_init.sql
fi

# 5. Start All Services
echo "🚀 Starting all services..."
docker-compose -f "$COMPOSE_FILE" up -d

echo "⏳ Waiting for services to start..."
sleep 10

# 6. Verify Services
echo "🔍 Verifying services..."
if docker-compose -f "$COMPOSE_FILE" ps | grep -q "Up"; then
    echo "✅ Services are running"
else
    echo "⚠️ Warning: Some services may not be running properly"
    docker-compose -f "$COMPOSE_FILE" ps
fi

# Cleanup
if [ -n "$TEMP_DIR" ]; then
    rm -rf "$TEMP_DIR"
fi

echo ""
echo "✅ Restore completed successfully!"
echo "🌐 Service should be available at: http://localhost:8000"
echo "🔧 Admin panel: http://localhost:8000/admin"
echo ""
echo "📊 To verify the restore:"
echo "   docker-compose logs -f app"
echo "   curl http://localhost:8000/api/v1/sources" 