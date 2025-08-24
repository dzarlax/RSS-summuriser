"""
Universal Migration Manager - fully reusable migration system.
Can be used in any FastAPI + SQLAlchemy + AsyncPG project.
"""

import asyncio
import logging
from typing import Dict, List, Optional, Any, Union
from datetime import datetime
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .base_migration import BaseMigration, TableExistsMigration, DataMigration

logger = logging.getLogger(__name__)


class UniversalMigrationManager:
    """
    Universal migration manager that can be used in any project.
    
    Features:
    - Automatic migration detection and execution
    - Support for custom migration classes
    - Built-in migration types (table creation, data migration)
    - Rollback support
    - Comprehensive logging and error handling
    - API endpoints integration
    - Version tracking
    """
    
    def __init__(self, db_session_factory, app_name: str = "Application"):
        """
        Initialize migration manager.
        
        Args:
            db_session_factory: Async database session factory (e.g., AsyncSessionLocal)
            app_name: Application name for logging
        """
        self.db_session_factory = db_session_factory
        self.app_name = app_name
        self.migrations: Dict[str, Union[BaseMigration, Dict[str, Any]]] = {}
        self._migration_history: List[Dict[str, Any]] = []
    
    def register_migration(self, migration: Union[BaseMigration, Dict[str, Any]]):
        """Register a migration."""
        if isinstance(migration, BaseMigration):
            self.migrations[migration.migration_id] = migration
        elif isinstance(migration, dict) and 'id' in migration:
            self.migrations[migration['id']] = migration
        else:
            raise ValueError("Migration must be BaseMigration instance or dict with 'id' key")
    
    def register_table_migration(self, migration_id: str, description: str, version: str,
                                required_tables: List[str], sql_statements: List[str]):
        """Register a table creation migration."""
        migration = TableExistsMigration(migration_id, description, version, 
                                       required_tables, sql_statements)
        self.register_migration(migration)
    
    def register_data_migration(self, migration_id: str, description: str, version: str,
                               check_query: str, migrate_queries: List[str]):
        """Register a data migration."""
        migration = DataMigration(migration_id, description, version,
                                check_query, migrate_queries)
        self.register_migration(migration)
    
    def register_custom_migration(self, migration_id: str, description: str, version: str,
                                 check_function, migrate_function, rollback_function=None):
        """Register a custom migration (legacy format)."""
        migration_dict = {
            'id': migration_id,
            'description': description,
            'version': version,
            'check_function': check_function,
            'migrate_function': migrate_function,
            'rollback_function': rollback_function
        }
        self.register_migration(migration_dict)
    
    async def check_and_run_migrations(self, dry_run: bool = False) -> Dict[str, Any]:
        """
        Check if migrations are needed and run them automatically.
        
        Args:
            dry_run: If True, only check what would be migrated without executing
            
        Returns:
            Migration results with statistics and errors
        """
        results = {
            'migrations_run': [],
            'migrations_skipped': [],
            'errors': [],
            'total_time': 0,
            'dry_run': dry_run
        }
        
        start_time = datetime.now()
        
        try:
            async with self.db_session_factory() as db:
                logger.info(f"🔍 Checking for required migrations in {self.app_name}...")
                
                for migration_id, migration in self.migrations.items():
                    try:
                        logger.info(f"Checking migration: {migration_id}")
                        
                        # Check if migration is needed
                        if isinstance(migration, BaseMigration):
                            is_needed = await migration.check_needed(db)
                            description = migration.description
                        else:
                            is_needed = await migration['check_function'](db)
                            description = migration['description']
                        
                        if is_needed:
                            logger.info(f"🔄 {'[DRY RUN] ' if dry_run else ''}Running migration: {migration_id}")
                            logger.info(f"   Description: {description}")
                            
                            if not dry_run:
                                # Run migration
                                if isinstance(migration, BaseMigration):
                                    migration_result = await migration.execute(db)
                                else:
                                    migration_result = await migration['migrate_function'](db)
                                
                                # Record in history
                                self._migration_history.append({
                                    'migration_id': migration_id,
                                    'executed_at': datetime.now(),
                                    'result': migration_result
                                })
                            else:
                                migration_result = {'dry_run': True}
                            
                            results['migrations_run'].append({
                                'id': migration_id,
                                'description': description,
                                'result': migration_result
                            })
                            
                            logger.info(f"✅ {'[DRY RUN] ' if dry_run else ''}Migration completed: {migration_id}")
                            
                        else:
                            logger.info(f"⏭️ Migration not needed: {migration_id}")
                            results['migrations_skipped'].append({
                                'id': migration_id,
                                'reason': 'Already applied or not needed'
                            })
                            
                    except Exception as e:
                        error_msg = f"Migration {migration_id} failed: {str(e)}"
                        logger.error(error_msg)
                        results['errors'].append(error_msg)
                        continue
                
                end_time = datetime.now()
                results['total_time'] = (end_time - start_time).total_seconds()
                
                if results['migrations_run']:
                    logger.info(f"🎉 {'[DRY RUN] ' if dry_run else ''}Completed {len(results['migrations_run'])} migrations in {results['total_time']:.1f}s")
                else:
                    logger.info(f"✅ No migrations needed - {self.app_name} database is up to date")
                    
                return results
                
        except Exception as e:
            error_msg = f"Migration system error: {str(e)}"
            logger.error(error_msg)
            results['errors'].append(error_msg)
            return results
    
    async def rollback_migration(self, migration_id: str) -> Dict[str, Any]:
        """Rollback a specific migration."""
        if migration_id not in self.migrations:
            raise ValueError(f"Migration {migration_id} not found")
        
        migration = self.migrations[migration_id]
        
        try:
            async with self.db_session_factory() as db:
                logger.info(f"🔄 Rolling back migration: {migration_id}")
                
                if isinstance(migration, BaseMigration):
                    result = await migration.rollback(db)
                elif 'rollback_function' in migration and migration['rollback_function']:
                    result = await migration['rollback_function'](db)
                else:
                    raise NotImplementedError(f"Rollback not implemented for {migration_id}")
                
                logger.info(f"✅ Rollback completed: {migration_id}")
                return result
                
        except Exception as e:
            error_msg = f"Rollback failed for {migration_id}: {str(e)}"
            logger.error(error_msg)
            raise
    
    def get_migration_status(self) -> Dict[str, Any]:
        """Get current migration status."""
        return {
            'app_name': self.app_name,
            'total_migrations': len(self.migrations),
            'available_migrations': list(self.migrations.keys()),
            'migration_history': self._migration_history,
            'last_check': datetime.now().isoformat()
        }
    
    def get_migration_info(self, migration_id: str) -> Optional[Dict[str, Any]]:
        """Get information about a specific migration."""
        if migration_id not in self.migrations:
            return None
        
        migration = self.migrations[migration_id]
        
        if isinstance(migration, BaseMigration):
            return {
                'id': migration.migration_id,
                'description': migration.description,
                'version': migration.version,
                'type': migration.__class__.__name__
            }
        else:
            return {
                'id': migration_id,
                'description': migration.get('description', 'No description'),
                'version': migration.get('version', 'Unknown'),
                'type': 'Custom'
            }


# Factory function for easy integration
def create_migration_manager(db_session_factory, app_name: str = "Application") -> UniversalMigrationManager:
    """Create a migration manager instance."""
    return UniversalMigrationManager(db_session_factory, app_name)


# Example usage:
"""
# In your main.py or migration setup:

from news_aggregator.migrations.universal_migration_manager import create_migration_manager
from news_aggregator.database import AsyncSessionLocal

# Create migration manager
migration_manager = create_migration_manager(AsyncSessionLocal, "RSS Summarizer v2")

# Register migrations
migration_manager.register_table_migration(
    migration_id='001_create_users',
    description='Create users and roles tables',
    version='1.0.0',
    required_tables=['users', 'roles'],
    sql_statements=[
        '''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username VARCHAR(50) UNIQUE NOT NULL,
            email VARCHAR(100) UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''',
        '''
        CREATE TABLE IF NOT EXISTS roles (
            id SERIAL PRIMARY KEY,
            name VARCHAR(30) UNIQUE NOT NULL
        )
        '''
    ]
)

migration_manager.register_data_migration(
    migration_id='002_migrate_old_data',
    description='Migrate data from old format',
    version='1.1.0',
    check_query="SELECT COUNT(*) FROM old_table WHERE migrated = false",
    migrate_queries=[
        "UPDATE old_table SET migrated = true WHERE migrated = false",
        "INSERT INTO new_table SELECT * FROM old_table WHERE migrated = true"
    ]
)

# In FastAPI lifespan:
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Run migrations on startup
    results = await migration_manager.check_and_run_migrations()
    if results['errors']:
        logger.warning(f"Migration errors: {results['errors']}")
    
    yield

# API endpoints:
@app.get("/api/migrations/status")
async def get_migration_status():
    return migration_manager.get_migration_status()

@app.post("/api/migrations/run")
async def run_migrations():
    results = await migration_manager.check_and_run_migrations()
    return {"success": len(results['errors']) == 0, "results": results}
"""
