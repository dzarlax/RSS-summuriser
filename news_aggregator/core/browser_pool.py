"""Shared browser pool — connects to a remote Chrome instance via CDP (nodriver)."""

import asyncio
import logging
from typing import Optional

import nodriver as uc

logger = logging.getLogger(__name__)

_browser: Optional[uc.Browser] = None
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

        if cdp_endpoint:
            # Parse host:port from endpoint like "ws://chrome:9222" or "chrome:9222"
            endpoint = cdp_endpoint.replace("ws://", "").replace("http://", "")
            host, _, port_str = endpoint.partition(":")
            port = int(port_str.split("/")[0]) if port_str else 9222

            logger.info(f"  Connecting to Chrome via CDP at {host}:{port}...")
            _browser = await uc.start(
                headless=True,
                host=host,
                port=port,
            )
            logger.info("  Connected to Chrome via CDP")
        else:
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
