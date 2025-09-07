# News Aggregator - Архитектура Продакшн Системы

## Текущее Состояние
Проект представляет собой полнофункциональную платформу агрегации новостей с ИИ-суммаризацией, веб-интерфейсом и базой данных PostgreSQL.

### Эволюция от Монолитной Архитектуры  
- ✅ **Модульная структура**: Разделение на core, services, sources с четкими границами
- ✅ **Асинхронная обработка**: Async/await для всех HTTP операций и API вызовов
- ✅ **Веб-интерфейс**: FastAPI с админ-панелью и публичным API
- ✅ **База данных**: PostgreSQL с полной схемой для персистентности (16+ таблиц)
- ✅ **Контейнеризация**: Docker + Nginx для продакшн развертывания
- ✅ **AI интеграция**: Constructor KM API с промптами и rate limiting
- ✅ **Миграционная система**: Универсальный менеджер миграций БД
- ✅ **Система извлечения**: AI-оптимизированная экстракция контента с обучением
- ⚠️ **Тестирование**: Отсутствует покрытие тестами (критический пробел)

## Продакшн Архитектура

### Ключевые Команды
- **Веб-сервер**: `python -m news_aggregator` или `uvicorn news_aggregator.main:app`
- **CLI управление**: `python -m news_aggregator.cli --help`
- **Docker**: `docker-compose up -d`
- **Миграции БД**: База инициализируется автоматически из `db/init.sql`
- **Бэкап**: `./scripts/backup.sh`

### Актуальная Структура Проекта
```
news_aggregator/
├── __init__.py
├── __main__.py             # Точка входа модуля
├── config.py               # Конфигурация с Pydantic
├── database.py             # SQLAlchemy setup
├── database_helpers.py     # DB helpers для оптимизации
├── models.py               # SQLAlchemy модели для БД (16+ таблиц)
├── orchestrator.py         # Главный оркестратор процессов
├── main.py                 # FastAPI приложение
├── api.py                  # API endpoints (50+ endpoints)
├── admin.py                # Админ интерфейс
├── public.py               # Публичные endpoints
├── auth.py                 # Аутентификация
├── auth_api.py             # API аутентификации
├── security.py             # Функции безопасности
├── cli.py                  # CLI интерфейс
├── core/
│   ├── __init__.py
│   ├── cache.py            # Файловый кеш
│   ├── http_client.py      # Async HTTP клиент
│   └── exceptions.py       # Кастомные исключения
├── migrations/             # Система миграций БД
│   ├── __init__.py
│   ├── base_migration.py   # Базовый класс миграций
│   ├── universal_migration_manager.py # Менеджер миграций
│   ├── multiple_categories_migration.py # Множественные категории
│   └── media_files_migration.py # Поддержка медиа файлов
├── services/
│   ├── __init__.py
│   ├── ai_client.py        # Constructor KM API клиент
│   ├── prompts.py          # Централизованные AI промпты
│   ├── source_manager.py   # Управление источниками
│   ├── telegram_service.py # Telegram уведомления
│   ├── telegraph_service.py# Telegraph публикация
│   ├── backup_service.py   # Система бэкапов
│   ├── scheduler.py        # Планировщик задач
│   ├── database_queue.py   # Универсальная очередь БД
│   ├── content_extractor.py# Извлечение контента
│   ├── extraction_memory.py# Обучающаяся экстракция
│   ├── ai_extraction_optimizer.py # AI оптимизация экстракции
│   ├── domain_stability_tracker.py # Отслеживание стабильности доменов
│   ├── custom_parsers.py   # Кастомные парсеры
│   ├── extraction_constants.py # Константы для экстракции
│   ├── category_parser.py  # Парсер категорий
│   ├── category_service.py # Сервис категорий
│   ├── ad_detector.py      # Детектор рекламы
│   └── smart_filter.py     # Умная фильтрация
├── sources/
│   ├── __init__.py
│   ├── base.py             # Базовый класс источника
│   ├── registry.py         # Реестр источников
│   ├── rss_source.py       # RSS источники
│   ├── telegram_source.py  # Telegram источники
│   ├── generic_source.py   # Универсальные источники
│   ├── page_monitor_source.py # Мониторинг страниц
│   ├── page_monitor_adapter.py # Адаптер мониторинга
│   └── ai_page_analyzer.py # AI анализ страниц
└── utils/
    ├── __init__.py
    └── html_utils.py       # HTML обработка

db/
├── init.sql               # Полная схема БД (16+ таблиц)
└── migrations/            # SQL миграции
    ├── 001_add_extraction_learning_tables.sql
    ├── 002_add_multiple_categories_support.sql
    └── 003_add_media_files_support.sql

docker/
├── Dockerfile
├── Dockerfile.dev
└── docker-compose.yml

web/
├── templates/             # Jinja2 шаблоны
│   ├── admin/            # Админ интерфейс
│   ├── public/           # Публичные страницы
│   └── base.html
└── static/               # CSS/JS ресурсы

scripts/
├── backup.sh             # Скрипты бэкапа
└── restore.sh

nginx/
└── nginx.conf            # Nginx конфигурация
```

## Технические Улучшения

### 1. Продакшн Python Stack
```python
# Веб-фреймворк
fastapi>=0.104.1        # Современный async веб-фреймворк
uvicorn[standard]>=0.24.0 # ASGI сервер

# База данных
asyncpg>=0.29.0         # Async PostgreSQL драйвер
sqlalchemy[asyncio]>=2.0.23 # ORM с async поддержкой

# HTTP клиенты
aiohttp>=3.9.1          # Async HTTP
httpx>=0.25.2           # Альтернативный HTTP клиент
tenacity>=8.2.3         # Retry механизм

# Конфигурация и валидация
pydantic>=2.5.0         # Валидация данных
pydantic-settings>=2.1.0 # Настройки приложения

# Обработка контента
feedparser>=6.0.10      # RSS parsing
beautifulsoup4>=4.12.2  # HTML parsing
telegraph>=2.2.0        # Telegraph API

# Файловые операции
aiofiles>=23.2.1        # Async file operations

# Мониторинг
structlog>=23.2.0       # Структурированное логирование
prometheus-client>=0.19.0 # Метрики

# CLI и UI
click>=8.1.7            # CLI интерфейс
rich>=13.7.0            # Красивый вывод
jinja2>=3.1.2           # Шаблоны

# Дата и время
python-dateutil>=2.8.2 # Работа с датами
pytz>=2023.3            # Часовые пояса
```

### 2. База Данных и Персистентность (16+ Таблиц)
```python
# PostgreSQL схема для полной персистентности
class Article(Base):
    __tablename__ = 'articles'
    
    id = Column(Integer, primary_key=True)
    title = Column(Text, nullable=False)  # Changed to Text
    content = Column(Text)
    summary = Column(Text)
    source_id = Column(Integer, ForeignKey('sources.id'))
    category = Column(String(50))  # Legacy single category
    media_files = Column(JSON, default=list)  # Multiple media files
    is_advertisement = Column(Boolean, default=False)  # Ad detection
    ad_confidence = Column(Float, default=0.0)
    ad_type = Column(String(50))
    ad_reasoning = Column(Text)
    summary_processed = Column(Boolean, default=False)
    category_processed = Column(Boolean, default=False)
    ad_processed = Column(Boolean, default=False)

# Множественные категории (новая система)
class Category(Base):
    __tablename__ = 'categories'
    
    name = Column(String(50), nullable=False, unique=True)
    display_name = Column(String(100), nullable=False)
    color = Column(String(7), default='#6c757d')

class ArticleCategory(Base):
    __tablename__ = 'article_categories'
    
    article_id = Column(Integer, ForeignKey('articles.id'))
    category_id = Column(Integer, ForeignKey('categories.id'))
    confidence = Column(Float, default=1.0)  # AI confidence

# AI-оптимизированная экстракция контента
class ExtractionPattern(Base):
    __tablename__ = 'extraction_patterns'
    
    domain = Column(String(255), nullable=False)
    selector_pattern = Column(Text, nullable=False)
    success_count = Column(Integer, default=0)
    quality_score_avg = Column(DECIMAL(5, 2), default=0)
    discovered_by = Column(String(20), default='manual')  # 'ai', 'heuristic'
    is_stable = Column(Boolean, default=False)

class DomainStability(Base):
    __tablename__ = 'domain_stability'
    
    domain = Column(String(255), unique=True, nullable=False)
    is_stable = Column(Boolean, default=False)
    success_rate_7d = Column(DECIMAL(5, 2), default=0)
    ai_credits_saved = Column(Integer, default=0)
    needs_reanalysis = Column(Boolean, default=False)

# И еще 9+ таблиц: sources, daily_summaries, processing_stats, 
# task_queue, schedule_settings, settings, extraction_attempts,
# ai_usage_tracking, news_clusters, cluster_articles
```

### 3. Rate-Limited AI API Integration
```python
# Constructor KM API с централизованными промптами
class AIClient:
    def __init__(self, api_key: str, rate_limit: int = 3):
        self.api_key = api_key
        self.rate_limiter = AsyncLimiter(max_rate=rate_limit, time_period=1.0)
    
    async def analyze_article_complete(self, title: str, content: str, url: str) -> dict:
        """Полный анализ статьи: категоризация, суммаризация, детекция рекламы."""
        async with self.rate_limiter:
            from .services.prompts import NewsPrompts
            prompt = NewsPrompts.unified_article_analysis(title, content, url)
            return await self._make_api_request(prompt)

# Система централизованных промптов
class NewsPrompts:
    @staticmethod
    def unified_article_analysis(title: str, content: str, url: str) -> str:
        """Единый промпт для полного анализа статьи."""
        return f"""Analyze this article and provide complete analysis in JSON format.
        
        ARTICLE: {title}
        URL: {url}
        CONTENT: {content[:2000]}...
        
        TASKS:
        1. TITLE OPTIMIZATION: Clear, informative headline (max 120 chars)
        2. CATEGORIZATION: Choose 1-2 relevant categories  
        3. SUMMARIZATION: 5-6 sentence summary in Russian
        4. ADVERTISEMENT DETECTION: Determine if promotional
        5. DATE EXTRACTION: Find publication date
        
        OUTPUT: Valid JSON with optimized_title, categories, summary, 
        is_advertisement, ad_confidence, etc."""

# Оркестратор для координации всех процессов
class NewsOrchestrator:
    async def run_full_cycle(self):
        """Полный цикл: синхронизация, обработка, генерация сводок."""
        # Uses SourceManager.fetch_from_all_sources() to get articles from all sources
        await self._process_unprocessed_articles()
        await self._generate_daily_summaries()
        return await self._create_combined_digest()
```

### 4. Конфигурация с Валидацией
```python
class Settings(BaseSettings):
    # База данных
    database_url: str = "postgresql://newsuser:newspass123@localhost:5432/newsdb"
    
    # Constructor KM API (основной ИИ)
    constructor_km_api: Optional[str] = None
    constructor_km_api_key: Optional[str] = None
    model: str = "gpt-4o-mini"
    
    # Специфичные модели для разных задач
    summarization_model: str = "gpt-4o-mini"
    categorization_model: str = "gpt-4o-mini" 
    digest_model: str = "gpt-4.1"
    
    # Telegram
    telegram_token: Optional[SecretStr] = None
    telegram_chat_id: Optional[str] = None
    telegraph_access_token: Optional[str] = None
    
    # Админ аутентификация
    admin_username: str = "admin"
    admin_password: Optional[str] = None
    
    # Приложение
    log_level: str = "INFO"
    development: bool = False
    use_custom_parsers: bool = False
    max_workers: int = 5
    cache_ttl: int = 86400
    cache_dir: str = "/tmp/rss_cache"
    
    # API Rate Limiting
    api_rate_limit: int = Field(default=3, alias="RPS")
    
    # Database Connection Pool (увеличенные настройки)
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_timeout: int = 60
    
    class Config:
        env_file = ".env"
        case_sensitive = False
```

### 5. Веб-интерфейс и API
```python
# FastAPI приложение с 50+ API endpoints
@router.get("/")
async def api_root():
    """API root с полным списком endpoints."""
    return {
        "message": "RSS Summarizer v2 API",
        "version": "2.0.0",
        "endpoints": {
            "feed": "/api/v1/feed - Get news feed",
            "categories": "/api/v1/categories - Get categories", 
            "sources": "/api/v1/sources - Manage sources",
            "summaries": "/api/v1/summaries/daily - Daily summaries",
            "process": "/api/v1/process/run - Manual processing",
            "telegram": "/api/v1/telegram/send-digest - Send digest",
            "backup": "/api/v1/backup - Backup management",
            "schedule": "/api/v1/schedule/settings - Task scheduling",
            "migrations": "/api/v1/migrations/status - DB migrations",
            "stats": "/api/v1/stats/dashboard - Dashboard stats"
        }
    }

# Публичный API с фильтрацией рекламы
@router.get("/api/public/feed") 
async def get_public_feed(
    limit: int = Query(20, ge=1, le=1000),
    category: Optional[str] = None,
    hide_ads: bool = Query(True)
):
    """Публичный API с поддержкой множественных категорий и медиа."""
    # Поддержка новой системы категорий через ArticleCategory
    # Автоматическое скрытие рекламы по умолчанию
    # Поддержка множественных медиа файлов
    return feed_data

# Админ интерфейс с полной статистикой
@router.get("/stats/dashboard")
async def get_dashboard_stats():
    """Comprehensive dashboard statistics."""
    return {
        "total_sources": total_sources,
        "active_sources": active_sources,
        "today_articles": today_articles,
        "api_calls_today": api_calls_today,
        "extraction_efficiency": extraction_stats,
        "queue_status": queue_stats
    }
```

## Статус Реализации

### ✅ Полностью Реализовано
1. **Модульная архитектура** - Разделение на core, services, sources, migrations
2. **Async обработка** - Все HTTP операции и БД запросы асинхронные
3. **База данных** - PostgreSQL с полной схемой (16+ таблиц)
4. **Веб-интерфейс** - FastAPI с админ-панелью и публичным API (50+ endpoints)
5. **Конфигурация** - Pydantic с валидацией и поддержкой .env
6. **Docker контейнеризация** - Полная настройка для продакшн
7. **Система источников** - Plugin-based архитектура (RSS, Telegram, Generic, PageMonitor)
8. **Бэкап система** - Автоматические бэкапы БД с веб-интерфейсом
9. **Telegraph интеграция** - Публикация в Telegraph
10. **AI интеграция** - Constructor KM API с централизованными промптами
11. **Множественные категории** - Новая система категорий с уверенностью
12. **Детекция рекламы** - AI-детекция рекламного контента
13. **Система миграций** - Универсальный менеджер миграций БД
14. **AI-экстракция** - Обучающаяся система извлечения контента
15. **Медиа поддержка** - Множественные медиа файлы (изображения, видео, документы)
16. **Универсальная очередь** - Database queue для всех операций
17. **Планировщик задач** - Гибкая настройка автоматических задач
18. **Аутентификация** - Админ аутентификация с JWT
19. **Централизованные промпты** - Система промптов в services/prompts.py

### ⚠️ Частично Реализовано
1. **Логирование** - Базовая настройка есть, структурированные логи частично
2. **Мониторинг** - Prometheus метрики настроены, но не все собираются
3. **CLI интерфейс** - Базовый функционал есть, но нужно расширение

### ❌ Не Реализовано (Критические Пробелы)
1. **Тестирование** - Полное отсутствие тестов (0% покрытие)
2. **GitHub Actions** - Workflows не адаптированы под новую архитектуру
3. **Документация API** - OpenAPI/Swagger документация неполная

## Переменные Окружения

### Обязательные для Продакшн
- `DATABASE_URL` - PostgreSQL подключение (по умолчанию: postgresql://newsuser:newspass123@localhost:5432/newsdb)
- `CONSTRUCTOR_KM_API` - Endpoint для Constructor KM API
- `CONSTRUCTOR_KM_API_KEY` - API ключ для Constructor KM
- `TELEGRAM_TOKEN` - Telegram bot token
- `TELEGRAM_CHAT_ID` - Telegram chat ID

### Опциональные
- `MODEL=gpt-4o-mini` - Модель ИИ для суммаризации
- `LOG_LEVEL=INFO` - Уровень логирования
- `DEVELOPMENT=false` - Режим разработки
- `MAX_WORKERS=5` - Максимум параллельных задач
- `CACHE_TTL=86400` - TTL кеша в секундах
- `TELEGRAPH_ACCESS_TOKEN` - Токен для Telegraph API

### Legacy (для совместимости)
- `API_ENDPOINT` - Старый Yandex API endpoint
- `API_TOKEN` - Старый API токен
- `RPS=3` - Лимит запросов к API (строго соблюдается!)
- `RSS_LINKS` - URL со списком RSS лент (для миграции)

## Развертывание и Запуск

### Docker Развертывание (Продакшн)
```bash
# Клонирование и настройка
git clone <repository>
cd v2

# Настройка переменных окружения
cp docker-compose.override.yml.example docker-compose.override.yml
# Отредактировать docker-compose.override.yml с актуальными значениями

# Запуск всех сервисов
docker-compose up -d

# Проверка статуса
docker-compose logs -f web
```

### Локальная Разработка
```bash
# Установка зависимостей
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Настройка базы данных
createdb newsdb
export DATABASE_URL="postgresql://user:pass@localhost:5432/newsdb"

# Запуск веб-сервера
python -m news_aggregator
# или
uvicorn news_aggregator.main:app --reload

# CLI команды
python -m news_aggregator.cli sources list
python -m news_aggregator.cli process --source-id 1
```

### GitHub Actions (Требует Обновления)
⚠️ **Текущие workflows НЕ совместимы с новой архитектурой**

```yaml
# Нужно обновить .github/workflows/
name: News Aggregator
on:
  schedule:
    - cron: '*/30 * * * *'  # Каждые 30 минут
  workflow_dispatch:

jobs:
  process:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_PASSWORD: newspass123
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v4
        with:
          python-version: '3.12'
      
      - name: Install dependencies
        run: pip install -r requirements.txt
          
      - name: Run News Processing
        run: python -m news_aggregator.cli process
        env:
          DATABASE_URL: postgresql://postgres:newspass123@localhost:5432/postgres
          CONSTRUCTOR_KM_API: ${{ secrets.CONSTRUCTOR_KM_API }}
          CONSTRUCTOR_KM_API_KEY: ${{ secrets.CONSTRUCTOR_KM_API_KEY }}
          TELEGRAM_TOKEN: ${{ secrets.TELEGRAM_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
```

## Достигнутые Улучшения vs Планируемые

### ✅ Превзошли Ожидания  
- 🏗️ **Архитектура**: Полная веб-платформа с 16+ таблицами БД вместо CLI
- 💾 **Персистентность**: PostgreSQL с миграциями и полной схемой
- 🌐 **Интерфейс**: Админ-панель + 50+ API endpoints + публичный API
- 🔌 **Расширяемость**: Plugin система (RSS, Telegram, Generic, PageMonitor)
- 🔄 **Бэкапы**: Автоматическая система с веб-интерфейсом управления
- 📰 **Telegraph**: Интеграция для публикации статей
- 🤖 **AI интеграция**: Централизованные промпты + детекция рекламы
- 🏷️ **Категоризация**: Множественные категории с AI уверенностью
- 📱 **Медиа**: Поддержка изображений, видео, документов
- 📊 **Мониторинг**: Dashboard со статистикой экстракции и очередей
- 🎯 **AI-экстракция**: Обучающаяся система с отслеживанием доменов
- ⚙️ **Миграции**: Универсальный менеджер миграций БД

### ✅ Выполнены Согласно Плану  
- 🚀 **Производительность**: Async обработка всех операций
- 🔧 **Поддерживаемость**: Модульная архитектура с четким разделением
- ⚙️ **Конфигурация**: Pydantic с валидацией и поддержкой .env
- 🛡️ **Надежность**: Улучшенная обработка ошибок с retry механизмами
- 📡 **API интеграция**: Rate-limited клиенты для внешних API

### ❌ Не Достигнуты (Критические Пробелы)
- 🧪 **Тестируемость**: 0% покрытие вместо планируемых 90%+
- 📊 **Мониторинг**: Частичная телеметрия вместо детальной
- ⚡ **GitHub Actions**: Workflows не адаптированы под новую архитектуру

## Следующие Шаги

### Приоритет 1 (Критично)
1. **Добавить тестирование** - pytest + покрытие
2. **Обновить GitHub Actions** - адаптировать под новую архитектуру
3. **Завершить API документацию** - полная OpenAPI спецификация

### Приоритет 2 (Важно)
1. **Улучшить мониторинг** - полные Prometheus метрики
2. **Расширить CLI** - дополнительные команды управления
3. **Оптимизировать производительность** - профилирование и кэширование

### Приоритет 3 (Желательно)
1. **Структурированное логирование** - полный переход на structlog
2. **Расширить веб-интерфейс** - дополнительные админ функции
3. **Добавить уведомления** - различные каналы оповещений