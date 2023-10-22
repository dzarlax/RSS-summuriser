# Стандартные библиотеки
import json
import logging
import time
import tempfile
from datetime import datetime, timedelta

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


# Загрузка конфигурации из JSON-файла
with open('config.json', 'r') as file:
    config = json.load(file)

# Настройте параметры
# iam token
iam_url = config["iam_url"]
service_account_id = config["service_account_id"]
key_id = config["key_id"]
with open("authorized_key.json", 'r') as private:
    data = json.load(private)
    private_key = data['private_key']

# YandexGPT
API_URL = config["API_URL"]
folder_id = config["x-folder-id"]
tokenize_url = config["tokenize_url"]

# S3
ENDPOINT_URL = config["ENDPOINT_URL"]
ACCESS_KEY = config["ACCESS_KEY"]
SECRET_KEY = config["SECRET_KEY"]
BUCKET_NAME = config["BUCKET_NAME"]

# Определите максимальное количество запросов, которое вы хотите выполнять в секунду.
# Например, если API позволяет делать 10 запросов в секунду:
rate_limiter = RateLimiter(max_calls=1, period=1)  # 10 вызовов в 1 секунду

# Инициализация S3 клиента
s3 = boto3.client('s3',
                  endpoint_url=ENDPOINT_URL,
                  aws_access_key_id=ACCESS_KEY,
                  aws_secret_access_key=SECRET_KEY,
                  config=Config(signature_version='s3v4'))

# links
rss_url = config["rss_url"]
logo = config["logo_url"]


def get_iam_api_token(service_account_id, key_id, iam_url, private_key):
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


def count_tokens(text, api_key, model="general"):
    url = tokenize_url
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


def upload_file_to_yandex(file_name, bucket, object_name="feed.xml"):
    if object_name is None:
        object_name = file_name

    s3.upload_file(file_name, bucket, object_name)
    LOGGER.info(f"File {object_name} uploaded to {bucket}/{object_name}.")


def query(payload, api_key):
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


def summarize(text, original_link, api_key):
    if text is None:
        return None

    token_count = count_tokens(text, api_key)

    # Если количество токенов >= 7400, возвращаем оригинальный текст
    if token_count >= 7400:
        return f"{text} <a href='{original_link}'>Читать оригинал</a>"

    payload = {
        "model": "general",
        "instruction_text": "переведи на русский и изложи кратко ",
        "request_text": text,
        "language": "ru"
    }

    output = query(payload, api_key)

    if not output or 'error' in output:
        return None

    return f"{output['result']['alternatives'][0]['text']} <a href='{original_link}'>Читать оригинал</a>"


def extract_image_url(downloaded):
    if downloaded is None:
        LOGGER.error("Error: No content downloaded")
        return logo
    soup = BeautifulSoup(downloaded, 'html.parser')
    im = soup.find("meta", property="og:image")
    return im['content'] if im else logo


def process_entry(entry, two_days_ago, api_key):
    pub_date = datetime.strptime(entry.published, '%a, %d %b %Y %H:%M:%S %z').replace(tzinfo=None)
    if pub_date < two_days_ago:
        return None
    im_url = logo
    downloaded = trafilatura.fetch_url(entry['link'])
    text = trafilatura.extract(downloaded, include_comments=False, include_tables=False)
    if entry['link'].startswith("https://t.me"):
        summary = f"{entry['summary']} <a href='{entry['link']}'>Читать оригинал</a>"
        im_url = extract_image_url(downloaded)
    elif not downloaded:
        summary = f"{entry['summary']} <a href='{entry['link']}'>Читать оригинал</a>"
    else:
        summary = summarize(text, entry['link'], api_key)

        if summary is None:
            summary = f"{entry['summary']} <a href='{entry['link']}'>Читать оригинал</a>"

        im_url = extract_image_url(downloaded)

    if 'youtube' in entry['link']:
        summary = "YouTube Video: " + entry['link']
        im_url = 'None'

    if 'mastodon' in entry['link'] or 'mastadon' in entry.summary:
        summary = "Mastadon Post: " + entry['link']
        im_url = 'None'

    if 'twitter' in entry['link']:
        summary = "Twitter Post: " + entry['link']
        im_url = 'None'

    return {
        'title': entry['title'],
        'link': entry['link'],
        'description': summary,
        'enclosure': Enclosure(im_url, '1234', 'image/jpeg')
    }


def main():
    api_key = get_iam_api_token(service_account_id, key_id, iam_url, private_key)

    in_feed = feedparser.parse(rss_url)
    out_feed = DefaultFeed(
        title="Dzarlax Feed",
        link="http://example.com/rss",
        description="Front Page articles from Dzarlax, summarized with AI"
    )

    two_days_ago = datetime.now().replace(tzinfo=None) - timedelta(days=2)
    # Сортировка записей по времени публикации
    sorted_entries = sorted(in_feed.entries,
                            key=lambda entry: datetime.strptime(entry.published, '%a, %d %b %Y %H:%M:%S %z'),
                            reverse=True)

    for entry in sorted_entries:
        processed = process_entry(entry, two_days_ago, api_key)
        if processed:
            in_feed.add_item(**processed)

    rss = out_feed.writeString('utf-8')

    # Используйте временный файл
    with tempfile.NamedTemporaryFile(suffix=".xml") as temp:
        temp.write(rss.encode('utf-8'))
        upload_file_to_yandex(temp.name, BUCKET_NAME)


if __name__ == "__main__":
    main()
