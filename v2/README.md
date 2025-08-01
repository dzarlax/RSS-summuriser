# News Aggregator v2.0

Продакшн система агрегации новостей с ИИ-суммаризацией, веб-интерфейсом и базой данных PostgreSQL.

## 🚀 Быстрый запуск

### Docker (Продакшн)
```bash
cd v2
docker-compose up -d
```

### Локальная разработка
```bash
cd v2
pip install -r requirements.txt
python -m news_aggregator
```

## 🏗️ Архитектура

### Ключевые компоненты
- **`news_aggregator/`** - FastAPI приложение с async обработкой
- **`web/`** - HTML шаблоны и статические файлы
- **`db/`** - PostgreSQL схема (автоинициализация)
- **`docker/`** - Docker конфигурации для dev/prod
- **`scripts/`** - Утилиты бэкапа и восстановления

### Технологический стек
- **Backend**: FastAPI + SQLAlchemy + asyncpg
- **Database**: PostgreSQL 15
- **Frontend**: Jinja2 + vanilla JS/CSS
- **Deployment**: Docker + Nginx
- **AI**: Constructor KM API integration

## ✅ Статус реализации

### Полностью готово
- [x] **Модульная архитектура** - core, services, sources
- [x] **База данных** - PostgreSQL с полной схемой (9 таблиц)
- [x] **Веб-интерфейс** - Админ-панель + публичный API
- [x] **Docker контейнеризация** - dev/prod окружения
- [x] **Система источников** - Plugin архитектура (RSS, Telegram, Generic)
- [x] **AI интеграция** - Constructor KM API с rate limiting
- [x] **Telegraph публикация** - Автоматическая публикация статей
- [x] **Backup система** - Автоматические бэкапы БД
- [x] **Async обработка** - Все операции асинхронные
- [x] **CLI интерфейс** - Управление через командную строку

### Частично реализовано
- [x] **Мониторинг** - Prometheus метрики (частично)
- [x] **Логирование** - Базовая настройка structlog

### Критические пробелы
- [ ] **Тестирование** - 0% покрытие тестами
- [ ] **GitHub Actions** - Workflows не адаптированы
- [ ] **API документация** - OpenAPI неполная

## 💻 Использование

### Веб-интерфейс
- **Админ-панель**: http://localhost:8000/admin
- **API документация**: http://localhost:8000/docs  
- **Публичная лента**: http://localhost:8000/feed
- **API endpoints**: http://localhost:8000/api/*

### CLI команды
```bash
# Обработка новостей
python -m news_aggregator.cli process

# Управление источниками
python -m news_aggregator.cli sources list
python -m news_aggregator.cli sources add --name "Habr" --type rss --url "https://habr.com/rss/"

# Система бэкапов
./scripts/backup.sh
./scripts/restore.sh <backup_path>

# Статистика и мониторинг
python -m news_aggregator.cli stats
```

### API Integration
```python
# Программный доступ к API
import aiohttp

async def get_news():
    async with aiohttp.ClientSession() as session:
        async with session.get('http://localhost:8000/api/feed') as resp:
            return await resp.json()
```

## 🔧 Конфигурация

### Обязательные переменные окружения
```bash
DATABASE_URL=postgresql://user:pass@localhost:5432/newsdb
CONSTRUCTOR_KM_API=https://api.constructor.km/v1
CONSTRUCTOR_KM_API_KEY=your_api_key
TELEGRAM_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

### Docker Compose Override
```bash
cp docker-compose.override.yml.example docker-compose.override.yml
# Отредактируйте переменные окружения
```

## 📚 Документация

- **CLAUDE.md** - Полная архитектурная документация
- **QUICKSTART.md** - Быстрый старт для разработчиков
- **BACKUP_SYSTEM.md** - Система бэкапов и восстановления
- **MIGRATION_GUIDE.md** - Руководство по миграции данных

## 🐛 Известные проблемы

1. **Отсутствие тестов** - Критический пробел, требует добавления pytest
2. **GitHub Actions** - Workflows не адаптированы под новую архитектуру
3. **Мониторинг** - Prometheus метрики настроены частично

## 🤝 Вклад в проект

1. Fork репозитория
2. Создайте feature branch
3. Добавьте тесты для новой функциональности
4. Убедитесь, что все проверки проходят
5. Создайте Pull Request

## 📄 Лицензия

[Укажите лицензию проекта]