# Use official Playwright image with Python 3.12
FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

# Build arguments for metadata
ARG BUILDTIME
ARG VERSION
ARG REVISION

# Add metadata labels
LABEL org.opencontainers.image.created=$BUILDTIME \
      org.opencontainers.image.version=$VERSION \
      org.opencontainers.image.revision=$REVISION \
      org.opencontainers.image.title="RSS News Aggregator" \
      org.opencontainers.image.description="AI-powered news aggregation system with web interface" \
      org.opencontainers.image.source="https://github.com/dzarlax/RSS-summuriser" \
      org.opencontainers.image.vendor="Dzarlax" \
      org.opencontainers.image.licenses="MIT"

WORKDIR /app

# Install additional system dependencies (PostgreSQL client)
RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --prefer-binary -r requirements.txt

# Install Playwright browsers
RUN playwright install chromium chromium-headless-shell --with-deps

# Копирование приложения
COPY news_aggregator/ ./news_aggregator/
COPY web/ ./web/
COPY db/ ./db/
COPY scripts/ ./scripts/

# Create directories and set permissions
RUN mkdir -p /app/logs /app/data /app/cache

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "news_aggregator.main:app", "--host", "0.0.0.0", "--port", "8000"]