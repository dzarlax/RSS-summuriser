# RSS Generator

## Описание

RSS Generator - это инструмент для автоматического извлечения, обработки и создания кастомных RSS-лент на основе исходных RSS-лент. Он также включает в себя возможность краткого изложения статей с помощью AI и загрузки итогового RSS на Yandex Cloud Storage.

## Установка

1. Клонируйте репозиторий:

```bash
git clone [URL вашего репозитория]
cd [название папки репозитория]
```

2. Установите зависимости:

```bash
pip install -r requirements.txt
```

## Конфигурация

Перед запуском убедитесь, что вы настроили `config.json` с необходимыми параметрами, такими как `service_account_id`, `key_id`, `ENDPOINT_URL` и другими. Также убедитесь, что у вас есть файл `authorized_key.json` с вашим приватным ключом.

## Запуск

```bash
python main.py
```

После выполнения скрипта результат будет загружен на Yandex Cloud Storage.

## Зависимости

- `jwt`
- `json`
- `time`
- `trafilatura`
- `feedparser`
- `requests`
- `BeautifulSoup4`
- `feedgenerator`
- `boto3`
- `botocore`

## Лицензия

TBD
