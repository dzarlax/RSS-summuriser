# 🚀 Автоматическая миграция для Synology

## 📋 Обзор

Система автоматической миграции для RSS Summarizer v2 на Synology NAS. Миграция выполняется автоматически при запуске контейнера и не требует ручного вмешательства.

## ✨ Особенности

- **🔍 Автоматическое обнаружение** - система сама определяет нужна ли миграция
- **⚡ Быстрое выполнение** - миграция занимает 10-30 секунд
- **🛡️ Безопасность** - не блокирует запуск приложения при ошибках
- **📊 Мониторинг** - API endpoints для проверки статуса
- **🔄 Идемпотентность** - можно запускать многократно без вреда

## 🎯 Что мигрируется

### Автоматически при старте приложения:
1. **Создание новых таблиц** (`categories`, `article_categories`)
2. **Миграция простых категорий** (`Business`, `Tech`, `Serbia`, etc.)
3. **Обработка составных категорий** (`Business|Tech` → Business + Tech)
4. **Создание индексов** для производительности

### Типы составных категорий:
- `Business|Tech` → Business AND Tech
- `Serbia/Business` → Serbia AND Business  
- `Tech,Science` → Tech AND Science
- `Serbia & Tech` → Serbia AND Tech
- `Business and Science` → Business AND Science

## 🔧 Как это работает

### При запуске контейнера:
```
🔍 Checking for database migrations...
✅ Applied 1 migrations
   - 002_multiple_categories: Add support for multiple categories per article
```

### Логика проверки:
1. Проверяет существование таблиц `categories` и `article_categories`
2. Ищет составные категории в поле `articles.category`
3. Проверяет статьи без связей в `article_categories`
4. Если что-то найдено → запускает миграцию

## 📡 API для мониторинга

### Проверка статуса миграции:
```bash
curl http://localhost:8000/api/v1/migrations/status
```

**Ответ:**
```json
{
  "migration_needed": false,
  "tables_exist": {
    "categories": true,
    "article_categories": true
  },
  "statistics": {
    "articles_with_categories": 837,
    "category_relationships": 822
  },
  "available_migrations": ["002_multiple_categories"]
}
```

### Ручной запуск миграции:
```bash
curl -X POST http://localhost:8000/api/v1/migrations/run
```

## 🚀 Развёртывание на Synology

### Шаг 1: Обновление кода
```bash
# В папке проекта на Synology
git pull origin main
```

### Шаг 2: Перезапуск контейнера
```bash
# Через Docker UI в DSM или командой:
docker compose restart app
```

### Шаг 3: Проверка логов
```bash
# Проверить что миграция выполнилась
docker logs your-app-container --tail 50 | grep -i migration
```

**Ожидаемый вывод:**
```
🔍 Checking for database migrations...
✅ Applied 1 migrations
   - 002_multiple_categories: Add support for multiple categories per article
```

### Шаг 4: Проверка работы
```bash
# Проверить API категорий
curl http://localhost:8000/api/v1/categories

# Проверить статьи с множественными категориями
curl http://localhost:8000/api/v1/feed?limit=1
```

## 📊 Результаты миграции

### До миграции:
```json
{
  "article_id": 123,
  "category": "Business|Tech",  // Проблемная составная категория
  "categories": null
}
```

### После миграции:
```json
{
  "article_id": 123,
  "category": "Business",  // Первая категория (legacy)
  "categories": [
    {
      "name": "Business",
      "display_name": "Бизнес",
      "confidence": 1.0,
      "color": "#28a745"
    },
    {
      "name": "Tech", 
      "display_name": "Технологии",
      "confidence": 1.0,
      "color": "#007bff"
    }
  ]
}
```

## ⚠️ Устранение неполадок

### Проблема: Миграция не запускается
**Решение:**
```bash
# Проверить статус
curl http://localhost:8000/api/v1/migrations/status

# Запустить вручную
curl -X POST http://localhost:8000/api/v1/migrations/run
```

### Проблема: Ошибки в логах
**Решение:**
```bash
# Посмотреть подробные логи
docker logs your-app-container --tail 100

# Проверить подключение к БД
docker exec your-app-container python -c "from news_aggregator.database import AsyncSessionLocal; print('DB OK')"
```

### Проблема: Составные категории остались
**Решение:**
```bash
# Запустить миграцию повторно
curl -X POST http://localhost:8000/api/v1/migrations/run

# Проверить результат
curl http://localhost:8000/api/v1/migrations/status
```

## 🔄 Откат (если нужен)

### Автоматический backup не создаётся
Для Synology рекомендуется создать backup вручную перед обновлением:

```bash
# Создать backup БД
docker exec your-db-container pg_dump -U postgres news_aggregator > backup_$(date +%Y%m%d).sql

# При необходимости отката:
docker exec -i your-db-container psql -U postgres news_aggregator < backup_YYYYMMDD.sql
```

## ✅ Критерии успеха

Миграция успешна если:
- [x] Контейнер запустился без ошибок
- [x] В логах есть сообщение "Applied 1 migrations"
- [x] API `/api/v1/categories` возвращает категории с цветами
- [x] API `/api/v1/feed` включает поле `categories` 
- [x] Веб-интерфейс показывает множественные категории

## 📞 Поддержка

### Полезные команды для диагностики:
```bash
# Статус миграции
curl http://localhost:8000/api/v1/migrations/status

# Проверка категорий
curl http://localhost:8000/api/v1/categories

# Проверка статей
curl "http://localhost:8000/api/v1/feed?limit=1" | jq '.items[0].categories'

# Логи приложения
docker logs your-app-container --tail 50

# Подключение к БД
docker exec -it your-db-container psql -U postgres news_aggregator
```

### SQL запросы для проверки:
```sql
-- Проверить таблицы
\dt

-- Статистика по категориям
SELECT c.display_name, COUNT(ac.article_id) 
FROM categories c 
LEFT JOIN article_categories ac ON c.id = ac.category_id 
GROUP BY c.display_name;

-- Статьи с множественными категориями
SELECT article_id, COUNT(*) as categories_count 
FROM article_categories 
GROUP BY article_id 
HAVING COUNT(*) > 1 
LIMIT 10;
```

---

**Система готова к автоматическому развёртыванию на Synology! 🎉**

**Время миграции:** ~10-30 секунд  
**Downtime:** Только время перезапуска контейнера (~5-10 секунд)  
**Безопасность:** Высокая (не блокирует запуск при ошибках)
