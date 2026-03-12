# Evening News

A self-hosted news digest service that collects articles from RSS feeds, Telegram channels, and custom sources — then uses AI to summarize, categorize, and deliver a daily digest to your Telegram channel.

**Live demo:** [news.dzarlax.dev](https://news.dzarlax.dev)

---

## What it does

1. **Collects** news from your configured sources throughout the day — RSS feeds, public Telegram channels, and arbitrary web pages.
2. **Summarizes** each article with AI (Google Gemini), extracting the key points in a consistent format.
3. **Categorizes** articles automatically. The more you correct the AI via the admin panel, the better it gets over time.
4. **Publishes** a daily digest to your Telegram channel as a formatted message, with a full-length Telegraph article attached for comfortable reading.

Everything runs on a schedule you control, or you can trigger any step manually from the admin panel.

---

## Admin panel

A web UI at `/admin` lets you manage everything without touching config files:

- **Dashboard** — today's articles, processing status, quick stats
- **Sources** — add/edit/remove RSS feeds, Telegram channels, and custom pages
- **Schedule** — configure when fetching, processing, and digest sending happen
- **Summaries** — browse AI-generated daily summaries by category
- **Categories** — manage categories and teach the AI to categorize better
- **Telegram** — configure delivery channels, send a test message
- **Backup** — create and restore database backups
- **Stats** — article counts, source activity, processing history

---

## Getting started

### With Docker (recommended)

```bash
cp docker-compose.example.yml docker-compose.yml
# Edit docker-compose.yml — fill in your API keys and passwords
docker-compose up -d
```

The app will be available at `http://localhost:8000`. The admin panel is at `/admin`.

### For local development

```bash
docker-compose -f docker-compose.dev.yml up -d
```

This mounts your local code into the container so changes take effect without rebuilding.

---

## Configuration

The only things you need to get started:

```bash
# Database
DATABASE_URL=mysql+aiomysql://newsuser:pass@mariadb:3306/newsdb

# Google Gemini (for summarization and categorization)
GEMINI_API_KEY=your_gemini_api_key

# Telegram (where digests are published)
TELEGRAM_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_channel_id

# Telegraph (for full-length digest articles)
TELEGRAPH_ACCESS_TOKEN=your_telegraph_token

# Admin panel
ADMIN_USERNAME=admin
ADMIN_PASSWORD=your_secure_password
JWT_SECRET=your_jwt_secret
```

Everything else has sensible defaults. Full reference is in `docker-compose.example.yml`.

---

## Sources

**RSS / Atom** — any standard feed URL.

**Telegram** — public channels via web preview. The parser strips UI chrome (forwarded headers, reactions, buttons) and tries to follow external links to get the full article text.

**Custom (Page Monitor)** — for sites that don't have RSS. You provide CSS selectors to identify article links and titles on a page.

---

## Digest format

Each digest is sent to Telegram as a brief summary per category, with a link to a Telegraph page that contains the full digest — article titles, short summaries, images, and source links — organized by category with a table of contents.

---

## Known limitations

- No automated tests
- Prometheus metrics are partially wired up but not complete
- GitHub Actions workflows are not aligned with the current architecture
