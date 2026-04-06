"""Process monitoring — lightweight health checker for the browser connection."""

import asyncio
import logging
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class ProcessMonitor:
    """Monitor browser connection health and trigger reconnection if needed."""

    def __init__(self, check_interval: int = 300):  # 5 minutes
        self.check_interval = check_interval
        self.cleanup_task: Optional[asyncio.Task] = None
        self.is_running = False

    async def start(self):
        """Start periodic health monitoring."""
        if self.is_running:
            logger.warning("Process monitor already running")
            return

        self.is_running = True
        self.cleanup_task = asyncio.create_task(self._monitor_loop())
        logger.info(f"Process monitor started with {self.check_interval}s interval")

    async def stop(self):
        """Stop periodic monitoring."""
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
                await self._check_browser_health()
                await asyncio.sleep(self.check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in process monitor loop: {e}")
                await asyncio.sleep(10)

    async def _check_browser_health(self):
        """Check browser connection and reconnect if needed."""
        try:
            from ..core.browser_pool import get_browser, close_browser

            browser = await get_browser()
            if browser is None or (hasattr(browser, 'connection') and
                                   (browser.connection is None or browser.connection.closed)):
                logger.warning("Browser connection unhealthy, resetting...")
                await close_browser()
                await self._force_content_extractor_cleanup()
        except Exception as e:
            logger.error(f"Error during browser health check: {e}")

    async def _force_content_extractor_cleanup(self):
        """Force cleanup of ContentExtractor after connection loss."""
        try:
            from ..extraction import cleanup_content_extractor
            await cleanup_content_extractor()
            logger.info("Forced ContentExtractor cleanup after browser reset")
        except Exception as e:
            logger.error(f"Error during forced ContentExtractor cleanup: {e}")

    async def manual_cleanup(self) -> dict:
        """Manually trigger health check and return status."""
        from ..core.browser_pool import _browser

        connected = False
        if _browser is not None:
            try:
                connected = _browser.connection and not _browser.connection.closed
            except Exception:
                pass

        return {
            "browser_connected": connected,
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
