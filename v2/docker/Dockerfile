FROM python:3.12-slim

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

# Установка системных зависимостей и Python пакетов в одном слое
COPY requirements.txt .
RUN apt-get update && apt-get install -y \
    curl \
    cron \
    wget \
    gnupg \
    ca-certificates \
    libnss3 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libxkbcommon0 \
    libgtk-3-0 \
    libgbm1 \
    libasound2 \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r requirements.txt \
    && playwright install-deps chromium

# Копирование приложения
COPY news_aggregator/ ./news_aggregator/
COPY web/ ./web/
COPY db/ ./db/
COPY scripts/ ./scripts/

# Создание пользователя и финальная настройка
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser
RUN playwright install chromium && mkdir -p /app/logs /app/data /app/cache

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "news_aggregator.main:app", "--host", "0.0.0.0", "--port", "8000"]