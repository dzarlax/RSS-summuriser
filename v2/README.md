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
- [x] **AI-enhanced контент экстракция** - Публикация дат, полные статьи
- [x] **Реклама detection** - ИИ-детекция рекламы в Telegram каналах
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
- **Главная страница (новости)**: http://localhost:8000
- **Админ-панель**: http://localhost:8000/admin (защищена паролем)
- **API документация**: http://localhost:8000/docs  
- **API endpoints**: http://localhost:8000/api/*
- **Статус аутентификации**: http://localhost:8000/auth-status

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
CONSTRUCTOR_KM_API=https://training.constructor.app/api/platform-kmapi/v1/knowledge-models/your-model-id/chat/completions/direct_llm
CONSTRUCTOR_KM_API_KEY=Bearer your_api_key_here
TELEGRAM_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# Аутентификация админки (ОБЯЗАТЕЛЬНО!)
ADMIN_USERNAME=admin
ADMIN_PASSWORD=your_secure_password

# AI модели для разных задач
SUMMARIZATION_MODEL=gpt-4o-mini    # Суммаризация статей
CATEGORIZATION_MODEL=gpt-4o-mini   # Категоризация новостей
DIGEST_MODEL=gpt-4.1               # Финальные дайджесты
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
- **CONTENT_EXTRACTOR_IMPROVEMENTS.md** - AI-enhanced экстракция контента
- **AI_ENHANCEMENTS.md** - Система ИИ-улучшений и детекции рекламы

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