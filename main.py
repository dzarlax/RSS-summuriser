# Стандартные библиотеки
import json
import os
import time
from datetime import datetime, timedelta

# Сторонние библиотеки
import boto3
from botocore.client import Config
import feedparser
from bs4 import BeautifulSoup
import jwt
from feedgenerator import DefaultFeed, Enclosure
import requests
import trafilatura


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

    headers = {
        "Content-Type": "application/json"
    }

    data = {
        "jwt": encoded_token
    }

    response = requests.post(iam_url, headers=headers, json=data)

    if response.status_code == 200:
        result = response.json()
        # Доступ к результату
        return result['iamToken']
    else:
        print("Ошибка при выполнении запроса:", response.status_code, response.text)
        return None


def count_tokens(text, api_key, model="general"):
    url = tokenize_url
    headers = {
        "Content-Type": "application/json",
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


def upload_file_to_yandex(file_name, bucket, object_name=None):
    if object_name is None:
        object_name = file_name

    try:
        s3.upload_file(file_name, bucket, object_name)
        print(f"File {file_name} uploaded to {bucket}/{object_name}.")
    except Exception as e:
        print(f"An error occurred: {e}")


def query(payload, api_key):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "x-folder-id": folder_id
    }
    response = requests.post(API_URL, headers=headers, json=payload)
    if response.status_code != 200:
        print(f"Error with Yandex API: {response.text}")
        return {'error': 'API error'}
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

    time.sleep(1)
    output = query(payload)

    if not output or 'error' in output:
        return None

    return f"{output['result']['alternatives'][0]['text']} <a href='{original_link}'>Читать оригинал</a>"


def fetch_and_parse_feed(url):
    return feedparser.parse(url)


def extract_image_url(downloaded):
    if downloaded is None:
        print("Error: No content downloaded")
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
    summary = None
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

    if api_key is None:
        print("Couldn't get the IAM API token. Exiting.")
        return
    IN_Feed = fetch_and_parse_feed(rss_url)
    Out_Feed = DefaultFeed(
        title="Dzarlax Feed",
        link="http://example.com/rss",
        description="Front Page articles from Dzarlax, summarized with AI"
    )

    two_days_ago = datetime.now().replace(tzinfo=None) - timedelta(days=2)

    for entry in IN_Feed.entries:
        processed = process_entry(entry, two_days_ago, api_key)
        if processed:
            Out_Feed.add_item(**processed)

    rss = Out_Feed.writeString('utf-8')

    with open('feed.xml', 'w') as f:
        f.write(rss)

    upload_file_to_yandex('feed.xml', BUCKET_NAME)
    os.remove('feed.xml')


if __name__ == "__main__":
    main()
