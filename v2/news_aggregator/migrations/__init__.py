"""
Database migrations system for RSS Summarizer v2.
"""

# Универсальная система миграций
from .universal_migration_manager import UniversalMigrationManager, create_migration_manager
from .base_migration import BaseMigration, TableExistsMigration, DataMigration

__all__ = [
    # Универсальная система  
    'UniversalMigrationManager', 'create_migration_manager',
    'BaseMigration', 'TableExistsMigration', 'DataMigration'
]
