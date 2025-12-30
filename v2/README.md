# News Aggregator v2.0

A production-ready news aggregation system with AI summarization, web interface, and PostgreSQL database. Features multi-category support, dynamic category management, AI category mapping, and intelligent content extraction.

## 🚀 Quick Start

### Docker (Production)
```bash
cd v2
# Configure environment variables
cp docker-compose.override.yml.example docker-compose.override.yml
# Edit variables in docker-compose.override.yml
docker-compose up -d
```

### Docker (Development)
```bash
cd v2
# Use dev configuration with auto-reload
docker-compose -f docker-compose.dev.yml up -d
```

### Local Development
```bash
cd v2
pip install -r requirements.txt
python -m news_aggregator
```

## 🏗️ Architecture

### Key Components
- **`news_aggregator/`** - FastAPI application with async processing
- **`web/`** - HTML templates and static files with modal interfaces
- **`db/`** - PostgreSQL schema (auto-initialization)
- **`docker/`** - Docker configurations for dev/prod
- **`scripts/`** - Backup and restore utilities

### Technology Stack
- **Backend**: FastAPI + SQLAlchemy + asyncpg
- **Database**: PostgreSQL 15
- **Frontend**: Jinja2 + vanilla JS/CSS with dynamic modals
- **Deployment**: Docker + Nginx
- **AI**: Google Gemini (Direct API)

## ✅ Implementation Status

### Fully Implemented
- [x] **Modular Architecture** - core, services, sources
- [x] **Database** - PostgreSQL with full schema (16+ tables)
- [x] **Web Interface** - Admin panel + public API + modal article views
- [x] **Docker Containerization** - dev/prod environments
- [x] **Source System** - Plugin architecture (RSS, Telegram, Generic, Custom)
- **AI Integration**: Google Gemini API with rate limiting
- [x] **Universal Database Queue** - Dedicated read/write queues for performance and deadlock resilience
- [x] **Selector Learning System** - Passive learning and caching of successful extraction patterns
- [x] **Smart Content Filtering** - Heuristic-based filtering to reduce redundant/low-quality AI requests
- [x] **Domain Stability Tracking** - Adaptive success tracking with exponential backoff and localized timeouts
- [x] **AI-Enhanced Content Extraction** - Publication dates, full articles, and dynamic selector discovery
- [x] **Advertisement Detection** - AI-based ad detection in Telegram channels
- [x] **Telegraph Publishing** - Automatic article publishing
- [x] **Backup System** - Automated database backups
- [x] **Async Processing** - All operations asynchronous
- [x] **CLI Interface** - Command-line management
- [x] **Multiple Categories** - Support for multiple categories per article with AI confidence
- [x] **Dynamic Category Management** - Color-coded categories, CRUD operations in admin
- [x] **AI Category Mapping** - Original AI categories with customizable mapping to main categories
- [x] **Category Mapping in Admin** - Visual interface for managing category mappings
- [x] **Automatic Migrations** - Self-checking database migration system
- [x] **Universal Migration System** - Reusable migration manager
- [x] **Intelligent Categorization** - AI with contextual analysis and confidence scoring
- [x] **Task Scheduler** - Reliable automatic task execution system
- [x] **AI Categories in Interface** - Display of original AI categories in modal windows
- [x] **Media Support** - Multiple media files (images, videos, documents)
- [x] **Centralized Prompts** - AI prompt management system
- [x] **Process Monitor** - Automated process monitoring and cleanup
- [x] **Modal Article Views** - Rich article modals with media galleries and category display

### Partially Implemented
- [x] **Monitoring** - Prometheus metrics (partial)
- [x] **Logging** - Basic structlog configuration

### Critical Gaps
- [ ] **Testing** - 0% test coverage
- [ ] **GitHub Actions** - Workflows not adapted to new architecture
- [ ] **API Documentation** - Incomplete OpenAPI documentation

## 💻 Usage

### Web Interface
- **Homepage (news feed)**: http://localhost:8000
- **Admin Panel**: http://localhost:8000/admin (password protected)
- **API Documentation**: http://localhost:8000/docs  
- **API Endpoints**: http://localhost:8000/api/*
- **Auth Status**: http://localhost:8000/auth-status

### Key API Endpoints

#### Public API
- **GET /api/public/feed** - Public news feed with category filtering
- **GET /api/public/article/{article_id}** - Detailed article with media and AI categories
- **GET /api/public/search** - Full-text search across articles (title, summary, content)
- **GET /api/public/categories/config** - Dynamic category configuration for UI

#### Admin API
- **GET /api/v1/categories** - List all categories with article counts
- **POST /api/v1/categories** - Create new category with color and description
- **PUT /api/v1/categories/{category_id}** - Update existing category
- **GET /api/v1/category-mappings/unmapped** - Get unmapped AI categories
- **POST /api/v1/category-mappings** - Create AI category mapping
- **PUT /api/v1/category-mappings/{mapping_id}** - Update category mapping
- **GET /api/v1/migrations/status** - Migration system status
- **POST /api/v1/migrations/run** - Manual migration execution
- **GET /api/v1/sources** - Source management
- **POST /api/v1/process/run** - Trigger news processing
- **GET /api/v1/schedule/settings** - Task scheduling management
- **POST /api/v1/telegram/send-digest** - Send Telegram digest
- **GET /api/v1/stats/dashboard** - Dashboard statistics
- **GET /api/v1/backup** - Backup management
- **GET /api/v1/system/process-monitor** - Process monitor status
- **POST /api/v1/system/process-monitor/cleanup** - Manual process cleanup

### CLI Commands
```bash
# News processing
python -m news_aggregator.cli process

# Source management
python -m news_aggregator.cli sources list
python -m news_aggregator.cli sources add --name "Habr" --type rss --url "https://habr.com/rss/"

# Backup system
./scripts/backup.sh
./scripts/restore.sh <backup_path>

# Statistics and monitoring
python -m news_aggregator.cli stats
python -m news_aggregator.cli config  # Configuration check

# Web server only
python -m news_aggregator
# or
uvicorn news_aggregator.main:app --host 0.0.0.0 --port 8000
```

### API Integration
```python
# Programmatic API access
import aiohttp

async def get_news():
    async with aiohttp.ClientSession() as session:
        async with session.get('http://localhost:8000/api/public/feed') as resp:
            return await resp.json()

async def get_article_details(article_id):
    async with aiohttp.ClientSession() as session:
        async with session.get(f'http://localhost:8000/api/public/article/{article_id}') as resp:
            return await resp.json()
```

## 🔧 Configuration

### Required Environment Variables
```bash
# Database
DATABASE_URL=postgresql://user:pass@localhost:5432/newsdb

# Google Gemini API (Direct)
GEMINI_API_KEY=your_gemini_api_key
GEMINI_API_ENDPOINT=https://generativelanguage.googleapis.com/v1/models

# Rate Limiting
RPS=3                           # Requests per second (strictly enforced!)

# Telegram integration
TELEGRAM_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
TELEGRAPH_ACCESS_TOKEN=your_telegraph_token

# Admin authentication (REQUIRED!)
ADMIN_USERNAME=admin
ADMIN_PASSWORD=your_secure_password

# AI models for different tasks (Gemini)
SUMMARIZATION_MODEL=gemini-3-flash-preview    # Fast & cost-effective
CATEGORIZATION_MODEL=gemini-3-flash-preview   # Smart & fast
DIGEST_MODEL=gemini-3-flash-preview         # High quality for digests

# Category settings (optional)
NEWS_CATEGORIES=Business,Tech,Science,Serbia,Nature,Media,Marketing,Other
DEFAULT_CATEGORY=Other

# Application settings
LOG_LEVEL=INFO
DEVELOPMENT=false
USE_CUSTOM_PARSERS=false
MAX_WORKERS=5
CACHE_TTL=86400
CACHE_DIR=/tmp/rss_cache

# Database Connection Pool
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=10
DB_POOL_TIMEOUT=60

# Content extraction settings (optional)
MAX_CONTENT_LENGTH=8000
MIN_CONTENT_LENGTH=200
BROWSER_CONCURRENCY=2
PLAYWRIGHT_TIMEOUT_FIRST_MS=25000
```

### Docker Compose Override
```bash
cp docker-compose.override.yml.example docker-compose.override.yml
# Edit environment variables
```

## 🎨 Category Management System

### Dynamic Categories
- **Color-coded categories** - Each category has customizable colors
- **Display names** - Separate internal names and user-facing display names
- **Admin CRUD** - Full create, read, update operations in admin panel
- **Category statistics** - Article counts per category

### AI Category Mapping
- **Original AI categories** - Preserved AI-generated category names
- **Mapping system** - Map AI categories to main categories
- **Confidence scores** - AI confidence levels for categorization
- **Unmapped categories** - Track and manage unmapped AI categories
- **Automatic application** - Apply mappings to existing articles

### Web Interface Features
- **Modal article views** - Rich popups with full article content
- **Media galleries** - Support for multiple images, videos, documents
- **Category badges** - Dynamic color-coded category display
- **Filter toolbar** - Category filtering with sticky toolbar
- **Mobile responsive** - Optimized for mobile devices

## 🔍 Search System

### Full-Text Search API
The system provides powerful search capabilities across all article content:

#### **Search Endpoint**: `GET /api/public/search`

**Parameters:**
- `q` (required) - Search query (minimum 2 characters)
- `limit` (optional) - Results per page (1-100, default: 20)
- `offset` (optional) - Pagination offset (default: 0)
- `category` (optional) - Filter by category name
- `since_hours` (optional) - Filter articles from last N hours (1-8760)
- `sort` (optional) - Sort order: `relevance`, `date`, `title` (default: relevance)
- `hide_ads` (optional) - Hide advertisements (default: true)

**Search Features:**
- **Multi-field search** - Searches across title, summary, and content
- **Word-based matching** - Splits query into words for better precision
- **Relevance scoring** - Prioritizes title matches, then summary, then content
- **Category filtering** - Filter by one or multiple categories
- **Time filtering** - Search within specific time ranges
- **Pagination** - Efficient pagination with total count
- **Flexible sorting** - Sort by relevance, date, or alphabetically

**Example Usage:**
```bash
# Basic search
GET /api/public/search?q=технологии

# Advanced search with filters
GET /api/public/search?q=искусственный интеллект&category=tech&since_hours=168&sort=date

# Search with pagination
GET /api/public/search?q=бизнес&limit=10&offset=20
```

**Response Format:**
```json
{
  "articles": [...],
  "pagination": {
    "total": 150,
    "limit": 20,
    "offset": 0,
    "has_more": true
  },
  "query": "технологии",
  "filters": {...},
  "results_count": 20
}
```

### Search Interface
- **Dedicated search page**: `/search`
- **Quick search button** in main toolbar
- **Advanced filters** for category and time range
- **Real-time results** with relevance scoring
- **Mobile-responsive** design

### Search Optimization
The system includes specialized database indexes for fast search:
- **Full-text indexes** using PostgreSQL's native capabilities
- **Russian language support** with proper stemming
- **Compound indexes** for multi-field searches
- **Performance indexes** for filtered searches

## 🔍 Article Extraction Methods

The system supports multiple source types and content extraction methods:

### 🗂️ Source Types

#### **RSS Sources** (`rss`)
- **Description**: Standard RSS/Atom feeds
- **Extraction**: XML feed parsing
- **Metadata**: Title, description, link, publication date
- **Example**: `https://habr.com/rss/`, `https://lenta.ru/rss`

#### **Telegram Sources** (`telegram`)
- **Description**: Telegram channels via Bot API
- **Extraction**: Message retrieval through Telegram Bot
- **Features**: AI ad detection, media processing
- **Example**: `https://t.me/tech_news_channel`

#### **Generic Sources** (`reddit`, `twitter`, `news_api`)
- **Description**: Universal sources without automatic loading
- **Extraction**: Manual addition or external integrations
- **Usage**: For sources requiring special handling

#### **Custom Sources** (`custom`)
- **Description**: Web page monitoring with configurable selectors
- **Extraction**: Page Monitor with CSS selectors
- **Features**: Change tracking, page snapshots

### 🧠 AI-Enhanced Content Extraction

#### **Multi-level Extraction**
1. **HTML parsing** - BeautifulSoup + Readability
2. **CSS selectors** - Schema.org, semantic tags
3. **Playwright browser** - JavaScript rendering for SPAs
4. **AI optimization** - Machine learning for selector improvement
5. **Passive Selector Learning** - Caching successful selectors for high-speed reuse

#### **Extraction Persistence and Learning** (`ExtractionMemoryService`)
- **Fast Lookups**: In-memory caching for active extraction patterns.
- **Selector Persistence**: Successful selectors are automatically saved to MariaDB.
- **Stability Tracking**: Monitoring domain stability to decide when to trigger browser rendering or AI optimization.
- **Performance**: Async database writes to ensure extraction latency is minimized.

### 🗄️ Database Optimizations

#### **Universal Database Queue** (`DatabaseQueueManager`)
- **Queue Separation**: Distinct read and write queues for high throughput.
- **Deadlock Resilience**: Automatic retry logic for MariaDB/MySQL deadlocks with exponential backoff.
- **Connection Management**: Active semaphore-based pooling at the application level.
- **Performance**: Decoupled IO operations from the main processing loops.

#### **Supported Markup Schemas**

##### **Schema.org Microdata**
```html
<article itemtype="http://schema.org/NewsArticle">
  <div itemprop="articleBody">Article content...</div>
  <time itemprop="datePublished">2024-01-15</time>
</article>
```

##### **JSON-LD Structured Data**
```json
{
  "@context": "https://schema.org",
  "@type": "NewsArticle",
  "articleBody": "Article content...",
  "datePublished": "2024-01-15"
}
```

##### **Open Graph Protocol**
```html
<meta property="og:title" content="Article Title" />
<meta property="og:description" content="Description..." />
<meta property="article:published_time" content="2024-01-15" />
```

##### **Semantic HTML5**
```html
<main>
  <article role="main">
    <header><h1>Title</h1></header>
    <section>Article content...</section>
    <time datetime="2024-01-15">January 15, 2024</time>
  </article>
</main>
```

### 🤖 AI Processing Services

#### **Combined Analysis** (`analyze_article_complete`)
- **Summarization**: 2-3 sentences in Russian
- **Categorization**: Business, Tech, Science, Serbia, Other + confidence
- **Ad Detection**: Heuristics + AI with typing
- **Date Extraction**: Automatic publication date detection

#### **Specialized AI Services**

##### **CategorizationAI**
- **Model**: Configurable via `CATEGORIZATION_MODEL`
- **Categories**: Configurable via `NEWS_CATEGORIES`
- **Caching**: 1 hour TTL
- **Fallback**: Default category

##### **TelegramAI**
- **Specialization**: Telegram content processing
- **Features**: Media detection, forward processing
- **Integration**: With Telegram Bot API

##### **AdDetector**
- **Heuristics**: Regular expressions for ad markers
- **AI refinement**: Contextual analysis for disputed cases
- **Typing**: `product_promotion`, `service_offer`, `event_promotion`
- **Confidence scoring**: 0.0-1.0 with explanation

#### **Smart Filtering** (`SmartFilter`)
- **Quality Gate**: Prevents processing of boilerplate, navigation, or low-quality content.
- **Language Detection**: Prioritizes target languages (Russian/English) using heuristic analysis.
- **Deduplication**: Hash-based detection to avoid reprocessing identical content within 24h.
- **Extraction Trigger**: Smart detection of RSS summaries that require full-content extraction.

#### **Domain Stability Tracking** (`DomainStabilityTracker`)
- **Performance History**: Tracks success rates and average extraction times per domain.
- **Adaptive Timeouts**: Dynamically adjusts browser/request timeouts based on domain performance.
- **Exponential Backoff**: Automatically throttles extraction attempts for domains experiencing persistent failures.
- **AI Cost Savings**: Skips AI optimization for stable domains to conserve credits.

#### **Telegraph Publishing** (`TelegraphService`)
- **Automated Summaries**: Generates daily digests and publishes them as enriched Telegraph pages.
- **Size Management**: Intelligent content truncation to stay within Telegraph's API limits.
- **Navigation**: Automatic generation of Table of Contents with anchor links for large digests.

#### **Process Monitoring** (`ProcessMonitor`)
- **Resource Cleanup**: Automated detection and termination of hanging Playwright/Chromium instances.
- **Zombie Prevention**: Periodic checks to ensure browser contexts are properly disposed of.
- **Manual Intervention**: Admin API endpoints to trigger resource cleanup on demand.


## 📚 Documentation

### Main Documentation
- **CLAUDE.md** - Complete architectural project documentation
- **PROMPTS_GUIDE.md** - AI prompts and usage guide

### Feature Guides
- **QUICKSTART.md** - Quick start for developers
- **BACKUP_SYSTEM.md** - Backup and restore system
- **MIGRATION_GUIDE.md** - Data migration guide
- **SYNOLOGY_MIGRATION_GUIDE.md** - Automatic migrations for Synology

### Technical Details
- **CONTENT_EXTRACTOR_IMPROVEMENTS.md** - AI-enhanced content extraction
- **AI_ENHANCEMENTS.md** - AI enhancement and ad detection system

### API and Interface
- **Swagger UI**: http://localhost:8000/docs - Interactive API documentation
- **ReDoc**: http://localhost:8000/redoc - Alternative API documentation

## 📈 New Features v2.0

### ✅ Recently Added
- **🔍 Full-Text Search API** - Advanced search across article titles, summaries, and content
- **🎨 Dynamic Category Management** - Color-coded categories with admin CRUD operations
- **🤖 AI Category Mapping** - Intelligent mapping of AI categories to main categories
- **📱 Rich Modal Interface** - Enhanced article modals with media galleries
- **🔄 Process Monitor** - Automated process monitoring and cleanup
- **📊 Category Analytics** - Real-time category statistics and usage tracking
- **🎯 Confidence Scoring** - AI confidence levels for categorization accuracy
- **🔧 Auto-remapping** - Automatic application of category mappings to existing articles
- **🌈 UI Color System** - Dynamic category colors with accessibility features
- **📋 Unmapped Category Tracking** - Monitor and manage unmapped AI categories
- **🎯 Search Interface** - Dedicated search page with filters and relevance scoring

### 🚧 Planned Features
- **🧪 Testing System** - Complete pytest coverage (critical priority)
- **🔄 GitHub Actions** - Workflow adaptation to new architecture
- **📊 Extended Monitoring** - Full Prometheus metrics
- **📚 API Documentation** - Complete OpenAPI specification

## 🐛 Known Issues

1. **No Tests** - Critical gap, requires pytest addition
2. **GitHub Actions** - Workflows not adapted to new architecture
3. **Monitoring** - Prometheus metrics partially configured

## 🔒 Database Migration Requirements

Before deploying the updated code, ensure these database changes are applied:

1. **Create required tables** - `article_categories`, `category_mapping`
2. **Add indexes** - Performance indexes for category queries
3. **Insert base categories** - Default category set
4. **Add ai_category field** - Critical for AI category tracking

⚠️ **Warning**: The application will not start without these database updates.

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure all checks pass
5. Create a Pull Request

## 📄 License

[Specify project license]