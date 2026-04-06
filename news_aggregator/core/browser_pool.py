"""Shared browser pool — connects to a remote Chrome instance via CDP (nodriver)."""

import asyncio
import logging
import os
from typing import Optional

import nodriver as uc
from nodriver.core.browser import Browser

logger = logging.getLogger(__name__)

_browser: Optional[Browser] = None
_lock = asyncio.Lock()


async def get_browser() -> uc.Browser:
    """Get or create a shared browser connection via CDP.

    Connects to a remote Chrome/Chromium (e.g. Alpine Chrome) using the
    Chrome DevTools Protocol through nodriver, eliminating the need for
    a Playwright server (Node.js) container.
    """
    global _browser

    if _browser is not None:
        try:
            # Quick liveness check — list targets
            if _browser.connection and not _browser.connection.closed:
                return _browser
        except Exception:
            logger.warning("  Shared browser connection lost, reconnecting...")
            _browser = None

    async with _lock:
        # Double-check after acquiring lock
        if _browser is not None:
            try:
                if _browser.connection and not _browser.connection.closed:
                    return _browser
            except Exception:
                _browser = None

        from ..config import settings
        cdp_endpoint = settings.browser_ws_endpoint
        
        # Log the actual endpoint being used to help with debugging
        logger.info(f"  Browser connection config: endpoint='{cdp_endpoint}'")

        if cdp_endpoint:
            # Parse host:port from endpoint like "ws://chrome:9222" or "chrome:9222"
            endpoint = cdp_endpoint.replace("ws://", "").replace("http://", "").rstrip("/")
            host, _, port_str = endpoint.partition(":")
            
            try:
                # Handle cases like "host:9222/" or just "host"
                port = int(port_str.split("/")[0]) if port_str and port_str.split("/")[0] else 9222
            except ValueError:
                logger.warning(f"  Invalid port in endpoint '{cdp_endpoint}', falling back to 9222")
                port = 9222

            logger.info(f"  Connecting to remote Chrome via CDP at {host}:{port}...")
            
            # Pre-flight check: can we even reach the port?
            try:
                # Direct TCP check to distinguish between network and nodriver issues
                conn = asyncio.open_connection(host, port)
                reader, writer = await asyncio.wait_for(conn, timeout=3.0)
                writer.close()
                await writer.wait_closed()
                logger.info(f"  ✅ Network check: {host}:{port} is reachable")
            except Exception as e:
                error_msg = f"Network check failed for {host}:{port}: {e}"
                logger.error(f"  ❌ {error_msg}")
                if os.path.exists('/.dockerenv'):
                    raise RuntimeError(error_msg)

            import sys
            try:
                # Use Browser.create() from nodriver.core.browser instead of uc.start()
                # Pass a dummy browser_executable_path to bypass the bug in nodriver's Config
                # which aggressively checks for a local Chrome binary even for remote connections.
                _browser = await Browser.create(
                    host=host,
                    port=port,
                    browser_executable_path=sys.executable
                )
                logger.info("  Connected to remote Chrome via CDP")
            except Exception as e:
                logger.error(f"  Failed to connect to remote Chrome at {host}:{port}: {e}")
                # In Docker, we shouldn't try to launch a local browser if remote fails
                if os.path.exists('/.dockerenv'):
                    raise RuntimeError(f"Could not connect to remote browser at {host}:{port}: {e}")
                
                logger.info("  Falling back to local browser launch (not in Docker)...")
                _browser = await uc.start(
                    headless=True,
                    browser_args=["--no-sandbox", "--disable-setuid-sandbox"],
                )
        else:
            # In Docker environment, BROWSER_WS_ENDPOINT must be set
            if os.path.exists('/.dockerenv'):
                logger.error("  ❌ BROWSER_WS_ENDPOINT is not set, but running in Docker!")
                raise RuntimeError("BROWSER_WS_ENDPOINT must be set when running in Docker.")
                
            logger.info("  Launching shared local Chromium...")
            _browser = await uc.start(
                headless=True,
                browser_args=["--no-sandbox", "--disable-setuid-sandbox"],
            )
            logger.info("  Shared local browser launched")

        return _browser


async def close_browser():
    """Close the shared browser (call on app shutdown only)."""
    global _browser

    if _browser:
        try:
            _browser.stop()
        except Exception:
            pass
        _browser = None
