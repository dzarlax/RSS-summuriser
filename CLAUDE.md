# Evening News v2 — Project Notes for Claude

## Key Facts

- **Project path**: `/Users/dzarlax/Projects/Code/Personal/RSS-summuriser-1/v2`
- **Production URL**: https://news.dzarlax.dev
- **Database**: PostgreSQL 16 (migrated from MariaDB)
- **DB connection**: `postgresql+asyncpg://...` via SQLAlchemy async
- **AI**: Google Gemini (direct API, not via OpenAI-compatible wrapper)
- **Dev container**: `v2-app-1`, PostgreSQL at `localhost:5432/newsdb`

## Model Field Names

Always use these exact names — they differ from what you might guess:

| Model | Correct field | Wrong field |
|-------|--------------|-------------|
| `DailySummary` | `summary_text` | `summary` |
| `DailySummary` | `articles_count` | `article_count` |
| `Article` | `fetched_at` | `created_at` |
| `ScheduleSettings` | `next_run`, `last_run`, `is_running`, `enabled` | — |

## Critical Architecture Rules

### DatabaseQueueManager
- All DB reads go through `execute_read(async_fn, timeout)`, writes through `execute_write(async_fn, timeout)`
- **Never call AI inside `execute_write`** — it blocks all DB writes for the duration of the AI call
- Pattern: read → AI outside lock → write
- The manager commits writes automatically after `execute_write` completes
- File: `news_aggregator/services/database_queue.py`

### TelegramService (singleton)
- Get via `get_telegram_service(chat_id=None, service_chat_id=None)`
- After changing settings: call `reset_telegram_service()` to invalidate singleton
- Two channels: `chat_id` (digests) vs `service_chat_id` (errors/alerts, fallback to chat_id)
- Channel IDs can be overridden via DB (`settings` table) without restart
- File: `news_aggregator/services/telegram_service.py`

### Orchestrator pipeline
Order of operations in `news_aggregator/orchestrator.py`:
1. `fetch_from_all_sources_no_db()` — HTTP fetch
2. `save_fetched_articles_with_sources()` — save to DB via `execute_write`
3. `_process_unprocessed_articles()` — AI: summary + categories
4. `save_results_operation()` — save AI results in one transaction
5. `_generate_daily_summaries()` — AI: per-category summaries (3-phase: read → AI → write)
6. `send_telegram_digest()` — publish to Telegram + Telegraph

### Date filtering
Use `func.date(Article.fetched_at) == date` (NOT `Article.fetched_at >= date`).

## Source Types

- `rss` — RSS/Atom via feedparser (`sources/rss_source.py`)
- `telegram` — Public channel HTML scraping (`telegram/telegram_source.py` + `telegram/message_parser.py`)
- `custom` — Page Monitor with CSS selectors (`sources/page_monitor_source.py` + `sources/page_monitor_adapter.py`)
- No generic/reddit/twitter sources (deleted)

## Browser (nodriver + Alpine Chrome)

Browser runs in a **separate Docker container** (`gcr.io/zenika-hub/alpine-chrome:123`).
App connects via Chrome DevTools Protocol (CDP) — controlled by `BROWSER_WS_ENDPOINT` env var (e.g. `ws://news_browser:9222`).

- Set: `nodriver.start(host=..., port=...)` — production / dev-container mode
- Unset: `nodriver.start(headless=True)` — local dev fallback (launches local Chrome)

Three files use the browser: `extraction/extraction_strategies.py`, `telegram/telegram_source.py`, `sources/page_monitor_source.py`. Connection pool managed in `core/browser_pool.py`.

Python library: `nodriver>=0.38` (direct CDP, no Node.js dependency).
Docker image: `gcr.io/zenika-hub/alpine-chrome:123` (~300MB, same as Karakeep).

## Category Mapping Enrichment

`services/prompts.py` → `get_available_categories()` enriches the AI prompt with accumulated examples from the `CategoryMapping` table (up to 5 examples per category, sorted by `usage_count` desc).
This means the more corrections you make in the admin UI, the better the AI categorizes automatically.

## Telegram Message Parsing

`telegram/message_parser.py` — key points:
- `_cleanup_message_div()` removes all Telegram UI chrome BEFORE text extraction:
  forwarded-from block, reply quotes, footer, views, date, service messages, keyboards
- `forwarded_from` metadata is extracted BEFORE cleanup (then cleanup removes the block)
- `_clean_message_content()` has regex fallback to strip forwarded arrows from plain text

## Telegram + Telegraph Settings

- `TELEGRAM_CHAT_ID` — main channel (digests)
- `TELEGRAM_SERVICE_CHAT_ID` — service channel (errors, alerts); falls back to main if unset
- Both can be overridden via Admin UI at `/admin/telegram` — stored in `settings` table in DB
- API: `GET/POST /api/v1/telegram/settings`, `POST /api/v1/telegram/test`

## Admin Panel Pages

All under `/admin/`, all extend `web/templates/admin/admin_base.html` (NOT `_sidebar.html`):
- `dashboard`, `sources`, `summaries`, `schedule`, `stats`, `categories`, `backup`, `telegram`

Navigation is in `admin_base.html` sidenav — add new pages there.

## Telegraph Page Format

Allowed HTML tags: `figure`, `figcaption`, `h3`, `h4`, `hr`, `img`, `blockquote`, `strong`, `em`, `p`, `a`, `br`
- TOC: `<blockquote>` with plain text category list (NO anchor links — Cyrillic anchors don't work)
- Category header: `<h3>Category <em>(N articles)</em></h3>`
- Article with image: `<figure><img src="..."><figcaption>Title — → source.com</figcaption></figure>`
- Article without image: `<p><strong>Title</strong></p><p>description... → source.com</p>`
- Separator between articles: `<hr>`

## Settings Table

`settings` table (key/value) already exists in `db/init.sql` — no migration needed.
Used for: `telegram_chat_id`, `telegram_service_chat_id`, and other runtime overrides.

## Scheduler

`ScheduleSettings` model — tasks: `fetch`, `process`, `digest`.
- Enable → `next_run` resets to next valid time from NOW
- Disable → `next_run` set to NULL
- Status badge on `/admin/schedule` updates immediately after toggle (calls `updateScheduleStatus()` post-save)

## Dev Environment Settings

```
NEWS_LIMIT_MAX_ARTICLES=2
NEWS_LIMIT_PER_SOURCE=2
LOG_LEVEL=DEBUG
DEVELOPMENT=true
AI model: gemini-3.1-flash-lite-preview (saves tokens)
```

## Common Pitfalls

1. **DB is PostgreSQL**: Use `JSONB`, `ON CONFLICT DO UPDATE`, `SERIAL`, partial indexes, etc.
2. **Config field**: `telegram_service_chat_id` is in `Settings` (config.py) and in `get_legacy_config()`.
3. **`_sidebar.html`** is not used/included anywhere — edit `admin_base.html` for nav changes.
4. **AI inside write lock**: Don't put async AI calls inside `execute_write` — it blocks all DB operations.
5. **`db.commit()`**: `execute_write` commits automatically. Direct session usage (outside queue) still needs explicit commit.
