# News Aggregator - Архитектура Продакшн Системы

## Текущее Состояние
Проект представляет собой полнофункциональную платформу агрегации новостей с ИИ-суммаризацией, веб-интерфейсом и базой данных PostgreSQL.

### Эволюция от Монолитной Архитектуры
- ✅ **Модульная структура**: Разделение на core, services, sources с четкими границами
- ✅ **Асинхронная обработка**: Async/await для всех HTTP операций и API вызовов
- ✅ **Веб-интерфейс**: FastAPI с админ-панелью и публичным API
- ✅ **База данных**: PostgreSQL с полной схемой для персистентности
- ✅ **Контейнеризация**: Docker + Nginx для продакшн развертывания
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
├── models.py               # SQLAlchemy модели для БД
├── orchestrator.py         # Главный оркестратор процессов
├── main.py                 # FastAPI приложение
├── api.py                  # API endpoints
├── admin.py                # Админ интерфейс
├── public.py               # Публичные endpoints
├── cli.py                  # CLI интерфейс
├── core/
│   ├── __init__.py
│   ├── cache.py            # Файловый кеш
│   ├── http_client.py      # Async HTTP клиент
│   └── exceptions.py       # Кастомные исключения
├── services/
│   ├── __init__.py
│   ├── ai_client.py        # Constructor KM API клиент
│   ├── source_manager.py   # Управление источниками
│   ├── telegram_service.py # Telegram уведомления
│   ├── telegram_ai.py      # Telegram + AI интеграция
│   ├── telegraph_service.py# Telegraph публикация
│   ├── backup_service.py   # Система бэкапов
│   ├── scheduler.py        # Планировщик задач
│   └── content_extractor.py# Извлечение контента
├── sources/
│   ├── __init__.py
│   ├── base.py             # Базовый класс источника
│   ├── registry.py         # Реестр источников
│   ├── rss_source.py       # RSS источники
│   ├── telegram_source.py  # Telegram источники
│   └── generic_source.py   # Универсальные источники
└── utils/
    ├── __init__.py
    └── html_utils.py       # HTML обработка

db/
└── init.sql               # Полная схема БД (все миграции включены)

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

### 2. База Данных и Персистентность
```python
# PostgreSQL схема для полной персистентности
class Article(Base):
    __tablename__ = 'articles'
    
    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    content = Column(Text)
    summary = Column(Text)
    source_id = Column(Integer, ForeignKey('sources.id'))
    created_at = Column(DateTime, default=datetime.utcnow)
    processed = Column(Boolean, default=False)

class Source(Base):
    __tablename__ = 'sources'
    
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    url = Column(String, nullable=False)
    source_type = Column(String, nullable=False)  # rss, telegram, generic
    is_active = Column(Boolean, default=True)

# Планировщик задач
class ScheduleSettings(Base):
    __tablename__ = 'schedule_settings'
    
    id = Column(Integer, primary_key=True)
    task_name = Column(String, nullable=False)
    enabled = Column(Boolean, default=False)
    schedule_type = Column(String, default='daily')
    hour = Column(Integer, default=9)
    minute = Column(Integer, default=0)
```

### 3. Rate-Limited AI API Integration
```python
# Constructor KM API с соблюдением лимитов
class AIClient:
    def __init__(self, api_key: str, rate_limit: int = 3):
        self.api_key = api_key
        self.rate_limiter = AsyncLimiter(max_rate=rate_limit, time_period=1.0)
    
    async def summarize_text(self, text: str) -> Optional[str]:
        async with self.rate_limiter:
            # Гарантированно не превышаем RPS лимит
            return await self._make_api_request(text)

# Оркестратор для координации всех процессов
class NewsOrchestrator:
    async def process_all_sources(self):
        """Обрабатывает все активные источники параллельно."""
        sources = await self.get_active_sources()
        tasks = [self.process_source(source) for source in sources]
        await asyncio.gather(*tasks, return_exceptions=True)
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
    
    # Legacy API (для совместимости)
    api_endpoint: Optional[str] = None
    api_token: Optional[SecretStr] = None
    api_rate_limit: int = Field(default=3, alias="RPS")
    
    # Telegram
    telegram_token: Optional[SecretStr] = None
    telegram_chat_id: Optional[str] = None
    telegraph_access_token: Optional[str] = None
    
    # Приложение
    log_level: str = "INFO"
    development: bool = False
    max_workers: int = 5
    cache_ttl: int = 86400
    
    class Config:
        env_file = ".env"
        case_sensitive = False
```

### 5. Веб-интерфейс и API
```python
# FastAPI приложение с админ-панелью
@app.get("/admin")
async def admin_dashboard():
    """Админ панель для управления источниками и мониторинга."""
    sources = await get_all_sources()
    stats = await get_processing_stats()
    return templates.TemplateResponse("admin/dashboard.html", {
        "sources": sources,
        "stats": stats
    })

@app.post("/api/sources")
async def create_source(source: SourceCreate):
    """API для создания новых источников."""
    return await create_new_source(source)

# Публичный API для получения новостей
@app.get("/api/feed")
async def get_news_feed(limit: int = 50):
    """Публичный API для получения новостной ленты."""
    return await get_latest_news(limit)
```

## Статус Реализации

### ✅ Полностью Реализовано
1. **Модульная архитектура** - Разделение на core, services, sources
2. **Async обработка** - Все HTTP операции и БД запросы асинхронные
3. **База данных** - PostgreSQL с полной схемой (9 таблиц)
4. **Веб-интерфейс** - FastAPI с админ-панелью и публичным API
5. **Конфигурация** - Pydantic с валидацией и поддержкой .env
6. **Docker контейнеризация** - Полная настройка для продакшн
7. **Система источников** - Plugin-based архитектура (RSS, Telegram, Generic)
8. **Бэкап система** - Автоматические бэкапы БД
9. **Telegraph интеграция** - Публикация в Telegraph
10. **AI интеграция** - Constructor KM API с rate limiting

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
- 🏗️ **Архитектура**: Полная веб-платформа вместо CLI инструмента
- 💾 **Персистентность**: PostgreSQL вместо файлового кеша
- 🌐 **Интерфейс**: Админ-панель + публичный API вместо CLI-only
- 🔌 **Расширяемость**: Plugin система источников (RSS, Telegram, Generic)
- 🔄 **Бэкапы**: Автоматическая система резервных копий
- 📰 **Telegraph**: Интеграция для публикации статей

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