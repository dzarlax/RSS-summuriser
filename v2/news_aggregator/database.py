"""Database connection and models."""

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

from .config import settings

# Create async engine with enhanced connection pool settings
engine = create_async_engine(
    settings.database_url.replace("postgresql://", "postgresql+asyncpg://"),
    echo=False,  # Disabled SQL logging for cleaner logs
    future=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    pool_pre_ping=settings.db_pool_pre_ping,
    pool_recycle=settings.db_pool_recycle,
    # Enhanced pool cleanup settings - force cleanup of connections
    pool_reset_on_return='rollback',  # More aggressive cleanup on return
    connect_args={
        "server_settings": {
            "application_name": "RSS_Aggregator_V2",
            "statement_timeout": str(settings.db_statement_timeout),  # Configurable timeout
        },
        # Enhanced timeout settings for asyncpg
        "command_timeout": 60,  # Individual command timeout
    }
)

# Create async session factory with enhanced settings
AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    # Enhanced session settings to prevent connection leaks
    autoflush=True,
    autocommit=False
)

# Base class for models
Base = declarative_base()


async def init_db():
    """Initialize database."""
    import os
    import logging
    from pathlib import Path
    
    logger = logging.getLogger(__name__)
    logger.info("🔧 Checking database initialization...")
    
    try:
        # Check if database is already initialized
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1 FROM articles LIMIT 1"))
            logger.info("✅ Database already initialized")
            return
    except Exception:
        # База не инициализирована, выполняем init.sql
        logger.info("🚀 Initializing database from init.sql...")
        
        # Путь к init.sql
        init_sql_path = Path(__file__).parent.parent / "db" / "init.sql"
        
        if not init_sql_path.exists():
            logger.error(f"❌ init.sql not found at {init_sql_path}")
            raise FileNotFoundError(f"init.sql not found at {init_sql_path}")
        
        # Читаем и выполняем init.sql
        with open(init_sql_path, 'r', encoding='utf-8') as f:
            init_sql = f.read()
        
        # Используем psql для выполнения сложного SQL с функциями  
        import subprocess
        import tempfile
        
        # Создаем временный файл с SQL
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sql', delete=False) as tmp_file:
            tmp_file.write(init_sql)
            tmp_sql_path = tmp_file.name
        
        try:
            # Execute via psql using parsed settings from database_url
            from urllib.parse import urlparse
            parsed = urlparse(settings.database_url)
            host = parsed.hostname or 'localhost'
            port = str(parsed.port or 5432)
            user = parsed.username or 'postgres'
            password = parsed.password or ''
            dbname = (parsed.path or '/postgres').lstrip('/')

            env = os.environ.copy()
            if password:
                env['PGPASSWORD'] = password
            
            result = subprocess.run([
                'psql',
                '-h', host,
                '-p', port,
                '-U', user,
                '-d', dbname,
                '-f', tmp_sql_path
            ], env=env, capture_output=True, text=True)
            
            if result.returncode != 0:
                logger.error(f"❌ psql failed: {result.stderr}")
                raise RuntimeError(f"Database initialization failed: {result.stderr}")
                
        finally:
            # Удаляем временный файл
            os.unlink(tmp_sql_path)
        
        logger.info("✅ Database initialization completed")


async def get_db():
    """Dependency to get database session with proper cleanup."""
    import logging
    logger = logging.getLogger(__name__)
    
    # Log pool status before getting connection
    try:
        pool_status = engine.pool.status()
        logger.debug(f"📊 DB Pool before request: {pool_status}")
    except:
        pass
    
    session = AsyncSessionLocal()
    try:
        yield session
    except Exception as e:
        logger.error(f"Database session error: {e}")
        await session.rollback()
        raise
    finally:
        try:
            await session.close()
            logger.debug("🔒 Session closed successfully")
        except Exception as e:
            logger.warning(f"Error closing session: {e}")
            # Force cleanup if regular close fails
            try:
                await session.get_bind().dispose()
            except:
                pass


async def close_db_engine():
    """Properly close database engine and all connections."""
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        # Close all connections in the pool
        await engine.dispose()
        logger.info("✅ Database engine disposed and all connections closed")
    except Exception as e:
        logger.error(f"❌ Error closing database engine: {e}")


async def get_db_pool_status():
    """Get current database pool status for monitoring."""
    try:
        return {
            "pool_status": engine.pool.status(),
            "pool_size": engine.pool.size(),
            "checked_in": engine.pool.checkedin(),
            "checked_out": engine.pool.checkedout(),
            "overflow": engine.pool.overflow(),
            "invalidated_time": getattr(engine.pool, '_invalidated_time', 'unknown')
        }
    except Exception as e:
        return {"error": str(e)}


async def force_pool_cleanup():
    """Force cleanup of database connection pool."""
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        # Get current status
        status_before = await get_db_pool_status()
        logger.info(f"🧹 Pool status before cleanup: {status_before}")
        
        # Dispose of all connections in pool
        await engine.dispose()
        
        # Get status after cleanup
        status_after = await get_db_pool_status()
        logger.info(f"✅ Pool status after cleanup: {status_after}")
        
        return {
            "status": "success",
            "before": status_before,
            "after": status_after
        }
        
    except Exception as e:
        logger.error(f"❌ Pool cleanup failed: {e}")
        return {"status": "failed", "error": str(e)}