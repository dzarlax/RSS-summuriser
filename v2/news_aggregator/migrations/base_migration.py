"""
Base classes for universal migration system.
"""

import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class BaseMigration(ABC):
    """Base class for all migrations."""
    
    def __init__(self, migration_id: str, description: str, version: str):
        self.migration_id = migration_id
        self.description = description
        self.version = version
    
    @abstractmethod
    async def check_needed(self, db: AsyncSession) -> bool:
        """Check if this migration is needed."""
        pass
    
    @abstractmethod
    async def execute(self, db: AsyncSession) -> Dict[str, Any]:
        """Execute the migration."""
        pass
    
    async def rollback(self, db: AsyncSession) -> Dict[str, Any]:
        """Rollback the migration (optional)."""
        return {"rollback": "not_implemented"}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert migration info to dictionary."""
        return {
            'description': self.description,
            'check_function': self.check_needed,
            'migrate_function': self.execute,
            'rollback_function': self.rollback,
            'version': self.version
        }


class TableExistsMigration(BaseMigration):
    """Migration that checks if specific tables exist."""
    
    def __init__(self, migration_id: str, description: str, version: str, 
                 required_tables: list, sql_statements: list):
        super().__init__(migration_id, description, version)
        self.required_tables = required_tables
        self.sql_statements = sql_statements
    
    async def check_needed(self, db: AsyncSession) -> bool:
        """Check if required tables exist."""
        for table_name in self.required_tables:
            try:
                await db.execute(text(f"SELECT 1 FROM {table_name} LIMIT 1"))
            except:
                logger.info(f"📋 Table '{table_name}' not found - migration needed")
                return True
        return False
    
    async def execute(self, db: AsyncSession) -> Dict[str, Any]:
        """Execute SQL statements."""
        migration_result = {
            'statements_executed': 0,
            'tables_created': len(self.required_tables),
            'errors': []
        }
        
        try:
            for sql in self.sql_statements:
                if sql.strip():
                    await db.execute(text(sql))
                    migration_result['statements_executed'] += 1
            
            await db.commit()
            logger.info(f"✅ {self.migration_id} completed successfully")
            return migration_result
            
        except Exception as e:
            error_msg = f"{self.migration_id} failed: {str(e)}"
            logger.error(error_msg)
            migration_result['errors'].append(error_msg)
            await db.rollback()
            raise


class DataMigration(BaseMigration):
    """Migration for data transformations."""
    
    def __init__(self, migration_id: str, description: str, version: str,
                 check_query: str, migrate_queries: list):
        super().__init__(migration_id, description, version)
        self.check_query = check_query
        self.migrate_queries = migrate_queries
    
    async def check_needed(self, db: AsyncSession) -> bool:
        """Check using custom query."""
        try:
            result = await db.execute(text(self.check_query))
            count = result.scalar()
            return count > 0
        except Exception as e:
            logger.warning(f"Could not check {self.migration_id}: {e}")
            return True  # Assume needed if can't check
    
    async def execute(self, db: AsyncSession) -> Dict[str, Any]:
        """Execute migration queries."""
        migration_result = {
            'queries_executed': 0,
            'rows_affected': 0,
            'errors': []
        }
        
        try:
            for query in self.migrate_queries:
                if query.strip():
                    result = await db.execute(text(query))
                    migration_result['queries_executed'] += 1
                    migration_result['rows_affected'] += result.rowcount
            
            await db.commit()
            logger.info(f"✅ {self.migration_id} completed: {migration_result['rows_affected']} rows affected")
            return migration_result
            
        except Exception as e:
            error_msg = f"{self.migration_id} failed: {str(e)}"
            logger.error(error_msg)
            migration_result['errors'].append(error_msg)
            await db.rollback()
            raise


# Примеры использования:

# 1. Простая миграция таблиц
user_preferences_migration = TableExistsMigration(
    migration_id='003_user_preferences',
    description='Add user preferences tables',
    version='2.1.0',
    required_tables=['user_preferences', 'user_settings'],
    sql_statements=[
        """
        CREATE TABLE IF NOT EXISTS user_preferences (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            preference_key VARCHAR(100) NOT NULL,
            preference_value TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS user_settings (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            theme VARCHAR(20) DEFAULT 'light',
            language VARCHAR(5) DEFAULT 'en'
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_user_preferences_user_id ON user_preferences(user_id)"
    ]
)

# 2. Миграция данных
cleanup_old_data_migration = DataMigration(
    migration_id='004_cleanup_old_data',
    description='Remove articles older than 1 year',
    version='2.2.0',
    check_query="SELECT COUNT(*) FROM articles WHERE created_at < NOW() - INTERVAL '1 year'",
    migrate_queries=[
        "DELETE FROM articles WHERE created_at < NOW() - INTERVAL '1 year'",
        "VACUUM ANALYZE articles"
    ]
)
