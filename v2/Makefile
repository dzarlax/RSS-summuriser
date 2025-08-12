# RSS Summarizer v2 Makefile

.PHONY: help dev prod stop clean logs shell db-shell migrate test lint format backup restore export import migration-prepare

help: ## Show this help message
	@echo "RSS Summarizer v2 Commands:"
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

##@ Development

check-data: ## Check existing data in volumes
	@echo "🔍 Checking existing data..."
	@echo "📦 PostgreSQL data volume:"
	@docker run --rm -v v2_postgres_data:/data alpine sh -c "ls -la /data/ | head -10" 2>/dev/null || echo "No PostgreSQL data found"
	@echo ""
	@echo "💾 App cache volume:"
	@docker run --rm -v v2_app_cache:/data alpine sh -c "ls -la /data/ | head -10" 2>/dev/null || echo "No cache data found"

dev: ## Start development environment (with hot reload)
	docker-compose -f docker-compose.dev.yml up -d
	@echo "🚀 Development environment started!"
	@echo "📱 Admin: http://localhost:8000/admin"
	@echo "📚 API Docs: http://localhost:8000/docs"
	@echo "🗄️ Database: localhost:5432"
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

db-shell: ## Open PostgreSQL shell
	docker-compose -f docker-compose.dev.yml exec postgres psql -U newsuser -d newsdb

##@ Production

prod: ## Start production environment
	docker-compose up -d
	@echo "🚀 Production environment started!"

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
	@echo "🔧 Setting up RSS Summarizer v2..."
	cp .env.example .env
	@echo "📝 Please edit .env file with your configuration"
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
	docker exec v2-postgres-1 pg_dump -U newsuser -d newsdb > exports/migration_$(shell date +%Y%m%d_%H%M%S).sql
	@echo "✅ Database exported to exports/"

import: ## Import data from migration file (usage: make import FILE=./exports/migration.sql)
	@if [ -z "$(FILE)" ]; then \
		echo "❌ Usage: make import FILE=./exports/migration.sql"; \
		exit 1; \
	fi
	@echo "📥 Importing data..."
	docker exec -i v2-postgres-1 psql -U newsuser -d newsdb < $(FILE)
	@echo "✅ Data imported successfully"

migration-prepare: ## Prepare for migration to new server
	@echo "📦 Preparing migration package..."
	@make backup
	@echo "✅ Migration package ready in ./backups/"
	@echo ""
	@echo "📋 Instructions for new server:"
	@echo "   1. Copy RSS Summarizer v2 source code"
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
	@echo "📊 Database size information:"
	@docker exec v2-postgres-1 psql -U newsuser -d newsdb -c "\l+"
	@docker exec v2-postgres-1 psql -U newsuser -d newsdb -c "\dt+"

volumes-list: ## List Docker volumes
	@echo "📦 Docker volumes:"
	@docker volume ls | grep v2
	@echo ""
	@echo "📊 Volume sizes:"
	@docker system df -v | grep v2 || true

volumes-backup: ## Backup Docker volumes
	@echo "💾 Backing up Docker volumes..."
	@mkdir -p backups/volumes
	@docker run --rm -v v2_postgres_data:/data -v $(PWD)/backups/volumes:/backup alpine tar czf /backup/postgres_data_$(shell date +%Y%m%d_%H%M%S).tar.gz -C /data .
	@docker run --rm -v v2_app_cache:/data -v $(PWD)/backups/volumes:/backup alpine tar czf /backup/app_cache_$(shell date +%Y%m%d_%H%M%S).tar.gz -C /data . 2>/dev/null || true
	@echo "✅ Volumes backed up to backups/volumes/"