# Стандартные библиотеки
import json
import logging
import os
import pytz
import time
import tempfile
from datetime import datetime, timedelta
from typing import Dict, Tuple, List, Optional, Union, Any

# Сторонние библиотеки
import boto3
import feedparser
import jwt
import requests
import trafilatura
from botocore.client import Config
from bs4 import BeautifulSoup
from feedgenerator import DefaultFeed, Enclosure
from ratelimiter import RateLimiter


LOGGER = logging.getLogger(__name__)

# Настройка логгера
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[logging.FileHandler("output.log"), logging.StreamHandler()])


def load_config(key: Optional[str] = None):
    # Получение абсолютного пути к директории, где находится main.py
    current_directory = os.path.dirname(os.path.abspath(__file__))
    # Объединение этого пути с именем файла, который вы хотите открыть
    file_path = os.path.join(current_directory, "config.json")

    with open(file_path, "r") as file:
        config = json.load(file)

    if key:
        if key not in config:
            raise KeyError(f"The key '{key}' was not found in the config file.")
        return config[key]  # Возвращаем значение заданного ключа
    else:
        return config  # Возвращаем весь конфигурационный словарь


# Определите максимальное количество запросов, которое вы хотите выполнять в секунду.
# Например, если API позволяет делать 10 запросов в секунду:
rate_limiter = RateLimiter(max_calls=1, period=1)  # 1 вызов в 1 секунду


def get_iam_api_token() -> str:
    current_directory = os.path.dirname(os.path.abspath(__file__))
    file_path_authorized_key = os.path.join(current_directory, "authorized_key.json")
    with open(file_path_authorized_key, 'r') as private:
        data = json.load(private)
        private_key = data['private_key']
    service_account_id = load_config("service_account_id")
    key_id = load_config("key_id")
    iam_url = load_config("iam_url")
    now = int(time.time())
    payload = {
        'aud': iam_url,
        'iss': service_account_id,
        'iat': now,
        'exp': now + 360
    }

    # Формирование JWT.
    encoded_token = jwt.encode(
        payload,
        private_key,
        algorithm='PS256',
        headers={'kid': key_id}
    )
    data = {
        "jwt": encoded_token
    }

    response = requests.post(iam_url, json=data)

    try:
        response.raise_for_status()
        result = response.json()
        # Доступ к результату
        return result['iamToken']
    except requests.RequestException:
        LOGGER.error(f'Error occurred while requesting an IAM token: {response.status_code}, {response.text}')
        raise


def count_tokens(text: str, api_key: str, folder_id: str) -> int:
    url = load_config("tokenize_url")
    model = load_config("model")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "x-folder-id": folder_id
    }
    data = {
        "model": model,
        "text": text
    }

    response = requests.post(url, headers=headers, json=data)
    response_data = response.json()

    tokens = response_data.get("tokens", [])
    return len(tokens)


def get_previous_feed_and_links(bucket_name: str, s3, object_name) -> Tuple[feedparser.FeedParserDict, List[str]]:

    # Загрузите XML из S3
    obj = s3.get_object(Bucket=bucket_name, Key=object_name)
    previous_rss_content = obj['Body'].read().decode('utf-8')
    parsed_rss = feedparser.parse(previous_rss_content)

    # Верните разобранный RSS и список ссылок
    return parsed_rss, [entry.link for entry in parsed_rss.entries]


def upload_file_to_yandex(file_name: str, bucket: str, s3, object_name) -> None:
    if object_name is None:
        object_name = file_name

    s3.upload_file(file_name, bucket, object_name)
    LOGGER.info(f"File {object_name} uploaded to {bucket}/{object_name}.")


def query(payload: Dict[str, Any], api_key: str, folder_id: str, API_URL: str) -> Dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "x-folder-id": folder_id
    }

    with rate_limiter:
        response = requests.post(API_URL, headers=headers, json=payload)
    if response.status_code != 200:
        LOGGER.error(f"Error with Yandex API: {response.text}")
        return {'error': response.text}
    return response.json()


def summarize(text: Optional[str], original_link: str, api_key: str, folder_id: str, API_URL: str) -> Optional[str]:
    if text is None:
        return None

    token_count = count_tokens(text, api_key, folder_id)

    # Если количество токенов >= 7400, возвращаем оригинальный текст
    if token_count >= 7400:
        return f"{text} <a href='{original_link}'>Читать оригинал</a>"

    payload = {
        "model": "general",
        "instruction_text": "переведи на русский и изложи кратко ",
        "request_text": text,
        "language": "ru"
    }

    output = query(payload, api_key, API_URL, folder_id)

    if not output or 'error' in output:
        return None

        # Добавим проверку на тип перед обращением к элементам словаря
    if isinstance(output, dict) and 'result' in output and 'alternatives' in output['result']:
        return f"{output['result']['alternatives'][0]['text']} <a href='{original_link}'>Читать оригинал</a>"
    return None


def extract_image_url(downloaded: Optional[str], logo: str) -> str:
    if downloaded is None:
        LOGGER.error("Error: No content downloaded")
        return logo
    soup = BeautifulSoup(downloaded, 'html.parser')
    im = soup.find("meta", property="og:image")
    return im['content'] if im else logo


def process_entry(entry: feedparser.FeedParserDict, two_days_ago: datetime, api_key: str, previous_links: List[str], logo: str, tokenize_url: str, API_URL: str) -> Optional[Dict[str, Union[str, Enclosure]]]:
    pub_date = datetime.strptime(entry.published, '%a, %d %b %Y %H:%M:%S %z').astimezone(pytz.utc)
    if pub_date < two_days_ago:
        return None
    im_url: str = logo
    downloaded = trafilatura.fetch_url(entry['link'])
    text = trafilatura.extract(downloaded, include_comments=False, include_tables=False)
    if entry['link'] in previous_links:
        return None
    if entry['link'].startswith("https://t.me"):
        summary = f"{entry['summary']} <a href='{entry['link']}'>Читать оригинал</a>"
        im_url = extract_image_url(downloaded, logo)
    elif not downloaded:
        summary = f"{entry['summary']} <a href='{entry['link']}'>Читать оригинал</a>"
    else:
        summary = summarize(text, entry['link'], api_key, tokenize_url, API_URL)
        if summary is None:
            summary = f"{entry['summary']} <a href='{entry['link']}'>Читать оригинал</a>"

        im_url = extract_image_url(downloaded, logo)

    return {
        'title': entry['title'],
        'link': entry['link'],
        'description': summary,
        'enclosure': Enclosure(im_url, '1234', 'image/jpeg'),
        'pubdate': pub_date
    }


def main() -> None:
    # Настройте параметры, которые используются несколько раз
    # YandexGPT
    API_URL = load_config("API_URL")
    folder_id = load_config("x-folder-id")

    # S3
    BUCKET_NAME = load_config("BUCKET_NAME")
    object_name = load_config("rss_file_name")
    # Инициализация S3 клиента
    s3 = boto3.client('s3',
                      endpoint_url=load_config("ENDPOINT_URL"),
                      aws_access_key_id=load_config("ACCESS_KEY"),
                      aws_secret_access_key=load_config("SECRET_KEY"),
                      config=Config(signature_version='s3v4'))

    # links
    logo = load_config("logo_url")

    api_key = get_iam_api_token()
    previous_feed, previous_links = get_previous_feed_and_links(BUCKET_NAME, s3, object_name)
    in_feed = feedparser.parse(load_config("rss_url"))
    out_feed = DefaultFeed(
        title="Dzarlax Feed",
        link="http://example.com/rss",
        description="Front Page articles from Dzarlax, summarized with AI"
    )
    for entry in previous_feed.entries:
        # Попытка извлечь дату публикации
        pub_date_str = entry.get("published", None)
        if pub_date_str:
            try:
                pub_date_dt = datetime.strptime(pub_date_str, '%a, %d %b %Y %H:%M:%S %z')
            except ValueError:
                pub_date_dt = datetime.strptime(pub_date_str, '%a, %d %b %Y %H:%M:%S')
        else:
            pub_date_dt = None  # или другое значение по умолчанию

        out_feed.add_item(
            title=entry.title,
            link=entry.link,
            description=entry.description,
            enclosure=Enclosure(entry.enclosures[0].href, '1234', 'image/jpeg'),
            pubdate=pub_date_dt
        )
    two_days_ago = datetime.now(pytz.utc) - timedelta(days=2)
    # Сортировка записей по времени публикации
    sorted_entries = sorted(in_feed.entries,
                            key=lambda entry: datetime.strptime(entry.published, '%a, %d %b %Y %H:%M:%S %z'),
                            reverse=True)

    for entry in sorted_entries:
        processed = process_entry(entry, two_days_ago, api_key, previous_links, logo, API_URL, folder_id)
        if processed:
            out_feed.add_item(
            **processed)

    rss = out_feed.writeString('utf-8')

    # Используйте временный файл
    with tempfile.NamedTemporaryFile(suffix=".xml") as temp:
        temp.write(rss.encode('utf-8'))
        upload_file_to_yandex(temp.name, BUCKET_NAME, s3, object_name)


if __name__ == "__main__":
    main()
