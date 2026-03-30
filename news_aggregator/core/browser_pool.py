"""Shared Playwright browser pool — single Node.js process for the entire app."""

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_playwright_context = None
_browser = None
_lock = asyncio.Lock()


async def get_browser():
    """Get or create a shared Playwright browser connection.

    Reuses a single ``async_playwright()`` context and browser connection
    across the whole application so we spawn only **one** Node.js driver
    process instead of one per component.
    """
    global _playwright_context, _browser

    if _browser is not None:
        try:
            _browser.contexts  # noqa: B018 — quick liveness check
            return _browser
        except Exception:
            logger.warning("  ⚠️ Shared browser connection lost, reconnecting...")
            _browser = None

    async with _lock:
        # Double-check after acquiring lock
        if _browser is not None:
            try:
                _browser.contexts
                return _browser
            except Exception:
                _browser = None

        from ..config import settings
        ws_endpoint = settings.browser_ws_endpoint

        if _playwright_context is None:
            from playwright.async_api import async_playwright
            logger.info("  🚀 Starting shared Playwright context...")
            _playwright_context = await async_playwright().start()

        if ws_endpoint:
            logger.info(f"  🔗 Connecting to remote browser at {ws_endpoint}...")
            _browser = await _playwright_context.chromium.connect(
                ws_endpoint=ws_endpoint
            )
            logger.info("  ✅ Connected to shared remote browser")
        else:
            logger.info("  🚀 Launching shared local Chromium...")
            _browser = await _playwright_context.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox"],
            )
            logger.info("  ✅ Shared local browser launched")

        return _browser


async def close_browser():
    """Close the shared browser (call on app shutdown only)."""
    global _playwright_context, _browser

    if _browser:
        try:
            await _browser.close()
        except Exception:
            pass
        _browser = None

    if _playwright_context:
        try:
            await _playwright_context.stop()
        except Exception:
            pass
        _playwright_context = None
