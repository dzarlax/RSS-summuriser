# Content Extractor Improvements

## Обзор улучшений

Реализована улучшенная система извлечения контента с множественными стратегиями и fallback механизмами.

## Новые возможности

### 1. **Mozilla Readability Algorithm**
- Использует проверенный алгоритм от Mozilla Firefox
- Лучше определяет основной контент статьи
- Удаляет рекламу и навигационные элементы

### 2. **JavaScript Site Support**
- Поддержка SPA сайтов через Playwright
- Рендеринг JavaScript для динамического контента
- Реалистичная эмуляция браузера

### 3. **Enhanced Content Selectors**
- Schema.org microdata поддержка
- JSON-LD structured data извлечение
- Open Graph meta tags
- Расширенный набор CSS селекторов

### 4. **Content Quality Assessment**
- Оценка качества контента по нескольким метрикам
- Фильтрация низкокачественного контента
- Умная обрезка по границам предложений

### 5. **Fallback Mechanisms**
- 4-уровневая система fallback'ов
- Автоматическое переключение между стратегиями
- Graceful degradation при ошибках

## Архитектура

```
ContentExtractionService
├── EnhancedContentExtractor (primary)
│   ├── Readability Algorithm
│   ├── Enhanced CSS Selectors
│   ├── JavaScript Rendering (Playwright)
│   └── Basic Fallback
└── ContentExtractor (fallback)
    └── Original implementation
```

## Стратегии извлечения (по приоритету)

### 1. **Readability Algorithm**
```python
doc = Document(html)
content = doc.summary()
```

### 2. **Enhanced Selectors**
- Schema.org microdata
- JSON-LD structured data
- Open Graph meta tags
- Улучшенные CSS селекторы

### 3. **JavaScript Rendering**
```python
browser = await playwright.chromium.launch()
page = await browser.new_page()
await page.goto(url)
content = await page.query_selector(selector).inner_text()
```

### 4. **Basic Fallback**
- Оригинальная реализация
- Простые селекторы и эвристики

## Использование

### Базовое использование
```python
from news_aggregator.services.content_integration import get_content_service

# Получить сервис
service = await get_content_service(use_enhanced=True)

# Извлечь контент
content = await service.extract_content(url)
```

### Batch извлечение
```python
urls = ["url1", "url2", "url3"]
results = await service.batch_extract(urls, max_concurrent=5)
```

### Context manager
```python
from news_aggregator.services.content_integration import content_extraction_context

async with content_extraction_context(use_enhanced=True) as service:
    content = await service.extract_content(url)
# Автоматическая очистка ресурсов
```

## Конфигурация

### Environment Variables
```bash
# Включить JavaScript рендеринг (требует больше ресурсов)
ENABLE_JS_RENDERING=true

# Максимальное время ожидания для JS сайтов (секунды)
JS_TIMEOUT=30

# Максимальная длина контента для AI
MAX_CONTENT_LENGTH=8000

# Минимальная длина для качественного контента
MIN_CONTENT_LENGTH=200
```

### Docker Setup
Для поддержки Playwright в Docker нужны дополнительные зависимости:

```dockerfile
# Добавить в Dockerfile
RUN playwright install chromium
RUN playwright install-deps
```

## Метрики качества

### Content Quality Score
- **Длина текста**: 40 баллов за >2000 символов
- **Количество предложений**: 20 баллов за >10 предложений  
- **Количество слов**: 15 баллов за >300 слов
- **Соотношение букв**: 15 баллов за >70% букв
- **Штрафы**: -5 баллов за рекламные паттерны

### Minimum Thresholds
- Минимальная длина: 200 символов
- Минимальный score: 30 баллов
- Минимум значимых слов: 2 для коротких текстов

## Производительность

### Время извлечения (примерное)
- **Readability**: 0.5-2 секунды
- **Enhanced Selectors**: 0.5-2 секунды
- **JavaScript Rendering**: 3-10 секунд
- **Basic Fallback**: 0.3-1 секунда

### Кеширование
- TTL: 24 часа
- Key prefix: `enhanced_article_content`
- Кеширование на уровне URL

## Мониторинг

### Логирование
```python
# Включено по умолчанию
print(f"🔗 Extracting content from URL: {url}")
print(f"⚠️ Readability extraction failed: {error}")
print(f"✅ Content extracted successfully (strategy: readability)")
```

### Статистика
```python
stats = await service.get_extraction_stats()
# {
#   "enhanced_enabled": True,
#   "basic_extractor_active": False,
#   "enhanced_extractor_active": True
# }
```

## Troubleshooting

### Проблемы с JavaScript сайтами
```bash
# Установить Playwright browsers
playwright install

# В Docker - добавить в requirements
playwright>=1.40.0
```

### Проблемы с памятью
```python
# Отключить JavaScript рендеринг
service = await get_content_service(use_enhanced=False)

# Или уменьшить concurrent extractions
results = await service.batch_extract(urls, max_concurrent=2)
```

### Низкое качество извлечения
```python
# Проверить конкретную стратегию
extractor = await get_content_extractor()
content = await extractor._extract_with_readability(url)
```

## Migration Guide

### Переход с старого экстрактора
```python
# Старый способ
from news_aggregator.services.content_extractor import ContentExtractor
extractor = ContentExtractor()
content = await extractor.extract_article_content(url)

# Новый способ
from news_aggregator.services.content_integration import get_content_service
service = await get_content_service()
content = await service.extract_content(url)
```

### Обратная совместимость
Старый экстрактор остается доступным как fallback механизм. При ошибках в новом экстракторе автоматически используется старая реализация.

## Известные ограничения

1. **JavaScript рендеринг**: Требует больше ресурсов и времени
2. **Playwright**: Нужна установка браузеров в Docker
3. **Memory usage**: Увеличенное потребление памяти при JS рендеринге
4. **Rate limiting**: Playwright может быть заблокирован на некоторых сайтах

## Рекомендации

1. **Продакшн**: Включить enhanced экстрактор с fallback
2. **Разработка**: Можно отключить JS рендеринг для экономии ресурсов
3. **Batch processing**: Использовать ограничение concurrent extractions
4. **Мониторинг**: Следить за временем выполнения и success rate