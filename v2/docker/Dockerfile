FROM python:3.12-slim

WORKDIR /app

# Установка системных зависимостей
RUN apt-get update && apt-get install -y \
    curl \
    cron \
    && rm -rf /var/lib/apt/lists/*

# Установка Python зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование приложения
COPY news_aggregator/ ./news_aggregator/
COPY web/ ./web/

# Создание пользователя для безопасности
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Создание директорий для данных
RUN mkdir -p /app/logs /app/data /app/cache

EXPOSE 8000

CMD ["uvicorn", "news_aggregator.main:app", "--host", "0.0.0.0", "--port", "8000"]