"""Database connection and models."""

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

from .config import settings

# Create async engine with connection pool settings
engine = create_async_engine(
    settings.database_url.replace("postgresql://", "postgresql+asyncpg://"),
    echo=settings.development,
    future=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    pool_pre_ping=True,  # Проверка соединений перед использованием
    pool_recycle=3600,   # Переиспользование соединений каждый час
    connect_args={
        "server_settings": {
            "application_name": "RSS_Aggregator_V2",
        },
        # Более агрессивные настройки таймаутов для asyncpg
        "command_timeout": 60,
    }
)

# Create async session factory
AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
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
        # Проверяем, инициализирована ли уже база данных
        async with AsyncSessionLocal() as session:
            result = await session.execute(text("SELECT 1 FROM articles LIMIT 1"))
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
            # Выполняем через psql
            env = os.environ.copy()
            env['PGPASSWORD'] = 'newspass123'
            
            result = subprocess.run([
                'psql', 
                '-h', 'postgres',
                '-U', 'newsuser', 
                '-d', 'newsdb',
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
    """Dependency to get database session."""
    import logging
    logger = logging.getLogger(__name__)
    
    # Log pool status before getting connection
    try:
        pool_status = engine.pool.status()
        logger.debug(f"📊 DB Pool before request: {pool_status}")
    except:
        pass
    
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()