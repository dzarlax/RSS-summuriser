# Evening News v2

Автономная система агрегации новостей с AI-суммаризацией, публикацией в Telegram и Telegraph, веб-интерфейсом и базой MariaDB.

## Быстрый старт

### Docker (production)
```bash
cp docker-compose.example.yml docker-compose.yml
# Отредактируйте docker-compose.yml — замените ключи и пароли
docker-compose up -d
```

### Локальная разработка
```bash
pip install -r requirements.txt
cp docker-compose.example.yml docker-compose.dev.yml
# Настройте .env
python -m news_aggregator
```

## Архитектура

```
news_aggregator/
├── api/              # FastAPI роутеры (articles, categories, processing, scheduler,
│                     #   telegram, backup, stats, system, sources, summaries, feed)
├── core/             # HTTP-клиент, кэш, circuit breaker, dead-letter queue
├── extraction/       # Многоуровневое извлечение контента (HTML, CSS, Playwright, AI)
├── migrations/       # Автоматические миграции БД
├── processing/       # AI-процессинг: суммаризация, категоризация, дайджест
├── services/         # Сервисы: AI-клиент, Telegram, Telegraph, бэкапы, планировщик,
│                     #   очередь БД, фильтрация, кэш категорий, мониторинг
├── sources/          # RSS, Telegram, Custom (Page Monitor)
├── telegram/         # Парсинг Telegram-каналов (message_parser, media_extractor)
├── admin.py          # HTML-маршруты админки
├── config.py         # Pydantic Settings (все env vars)
├── orchestrator.py   # Главный оркестратор обработки новостей
└── models.py         # SQLAlchemy модели

web/
├── templates/admin/  # Jinja2 шаблоны: dashboard, sources, summaries, schedule,
│                     #   stats, categories, backup, telegram
└── static/           # CSS, JS
```

**Стек:** FastAPI · SQLAlchemy async · aiomysql · MariaDB · Google Gemini · Jinja2 · Docker

## Конфигурация

### Обязательные переменные
```bash
# База данных
DATABASE_URL=mysql+aiomysql://newsuser:pass@mariadb:3306/newsdb

# Google Gemini
GEMINI_API_KEY=your_gemini_api_key
GEMINI_API_ENDPOINT=https://generativelanguage.googleapis.com/v1/models

# Telegram
TELEGRAM_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_main_channel_id       # Основной канал — дайджесты с новостями
TELEGRAM_SERVICE_CHAT_ID=your_service_id    # Сервисный канал — ошибки и алерты
                                             # (если пусто — используется TELEGRAM_CHAT_ID)
TELEGRAPH_ACCESS_TOKEN=your_telegraph_token

# Админка
ADMIN_USERNAME=admin
ADMIN_PASSWORD=your_secure_password
JWT_SECRET=your_jwt_secret
```

### Дополнительные переменные
```bash
# AI модели
SUMMARIZATION_MODEL=gemini-1.5-flash-latest
CATEGORIZATION_MODEL=gemini-1.5-flash-latest
DIGEST_MODEL=gemini-1.5-pro-latest

# Категории
NEWS_CATEGORIES=Business,Tech,Science,Serbia,Nature,Media,Marketing,Other
DEFAULT_CATEGORY=Other

# Приложение
LOG_LEVEL=INFO
DEVELOPMENT=false
RPS=3                        # Запросов в секунду к AI
MAX_WORKERS=5
CACHE_TTL=86400
CACHE_DIR=/tmp/rss_cache
ALLOW_CREATE_ALL=true        # false в prod после первого запуска

# CORS / Trusted hosts
ALLOWED_ORIGINS=https://your-domain.com,http://localhost:8000
TRUSTED_HOSTS=your-domain.com,localhost

# Планировщик
SCHEDULER_CHECK_INTERVAL_SECONDS=60
SCHEDULER_RESET_EVERY_CHECKS=10
SCHEDULER_STUCK_HOURS=4
SCHEDULER_TASK_TIMEOUT_SECONDS=0   # 0 = без таймаута

# Пул соединений БД
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=10
DB_POOL_TIMEOUT=30

# Ограничение обрабатываемых статей (dev/debug)
NEWS_LIMIT_ENABLED=false
NEWS_LIMIT_MAX_ARTICLES=50
NEWS_LIMIT_PER_SOURCE=50
NEWS_LIMIT_DAYS=1

# Дайджест
DIGEST_TELEGRAM_LIMIT=3600           # Макс. символов для Telegram-сообщения
DIGEST_MAX_ARTICLES_PER_CATEGORY=10
DIGEST_PARALLEL_CATEGORIES=true
```

## API

### Публичный API
| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/public/feed` | Лента новостей (с фильтрацией по категории) |
| GET | `/api/public/article/{id}` | Детали статьи с медиа и AI-категориями |
| GET | `/api/public/search` | Полнотекстовый поиск (q, category, since_hours, sort) |
| GET | `/api/public/categories/config` | Конфиг категорий для UI |

### Админ API (`/api/v1/`)
| Метод | Путь | Описание |
|-------|------|----------|
| GET/POST | `/sources` | Управление источниками |
| POST | `/process/run` | Запустить обработку новостей |
| GET/PUT | `/schedule/settings` | Управление расписанием задач |
| GET | `/telegram/settings` | Текущие настройки Telegram (с источником: db/env/fallback) |
| POST | `/telegram/settings` | Сохранить override каналов в БД |
| POST | `/telegram/test` | Отправить тестовое сообщение в сервисный канал |
| POST | `/telegram/send-digest` | Сгенерировать и отправить дайджест |
| GET | `/categories` | Список категорий со статистикой |
| POST | `/categories` | Создать категорию |
| PUT | `/categories/{id}` | Обновить категорию |
| GET | `/category-mappings/unmapped` | Неразмеченные AI-категории |
| POST/PUT | `/category-mappings` | Управление маппингом AI-категорий |
| GET | `/summaries` | Дневные сводки |
| GET | `/stats/dashboard` | Статистика дашборда |
| GET/POST | `/backup` | Управление резервными копиями |
| GET/POST | `/migrations/status` | Статус и запуск миграций |
| GET/POST | `/system/process-monitor` | Мониторинг и очистка зависших процессов |

### Swagger UI: `http://localhost:8000/docs`

## Источники

### RSS (`rss`)
Стандартные RSS/Atom-ленты. Парсит XML, извлекает title, link, description, дату публикации, изображения из enclosure/media:content.

### Telegram (`telegram`)
Каналы через публичный web-превью (`t.me/channel`). Парсит HTML-страницу канала через BeautifulSoup. Особенности:
- Очистка UI-хрома Telegram (forwarded-from, footer, реакции, кнопки)
- Фильтрация аватаров и служебных изображений
- AI-детекция рекламы (`AdDetector`)
- Попытка получить полный текст из внешней ссылки, если контент < 200 символов

### Custom (`custom`)
Page Monitor с CSS-селекторами — для агрегаторских страниц без RSS.

## Обработка статей (pipeline)

```
1. fetch_from_all_sources()          — HTTP-загрузка по всем источникам
2. save_fetched_articles()           — Сохранение в БД (execute_write)
3. _process_unprocessed_articles()   — AI: суммаризация + категоризация
4. save_results_operation()          — Сохранение результатов в одной транзакции
5. _generate_daily_summaries()       — AI: сводки по категориям
6. send_telegram_digest()            — Публикация дайджеста в Telegram + Telegraph
```

AI-вызовы выполняются вне блокировки очереди БД (read → AI → write).

## Извлечение контента

Многоуровневая стратегия для каждой статьи:
1. **HTML + BeautifulSoup** — семантические теги, Schema.org, JSON-LD, Open Graph
2. **CSS-селекторы** — из `ExtractionMemoryService` (обучается на успешных извлечениях)
3. **Playwright** — для JS-rendered страниц
4. **AI-оптимизация** — генерация новых селекторов для нестандартных сайтов

## Telegram + Telegraph

**Два канала:**
- `TELEGRAM_CHAT_ID` — основной канал, дайджесты с новостями
- `TELEGRAM_SERVICE_CHAT_ID` — сервисный канал, ошибки и системные алерты (fallback на основной)

Channel IDs можно переопределить через UI без перезапуска: `/admin/telegram` → сохраняется в таблицу `settings` БД, перекрывает `.env`.

**Telegraph:** Каждый дайджест публикуется как Telegraph-страница. Структура: оглавление (blockquote) → секции по категориям (h3) → статьи с изображениями (figure/figcaption) или текстом, разделённые `<hr>`.

## Дашборд / Планировщик

Автоматические задачи (`/admin/schedule`):
- **fetch** — загрузка новостей из источников
- **process** — AI-обработка непроцессированных статей
- **digest** — генерация и отправка дайджеста

Каждая задача хранит `next_run`, `last_run`, `is_running`, `enabled`. При включении `next_run` сбрасывается на ближайшее допустимое время.

## Резервные копии

```bash
./scripts/backup.sh             # Создать дамп БД
./scripts/restore.sh <path>     # Восстановить из дампа
```

Также доступно через UI: `/admin/backup`.

## CLI

```bash
python -m news_aggregator.cli process     # Запустить обработку новостей
python -m news_aggregator.cli sources list
python -m news_aggregator.cli sources add --name "Habr" --type rss --url "https://habr.com/rss/"
python -m news_aggregator.cli stats
python -m news_aggregator.cli config      # Проверка конфигурации
```

## Известные ограничения

- Нет тестов (0% coverage)
- Prometheus-метрики подключены частично
- GitHub Actions не адаптированы под текущую архитектуру
