"""Constants and thresholds for content extraction."""

# Text length thresholds
MAX_CONTENT_LENGTH = 8000
MIN_CONTENT_LENGTH = 200

# Playwright/browser settings
BROWSER_CONCURRENCY = 2
# Balance per-attempt timeouts with total budget to allow multiple retries
PLAYWRIGHT_TIMEOUT_FIRST_MS = 25_000
PLAYWRIGHT_TIMEOUT_RETRY_MS = 35_000
PLAYWRIGHT_TOTAL_BUDGET_MS = 90_000

# Heuristic quality thresholds
MIN_QUALITY_SCORE = 30

# Lightweight caches
HTML_CACHE_TTL_SECONDS = 300        # cache fetched HTML for 5 minutes
SELECTOR_CACHE_TTL_SECONDS = 21600  # cache domain selector for 6 hours


