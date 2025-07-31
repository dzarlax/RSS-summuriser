# News Aggregator v2 - Быстрый Старт

## 🚀 Продакшн развертывание (Docker)

1. **Клонируйте репозиторий:**
   ```bash
   git clone <repository_url>
   cd v2
   ```

2. **Настройте переменные окружения:**
   ```bash
   cp docker-compose.override.yml.example docker-compose.override.yml
   # Отредактируйте docker-compose.override.yml с вашими настройками:
   # - DATABASE_URL
   # - CONSTRUCTOR_KM_API_KEY
   # - TELEGRAM_TOKEN
   # - TELEGRAM_CHAT_ID
   ```

3. **Запустите все сервисы:**
   ```bash
   docker-compose up -d
   ```

4. **Проверьте статус:**
   ```bash
   docker-compose logs -f web
   ```

5. **Откройте в браузере:**
   - **Админ-панель**: http://localhost:8000/admin
   - **API документация**: http://localhost:8000/docs
   - **Публичная лента**: http://localhost:8000/feed
   - **API**: http://localhost:8000/api/feed

## 🛠️ Локальная разработка

1. **Подготовка окружения:**
   ```bash
   cd v2
   python -m venv venv
   source venv/bin/activate  # Linux/Mac
   # или venv\Scripts\activate  # Windows
   ```

2. **Установка зависимостей:**
   ```bash
   pip install -r requirements.txt
   pip install -r requirements-dev.txt
   ```

3. **Настройка базы данных:**
   ```bash
   # Установите PostgreSQL локально или используйте Docker
   docker run -d --name postgres-dev \
     -e POSTGRES_USER=newsuser \
     -e POSTGRES_PASSWORD=newspass123 \
     -e POSTGRES_DB=newsdb \
     -p 5432:5432 postgres:15
   
   # Установите переменную окружения
   export DATABASE_URL="postgresql://newsuser:newspass123@localhost:5432/newsdb"
   ```

4. **Запуск приложения:**
   ```bash
   # Веб-сервер
   python -m news_aggregator
   # или
   uvicorn news_aggregator.main:app --reload --host 0.0.0.0 --port 8000
   ```

## 📁 Структура проекта

```
v2/
├── news_aggregator/          # ✅ Основное приложение
│   ├── config.py            # ✅ Pydantic конфигурация
│   ├── main.py              # ✅ FastAPI приложение
│   ├── models.py            # ✅ SQLAlchemy модели (9 таблиц)
│   ├── database.py          # ✅ Async подключение к БД
│   ├── orchestrator.py      # ✅ Главный оркестратор
│   ├── api.py               # ✅ REST API endpoints
│   ├── admin.py             # ✅ Админ интерфейс
│   ├── public.py            # ✅ Публичные страницы
│   ├── cli.py               # ✅ CLI команды
│   ├── core/                # ✅ Ядро системы
│   │   ├── cache.py         # Файловое кеширование
│   │   ├── http_client.py   # Async HTTP клиент
│   │   └── exceptions.py    # Кастомные исключения
│   ├── services/            # ✅ Бизнес-логика
│   │   ├── ai_client.py     # Constructor KM API
│   │   ├── source_manager.py # Управление источниками
│   │   ├── telegram_*.py    # Telegram интеграция
│   │   └── telegraph_service.py # Telegraph публикация
│   ├── sources/             # ✅ Система источников
│   │   ├── rss_source.py    # RSS обработка
│   │   ├── telegram_source.py # Telegram каналы
│   │   └── generic_source.py # Универсальные источники
│   └── utils/               # ✅ Утилиты
├── web/                     # ✅ Веб-интерфейс
│   ├── templates/           # Jinja2 шаблоны (админ + публичные)
│   └── static/              # CSS/JS ресурсы
├── db/                      # ✅ База данных
│   └── init.sql            # Полная схема (все миграции включены)
├── docker/                  # ✅ Контейнеризация
├── scripts/                 # ✅ Утилиты
│   ├── backup.sh           # Автоматические бэкапы
│   └── restore.sh          # Восстановление из бэкапа
└── nginx/                   # ✅ Nginx конфигурация
```

## ⚙️ CLI команды

```bash
# Основные операции
python -m news_aggregator.cli process        # Обработка новостей
python -m news_aggregator.cli sources list   # Список источников
python -m news_aggregator.cli stats          # Статистика

# Управление источниками
python -m news_aggregator.cli sources add \
  --name "Habr" --type rss --url "https://habr.com/rss/"

# Система бэкапов
./scripts/backup.sh                          # Создать бэкап
./scripts/restore.sh path/to/backup.tar.gz   # Восстановить

# Docker команды
docker-compose up -d                         # Запуск всех сервисов
docker-compose logs -f web                   # Логи веб-сервера
docker-compose exec web python -m news_aggregator.cli stats
```

## 🔧 Конфигурация

### Обязательные переменные
```bash
# Database (PostgreSQL)
DATABASE_URL=postgresql://newsuser:newspass123@localhost:5432/newsdb

# AI API (Constructor KM)
CONSTRUCTOR_KM_API=https://api.constructor.km/v1
CONSTRUCTOR_KM_API_KEY=your_api_key_here

# Telegram Integration
TELEGRAM_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# Telegraph (optional)
TELEGRAPH_ACCESS_TOKEN=your_telegraph_token
```

### Docker Compose Override
```yaml
# docker-compose.override.yml
version: '3.8'
services:
  web:
    environment:
      - CONSTRUCTOR_KM_API_KEY=your_actual_key
      - TELEGRAM_TOKEN=your_actual_token
      - TELEGRAM_CHAT_ID=your_actual_chat_id
```

## 🎯 Статус системы

### ✅ Продакшн готово
- **Полная архитектура** - Все компоненты реализованы
- **База данных** - PostgreSQL с 9 таблицами
- **Веб-интерфейс** - Админ-панель + публичный API
- **AI интеграция** - Constructor KM с rate limiting
- **Telegram бот** - Уведомления и публикация
- **Telegraph** - Автоматическая публикация статей
- **Backup система** - Полные бэкапы БД
- **Docker deployment** - Готово к продакшн

### ⚠️ Критические пробелы
- **Тестирование** - 0% покрытие (нужен pytest)
- **GitHub Actions** - Workflows не адаптированы
- **Мониторинг** - Prometheus метрики частично

## 🚀 Быстрый тест

После запуска проверьте:
```bash
# Веб-интерфейс доступен
curl http://localhost:8000/

# API работает
curl http://localhost:8000/api/feed

# База данных инициализирована
docker-compose exec db psql -U newsuser -d newsdb -c "\dt"

# Сервисы запущены
docker-compose ps
```

## 📚 Дополнительная документация

- **CLAUDE.md** - Детальная архитектурная документация
- **BACKUP_SYSTEM.md** - Система бэкапов и восстановления
- **MIGRATION_GUIDE.md** - Руководство по миграции данных

---

**Статус:** 🟢 **Готово к продакшн использованию** (добавить тесты для полной готовности)