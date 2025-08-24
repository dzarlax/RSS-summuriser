# News Aggregator v2.0

Продакшн система агрегации новостей с ИИ-суммаризацией, веб-интерфейсом и базой данных PostgreSQL. Поддерживает множественные категории, автоматические миграции и интеллектуальную экстракцию контента.

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
- [x] **База данных** - PostgreSQL с полной схемой (11 таблиц)
- [x] **Веб-интерфейс** - Админ-панель + публичный API
- [x] **Docker контейнеризация** - dev/prod окружения
- [x] **Система источников** - Plugin архитектура (RSS, Telegram, Generic, Custom)
- [x] **AI интеграция** - Constructor KM API с rate limiting
- [x] **AI-enhanced контент экстракция** - Публикация дат, полные статьи
- [x] **Реклама detection** - ИИ-детекция рекламы в Telegram каналах
- [x] **Telegraph публикация** - Автоматическая публикация статей
- [x] **Backup система** - Автоматические бэкапы БД
- [x] **Async обработка** - Все операции асинхронные
- [x] **CLI интерфейс** - Управление через командную строку
- [x] **Множественные категории** - Поддержка нескольких категорий на статью
- [x] **Автоматические миграции** - Самопроверяющаяся система миграций БД
- [x] **Универсальная система миграций** - Переиспользуемый менеджер миграций
- [x] **Интеллектуальная категоризация** - AI с контекстным анализом и confidence scoring

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

### Ключевые API endpoints
- **GET /api/v1/feed** - Лента новостей с поддержкой множественных категорий
- **GET /api/v1/categories** - Список всех категорий с количеством статей
- **GET /api/v1/migrations/status** - Статус системы миграций
- **POST /api/v1/migrations/run** - Запуск миграций вручную
- **GET /api/v1/sources** - Управление источниками новостей
- **POST /api/v1/process/run** - Запуск обработки новостей

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

# Настройка категорий (опционально)
NEWS_CATEGORIES=Business,Tech,Science,Serbia,Nature,Media,Marketing,Other
DEFAULT_CATEGORY=Other

# Настройки экстракции контента (опционально)
MAX_CONTENT_LENGTH=8000
MIN_CONTENT_LENGTH=200
BROWSER_CONCURRENCY=2
PLAYWRIGHT_TIMEOUT_FIRST_MS=25000
```

### Docker Compose Override
```bash
cp docker-compose.override.yml.example docker-compose.override.yml
# Отредактируйте переменные окружения
```

## 🔍 Методы экстракции статей

Система поддерживает несколько типов источников и методов экстракции контента:

### 🗂️ Типы источников

#### **RSS Sources** (`rss`)
- **Описание**: Стандартные RSS/Atom фиды
- **Экстракция**: Парсинг XML структуры фида
- **Метаданные**: Заголовок, описание, ссылка, дата публикации
- **Пример**: `https://habr.com/rss/`, `https://lenta.ru/rss`

#### **Telegram Sources** (`telegram`)
- **Описание**: Telegram каналы через Bot API
- **Экстракция**: Получение сообщений через Telegram Bot
- **Особенности**: AI-детекция рекламы, обработка медиа
- **Пример**: `https://t.me/tech_news_channel`

#### **Generic Sources** (`reddit`, `twitter`, `news_api`)
- **Описание**: Универсальные источники без автоматической загрузки
- **Экстракция**: Ручное добавление или внешние интеграции
- **Использование**: Для источников, требующих специальной обработки

#### **Custom Sources** (`custom`)
- **Описание**: Мониторинг веб-страниц с настраиваемыми селекторами
- **Экстракция**: Page Monitor с CSS селекторами
- **Особенности**: Отслеживание изменений, снапшоты страниц

### 🧠 AI-Enhanced экстракция контента

#### **Многоуровневая экстракция**
1. **HTML парсинг** - BeautifulSoup + Readability
2. **CSS селекторы** - Schema.org, семантические теги
3. **Playwright браузер** - JavaScript-рендеринг для SPA
4. **AI оптимизация** - Машинное обучение для улучшения селекторов

#### **Поддерживаемые схемы разметки**

##### **Schema.org Microdata**
```html
<article itemtype="http://schema.org/NewsArticle">
  <div itemprop="articleBody">Содержание статьи...</div>
  <time itemprop="datePublished">2024-01-15</time>
</article>
```

##### **JSON-LD Structured Data**
```json
{
  "@context": "https://schema.org",
  "@type": "NewsArticle",
  "articleBody": "Содержание статьи...",
  "datePublished": "2024-01-15"
}
```

##### **Open Graph Protocol**
```html
<meta property="og:title" content="Заголовок статьи" />
<meta property="og:description" content="Описание..." />
<meta property="article:published_time" content="2024-01-15" />
```

##### **Semantic HTML5**
```html
<main>
  <article role="main">
    <header><h1>Заголовок</h1></header>
    <section>Содержание статьи...</section>
    <time datetime="2024-01-15">15 января 2024</time>
  </article>
</main>
```

#### **CSS селекторы по приоритету**

##### **Высокий приоритет** (Schema.org)
- `[itemtype*="Article"] [itemprop="articleBody"]`
- `[itemtype*="NewsArticle"] [itemprop="articleBody"]`
- `[itemtype*="BlogPosting"] [itemprop="articleBody"]`

##### **Средний приоритет** (Семантические теги)
- `article[role="main"]`
- `main article`
- `[role="main"] article`

##### **Современные фреймворки**
- `.prose` (TailwindCSS typography)
- `.container .text-base`
- `[class*="text-"] div:not([class*="nav"])`

##### **Специфичные для русских сайтов**
- `.mb-14` (N+1.ru)
- `.article__text`
- `.news-text`, `.news-content`
- `.material-text`, `.full-text`

##### **CMS паттерны**
- `.entry-content` (WordPress)
- `.post-content`
- `.article-content`
- `.content-body`

#### **Пользовательские парсеры**

##### **BalkanInsight Parser**
- **Домен**: `balkaninsight.com`
- **Селекторы**: Специализированные для структуры сайта
- **Метаданные**: Дата публикации, автор, теги

##### **Расширяемая архитектура**
```python
class CustomParser(BaseCustomParser):
    def can_parse(self, url: str) -> bool:
        return "example.com" in url
    
    def extract_content(self, soup: BeautifulSoup, url: str) -> str:
        return soup.select_one('.custom-content').get_text()
```

### 🤖 AI-сервисы обработки

#### **Комбинированный анализ** (`analyze_article_complete`)
- **Суммаризация**: 2-3 предложения на русском языке
- **Категоризация**: Business, Tech, Science, Serbia, Other + confidence
- **Детекция рекламы**: Heuristics + AI с типизацией
- **Извлечение дат**: Автоматическое определение даты публикации

#### **Специализированные AI-сервисы**

##### **CategorizationAI**
- **Модель**: Настраиваемая через `CATEGORIZATION_MODEL`
- **Категории**: Конфигурируемые через `NEWS_CATEGORIES`
- **Кэширование**: 1 час TTL
- **Fallback**: Категория по умолчанию

##### **TelegramAI**
- **Специализация**: Обработка Telegram контента
- **Особенности**: Детекция медиа, обработка форвардов
- **Интеграция**: С Telegram Bot API

##### **AdDetector**
- **Эвристики**: Регулярные выражения для маркеров рекламы
- **AI уточнение**: Контекстный анализ для спорных случаев
- **Типизация**: `product_promotion`, `service_offer`, `event_promotion`
- **Confidence scoring**: 0.0-1.0 с объяснением решения

#### **Система обучения и оптимизации**

##### **ExtractionMemory**
- **Отслеживание**: Успешность экстракции по доменам
- **Обучение**: Автоматическое улучшение селекторов
- **Статистика**: Качество экстракции, время обработки

##### **DomainStabilityTracker**
- **Мониторинг**: Стабильность доменов во времени
- **Адаптация**: Переключение методов при изменении структуры
- **Предупреждения**: Уведомления о проблемных доменах

##### **AIExtractionOptimizer**
- **Машинное обучение**: Улучшение селекторов на основе успешности
- **A/B тестирование**: Сравнение разных подходов
- **Автоматизация**: Самообучающаяся система

### ⚙️ Конфигурация экстракции

#### **Константы производительности**
```python
MAX_CONTENT_LENGTH = 8000        # Максимальная длина контента
MIN_CONTENT_LENGTH = 200         # Минимальная длина для валидности
BROWSER_CONCURRENCY = 2          # Параллельные браузерные сессии
PLAYWRIGHT_TIMEOUT_FIRST_MS = 25000   # Таймаут первой попытки
PLAYWRIGHT_TOTAL_BUDGET_MS = 90000    # Общий бюджет времени
MIN_QUALITY_SCORE = 30           # Минимальный балл качества
```

#### **Кэширование**
```python
HTML_CACHE_TTL_SECONDS = 300     # Кэш HTML на 5 минут
SELECTOR_CACHE_TTL_SECONDS = 21600 # Кэш селекторов на 6 часов
```

## 📚 Документация

- **CLAUDE.md** - Полная архитектурная документация
- **QUICKSTART.md** - Быстрый старт для разработчиков
- **BACKUP_SYSTEM.md** - Система бэкапов и восстановления
- **MIGRATION_GUIDE.md** - Руководство по миграции данных
- **SYNOLOGY_MIGRATION_GUIDE.md** - Автоматические миграции для Synology
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