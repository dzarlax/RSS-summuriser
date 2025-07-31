FROM python:3.12-slim

WORKDIR /app

# Установка системных зависимостей для Playwright
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
    && rm -rf /var/lib/apt/lists/*

# Установка Python зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Установка системных зависимостей Playwright (требует root)
RUN playwright install-deps chromium

# Копирование приложения
COPY news_aggregator/ ./news_aggregator/
COPY web/ ./web/

# Создание пользователя для безопасности
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Установка браузеров Playwright (под пользователем)
RUN playwright install chromium

# Создание директорий для данных
RUN mkdir -p /app/logs /app/data /app/cache

EXPOSE 8000

CMD ["uvicorn", "news_aggregator.main:app", "--host", "0.0.0.0", "--port", "8000"]