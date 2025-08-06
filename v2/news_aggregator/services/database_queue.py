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
        
    async def start(self):
        """Start the database queue system."""
        if self.running:
            logger.warning("Database queue already running")
            return
            
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
                return await asyncio.wait_for(result_future, timeout=timeout)
            else:
                return await result_future
        except asyncio.TimeoutError:
            logger.error(f"Database operation timed out: {task.task_id}")
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
        """Process a database task."""
        start_time = datetime.now()
        
        # Check if task was already cancelled before processing
        if task.result_future.cancelled():
            logger.debug(f"⚠️ Task {task.task_id} was cancelled before processing")
            return
        
        session = None
        try:
            # Acquire connection semaphore
            async with semaphore:
                # Execute database operation
                session = AsyncSessionLocal()
                try:
                    result = await task.operation(session)
                    
                    # Double-check task wasn't cancelled during operation
                    if not task.result_future.cancelled() and not task.result_future.done():
                        task.result_future.set_result(result)
                        
                        # Update stats
                        if task.operation_type == OperationType.READ:
                            self.stats['read_operations'] += 1
                        else:
                            self.stats['write_operations'] += 1
                            
                        self.stats['total_processed'] += 1
                        
                        duration = (datetime.now() - start_time).total_seconds()
                        logger.debug(f"✅ {worker_name} completed {task.task_id} in {duration:.3f}s")
                    else:
                        logger.debug(f"⚠️ Task {task.task_id} was cancelled during processing")
                        
                except Exception as e:
                    if not task.result_future.cancelled() and not task.result_future.done():
                        task.result_future.set_exception(e)
                        
                        # Update error stats
                        if task.operation_type == OperationType.READ:
                            self.stats['read_errors'] += 1
                        else:
                            self.stats['write_errors'] += 1
                            
                        logger.error(f"❌ {worker_name} failed {task.task_id}: {e}")
                    else:
                        logger.debug(f"⚠️ Task {task.task_id} failed but was already cancelled: {e}")
                finally:
                    if session:
                        await session.close()
                        
        except Exception as e:
            # This shouldn't happen, but just in case
            if not task.result_future.cancelled() and not task.result_future.done():
                task.result_future.set_exception(e)
            logger.error(f"💥 Fatal error processing {task.task_id}: {e}")
        finally:
            # Ensure session is closed
            if session:
                try:
                    await session.close()
                except Exception as e:
                    logger.debug(f"Error closing session for {task.task_id}: {e}")
            
    def get_stats(self) -> Dict[str, Any]:
        """Get queue statistics."""
        return {
            **self.stats,
            'read_queue_size': self.read_queue.qsize(),
            'write_queue_size': self.write_queue.qsize(),
            'read_connections_available': self.read_semaphore._value,
            'write_connections_available': self.write_semaphore._value,
            'total_workers': len(self.worker_tasks),
            'running': self.running
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


# Convenience functions for common use cases
async def execute_read_query(operation: Callable, timeout: Optional[float] = 30.0) -> Any:
    """Execute a read query through the database queue."""
    queue = get_database_queue()
    return await queue.execute_read(operation, timeout)


async def execute_write_query(operation: Callable, timeout: Optional[float] = 60.0) -> Any:
    """Execute a write query through the database queue."""
    queue = get_database_queue()
    return await queue.execute_write(operation, timeout)