# Стандартные библиотеки
import html
import json
import logging
import os
import pytz
import tempfile
from datetime import datetime, timedelta
from typing import Dict, Tuple, List, Optional, Union
# Сторонние библиотеки
import boto3
import feedparser
import requests
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


def send_telegram_message(message):
    # Place your Telegram bot's API token here
    TELEGRAM_TOKEN = load_config("TELEGRAM_BOT_TOKEN")
    # Place your own Telegram user ID here
    TELEGRAM_CHAT_ID = load_config("TELEGRAM_CHAT_ID")
    send_message_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }
    response = requests.post(send_message_url, data=data)
    return response.json()


# Определите максимальное количество запросов, которое вы хотите выполнять в секунду.
# Например, если API позволяет делать 10 запросов в секунду:
rate_limiter = RateLimiter(max_calls=int(load_config("RPS")), period=3)  # 1 вызов в 1 секунду


def get_previous_feed_and_links(bucket_name: str, s3, object_name) -> Tuple[feedparser.FeedParserDict, List[str]]:

    # Загрузите XML из S3
    obj = s3.get_object(Bucket=bucket_name, Key=object_name)
    previous_rss_content = obj['Body'].read().decode('utf-8')
    parsed_rss = feedparser.parse(previous_rss_content)

    # Верните разобранный RSS и список ссылок
    return parsed_rss, [entry.link for entry in parsed_rss.entries]


def is_entry_recent(entry: feedparser.FeedParserDict, two_days_ago: datetime) -> bool:
    """Проверяет, что запись была опубликована не позднее, чем два дня назад."""
    pub_date_str = entry.get("published", None)
    if pub_date_str:
        try:
            pub_date_dt = datetime.strptime(pub_date_str, '%a, %d %b %Y %H:%M:%S %z')
        except ValueError:
            pub_date_dt = datetime.strptime(pub_date_str, '%a, %d %b %Y %H:%M:%S')
    else:
        return False

    return pub_date_dt >= two_days_ago


def upload_file_to_yandex(file_name: str, bucket: str, s3, object_name) -> None:
    if object_name is None:
        object_name = file_name

    s3.upload_file(file_name, bucket, object_name)
    LOGGER.info(f"File {object_name} uploaded to {bucket}/{object_name}.")


def extract_image_url(summary: Optional[str], logo: str) -> str:
    if summary is None:
        LOGGER.error("Error: No content downloaded")
        return logo
    soup = BeautifulSoup(summary, features="html.parser")
    image_tag = soup.find('img')
    if image_tag and 'src' in image_tag.attrs:
        image_url = image_tag['src']
    else:
        image_url = logo
    return image_url


def ya300(link, endpoint, token):
    url = None
    try:
        LOGGER.info(f"Sending request to endpoint with link: {link}")
        response = requests.post(
            endpoint,
            json={'article_url': link},
            headers={'Authorization': f"OAuth {token}"}
        )
        LOGGER.info(f"Response: {response}")
        LOGGER.info(f"Response text: {response.text}")
        LOGGER.info(f"Response status code: {response.status_code}")
        if response.status_code == 200:
            response_data = response.json()
            url = response_data.get("sharing_url")
        else:
            LOGGER.warning(f"Received non-200 response: {response.status_code}")
        return url
    except json.JSONDecodeError as e:
        LOGGER.error(f"JSONDecodeError in ya300: {e}")
        LOGGER.error("Invalid JSON content received.")
    except requests.exceptions.ConnectionError as e:
        LOGGER.error(f"ConnectionError in ya300: {e}")
    except Exception as e:
        LOGGER.error(f"Unexpected error occurred in ya300: {e}")
        raise  # It's usually not a good practice to raise an exception after logging in a catch-all except block.
    return None  # T


def process_entry(entry: feedparser.FeedParserDict, two_days_ago: datetime, previous_links: List[str], logo: str, endpoint, token) -> Optional[Dict[str, Union[str, Enclosure]]]:
    pub_date = datetime.strptime(entry.published, '%a, %d %b %Y %H:%M:%S %z').astimezone(pytz.utc)
    if pub_date < two_days_ago:
        return None
    im_url: str = logo
    if entry['link'] in previous_links:
        return None
    if entry['link'].startswith("https://t.me"):
        summary = f"{entry['summary']} <a href='{entry['link']}'>Читать оригинал</a>"
        im_url = extract_image_url(entry['summary'], logo)
    elif entry['link'].startswith("https://radio-t.com"):
        summary = f"{entry['summary']} <a href='{entry['link']}'>Читать оригинал</a>"
        im_url = extract_image_url(entry['summary'], logo)
    else:
        with rate_limiter:
            sum_link = ya300(entry['link'], endpoint, token)
            LOGGER.info(sum_link)
            if sum_link is None:
                summary = f"{entry['summary']} <a href='{entry['link']}'>Читать оригинал</a>"
            else:
                response = requests.get(sum_link)
                LOGGER.info(response)
                webpage = response.content
                soup = BeautifulSoup(webpage, 'html.parser')
                summary_div = soup.find(lambda tag: tag.name == "div" and "class" in tag.attrs and any(
                    cls.startswith("summary-text") for cls in tag["class"]))
                if summary_div:
                    LOGGER.info(summary_div)
                    div_element = soup.find('div', class_=lambda value: value and 'summary-text' in value)
                    result_html = ''
                    if div_element:
                        # Получаем заголовок из элемента <h1> и добавляем его в итоговый HTML текст
                        h1_text = div_element.find('h1', class_='title').get_text()
                        result_html += f'<h1>{h1_text}</h1>\n'

                        # Итерируемся по элементам <li> с классами, содержащими "thesis"
                        li_elements = div_element.select('ul.theses li[class*=thesis]')
                        for li in li_elements:
                            # Получаем текст из элемента <li>
                            li_text = li.find('p', class_='thesis-text').get_text()
                            # Добавляем текст в итоговый HTML с тегом <h1>
                            result_html += f'<p>{li_text}</p>\n'
                    else:
                        # Если элемент <ul> не найден, выводим сообщение об ошибке или делаем необходимые действия
                        print("Элемент <ul> с классом 'theses svelte-91sedu' не найден в HTML тексте.")
                    LOGGER.info(result_html)
                    summary = f"{result_html} <a href='{entry['link']}'>Читать оригинал</a>"
                else:
                    summary = f"{entry['summary']} <a href='{entry['link']}'>Читать оригинал</a>"
        im_url = extract_image_url(entry['summary'], logo)
    if im_url == logo:
        return {
            'title': entry['title'],
            'link': entry['link'],
            'description': summary,
            'pubdate': pub_date
        }
    else:
        return {
            'title': entry['title'],
            'link': entry['link'],
            'description': summary,
            'pubdate': pub_date
        }


def main_func() -> None:
    try:
        # Настройте параметры, которые используются несколько раз
        endpoint = load_config("endpoint_300")
        token = load_config("token_300")
        # S3
        BUCKET_NAME = load_config("BUCKET_NAME")
        object_name = load_config("rss_300_file_name")
        # Инициализация S3 клиента
        s3 = boto3.client('s3',
                          endpoint_url=load_config("ENDPOINT_URL"),
                          aws_access_key_id=load_config("ACCESS_KEY"),
                          aws_secret_access_key=load_config("SECRET_KEY"),
                          config=Config(signature_version='s3v4'))

        # links
        logo = load_config("logo_url")
        two_days_ago = datetime.now(pytz.utc) - timedelta(days=2)
        previous_feed, previous_links = get_previous_feed_and_links(BUCKET_NAME, s3, object_name)
        in_feed = feedparser.parse(load_config("rss_url"))
        out_feed = DefaultFeed(
            title="Dzarlax Feed",
            link="https://s3.dzarlax.dev/feed.rss",
            description="Front Page articles from Dzarlax, summarized with AI"
        )
        for entry in previous_feed.entries:
            if is_entry_recent(entry, two_days_ago):
                # Попытка извлечь дату публикации
                pub_date_str = entry.get("published", None)
                if pub_date_str:
                    try:
                        pub_date_dt = datetime.strptime(pub_date_str, '%a, %d %b %Y %H:%M:%S %z')
                    except ValueError:
                        pub_date_dt = datetime.strptime(pub_date_str, '%a, %d %b %Y %H:%M:%S')
                else:
                    pub_date_dt = None  # или другое значение по умолчанию
                # Check if 'enclosures' exists and has at least one item
                if 'enclosures' in entry and len(entry.enclosures) > 0:
                    # Check if the first enclosure has an 'href' attribute
                    if 'href' in entry.enclosures[0]:
                        enclosure_href = entry.enclosures[0]['href']
                    else:
                        enclosure_href = logo  # or some default image URL
                else:
                    enclosure_href = logo  # or some default image URL

                out_feed.add_item(
                    title=entry.title,
                    link=entry.link,
                    description=entry.description,
                    enclosure=Enclosure(enclosure_href, '1234', 'image/jpeg'),
                    pubdate=pub_date_dt
                )
        # Сортировка записей по времени публикации
        sorted_entries = sorted(in_feed.entries,
                                key=lambda entry: datetime.strptime(entry.published, '%a, %d %b %Y %H:%M:%S %z'),
                                reverse=True)

        for entry in sorted_entries:
            processed = process_entry(entry, two_days_ago, previous_links, logo, endpoint, token)
            if processed:
                out_feed.add_item(
                **processed)

        rss = out_feed.writeString('utf-8')

        # Используйте временный файл
        with tempfile.NamedTemporaryFile(suffix=".xml") as temp:
            temp.write(rss.encode('utf-8'))
            upload_file_to_yandex(temp.name, BUCKET_NAME, s3, object_name)
        pass
    except Exception as e:
        error_message = f"Application crashed with error: {e}"
        print(error_message)
        send_telegram_message(error_message)
    except json.JSONDecodeError as e:
        LOGGER.error(f"JSONDecodeError в main: {e}")
        LOGGER.error(f"Получен недопустимый JSON контент.")
    except Exception as e:
        LOGGER.error(f"Произошла непредвиденная ошибка: {e}")
        raise


if __name__ == "__main__":
    main_func()
