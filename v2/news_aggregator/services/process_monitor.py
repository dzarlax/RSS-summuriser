"""Process monitoring and cleanup service for hanging Playwright processes."""

import asyncio
import logging
import psutil
from typing import List, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class ProcessMonitor:
    """Monitor and cleanup hanging Playwright processes."""
    
    def __init__(self, check_interval: int = 300):  # 5 minutes
        """
        Initialize process monitor.
        
        Args:
            check_interval: Interval in seconds between cleanup checks
        """
        self.check_interval = check_interval
        self.cleanup_task: Optional[asyncio.Task] = None
        self.is_running = False
    
    async def start(self):
        """Start periodic process monitoring."""
        if self.is_running:
            logger.warning("Process monitor already running")
            return
        
        self.is_running = True
        self.cleanup_task = asyncio.create_task(self._monitor_loop())
        logger.info(f"Process monitor started with {self.check_interval}s interval")
    
    async def stop(self):
        """Stop periodic process monitoring."""
        self.is_running = False
        
        if self.cleanup_task:
            self.cleanup_task.cancel()
            try:
                await self.cleanup_task
            except asyncio.CancelledError:
                pass
            self.cleanup_task = None
        
        logger.info("Process monitor stopped")
    
    async def _monitor_loop(self):
        """Main monitoring loop."""
        while self.is_running:
            try:
                await self._cleanup_hanging_processes()
                await asyncio.sleep(self.check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in process monitor loop: {e}")
                await asyncio.sleep(10)  # Wait before retry
    
    async def _cleanup_hanging_processes(self):
        """Check for and cleanup hanging Playwright processes."""
        try:
            playwright_processes = self._find_playwright_processes()
            
            if not playwright_processes:
                return
            
            hanging_processes = self._identify_hanging_processes(playwright_processes)
            
            if hanging_processes:
                logger.info(f"Found {len(hanging_processes)} hanging Playwright processes")
                cleaned_up = await self._cleanup_processes(hanging_processes)
                
                if cleaned_up:
                    logger.info(f"Cleaned up {cleaned_up} hanging processes")
                    
                    # Force ContentExtractor cleanup after process cleanup
                    await self._force_content_extractor_cleanup()
            
        except Exception as e:
            logger.error(f"Error during process cleanup: {e}")
    
    def _find_playwright_processes(self) -> List[psutil.Process]:
        """Find all Playwright-related processes."""
        playwright_processes = []
        
        try:
            for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'create_time']):
                try:
                    proc_info = proc.info
                    
                    # Check process name
                    if proc_info['name'] and 'node' in proc_info['name'].lower():
                        cmdline = proc_info.get('cmdline', [])
                        if cmdline:
                            cmdline_str = ' '.join(cmdline).lower()
                            if any(keyword in cmdline_str for keyword in [
                                'playwright', 'chromium', 'chrome', 'browser'
                            ]):
                                playwright_processes.append(proc)
                
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
        
        except Exception as e:
            logger.error(f"Error finding Playwright processes: {e}")
        
        return playwright_processes
    
    def _identify_hanging_processes(self, processes: List[psutil.Process]) -> List[psutil.Process]:
        """Identify processes that appear to be hanging."""
        hanging_processes = []
        current_time = datetime.now()
        
        # Consider processes older than 30 minutes as potentially hanging
        hanging_threshold = timedelta(minutes=30)
        
        for proc in processes:
            try:
                proc_create_time = datetime.fromtimestamp(proc.create_time())
                proc_age = current_time - proc_create_time
                
                # Check if process is old and potentially hanging
                if proc_age > hanging_threshold:
                    # Additional checks to confirm it's hanging
                    try:
                        # Check CPU usage - hanging processes usually have low CPU
                        cpu_percent = proc.cpu_percent(interval=1)
                        
                        # If very low CPU and old, likely hanging
                        if cpu_percent < 1.0:
                            hanging_processes.append(proc)
                            logger.debug(f"Identified hanging process: PID {proc.pid}, age {proc_age}, CPU {cpu_percent}%")
                    
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
            
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        
        return hanging_processes
    
    async def _cleanup_processes(self, processes: List[psutil.Process]) -> int:
        """Cleanup hanging processes."""
        cleaned_up = 0
        
        for proc in processes:
            try:
                logger.info(f"Terminating hanging Playwright process: PID {proc.pid}")
                
                # Try graceful termination first
                proc.terminate()
                
                # Wait a bit for graceful shutdown
                try:
                    proc.wait(timeout=5)
                    cleaned_up += 1
                except psutil.TimeoutExpired:
                    # Force kill if graceful termination fails
                    logger.warning(f"Force killing process PID {proc.pid}")
                    proc.kill()
                    proc.wait(timeout=3)
                    cleaned_up += 1
            
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                # Process already gone or no access
                continue
            except Exception as e:
                logger.error(f"Error cleaning up process PID {proc.pid}: {e}")
        
        return cleaned_up
    
    async def _force_content_extractor_cleanup(self):
        """Force cleanup of ContentExtractor after process cleanup."""
        try:
            from ..extraction import cleanup_content_extractor
            await cleanup_content_extractor()
            logger.info("Forced ContentExtractor cleanup after process cleanup")
        except Exception as e:
            logger.error(f"Error during forced ContentExtractor cleanup: {e}")
    
    async def manual_cleanup(self) -> dict:
        """Manually trigger process cleanup and return statistics."""
        before_processes = self._find_playwright_processes()
        before_count = len(before_processes)
        
        hanging_processes = self._identify_hanging_processes(before_processes)
        hanging_count = len(hanging_processes)
        
        if hanging_processes:
            cleaned_up = await self._cleanup_processes(hanging_processes)
            await self._force_content_extractor_cleanup()
        else:
            cleaned_up = 0
        
        after_processes = self._find_playwright_processes()
        after_count = len(after_processes)
        
        return {
            "processes_before": before_count,
            "processes_after": after_count,
            "hanging_identified": hanging_count,
            "processes_cleaned": cleaned_up,
            "timestamp": datetime.utcnow().isoformat()
        }


# Global process monitor instance
_process_monitor: Optional[ProcessMonitor] = None


def get_process_monitor() -> ProcessMonitor:
    """Get global process monitor instance."""
    global _process_monitor
    
    if _process_monitor is None:
        _process_monitor = ProcessMonitor()
    
    return _process_monitor


async def start_process_monitor():
    """Start the global process monitor."""
    monitor = get_process_monitor()
    await monitor.start()


async def stop_process_monitor():
    """Stop the global process monitor."""
    monitor = get_process_monitor()
    await monitor.stop()