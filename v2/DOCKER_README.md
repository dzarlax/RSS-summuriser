# RSS News Aggregator

[![Docker Image](https://img.shields.io/docker/v/dzarlax/rss-summarizer?sort=semver)](https://hub.docker.com/r/dzarlax/rss-summarizer)
[![Docker Image Size](https://img.shields.io/docker/image-size/dzarlax/rss-summarizer/latest)](https://hub.docker.com/r/dzarlax/rss-summarizer)
[![Docker Pulls](https://img.shields.io/docker/pulls/dzarlax/rss-summarizer)](https://hub.docker.com/r/dzarlax/rss-summarizer)

AI-powered news aggregation system with web interface, Telegram integration, and advertising detection.

## Features

- 🤖 **AI-Enhanced Content Extraction** - Publication dates, full articles
- 🚨 **Advertising Detection** - AI-powered spam detection for Telegram channels  
- 🌐 **Web Interface** - Admin panel and public API
- 📱 **Telegram Integration** - Bot notifications and channel monitoring
- 🐘 **PostgreSQL Database** - Full persistence and data integrity
- 🔄 **Multi-source Support** - RSS, Telegram, Generic sources
- 📰 **Telegraph Publishing** - Automatic article publishing
- 🛡️ **Security Scanning** - Regular vulnerability checks

## Quick Start

### Using Docker Compose (Recommended)

```bash
# Download the compose file
curl -o docker-compose.yml https://raw.githubusercontent.com/dzarlax/RSS-summuriser-1/main/v2/docker-compose.example.yml

# Configure environment variables
export CONSTRUCTOR_KM_API="https://training.constructor.app/api/platform-kmapi/v1/knowledge-models/your-model-id/chat/completions/direct_llm"
export CONSTRUCTOR_KM_API_KEY="Bearer your_api_key_here"
export TELEGRAM_TOKEN="your_bot_token"
export TELEGRAM_CHAT_ID="your_chat_id"

# Start services
docker-compose up -d
```

### Using Docker Run

```bash
# Create network and volume
docker network create news_network
docker volume create postgres_data

# Start PostgreSQL
docker run -d \
  --name news_db \
  --network news_network \
  -e POSTGRES_DB=newsdb \
  -e POSTGRES_USER=newsuser \
  -e POSTGRES_PASSWORD=newspass123 \
  -v postgres_data:/var/lib/postgresql/data \
  postgres:15-alpine

# Start News Aggregator
docker run -d \
  --name news_aggregator \
  --network news_network \
  -p 8000:8000 \
  -e DATABASE_URL="postgresql://newsuser:newspass123@news_db:5432/newsdb" \
  -e CONSTRUCTOR_KM_API="your_api_endpoint" \
  -e CONSTRUCTOR_KM_API_KEY="Bearer your_api_key" \
  -e TELEGRAM_TOKEN="your_telegram_token" \
  -e TELEGRAM_CHAT_ID="your_chat_id" \
  dzarlax/rss-summarizer:latest
```

## Environment Variables

### Required
- `DATABASE_URL` - PostgreSQL connection string
- `CONSTRUCTOR_KM_API` - Constructor KM API endpoint
- `CONSTRUCTOR_KM_API_KEY` - API key (with "Bearer " prefix)
- `TELEGRAM_TOKEN` - Telegram bot token
- `TELEGRAM_CHAT_ID` - Telegram chat ID for notifications

### AI Models Configuration
- `SUMMARIZATION_MODEL=gpt-4o-mini` - Model for article summarization
- `CATEGORIZATION_MODEL=gpt-4o-mini` - Model for content categorization  
- `DIGEST_MODEL=gpt-4.1` - Model for final digest generation

### Optional
- `LOG_LEVEL=INFO` - Logging level
- `MAX_WORKERS=5` - Maximum concurrent workers
- `CACHE_TTL=86400` - Cache TTL in seconds
- `TELEGRAPH_ACCESS_TOKEN` - Telegraph API token (optional)

## Web Interface

Once running, access the application at:

- **Admin Panel**: http://localhost:8000/admin
- **Public Feed**: http://localhost:8000/feed
- **API Documentation**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/health

## API Endpoints

- `GET /api/feed` - Get news feed
- `GET /api/sources` - List news sources
- `POST /api/sources` - Add new source
- `GET /health` - Health check
- `GET /metrics` - Prometheus metrics

## Database

The application requires PostgreSQL 15+. The database schema is automatically initialized on first run.

**Tables created:**
- `articles` - News articles with AI analysis
- `sources` - News sources configuration
- `extraction_memory` - AI extraction learning
- `extraction_patterns` - Successful extraction patterns
- And more...

## Volumes

Recommended volume mounts:
- `/app/logs` - Application logs
- `/app/data` - Data files and exports
- `/app/cache` - Application cache
- `/app/backups` - Database backups

## Health Checks

The container includes health checks that verify:
- Web server responsiveness on port 8000
- Database connectivity
- API endpoint availability

## Security

- Runs as non-root user (uid: 1000)
- Regular security scanning with Trivy
- No secrets in image layers
- Minimal attack surface

## Building from Source

```bash
git clone https://github.com/dzarlax/RSS-summuriser.git
cd RSS-summuriser-1/v2
docker build -f docker/Dockerfile -t rss-summarizer .
```

## Architecture

- **Backend**: FastAPI with async processing
- **Database**: PostgreSQL 15 with SQLAlchemy ORM
- **AI Integration**: Constructor KM API
- **Frontend**: Jinja2 templates with vanilla JS
- **Deployment**: Multi-platform Docker images (AMD64, ARM64)

## Support

- **GitHub**: [dzarlax/RSS-summuriser-1](https://github.com/dzarlax/RSS-summuriser-1)
- **Documentation**: See README.md in the repository
- **Issues**: [GitHub Issues](https://github.com/dzarlax/RSS-summuriser-1/issues)

## Tags

- `latest` - Latest stable release from main branch
- `v2.x.x` - Specific version releases
- `main` - Latest development build

All images are built for both `linux/amd64` and `linux/arm64` platforms.