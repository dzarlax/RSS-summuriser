# RSS Generator

## Описание

RSS Generator - это инструмент для автоматического извлечения, обработки и создания кастомных RSS-лент на основе исходных RSS-лент. Он также включает в себя возможность краткого изложения статей с помощью AI и загрузки итогового RSS на Yandex Cloud Storage.

## Установка

1. Клонируйте репозиторий:

```bash
git clone https://github.com/dzarlax/RSS-summuriser.git
cd RSS-summuriser
```

2. Создайте и активируйте виртуальное окружение:

```bash
python3 -m venv rss
source rss/bin/activate  # Для Windows: .\rss\Scripts\activate
 ```

3. Установите зависимости:

```bash
pip3 install -r requirements.txt
```

## Конфигурация

Перед запуском убедитесь, что вы настроили `config.json` с необходимыми параметрами, такими как `service_account_id`, `key_id`, `ENDPOINT_URL` и другими. Также убедитесь, что у вас есть файл `authorized_key.json` с вашим приватным ключом.

## Запуск

```bash
python3 main.py
```

После выполнения скрипта результат будет загружен на Yandex Cloud Storage.




## Лицензия

TBD
