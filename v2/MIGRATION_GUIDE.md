# RSS Summarizer v2 - Migration Guide

## 🚀 Перенос сервиса на новый сервер

### Предварительные требования

- **Docker** и **Docker Compose** установлены на новом сервере
- **Git** для клонирования репозитория
- Доступ к файлам текущего сервера

---

## 📦 Метод 1: Полный перенос через backup

### 1. Подготовка на текущем сервере

```bash
cd /path/to/rss-summarizer/v2

# Создание полного бэкапа
make backup

# Проверяем созданные файлы
ls -la backups/
```

Результат: архив `news_aggregator_backup_YYYYMMDD_HHMMSS.tar.gz`

### 2. Копирование на новый сервер

```bash
# Скопировать архив на новый сервер
scp backups/news_aggregator_backup_*.tar.gz user@new-server:/tmp/

# Склонировать код
ssh user@new-server
git clone <your-repository> /path/to/rss-summarizer
cd /path/to/rss-summarizer/v2

# Переместить архив
mv /tmp/news_aggregator_backup_*.tar.gz ./backups/
```

### 3. Восстановление на новом сервере

```bash
# Восстановление из архива
make restore BACKUP=./backups/news_aggregator_backup_*.tar.gz

# Проверка работы
make prod
```

---

## 📤 Метод 2: Миграция только данных

### 1. Экспорт данных на текущем сервере

```bash
cd /path/to/rss-summarizer/v2

# Экспорт базы данных
make export

# Скопировать конфигурацию
cp .env .env.backup
cp docker-compose.yml docker-compose.yml.backup

# Архивировать данные приложения
tar -czf app_data.tar.gz data/ logs/ 2>/dev/null || true
```

### 2. Настройка на новом сервере

```bash
# Склонировать код
git clone <your-repository> /path/to/rss-summarizer
cd /path/to/rss-summarizer/v2

# Скопировать конфигурацию
scp user@old-server:/path/to/.env.backup .env
scp user@old-server:/path/to/docker-compose.yml.backup docker-compose.yml
scp user@old-server:/path/to/exports/migration_*.sql ./exports/
scp user@old-server:/path/to/app_data.tar.gz ./

# Распаковать данные приложения
tar -xzf app_data.tar.gz 2>/dev/null || true

# Запустить сервисы
make prod

# Импорт данных
make import FILE=./exports/migration_*.sql
```

---

## 🗂️ Что сохраняется при переносе

### ✅ **Полностью персистентные данные:**

1. **База данных PostgreSQL**
   - Все статьи с резюме и категориями
   - Источники новостей (RSS, Telegram каналы)
   - Кластеры новостей и дайджесты
   - Настройки расписания обработки

2. **Конфигурация сервиса**
   - Переменные окружения (`.env`)
   - Docker Compose конфигурация
   - Миграции базы данных (`./db/`)

3. **Данные приложения**
   - Логи обработки (`./logs/`)
   - Кеш и временные файлы (`./data/`)
   - Персистентные тома Docker

### ⚙️ **Автоматически восстанавливается:**

- **Источники новостей** - все добавленные Telegram каналы и RSS фиды
- **Категории статей** - Business, Tech, Science, Nature, Serbia, Marketing, Other
- **Расписание обработки** - автоматическая обработка новостей
- **AI настройки** - конфигурация суммаризации и категоризации

---

## 🔄 Автоматизация бэкапов

### Настройка регулярных бэкапов

Добавьте в crontab для ежедневного создания бэкапов:

```bash
crontab -e

# Ежедневный бэкап в 3:00 ночи
0 3 * * * cd /path/to/rss-summarizer/v2 && make backup > /var/log/rss-backup.log 2>&1

# Еженедельная очистка старых бэкапов (старше 30 дней)
0 4 * * 0 cd /path/to/rss-summarizer/v2 && make cleanup-backups
```

### Мониторинг бэкапов

```bash
# Просмотр созданных бэкапов
make list-backups

# Проверка размера базы данных
make db-size

# Проверка Docker томов
make volumes-list
```

---

## 🔍 Проверка после миграции

### 1. Проверка сервисов

```bash
# Статус контейнеров
docker-compose ps

# Логи приложения
make logs

# Доступность веб-интерфейса
curl -I http://localhost:8000
```

### 2. Проверка данных

```bash
# Количество источников
curl -s http://localhost:8000/api/v1/sources | jq '.sources | length'

# Последние статьи
curl -s http://localhost:8000/api/v1/feed?limit=5

# Проверка Telegram источников
make process
```

### 3. Тестирование функций

- **Админ-панель**: http://localhost:8000/admin
- **API документация**: http://localhost:8000/docs
- **Публичная лента**: http://localhost:8000

---

## 🛠️ Troubleshooting

### Проблема: Контейнеры не запускаются

```bash
# Проверить логи
docker-compose logs

# Пересобрать образы
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

### Проблема: База данных не восстанавливается

```bash
# Проверить подключение к PostgreSQL
make db-shell

# Пересоздать базу данных
docker-compose down
docker volume rm v2_postgres_data
docker-compose up -d postgres

# Повторить импорт
make import FILE=./exports/migration_*.sql
```

### Проблема: Telegram источники не работают

```bash
# Проверить доступность Telegram
curl -I https://t.me/s/channelname

# Проверить логи обработки
make logs | grep -i telegram

# Протестировать источник
curl http://localhost:8000/api/v1/sources/1/test
```

---

## 📋 Команды для быстрого переноса

### Упрощенный перенос одной командой

На старом сервере:
```bash
make migration-prepare
```

На новом сервере:
```bash
git clone <repo> rss-summarizer
cd rss-summarizer/v2
make restore BACKUP=backup.tar.gz
```

### Проверка успешного переноса

```bash
# Один скрипт для полной проверки
curl -f http://localhost:8000/api/v1/sources && \
curl -f http://localhost:8000/api/v1/feed?limit=1 && \
echo "✅ Migration successful!" || \
echo "❌ Migration failed!"
```

---

## ⚡ Performance Tips

### После миграции

1. **Оптимизация PostgreSQL**
```bash
docker exec v2-postgres-1 psql -U newsuser -d newsdb -c "VACUUM ANALYZE;"
```

2. **Очистка Docker**
```bash
docker system prune -f
```

3. **Мониторинг ресурсов**
```bash
docker stats
make db-size
```

---

**🎯 Ваш сервис теперь полностью переносим!**

Весь процесс занимает 5-10 минут и гарантирует сохранение всех данных, настроек и работоспособности сервиса на новом сервере. 