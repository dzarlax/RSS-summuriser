"""Database access manager with separate read/write semaphores and retry logic."""

import asyncio
import logging
from asyncio import Semaphore
from typing import Any, Callable, Optional, Dict
from enum import Enum
from datetime import datetime

from ..database import AsyncSessionLocal

logger = logging.getLogger(__name__)


class OperationType(Enum):
    READ = "read"
    WRITE = "write"


class DatabaseQueueManager:
    """Database access manager: semaphore-based concurrency, retry on deadlock."""

    def __init__(self,
                 read_pool_size: int = 8,
                 write_pool_size: int = 3,
                 # Legacy params accepted but ignored
                 read_workers: int = 0,
                 write_workers: int = 0,
                 max_queue_size: int = 0):

        self.read_semaphore = Semaphore(read_pool_size)
        self.write_semaphore = Semaphore(write_pool_size)
        self.running = False
        self.stats: Dict[str, int] = {
            'read_operations': 0,
            'write_operations': 0,
            'read_errors': 0,
            'write_errors': 0,
            'total_processed': 0,
        }
        self.active_tasks: Dict[str, Dict[str, Any]] = {}

    async def start(self):
        if self.running:
            return
        self.running = True
        logger.info(
            "Database queue started (read_sem=%s, write_sem=%s)",
            self.read_semaphore._value,
            self.write_semaphore._value,
        )

    async def stop(self):
        if not self.running:
            return
        self.running = False
        logger.info("Database queue stopped")

    async def execute_read(self, operation: Callable, timeout: Optional[float] = 30.0, priority: int = 0) -> Any:
        """Execute a read operation."""
        return await self._execute(OperationType.READ, self.read_semaphore, operation, timeout)

    async def execute_write(self, operation: Callable, timeout: Optional[float] = 60.0, priority: int = 0) -> Any:
        """Execute a write operation (auto-commits on success)."""
        return await self._execute(OperationType.WRITE, self.write_semaphore, operation, timeout)

    async def _execute(self, op_type: OperationType, semaphore: Semaphore,
                       operation: Callable, timeout: Optional[float]) -> Any:
        if not self.running:
            logger.warning("Database queue is not running — attempting auto-restart")
            await self.start()

        task_id = (
            f"{op_type.value}_"
            f"{asyncio.current_task().get_name() if asyncio.current_task() else 'unknown'}_"
            f"{datetime.now().microsecond}"
        )
        operation_name = getattr(operation, '__name__', 'unknown')

        async def _run():
            start_time = datetime.now()
            self.active_tasks[task_id] = {
                'operation': operation_name,
                'type': op_type.value,
                'started_at': start_time,
            }
            try:
                async with semaphore:
                    return await self._run_with_retry(op_type, operation, task_id, operation_name, start_time)
            finally:
                self.active_tasks.pop(task_id, None)

        try:
            if timeout:
                return await asyncio.wait_for(_run(), timeout=float(timeout))
            return await _run()
        except asyncio.TimeoutError:
            logger.error(
                "DB operation timed out: %s (%s), active=%s, read_sem=%s, write_sem=%s",
                task_id, operation_name, len(self.active_tasks),
                self.read_semaphore._value, self.write_semaphore._value,
            )
            if self.active_tasks:
                now = datetime.now()
                for tid, info in self.active_tasks.items():
                    duration = (now - info['started_at']).total_seconds()
                    logger.error("  active: %s (%s) for %.1fs", tid, info['operation'], duration)
            raise

    async def _run_with_retry(self, op_type: OperationType, operation: Callable,
                               task_id: str, operation_name: str, start_time: datetime) -> Any:
        max_retries = 3
        retry_delay = 0.1

        for attempt in range(max_retries + 1):
            try:
                async with AsyncSessionLocal() as session:
                    result = await operation(session)
                    if op_type == OperationType.WRITE:
                        await session.commit()

                    duration = (datetime.now() - start_time).total_seconds()
                    if duration > 10:
                        logger.warning("Slow DB task: %s (%s) took %.1fs", task_id, operation_name, duration)

                    if op_type == OperationType.READ:
                        self.stats['read_operations'] += 1
                    else:
                        self.stats['write_operations'] += 1
                    self.stats['total_processed'] += 1

                    retry_note = f" (after {attempt} retries)" if attempt > 0 else ""
                    logger.debug("DB %s completed %s in %.3fs%s", op_type.value, task_id, duration, retry_note)
                    return result

            except Exception as e:
                error_str = str(e).lower()
                is_deadlock = '1213' in error_str or 'deadlock' in error_str
                is_rollback = not is_deadlock and ('rolled back' in error_str or 'rollback' in error_str)

                if (is_deadlock or is_rollback) and attempt < max_retries:
                    reason = 'deadlock' if is_deadlock else 'rollback'
                    logger.warning("Retrying %s (attempt %s/%s) after %s: %s",
                                   task_id, attempt + 1, max_retries + 1, reason, e)
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
                    continue

                if op_type == OperationType.READ:
                    self.stats['read_errors'] += 1
                else:
                    self.stats['write_errors'] += 1

                error_type = ("Deadlock (max retries)" if is_deadlock
                              else "Rollback (max retries)" if is_rollback else "Error")
                logger.error("DB %s failed %s: %s: %s", op_type.value, task_id, error_type, e)
                raise

    def get_stats(self) -> Dict[str, Any]:
        return {
            **self.stats,
            'read_connections_available': self.read_semaphore._value,
            'write_connections_available': self.write_semaphore._value,
            'active_tasks': len(self.active_tasks),
            'running': self.running,
            'healthy': self.running,
        }


# Global queue manager instance
_queue_manager: Optional[DatabaseQueueManager] = None


def get_database_queue() -> DatabaseQueueManager:
    """Get global database queue manager instance."""
    global _queue_manager

    if _queue_manager is None:
        _queue_manager = DatabaseQueueManager(
            read_pool_size=12,
            write_pool_size=4,
        )

    return _queue_manager


# Backward-compatibility alias (several modules still use the old name)
get_db_queue_manager = get_database_queue


async def ensure_database_queue_running() -> DatabaseQueueManager:
    """Ensure database queue is running and return the instance."""
    queue = get_database_queue()
    if not queue.running:
        await queue.start()
    return queue


async def execute_read_query(operation: Callable, timeout: Optional[float] = 30.0) -> Any:
    """Execute a read query through the database queue."""
    queue = await ensure_database_queue_running()
    return await queue.execute_read(operation, timeout)


async def execute_write_query(operation: Callable, timeout: Optional[float] = 60.0) -> Any:
    """Execute a write query through the database queue."""
    queue = await ensure_database_queue_running()
    return await queue.execute_write(operation, timeout)
