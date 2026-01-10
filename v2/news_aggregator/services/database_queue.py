"""Universal database queue system with separate read and write queues."""

import asyncio
import logging
from asyncio import Queue, Semaphore
from dataclasses import dataclass
from typing import Any, Callable, Optional, Union, Dict
from enum import Enum
from datetime import datetime

from ..database import AsyncSessionLocal

logger = logging.getLogger(__name__)


class OperationType(Enum):
    """Database operation types."""
    READ = "read"
    WRITE = "write"


@dataclass
class DatabaseTask:
    """Database task for queue processing."""
    operation_type: OperationType
    operation: Callable  # Async function that takes (session) and returns result
    result_future: asyncio.Future
    task_id: str
    created_at: datetime
    timeout: Optional[float] = None
    priority: int = 0  # Higher number = higher priority


class DatabaseQueueManager:
    """Universal database queue manager with separate read and write queues."""
    
    def __init__(self, 
                 read_pool_size: int = 8,      # Read operations are fast, allow more
                 write_pool_size: int = 3,     # Write operations need control
                 read_workers: int = 6,        # Worker threads for reads
                 write_workers: int = 4,       # Worker threads for writes
                 max_queue_size: int = 2000):
        
        # Queue configuration
        self.read_queue: Queue[DatabaseTask] = Queue(maxsize=max_queue_size)
        self.write_queue: Queue[DatabaseTask] = Queue(maxsize=max_queue_size)
        
        # Connection pool limits
        self.read_semaphore = Semaphore(read_pool_size)
        self.write_semaphore = Semaphore(write_pool_size)
        
        # Worker configuration
        self.read_workers = read_workers
        self.write_workers = write_workers
        
        # Runtime state
        self.running = False
        self.worker_tasks: list[asyncio.Task] = []
        self.stats = {
            'read_operations': 0,
            'write_operations': 0,
            'read_errors': 0,
            'write_errors': 0,
            'total_processed': 0
        }

        # Track active tasks for debugging
        self.active_tasks: Dict[str, Dict[str, Any]] = {}

    def _log_unhealthy_workers(self):
        active_workers = [task for task in self.worker_tasks if not task.done()]
        expected = self.read_workers + self.write_workers
        if len(active_workers) < expected:
            logger.warning(
                "Database queue unhealthy: %s/%s workers active",
                len(active_workers),
                expected,
            )
        
    async def start(self):
        """Start the database queue system."""
        if self.running:
            # Check if workers are actually running
            active_workers = [task for task in self.worker_tasks if not task.done()]
            if len(active_workers) == (self.read_workers + self.write_workers):
                logger.debug("Database queue already running with active workers")
                return
            else:
                logger.warning(f"Database queue marked as running but only {len(active_workers)} workers active, restarting...")
                await self.stop()
                # Continue to restart
            
        self.running = True
        
        # Start read workers
        for i in range(self.read_workers):
            task = asyncio.create_task(self._read_worker(worker_id=i))
            self.worker_tasks.append(task)
            
        # Start write workers  
        for i in range(self.write_workers):
            task = asyncio.create_task(self._write_worker(worker_id=i))
            self.worker_tasks.append(task)
            
        logger.info(f"🚀 Database queue started: {self.read_workers} read workers "
                   f"(max {self.read_semaphore._value} connections), "
                   f"{self.write_workers} write workers (max {self.write_semaphore._value} connections)")
                   
    async def stop(self):
        """Stop the database queue system."""
        if not self.running:
            return
            
        self.running = False
        
        # Cancel all worker tasks
        for task in self.worker_tasks:
            task.cancel()
            
        # Wait for tasks to finish
        if self.worker_tasks:
            await asyncio.gather(*self.worker_tasks, return_exceptions=True)
            
        self.worker_tasks.clear()
        logger.info("🛑 Database queue stopped")
        
    async def execute_read(self, operation: Callable, timeout: Optional[float] = 30.0, priority: int = 0) -> Any:
        """Execute a read operation through the read queue."""
        return await self._execute_operation(OperationType.READ, operation, timeout, priority)
        
    async def execute_write(self, operation: Callable, timeout: Optional[float] = 60.0, priority: int = 0) -> Any:
        """Execute a write operation through the write queue."""
        return await self._execute_operation(OperationType.WRITE, operation, timeout, priority)
        
    async def _execute_operation(self, op_type: OperationType, operation: Callable, 
                                timeout: Optional[float], priority: int) -> Any:
        """Execute database operation through appropriate queue."""
        if not self.running:
            raise RuntimeError("Database queue is not running")

        self._log_unhealthy_workers()
            
        # Create future for result
        result_future = asyncio.Future()
        
        # Create task
        task = DatabaseTask(
            operation_type=op_type,
            operation=operation,
            result_future=result_future,
            task_id=f"{op_type.value}_{asyncio.current_task().get_name() if asyncio.current_task() else 'unknown'}_{datetime.now().microsecond}",
            created_at=datetime.now(),
            timeout=timeout,
            priority=priority
        )
        
        # Add to appropriate queue
        try:
            if op_type == OperationType.READ:
                await self.read_queue.put(task)
            else:
                await self.write_queue.put(task)
                
        except Exception as e:
            result_future.set_exception(e)
            
        # Wait for result with timeout
        try:
            if timeout:
                # Ensure timeout is a number
                if isinstance(timeout, str):
                    timeout = float(timeout)
                return await asyncio.wait_for(result_future, timeout=timeout)
            else:
                return await result_future
        except asyncio.TimeoutError:
            # Enhanced logging with semaphore state and active tasks
            read_sem_value = getattr(self.read_semaphore, '_value', 'unknown')
            write_sem_value = getattr(self.write_semaphore, '_value', 'unknown')

            logger.error(
                "Database operation timed out: %s (read_queue=%s, write_queue=%s, read_sem=%s/%s, write_sem=%s/%s, timeout=%s)",
                task.task_id,
                self.read_queue.qsize(),
                self.write_queue.qsize(),
                read_sem_value,
                self.read_semaphore._value if hasattr(self.read_semaphore, '_value') else '?',
                write_sem_value,
                self.write_semaphore._value if hasattr(self.write_semaphore, '_value') else '?',
                timeout
            )
            logger.error(f"Task details: type={task.operation_type}, operation={task.operation.__name__ if hasattr(task.operation, '__name__') else 'unknown'}")

            # Log active tasks if any
            if self.active_tasks:
                logger.error(f"⚠️ Active tasks ({len(self.active_tasks)}):")
                now = datetime.now()
                for task_id, info in self.active_tasks.items():
                    duration = (now - info['started_at']).total_seconds()
                    logger.error(f"  - {task_id} ({info['operation']}) running for {duration:.1f}s on {info['worker']}")

            raise
            
    async def _read_worker(self, worker_id: int):
        """Worker for processing read operations."""
        worker_name = f"read_worker_{worker_id}"
        logger.debug(f"🔍 {worker_name} started")
        
        try:
            while self.running:
                try:
                    # Get task from read queue
                    task = await asyncio.wait_for(self.read_queue.get(), timeout=1.0)
                    await self._process_task(task, self.read_semaphore, worker_name)
                    
                except asyncio.TimeoutError:
                    # Normal timeout, continue loop
                    continue
                except Exception as e:
                    logger.error(f"Error in {worker_name}: {e}")
                    await asyncio.sleep(1)
                    
        except asyncio.CancelledError:
            logger.debug(f"🔍 {worker_name} cancelled")
        except Exception as e:
            logger.error(f"Fatal error in {worker_name}: {e}")
            
    async def _write_worker(self, worker_id: int):
        """Worker for processing write operations."""
        worker_name = f"write_worker_{worker_id}"
        logger.debug(f"✏️ {worker_name} started")
        
        try:
            while self.running:
                try:
                    # Get task from write queue
                    task = await asyncio.wait_for(self.write_queue.get(), timeout=1.0)
                    await self._process_task(task, self.write_semaphore, worker_name)
                    
                except asyncio.TimeoutError:
                    # Normal timeout, continue loop
                    continue
                except Exception as e:
                    logger.error(f"Error in {worker_name}: {e}")
                    await asyncio.sleep(1)
                    
        except asyncio.CancelledError:
            logger.debug(f"✏️ {worker_name} cancelled")
        except Exception as e:
            logger.error(f"Fatal error in {worker_name}: {e}")
            
    async def _process_task(self, task: DatabaseTask, semaphore: Semaphore, worker_name: str):
        """Process a database task with active tracking."""
        start_time = datetime.now()
        session = None

        # Check if task was already cancelled before processing
        if task.result_future.cancelled():
            logger.debug(f"⚠️ Task {task.task_id} was cancelled before processing")
            return

        # Track active task
        operation_name = task.operation.__name__ if hasattr(task.operation, '__name__') else 'unknown'
        self.active_tasks[task.task_id] = {
            'worker': worker_name,
            'operation': operation_name,
            'type': task.operation_type.value,
            'started_at': start_time,
            'timeout': task.timeout
        }

        try:
            # Acquire connection semaphore
            async with semaphore:
                # Execute database operation using proper context manager
                # Retry logic for deadlock and transient errors
                max_retries = 3
                retry_delay = 0.1  # Start with 100ms

                for attempt in range(max_retries + 1):
                    try:
                        async with AsyncSessionLocal() as session:
                            try:
                                # Execute operation
                                result = await task.operation(session)

                                # Check execution time
                                duration = (datetime.now() - start_time).total_seconds()

                                # Log slow tasks (> 10 seconds)
                                if duration > 10:
                                    logger.warning(
                                        f"⚠️ Slow DB task: {task.task_id} ({operation_name}) took {duration:.1f}s"
                                    )

                                # Success! Double-check task wasn't cancelled
                                if not task.result_future.cancelled() and not task.result_future.done():
                                    task.result_future.set_result(result)

                                    # Update stats
                                    if task.operation_type == OperationType.READ:
                                        self.stats['read_operations'] += 1
                                    else:
                                        self.stats['write_operations'] += 1

                                    self.stats['total_processed'] += 1

                                    duration = (datetime.now() - start_time).total_seconds()
                                    retry_note = f" (after {attempt} retries)" if attempt > 0 else ""
                                    logger.debug(f"✅ {worker_name} completed {task.task_id} in {duration:.3f}s{retry_note}")
                                else:
                                    logger.debug(f"⚠️ Task {task.task_id} was cancelled during processing")

                                # Success - break retry loop
                                break

                            except Exception as e:
                                # Check if this is a retryable error (deadlock or transaction rollback)
                                is_deadlock = False
                                is_rollback = False
                                error_str = str(e).lower()

                                # Detect deadlock errors
                                if '1213' in error_str or 'deadlock' in error_str:
                                    is_deadlock = True
                                # Detect transaction rollback errors
                                elif 'rolled back' in error_str or 'rollback' in error_str:
                                    is_rollback = True

                                # Retry deadlock and rollback errors
                                if (is_deadlock or is_rollback) and attempt < max_retries:
                                    logger.warning(f"🔄 {worker_name} retrying {task.task_id} (attempt {attempt + 1}/{max_retries + 1}) after {'deadlock' if is_deadlock else 'rollback'}: {e}")
                                    await session.rollback()  # Ensure clean state
                                    await asyncio.sleep(retry_delay)
                                    retry_delay *= 2  # Exponential backoff
                                    continue  # Retry

                                # Non-retryable error or max retries exceeded
                                if not task.result_future.cancelled() and not task.result_future.done():
                                    await session.rollback()  # Clean rollback
                                    task.result_future.set_exception(e)

                                    # Update error stats
                                    if task.operation_type == OperationType.READ:
                                        self.stats['read_errors'] += 1
                                    else:
                                        self.stats['write_errors'] += 1

                                    error_type = "Deadlock (max retries)" if is_deadlock else "Rollback (max retries)" if is_rollback else "Error"
                                    logger.error(f"❌ {worker_name} failed {task.task_id}: {error_type}: {e}")
                                else:
                                    logger.debug(f"⚠️ Task {task.task_id} failed but was already cancelled: {e}")

                                # Don't retry if future is cancelled or error is not retryable
                                break

                    except Exception as outer_e:
                        # Session context manager error
                        logger.error(f"💥 Session error for {task.task_id}: {outer_e}")
                        if not task.result_future.cancelled() and not task.result_future.done():
                            task.result_future.set_exception(outer_e)
                        break

        except Exception as e:
            # This shouldn't happen, but just in case
            if not task.result_future.cancelled() and not task.result_future.done():
                task.result_future.set_exception(e)
            logger.error(f"💥 Fatal error processing {task.task_id}: {e}")

        finally:
            # Always remove from active tasks
            if task.task_id in self.active_tasks:
                duration = (datetime.now() - start_time).total_seconds()
                del self.active_tasks[task.task_id]
    def get_stats(self) -> Dict[str, Any]:
        """Get queue statistics."""
        active_workers = [task for task in self.worker_tasks if not task.done()]
        return {
            **self.stats,
            'read_queue_size': self.read_queue.qsize(),
            'write_queue_size': self.write_queue.qsize(),
            'read_connections_available': self.read_semaphore._value,
            'write_connections_available': self.write_semaphore._value,
            'total_workers': len(self.worker_tasks),
            'active_workers': len(active_workers),
            'expected_workers': self.read_workers + self.write_workers,
            'running': self.running,
            'healthy': self.running and len(active_workers) == (self.read_workers + self.write_workers)
        }


# Global queue manager instance
_queue_manager: Optional[DatabaseQueueManager] = None


def get_database_queue() -> DatabaseQueueManager:
    """Get global database queue manager instance."""
    global _queue_manager
    
    if _queue_manager is None:
        _queue_manager = DatabaseQueueManager(
            read_pool_size=12,   # Reads are fast, allow more concurrent
            write_pool_size=4,   # Writes need careful control  
            read_workers=10,     # Much more read workers for web requests
            write_workers=3      # Fewer write workers
        )
    
    return _queue_manager


async def ensure_database_queue_running() -> DatabaseQueueManager:
    """Ensure database queue is running and return the instance."""
    queue = get_database_queue()
    if not queue.running:
        await queue.start()
    return queue


# Convenience functions for common use cases
async def execute_read_query(operation: Callable, timeout: Optional[float] = 30.0) -> Any:
    """Execute a read query through the database queue."""
    queue = await ensure_database_queue_running()
    return await queue.execute_read(operation, timeout)


async def execute_write_query(operation: Callable, timeout: Optional[float] = 60.0) -> Any:
    """Execute a write query through the database queue."""
    queue = await ensure_database_queue_running()
    return await queue.execute_write(operation, timeout)
