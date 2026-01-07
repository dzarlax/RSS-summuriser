# Evening News v2 Makefile

.PHONY: help dev prod stop clean logs shell db-shell migrate test lint format backup restore export import migration-prepare

help: ## Show this help message
	@echo "Evening News v2 Commands:"
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

##@ Development

check-data: ## Check existing data in volumes
	@echo "🔍 Checking existing data..."
	@echo "💾 App cache volume:"
	@docker run --rm -v v2_app_cache:/data alpine sh -c "ls -la /data/ | head -10" 2>/dev/null || echo "No cache data found"
	@echo ""
	@echo "📁 App data directories:"
	@ls -la data/ logs/ backups/ 2>/dev/null || echo "No local data directories found"

dev: ## Start development environment (with hot reload)
	docker-compose -f docker-compose.dev.yml up -d
	@echo "🚀 Development environment started!"
	@echo "📱 Admin: http://localhost:8000/admin"
	@echo "📚 API Docs: http://localhost:8000/docs"
	@echo "🗄️ Database: MariaDB at 192.168.50.5:3306 (external)"
	@echo "⚡ Hot reload enabled - code changes apply automatically!"

stop: ## Stop all containers
	docker-compose -f docker-compose.dev.yml down
	docker-compose down

clean: ## Stop containers and remove volumes
	docker-compose -f docker-compose.dev.yml down -v
	docker-compose down -v
	docker system prune -f

logs: ## Show application logs
	docker-compose -f docker-compose.dev.yml logs -f app

shell: ## Open shell in app container
	docker-compose -f docker-compose.dev.yml exec app /bin/bash

db-shell: ## Open MariaDB shell (external database)
	@echo "🗄️ Connecting to external MariaDB..."
	docker run -it --rm mariadb:11 mysql -h 192.168.50.5 -u dzarlax -p newsdbdev

##@ Production

build: ## Build Docker image
	@echo "🏗️ Building Docker image..."
	docker build -f docker/Dockerfile -t dzarlax/rss-summarizer:latest \
		--build-arg BUILDTIME="$(shell date -u +'%Y-%m-%dT%H:%M:%SZ')" \
		--build-arg VERSION="$(shell git describe --tags --always 2>/dev/null || echo 'dev')" \
		--build-arg REVISION="$(shell git rev-parse --short HEAD 2>/dev/null || echo 'unknown')" \
		.
	@echo "✅ Docker image built successfully!"

push: build ## Build and push Docker image to registry
	@echo "🚀 Pushing Docker image to registry..."
	docker push dzarlax/rss-summarizer:latest
	@echo "✅ Docker image pushed successfully!"

prod: ## Start production environment
	docker-compose up -d
	@echo "🚀 Production environment started!"

prod-update: ## Pull latest image and restart production
	@echo "⬇️ Pulling latest Docker image..."
	docker-compose pull
	docker-compose up -d --force-recreate
	@echo "✅ Production updated and restarted!"

##@ Application

migrate: ## Run migration from v1
	docker-compose -f docker-compose.dev.yml exec app python migration.py

process: ## Run news processing
	docker-compose -f docker-compose.dev.yml exec app python -m news_aggregator process

sources: ## Show sources
	docker-compose -f docker-compose.dev.yml exec app python -m news_aggregator sources

stats: ## Show processing stats
	docker-compose -f docker-compose.dev.yml exec app python -m news_aggregator stats

##@ Development Tools

test: ## Run tests
	docker-compose -f docker-compose.dev.yml exec app pytest tests/ -v

lint: ## Run linting
	docker-compose -f docker-compose.dev.yml exec app ruff check .
	docker-compose -f docker-compose.dev.yml exec app mypy news_aggregator/

format: ## Format code
	docker-compose -f docker-compose.dev.yml exec app black .
	docker-compose -f docker-compose.dev.yml exec app isort .

##@ Setup

setup: ## Initial setup
	@echo "🔧 Setting up Evening News v2..."
	cp .env.example .env 2>/dev/null || echo "⚠️ .env.example not found, create .env manually"
	@echo "📝 Please edit .env file with your configuration"
	@echo "🔗 Database: External MariaDB at 192.168.50.5:3306"
	@echo "🐳 Run 'make dev' to start development environment"

install: ## Install local dependencies (for IDE)
	pip install -r requirements-dev.txt

##@ Backup & Restore

backup: ## Create full backup of all data
	@echo "🗄️ Creating backup..."
	@mkdir -p scripts backups/postgres
	@chmod +x scripts/backup.sh
	./scripts/backup.sh

restore: ## Restore from backup (usage: make restore BACKUP=./backups/20241231_120000)
	@if [ -z "$(BACKUP)" ]; then \
		echo "❌ Usage: make restore BACKUP=./backups/20241231_120000"; \
		echo "📦 Or: make restore BACKUP=./backups/backup.tar.gz"; \
		exit 1; \
	fi
	@echo "🔄 Restoring from backup..."
	@chmod +x scripts/restore.sh
	./scripts/restore.sh $(BACKUP)

export: ## Export current data for migration
	@echo "📤 Exporting data for migration..."
	@mkdir -p exports
	@echo "🗄️ Using external MariaDB - run mysqldump manually:"
	@echo "   mysqldump -h 192.168.50.5 -u dzarlax -p newsdb > exports/migration_$(shell date +%Y%m%d_%H%M%S).sql"

import: ## Import data from migration file (usage: make import FILE=./exports/migration.sql)
	@if [ -z "$(FILE)" ]; then \
		echo "❌ Usage: make import FILE=./exports/migration.sql"; \
		exit 1; \
	fi
	@echo "📥 Importing data to external MariaDB..."
	@echo "🗄️ Run manually:"
	@echo "   mysql -h 192.168.50.5 -u dzarlax -p newsdb < $(FILE)"

migration-prepare: ## Prepare for migration to new server
	@echo "📦 Preparing migration package..."
	@make backup
	@echo "✅ Migration package ready in ./backups/"
	@echo ""
	@echo "📋 Instructions for new server:"
	@echo "   1. Copy Evening News v2 source code"
	@echo "   2. Copy latest backup archive from ./backups/"
	@echo "   3. Run: make restore BACKUP=backup.tar.gz"

##@ Data Management

list-backups: ## List available backups
	@echo "📂 Available backups:"
	@ls -la backups/ 2>/dev/null || echo "No backups found"

cleanup-backups: ## Remove backups older than 30 days
	@echo "🧹 Cleaning up old backups (older than 30 days)..."
	@find backups/ -name "*.tar.gz" -mtime +30 -delete 2>/dev/null || true
	@find backups/ -type d -mtime +30 -exec rm -rf {} + 2>/dev/null || true
	@echo "✅ Cleanup completed"

db-size: ## Show database size
	@echo "📊 Database size information (external MariaDB):"
	@echo "🗄️ Run manually:"
	@echo "   docker run -it --rm mariadb:11 mysql -h 192.168.50.5 -u dzarlax -p -e 'SELECT table_schema, SUM(data_length + index_length) / 1024 / 1024 AS size_mb FROM information_schema.tables WHERE table_schema = \"newsdb\" GROUP BY table_schema;'"

volumes-list: ## List Docker volumes
	@echo "📦 Docker volumes:"
	@docker volume ls | grep v2
	@echo ""
	@echo "📊 Volume sizes:"
	@docker system df -v | grep v2 || true

volumes-backup: ## Backup Docker volumes
	@echo "💾 Backing up Docker volumes..."
	@mkdir -p backups/volumes
	@docker run --rm -v v2_app_cache:/data -v $(PWD)/backups/volumes:/backup alpine tar czf /backup/app_cache_$(shell date +%Y%m%d_%H%M%S).tar.gz -C /data . 2>/dev/null || true
	@docker run --rm -v app_cache:/data -v $(PWD)/backups/volumes:/backup alpine tar czf /backup/app_cache_prod_$(shell date +%Y%m%d_%H%M%S).tar.gz -C /data . 2>/dev/null || true
	@echo "✅ Volumes backed up to backups/volumes/"