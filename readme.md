# RSS Summarizer

Приложение для сбора и суммаризации RSS-фидов с использованием API суммаризации.

## Особенности

- Сбор и объединение RSS-фидов из различных источников
- Суммаризация статей с использованием API
- Кэширование результатов для оптимизации использования API
- Загрузка результатов в S3-совместимое хранилище
- Уведомления об ошибках через Telegram

## Требования

- Python 3.8+
- Доступ к API суммаризации
- S3-совместимое хранилище (например, AWS S3, Yandex Object Storage)
- Telegram бот (опционально, для уведомлений)

## Установка

1. Клонируйте репозиторий:
```bash
git clone https://github.com/yourusername/rss-summarizer.git
cd rss-summarizer
```

2. Создайте и активируйте виртуальное окружение:
```bash
python -m venv venv
source venv/bin/activate  # На Windows: venv\Scripts\activate
```

3. Установите зависимости:
```bash
pip install -r src/requirements.txt
```

4. Настройте переменные окружения:
```bash
cp src/.env.example src/.env
```

5. Отредактируйте файл `.env`, указав свои значения для всех переменных.

## Конфигурация

Отредактируйте файл `.env` и укажите следующие параметры:

### API настройки
- `endpoint_300`: URL API суммаризации
- `token_300`: Токен авторизации API
- `RPS`: Максимальное количество запросов в секунду к API

### S3 настройки
- `BUCKET_NAME`: Имя бакета S3
- `ENDPOINT_URL`: URL S3-совместимого хранилища
- `ACCESS_KEY`: Ключ доступа
- `SECRET_KEY`: Секретный ключ
- `rss_300_file_name`: Имя файла для сохранения RSS-фида

### Настройки RSS
- `logo_url`: URL логотипа по умолчанию
- `RSS_LINKS`: URL файла со списком RSS-фидов для обработки

### Настройки Telegram
- `TELEGRAM_BOT_TOKEN`: Токен Telegram бота
- `TELEGRAM_CHAT_ID`: ID чата для отправки уведомлений

## Использование

Запустите скрипт суммаризации:

```bash
cd src
python summarization.py
```

## Структура проекта

- `src/summarization.py`: Основной скрипт суммаризации
- `src/shared.py`: Общие функции и утилиты
- `src/requirements.txt`: Зависимости проекта
- `src/.env`: Файл с переменными окружения (не включен в репозиторий)
- `src/.env.example`: Пример файла с переменными окружения

## Логирование

Логи сохраняются в файл `output.log` в корневой директории проекта. Уровень логирования можно настроить в функции `setup_logging()` в файле `summarization.py`.
