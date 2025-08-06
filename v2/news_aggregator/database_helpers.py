"""Database helper functions using the universal queue system."""

from typing import Any, Callable, Optional, List, TypeVar
from sqlalchemy import select, insert, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from .services.database_queue import execute_read_query, execute_write_query

T = TypeVar('T')


# Read operations (SELECT queries)
async def fetch_one(query, timeout: Optional[float] = 30.0) -> Optional[Any]:
    """Fetch one row using read queue."""
    async def operation(session: AsyncSession):
        result = await session.execute(query)
        row = result.scalar_one_or_none()
        # Force close result to release connection immediately
        result.close()
        return row
    
    return await execute_read_query(operation, timeout)


async def fetch_all(query, timeout: Optional[float] = 30.0) -> List[Any]:
    """Fetch all rows using read queue."""
    async def operation(session: AsyncSession):
        result = await session.execute(query)
        rows = list(result.scalars().all())  # Force list materialization
        # Force close result to release connection immediately
        result.close()
        return rows
    
    return await execute_read_query(operation, timeout)


async def fetch_raw_all(query, timeout: Optional[float] = 30.0) -> List[Any]:
    """Fetch all raw rows (tuples) using read queue."""
    async def operation(session: AsyncSession):
        result = await session.execute(query)
        rows = list(result.all())  # Force list materialization
        # Force close result to release connection immediately
        result.close()
        return rows
    
    return await execute_read_query(operation, timeout)


async def count_query(query, timeout: Optional[float] = 15.0) -> int:
    """Execute count query using read queue."""
    async def operation(session: AsyncSession):
        result = await session.execute(query)
        count = result.scalar() or 0
        # Force close result to release connection immediately
        result.close()
        return count
    
    return await execute_read_query(operation, timeout)


# Write operations (INSERT, UPDATE, DELETE)
async def insert_one(model_instance, timeout: Optional[float] = 60.0) -> Any:
    """Insert one record using write queue."""
    async def operation(session: AsyncSession):
        session.add(model_instance)
        await session.commit()
        await session.refresh(model_instance)
        return model_instance
    
    return await execute_write_query(operation, timeout)


async def insert_many(model_instances: List[Any], timeout: Optional[float] = 120.0) -> List[Any]:
    """Insert multiple records using write queue."""
    async def operation(session: AsyncSession):
        session.add_all(model_instances)
        await session.commit()
        for instance in model_instances:
            await session.refresh(instance)
        return model_instances
    
    return await execute_write_query(operation, timeout)


async def update_query(query, timeout: Optional[float] = 60.0) -> int:
    """Execute update query using write queue."""
    async def operation(session: AsyncSession):
        result = await session.execute(query)
        await session.commit()
        return result.rowcount
    
    return await execute_write_query(operation, timeout)


async def delete_query(query, timeout: Optional[float] = 60.0) -> int:
    """Execute delete query using write queue."""
    async def operation(session: AsyncSession):
        result = await session.execute(query)
        await session.commit()
        return result.rowcount
    
    return await execute_write_query(operation, timeout)


async def execute_custom_write(operation: Callable[[AsyncSession], Any], timeout: Optional[float] = 60.0) -> Any:
    """Execute custom write operation using write queue."""
    return await execute_write_query(operation, timeout)


async def execute_custom_read(operation: Callable[[AsyncSession], Any], timeout: Optional[float] = 30.0) -> Any:
    """Execute custom read operation using read queue."""
    return await execute_read_query(operation, timeout)


# Transaction-based operations
async def execute_transaction(operations: List[Callable[[AsyncSession], Any]], timeout: Optional[float] = 120.0) -> List[Any]:
    """Execute multiple operations in a single transaction using write queue."""
    async def transaction_operation(session: AsyncSession):
        results = []
        for operation in operations:
            result = await operation(session)
            results.append(result)
        await session.commit()
        return results
    
    return await execute_write_query(transaction_operation, timeout)


# Legacy compatibility helpers
async def get_or_create(model_class, defaults: Optional[dict] = None, timeout: Optional[float] = 60.0, **kwargs) -> tuple[Any, bool]:
    """Get existing record or create new one."""
    async def operation(session: AsyncSession):
        # Try to get existing
        query = select(model_class).filter_by(**kwargs)
        result = await session.execute(query)
        instance = result.scalar_one_or_none()
        
        if instance:
            return instance, False
            
        # Create new
        create_kwargs = kwargs.copy()
        if defaults:
            create_kwargs.update(defaults)
            
        instance = model_class(**create_kwargs)
        session.add(instance)
        await session.commit()
        await session.refresh(instance)
        return instance, True
    
    return await execute_write_query(operation, timeout)


# Convenience functions for common patterns
async def safe_fetch_one(query, default=None, timeout: Optional[float] = 30.0) -> Any:
    """Safely fetch one row, return default if not found."""
    try:
        result = await fetch_one(query, timeout)
        return result if result is not None else default
    except Exception:
        return default


async def safe_count(query, default: int = 0, timeout: Optional[float] = 30.0) -> int:
    """Safely count rows, return default on error."""
    try:
        return await count_query(query, timeout)
    except Exception:
        return default