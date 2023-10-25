# RSS Generator

## Описание

RSS Generator - это инструмент для автоматического извлечения, обработки и создания кастомных RSS-лент на основе исходных RSS-лент, а также включает в себя возможность краткого изложения статей с помощью YandexGPT и загрузки итогового RSS на S3.
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

Перед запуском убедитесь, что вы настроили `config.json` с необходимыми параметрами. Также убедитесь, что у вас есть файл `authorized_key.json` с вашим приватным ключом.
### Конфигурационный файл

```
{
  "service_account_id" : "XXX",
  "key_id" : "XXX",
  "ENDPOINT_URL" : "XXX",
  "ACCESS_KEY" : "XXX",
  "SECRET_KEY" : "XXX",
  "BUCKET_NAME" : "XXX",
  "API_URL" : "XXX",
  "rss_url": "XXX",
  "iam_url": "XXX",
  "x-folder-id": "XXX",
  "logo_url": "XXX",
  "tokenize_url": "XXX",
  "model": "XXX",
  "rss_file_name": "XXX"
}
```
#### 1. `service_account_id`
- Идентификатор учетной записи сервиса. Используется для авторизации сервисного аккаунта.

#### 2. `key_id`
- Уникальный идентификатор ключа, ассоциированный с сервисным аккаунтом.

#### 3. `ENDPOINT_URL`
- URL-адрес эндпоинта для S3.

#### 4. `ACCESS_KEY`
- Ключ доступа для авторизации в S3.

#### 5. `SECRET_KEY`
- Секретный ключ, используемый вместе с `ACCESS_KEY`.

#### 6. `BUCKET_NAME`
- Имя корзины (бакета) в S3.

#### 7. `API_URL`
- URL-адрес эндпоинта API Yandex GPT.

#### 8. `rss_url`
- URL-адрес источника RSS-ленты.

#### 9. `iam_url`
- URL-адрес для IAM аутентификации.

#### 10. `x-folder-id`
- Идентификатор фолдера в Яндекс.Облаке.

#### 11. `logo_url`
- URL-адрес замещающего изображения.

#### 12. `tokenize_url`
- URL-адрес для токенизации текста.

#### 13. `model`
- Идентификатор или название модели.

#### 14. `rss_file_name`
- Имя итогового файла с RSS-лентой.


## Запуск

```bash
python3 main.py
```

После выполнения скрипта результат будет загружен на S3.


## Зависимости

### Стандартные библиотеки:
- datetime 
- json
- logging
- os
- pytz
- tempfile
- time
- typing 

### Сторонние библиотеки:
- boto3
- botocore 
- bs4 
- feedgenerator 
- feedparser
- jwt
- ratelimiter 
- requests
- trafilatura

## Логгер

Логгер настроен так, чтобы записывать информацию в файл `output.log` и выводить её в стандартный поток вывода. Уровень логирования установлен на `INFO`.

## Функции

### `load_config()`

Загружает конфигурационные данные из файла `config.json`. Может возвращать либо значение конкретного ключа, либо весь конфигурационный словарь.

### `get_iam_api_token()`

Получает IAM токен для авторизации.

### `count_tokens()`

Считает количество токенов в тексте.

### `get_previous_feed_and_links()`

Загружает предыдущий RSS-фид и ссылки на статьи из S3.

### `upload_file_to_yandex()`

Загружает файл на S3.

### `query()`

Делает запрос к API YandexGPT.

### `summarize()`

Суммирует и переводит текст на русский язык.

### `extract_image_url()`

Извлекает URL изображения из HTML.

### `process_entry()`

Обрабатывает каждую запись в RSS-фиде.

### `main()`

Главная функция, которая обрабатывает RSS-фид и загружает его в S3.

