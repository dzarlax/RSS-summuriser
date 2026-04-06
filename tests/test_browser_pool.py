"""Tests for the shared browser pool (nodriver + CDP)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from news_aggregator.core.browser_pool import get_browser, close_browser


@pytest.fixture(autouse=True)
def reset_browser_pool():
    """Reset global browser state before each test."""
    import news_aggregator.core.browser_pool as bp
    bp._browser = None
    bp._lock = asyncio.Lock()
    yield
    bp._browser = None


@pytest.fixture
def mock_settings_remote():
    settings = MagicMock()
    settings.browser_ws_endpoint = "ws://chrome:9222"
    return settings


@pytest.fixture
def mock_settings_local():
    settings = MagicMock()
    settings.browser_ws_endpoint = None
    return settings


@pytest.mark.asyncio
async def test_get_browser_remote(mock_settings_remote):
    """Connecting to remote Chrome via CDP should call uc.start with host/port."""
    mock_browser = MagicMock()
    mock_browser.connection = MagicMock()
    mock_browser.connection.closed = False

    with patch("news_aggregator.core.browser_pool.uc") as mock_uc, \
         patch("news_aggregator.config.settings", mock_settings_remote):
        mock_uc.start = AsyncMock(return_value=mock_browser)

        browser = await get_browser()

        mock_uc.start.assert_awaited_once_with(
            headless=True,
            host="chrome",
            port=9222,
        )
        assert browser is mock_browser


@pytest.mark.asyncio
async def test_get_browser_local(mock_settings_local):
    """Without endpoint configured, should launch local Chromium."""
    mock_browser = MagicMock()
    mock_browser.connection = MagicMock()
    mock_browser.connection.closed = False

    with patch("news_aggregator.core.browser_pool.uc") as mock_uc, \
         patch("news_aggregator.config.settings", mock_settings_local):
        mock_uc.start = AsyncMock(return_value=mock_browser)

        browser = await get_browser()

        mock_uc.start.assert_awaited_once_with(
            headless=True,
            browser_args=["--no-sandbox", "--disable-setuid-sandbox"],
        )
        assert browser is mock_browser


@pytest.mark.asyncio
async def test_get_browser_reuses_connection():
    """Subsequent calls should return the same browser instance."""
    import news_aggregator.core.browser_pool as bp

    mock_browser = MagicMock()
    mock_browser.connection = MagicMock()
    mock_browser.connection.closed = False
    bp._browser = mock_browser

    browser = await get_browser()
    assert browser is mock_browser


@pytest.mark.asyncio
async def test_get_browser_reconnects_on_closed():
    """Should reconnect if existing connection is closed."""
    import news_aggregator.core.browser_pool as bp

    old_browser = MagicMock()
    old_browser.connection = MagicMock()
    old_browser.connection.closed = True
    bp._browser = old_browser

    new_browser = MagicMock()
    new_browser.connection = MagicMock()
    new_browser.connection.closed = False

    mock_settings = MagicMock()
    mock_settings.browser_ws_endpoint = "ws://chrome:9222"

    with patch("news_aggregator.core.browser_pool.uc") as mock_uc, \
         patch("news_aggregator.config.settings", mock_settings):
        mock_uc.start = AsyncMock(return_value=new_browser)

        browser = await get_browser()

        assert browser is new_browser
        assert bp._browser is new_browser


@pytest.mark.asyncio
async def test_close_browser():
    """close_browser should call stop() and reset global."""
    import news_aggregator.core.browser_pool as bp

    mock_browser = MagicMock()
    bp._browser = mock_browser

    await close_browser()

    mock_browser.stop.assert_called_once()
    assert bp._browser is None


@pytest.mark.asyncio
async def test_close_browser_noop_when_none():
    """close_browser should be safe to call when no browser exists."""
    import news_aggregator.core.browser_pool as bp
    bp._browser = None

    await close_browser()  # Should not raise

    assert bp._browser is None


@pytest.mark.asyncio
async def test_endpoint_parsing_variants():
    """Should correctly parse different endpoint URL formats."""
    import news_aggregator.core.browser_pool as bp

    new_browser = MagicMock()
    new_browser.connection = MagicMock()
    new_browser.connection.closed = False

    test_cases = [
        ("ws://myhost:1234", "myhost", 1234),
        ("http://chrome:9222", "chrome", 9222),
        ("browser:5555", "browser", 5555),
    ]

    for endpoint, expected_host, expected_port in test_cases:
        bp._browser = None
        bp._lock = asyncio.Lock()

        mock_settings = MagicMock()
        mock_settings.browser_ws_endpoint = endpoint

        with patch("news_aggregator.core.browser_pool.uc") as mock_uc, \
             patch("news_aggregator.config.settings", mock_settings):
            mock_uc.start = AsyncMock(return_value=new_browser)

            await get_browser()

            mock_uc.start.assert_awaited_once_with(
                headless=True,
                host=expected_host,
                port=expected_port,
            )
