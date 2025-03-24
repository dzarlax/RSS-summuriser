# Стандартные библиотеки
import json
import logging
import tempfile
import time
import threading
import functools
from datetime import datetime, timedelta
from dateutil import parser
from typing import Dict, Tuple, List, Optional, Union, Any
from collections import Counter

# Сторонние библиотеки
import boto3
import feedparser
import pytz
import PyRSS2Gen
import requests
from botocore.client import Config
from bs4 import BeautifulSoup
from feedgenerator import DefaultFeed, Enclosure
from ratelimit import limits, sleep_and_retry

from shared import load_config, send_telegram_message

# Настройка логгера
def setup_logging(log_file="../output.log", log_level=logging.INFO):
    """Настройка логирования с более подробной информацией."""
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s'
    )
    
    # Настроить обработчик файла
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(formatter)
    
    # Настроить обработчик консоли
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    
    # Настроить корневой логгер
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Удалить существующие обработчики, чтобы избежать дублирования
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
        
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    # Вернуть логгер для модуля
    logger = logging.getLogger(__name__)
    return logger

LOGGER = setup_logging()

# Определите максимальное количество запросов, которое вы хотите выполнять в секунду.
CALLS = int(load_config("RPS"))
PERIOD = 3

# Класс для кэширования результатов API
class ApiCache:
    """Кэш для результатов API запросов."""
    
    def __init__(self, max_size=1000, ttl=86400):  # TTL = 1 день в секундах
        self.cache = {}
        self.max_size = max_size
        self.ttl = ttl
    
    def get(self, key):
        """Получить значение из кэша."""
        if key not in self.cache:
            return None
        
        value, timestamp = self.cache[key]
        if time.time() - timestamp > self.ttl:
            # Значение устарело
            del self.cache[key]
            return None
            
        return value
    
    def set(self, key, value):
        """Добавить значение в кэш."""
        # Если кэш переполнен, удалить самые старые записи
        if len(self.cache) >= self.max_size:
            oldest_keys = sorted(self.cache.keys(), 
                                key=lambda k: self.cache[k][1])[:len(self.cache) // 10]  # Удалить 10% старых записей
            for old_key in oldest_keys:
                del self.cache[old_key]
        
        self.cache[key] = (value, time.time())
        
    def clear(self):
        """Очистить кэш."""
        self.cache.clear()

# Мониторинг использования API
class ApiMonitor:
    """Мониторинг использования API."""
    
    def __init__(self, quota_limit=10000):
        self.quota_limit = quota_limit
        self.calls_today = 0
        self.errors = Counter()
        self.response_times = []
        self.last_reset = datetime.now().date()
        
    def record_call(self, response_time=None, error=None):
        """Записать информацию о вызове API."""
        # Сбросить счетчики при смене дня
        today = datetime.now().date()
        if today != self.last_reset:
            self.calls_today = 0
            self.last_reset = today
            
        self.calls_today += 1
        
        if response_time is not None:
            self.response_times.append(response_time)
            # Хранить только последние 1000 значений
            if len(self.response_times) > 1000:
                self.response_times.pop(0)
                
        if error:
            self.errors[error] += 1
    
    def get_stats(self):
        """Получить статистику использования API."""
        avg_response_time = sum(self.response_times) / len(self.response_times) if self.response_times else 0
        
        return {
            "calls_today": self.calls_today,
            "quota_remaining": max(0, self.quota_limit - self.calls_today),
            "quota_used_percent": (self.calls_today / self.quota_limit) * 100 if self.quota_limit else 0,
            "avg_response_time": avg_response_time,
            "errors": dict(self.errors),
        }
    
    def log_stats(self, logger=None):
        """Записать статистику в лог."""
        if logger is None:
            logger = LOGGER
            
        stats = self.get_stats()
        logger.info(f"API Stats: {json.dumps(stats, indent=2)}")

# Инициализация глобальных объектов
api_cache = ApiCache()
api_monitor = ApiMonitor()


def get_previous_feed_and_links(bucket_name: str, s3, object_name) -> Tuple[feedparser.FeedParserDict, List[str]]:
    # Загрузите XML из S3
    obj = s3.get_object(Bucket=bucket_name, Key=object_name)
    previous_rss_content = obj['Body'].read().decode('utf-8')
    parsed_rss = feedparser.parse(previous_rss_content)

    # Верните разобранный RSS и список ссылок
    return parsed_rss, [entry.link for entry in parsed_rss.entries]


def is_entry_recent(entry: feedparser.FeedParserDict, days_ago: datetime) -> tuple:
    """Проверяет, что запись была опубликована не позднее, чем два дня назад."""
    pub_date_str = entry.get("published", None)
    if pub_date_str:
        try:
            pub_date_dt = parser.parse(pub_date_str)
            later = pub_date_dt >= days_ago
        except ValueError:
            pub_date_dt = datetime.now(pytz.utc)
            print(pub_date_str)
    else:
        return False, datetime.now(pytz.utc)

    return later, pub_date_dt


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


def adaptive_rate_limit(calls, period, backoff_factor=2, max_backoff=60):
    """Адаптивный декоратор для ограничения частоты запросов."""
    def decorator(func):
        last_calls = []
        lock = threading.Lock()
        
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with lock:
                now = time.time()
                # Удалить устаревшие записы о вызовах
                last_calls[:] = [t for t in last_calls if now - t < period]
                
                if len(last_calls) >= calls:
                    # Превышен лимит вызовов
                    sleep_time = period - (now - last_calls[0])
                    if sleep_time > 0:
                        # Применить экспоненциальную задержку при частых превышениях
                        if len(last_calls) > calls * 1.5:
                            sleep_time = min(sleep_time * backoff_factor, max_backoff)
                        LOGGER.info(f"Rate limit reached. Sleeping for {sleep_time:.2f} seconds")
                        time.sleep(sleep_time)
                
                # Добавить текущий вызов
                last_calls.append(time.time())
                
                return func(*args, **kwargs)
        return wrapper
    return decorator

@adaptive_rate_limit(calls=CALLS, period=PERIOD)
def ya300(link, endpoint, token, max_retries=3):
    """
    Получить суммаризацию статьи через API.
    
    Args:
        link (str): URL статьи для суммаризации
        endpoint (str): Endpoint API
        token (str): Токен авторизации
        max_retries (int, optional): Максимальное количество повторных попыток. По умолчанию 3.
        
    Returns:
        str or None: URL суммаризации или None в случае ошибки
    """
    # Проверка входных параметров
    if not link or not endpoint or not token:
        LOGGER.error("Missing required parameters for API call")
        api_monitor.record_call(error="missing_params")
        return None
    
    # Проверка кэша
    cached_result = api_cache.get(link)
    if cached_result:
        LOGGER.info(f"Using cached result for link: {link}")
        return cached_result
    
    start_time = time.time()
    
    for retry in range(max_retries):
        try:
            LOGGER.info(f"Sending request to endpoint with link: {link} (attempt {retry+1}/{max_retries})")
            response = requests.post(
                endpoint,
                json={'article_url': link},
                headers={'Authorization': f"OAuth {token}"}
            )
            
            response_time = time.time() - start_time
            LOGGER.info(f"Response status code: {response.status_code} (time: {response_time:.2f}s)")
            
            if response.status_code == 200:
                try:
                    response_data = response.json()
                    url = response_data.get("sharing_url")
                    
                    # Кэшировать успешный результат
                    if url:
                        api_cache.set(link, url)
                    
                    api_monitor.record_call(response_time=response_time)
                    return url
                except json.JSONDecodeError as e:
                    LOGGER.error(f"JSONDecodeError in ya300: {e}")
                    api_monitor.record_call(response_time=response_time, error="json_error")
                    if retry < max_retries - 1:
                        continue
                    return None
            elif response.status_code == 429:  # Too Many Requests
                wait_time = min(2 ** retry, 60)  # Экспоненциальная задержка, максимум 60 секунд
                LOGGER.warning(f"Rate limit exceeded. Waiting {wait_time} seconds before retry.")
                api_monitor.record_call(error="rate_limit")
                time.sleep(wait_time)
                continue
            else:
                error_msg = f"API error: {response.status_code}"
                LOGGER.warning(error_msg)
                api_monitor.record_call(response_time=response_time, error=f"http_{response.status_code}")
                
                # Для некоторых ошибок нет смысла повторять запрос
                if response.status_code in [400, 401, 403, 404]:
                    return None
                
                if retry < max_retries - 1:
                    wait_time = min(2 ** retry, 30)
                    LOGGER.info(f"Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                    continue
                
                return None
                
        except requests.exceptions.ConnectionError as e:
            LOGGER.error(f"ConnectionError in ya300: {e}")
            api_monitor.record_call(error="connection_error")
            if retry < max_retries - 1:
                wait_time = min(2 ** retry, 30)
                LOGGER.info(f"Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
            else:
                return None
        except Exception as e:
            LOGGER.error(f"Unexpected error occurred in ya300: {e}", exc_info=True)
            api_monitor.record_call(error="unknown_error")
            return None
    
    return None


def parse_summary_page(sum_link: str) -> Optional[str]:
    """
    Парсит страницу суммаризации и извлекает HTML-контент.
    
    Args:
        sum_link (str): URL страницы с суммаризацией
        
    Returns:
        Optional[str]: HTML-контент суммаризации или None в случае ошибки
    """
    try:
        response = requests.get(sum_link)
        if response.status_code != 200:
            LOGGER.warning(f"Failed to fetch summary page: {response.status_code}")
            return None
            
        webpage = response.content
        soup = BeautifulSoup(webpage, 'html.parser')
        
        # Находим div с классом, содержащим "summary-text"
        div_element = soup.find('div', class_=lambda value: value and 'summary-text' in value)
        if not div_element:
            LOGGER.warning("Summary div not found in the page")
            return None
            
        result_html = ''
        
        # Получаем заголовок
        h1_element = div_element.find('h1', class_='title')
        if h1_element:
            h1_text = h1_element.get_text()
            result_html += f'<h1>{h1_text}</h1>\n'
        
        # Получаем тезисы
        li_elements = div_element.select('ul.theses li[class*=thesis]')
        if li_elements:
            for li in li_elements:
                thesis_element = li.find('p', class_='thesis-text')
                if thesis_element:
                    li_text = thesis_element.get_text()
                    result_html += f'<p>{li_text}</p>\n'
        else:
            LOGGER.warning("No thesis elements found in the summary")
            
        return result_html if result_html else None
        
    except Exception as e:
        LOGGER.error(f"Error parsing summary page: {e}", exc_info=True)
        return None

def process_special_source(entry: feedparser.FeedParserDict, logo: str) -> Tuple[str, str]:
    """
    Обрабатывает записи из специальных источников (Telegram, Radio-T).
    
    Args:
        entry (feedparser.FeedParserDict): Запись RSS
        logo (str): URL логотипа по умолчанию
        
    Returns:
        Tuple[str, str]: (summary, image_url)
    """
    summary = f"{entry['summary']} <a href='{entry['link']}'>Читать оригинал</a>"
    im_url = extract_image_url(entry['summary'], logo)
    return summary, im_url

def process_entry(entry: feedparser.FeedParserDict, days_ago: datetime, previous_links: List[str], logo: str, endpoint,
                  token) -> Optional[Dict[str, Union[str, Enclosure]]]:
    """
    Обрабатывает запись RSS и создает элемент для выходного фида.
    
    Args:
        entry (feedparser.FeedParserDict): Запись RSS
        days_ago (datetime): Дата, раньше которой записи игнорируются
        previous_links (List[str]): Список ссылок из предыдущего фида
        logo (str): URL логотипа по умолчанию
        endpoint (str): Endpoint API суммаризации
        token (str): Токен авторизации API
        
    Returns:
        Optional[Dict[str, Union[str, Enclosure]]]: Данные для добавления в выходной фид или None
    """
    try:
        # Проверка даты публикации
        pub_date = parser.parse(entry.published).astimezone(pytz.utc)
        if pub_date < days_ago:
            return None
            
        # Проверка на дубликаты
        if entry['link'] in previous_links:
            return None
            
        im_url = logo
        summary = ""
        
        # Обработка в зависимости от источника
        if entry['link'].startswith("https://t.me") or entry['link'].startswith("https://radio-t.com"):
            summary, im_url = process_special_source(entry, logo)
        else:
            # Получение суммаризации через API
            sum_link = ya300(entry['link'], endpoint, token)
            LOGGER.info(f"Summarization link: {sum_link}")
            
            if sum_link is None:
                # Если суммаризация не удалась, используем оригинальное описание
                summary = f"{entry['summary']} <a href='{entry['link']}'>Читать оригинал</a>"
            else:
                # Парсинг страницы суммаризации
                result_html = parse_summary_page(sum_link)
                
                if result_html:
                    summary = f"{result_html} <a href='{entry['link']}'>Читать оригинал</a>"
                else:
                    summary = f"{entry['summary']} <a href='{entry['link']}'>Читать оригинал</a>"
                    
            # Извлечение URL изображения
            im_url = extract_image_url(entry['summary'], logo)
        
        # Формирование результата
        return {
            'title': entry['title'],
            'link': entry['link'],
            'description': summary,
            'pubdate': pub_date
        }
        
    except Exception as e:
        LOGGER.error(f"Error processing entry {entry.get('link', 'unknown')}: {e}", exc_info=True)
        return None


def merge_rss_feeds(url: str) -> List[PyRSS2Gen.RSSItem]:
    """
    Объединяет несколько RSS-фидов в один список элементов.
    
    Args:
        url (str): URL файла со списком URL RSS-фидов
        
    Returns:
        List[PyRSS2Gen.RSSItem]: Список элементов RSS
    """
    items = []
    
    try:
        # Получение списка URL
        response = requests.get(url, timeout=30)
        if response.status_code != 200:
            LOGGER.error(f"Failed to fetch RSS list: {response.status_code}")
            return items
            
        urls = response.text.splitlines()
        LOGGER.info(f"Found {len(urls)} RSS feeds to process")
        
        # Обработка каждого URL
        for feed_url in urls:
            if not feed_url.strip():
                continue
                
            try:
                LOGGER.info(f"Processing feed: {feed_url}")
                feed_response = requests.get(feed_url, timeout=30)
                
                if feed_response.status_code != 200:
                    LOGGER.warning(f"Failed to fetch feed {feed_url}: {feed_response.status_code}")
                    continue
                    
                feed = feedparser.parse(feed_response.content)
                
                if feed.bozo:
                    LOGGER.warning(f"Feed {feed_url} has errors: {feed.bozo_exception}")
                
                # Обработка записей
                for entry in feed.entries:
                    try:
                        # Определение даты публикации
                        pub_date = get_entry_date(entry)
                        
                        # Создание элемента RSS
                        item = PyRSS2Gen.RSSItem(
                            title=entry.title if hasattr(entry, "title") else "No title",
                            link=entry.link if hasattr(entry, "link") else "No link",
                            description=entry.description if hasattr(entry, "description") else "No description",
                            guid=PyRSS2Gen.Guid(entry.link if hasattr(entry, "link") else "No link"),
                            pubDate=pub_date
                        )
                        items.append(item)
                    except Exception as entry_error:
                        LOGGER.error(f"Error processing entry in feed {feed_url}: {entry_error}", exc_info=True)
                        continue
                        
                LOGGER.info(f"Processed {len(feed.entries)} entries from {feed_url}")
                
            except requests.exceptions.RequestException as e:
                LOGGER.error(f"Request error for feed {feed_url}: {e}")
            except Exception as e:
                LOGGER.error(f"Error processing feed {feed_url}: {e}", exc_info=True)
                
    except requests.exceptions.RequestException as e:
        LOGGER.error(f"Request error for RSS list URL {url}: {e}")
    except Exception as e:
        LOGGER.error(f"Error merging RSS feeds: {e}", exc_info=True)
        
    LOGGER.info(f"Total items collected: {len(items)}")
    return items

def get_entry_date(entry: feedparser.FeedParserDict) -> datetime:
    """
    Извлекает дату публикации из записи RSS.
    
    Args:
        entry (feedparser.FeedParserDict): Запись RSS
        
    Returns:
        datetime: Дата публикации или текущая дата, если дата не найдена
    """
    try:
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            # Использование структурированной даты
            return datetime(*entry.published_parsed[:6]).replace(tzinfo=pytz.utc)
        elif hasattr(entry, "published"):
            # Парсинг строки даты
            return parser.parse(entry.published).replace(tzinfo=pytz.utc)
        elif hasattr(entry, "pub_date"):
            # Альтернативное поле даты
            return parser.parse(entry.pub_date).replace(tzinfo=pytz.utc)
        elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
            # Использование даты обновления
            return datetime(*entry.updated_parsed[:6]).replace(tzinfo=pytz.utc)
        elif hasattr(entry, "updated"):
            # Парсинг строки даты обновления
            return parser.parse(entry.updated).replace(tzinfo=pytz.utc)
        else:
            # Если дата не найдена, используем текущую
            return datetime.now(pytz.utc)
    except (ValueError, TypeError) as e:
        LOGGER.warning(f"Error parsing date for entry {entry.get('title', 'unknown')}: {e}")
        return datetime.now(pytz.utc)


def create_new_rss(items: List[PyRSS2Gen.RSSItem], config: Optional[Dict[str, Any]] = None) -> PyRSS2Gen.RSS2:
    """
    Создает новый RSS-фид из списка элементов.
    
    Args:
        items (List[PyRSS2Gen.RSSItem]): Список элементов RSS
        config (Optional[Dict[str, Any]]): Конфигурация фида (опционально)
        
    Returns:
        PyRSS2Gen.RSS2: Объект RSS-фида
    """
    if config is None:
        config = {}
        
    # Значения по умолчанию
    title = config.get("feed_title", "Объединенный RSS фид")
    link = config.get("feed_link", "http://example.com/new-feed.xml")
    description = config.get("feed_description", "Новый RSS фид, объединяющий несколько источников.")
    
    # Создание фида
    rss = PyRSS2Gen.RSS2(
        title=title,
        link=link,
        description=description,
        lastBuildDate=datetime.now(pytz.utc),
        items=items,
        # Дополнительные метаданные
        generator=config.get("generator", "RSS Summarizer"),
        docs=config.get("docs", "https://cyber.harvard.edu/rss/rss.html"),
        language=config.get("language", "ru")
    )
    
    return rss


def load_app_config() -> Dict[str, Any]:
    """
    Загрузить конфигурацию приложения из переменных окружения.
    
    Returns:
        Dict[str, Any]: Словарь с конфигурацией приложения
    """
    try:
        config = {
            # API настройки
            "endpoint_300": load_config("endpoint_300"),
            "token_300": load_config("token_300"),
            "api_calls_limit": int(load_config("RPS")),
            "api_period": 3,
            
            # S3 настройки
            "bucket_name": load_config("BUCKET_NAME"),
            "endpoint_url": load_config("ENDPOINT_URL"),
            "access_key": load_config("ACCESS_KEY"),
            "secret_key": load_config("SECRET_KEY"),
            "rss_file_name": load_config("rss_300_file_name"),
            
            # Настройки RSS
            "logo_url": load_config("logo_url"),
            "rss_links": load_config("RSS_LINKS"),
            "days_to_keep": 7,
            
            # Настройки Telegram
            "telegram_token": load_config("TELEGRAM_BOT_TOKEN"),
            "telegram_chat_id": load_config("TELEGRAM_CHAT_ID"),
            
            # Настройки фида
            "feed_title": "Dzarlax Feed",
            "feed_link": "https://s3.dzarlax.dev/feed.rss",
            "feed_description": "Front Page articles from Dzarlax, summarized with AI"
        }
        
        return config
    except KeyError as e:
        LOGGER.error(f"Missing required configuration key: {e}")
        raise
    except Exception as e:
        LOGGER.error(f"Error loading configuration: {e}", exc_info=True)
        raise

def init_s3_client(config: Dict[str, Any]):
    """
    Инициализировать клиент S3.
    
    Args:
        config (Dict[str, Any]): Конфигурация приложения
        
    Returns:
        boto3.client: Клиент S3
    """
    try:
        s3 = boto3.client('s3',
                      endpoint_url=config["endpoint_url"],
                      aws_access_key_id=config["access_key"],
                      aws_secret_access_key=config["secret_key"],
                      config=Config(signature_version='s3v4'))
        return s3
    except Exception as e:
        LOGGER.error(f"Failed to initialize S3 client: {e}", exc_info=True)
        raise

def process_previous_entries(previous_feed, days_ago, logo):
    """
    Обработать записи из предыдущего фида.
    
    Args:
        previous_feed (feedparser.FeedParserDict): Предыдущий фид
        days_ago (datetime): Дата, раньше которой записи игнорируются
        logo (str): URL логотипа по умолчанию
        
    Returns:
        List[Dict]: Список записей для добавления в выходной фид
    """
    entries = []
    
    for entry in previous_feed.entries:
        later, pub_date_dt = is_entry_recent(entry, days_ago)
        if not later:
            continue
            
        # Определение URL изображения
        if 'enclosures' in entry and len(entry.enclosures) > 0:
            # Check if the first enclosure has an 'href' attribute
            if 'href' in entry.enclosures[0]:
                enclosure_href = entry.enclosures[0]['href']
            else:
                enclosure_href = logo  # or some default image URL
        else:
            enclosure_href = logo  # or some default image URL

        entries.append({
            'title': entry.title,
            'link': entry.link,
            'description': entry.description,
            'enclosure': Enclosure(enclosure_href, '1234', 'image/jpeg'),
            'pubdate': pub_date_dt
        })
        
    return entries

def create_output_feed(config, previous_entries, new_entries):
    """
    Создать выходной RSS-фид.
    
    Args:
        config (Dict[str, Any]): Конфигурация приложения
        previous_entries (List[Dict]): Записи из предыдущего фида
        new_entries (List[Dict]): Новые записи
        
    Returns:
        str: RSS-фид в формате XML
    """
    out_feed = DefaultFeed(
        title=config["feed_title"],
        link=config["feed_link"],
        description=config["feed_description"]
    )
    
    # Добавить записи из предыдущего фида
    for entry in previous_entries:
        out_feed.add_item(**entry)
    
    # Добавить новые записи
    for entry in new_entries:
        if entry:  # Проверка на None
            out_feed.add_item(**entry)
    
    return out_feed.writeString('utf-8')

def main_func() -> None:
    """Основная функция приложения."""
    start_time = time.time()
    LOGGER.info("Starting RSS summarization process")
    
    try:
        # Загрузка конфигурации
        config = load_app_config()
        LOGGER.info("Configuration loaded successfully")
        
        # Инициализация S3 клиента
        s3 = init_s3_client(config)
        LOGGER.info("S3 client initialized")
        
        # Получение предыдущего фида
        previous_feed, previous_links = get_previous_feed_and_links(
            config["bucket_name"], 
            s3, 
            config["rss_file_name"]
        )
        LOGGER.info(f"Previous feed loaded with {len(previous_links)} entries")
        
        # Настройка параметров
        logo = config["logo_url"]
        days_ago = datetime.now(pytz.utc) - timedelta(days=config["days_to_keep"])
        
        # Получение и обработка новых записей
        items = merge_rss_feeds(config["rss_links"])
        LOGGER.info(f"Merged RSS feeds, got {len(items)} items")
        
        # Создание нового фида
        rss_string = create_new_rss(items, config).to_xml('utf-8')
        in_feed = feedparser.parse(rss_string)
        
        # Обработка предыдущих записей
        previous_entries = process_previous_entries(previous_feed, days_ago, logo)
        LOGGER.info(f"Processed {len(previous_entries)} entries from previous feed")
        
        # Сортировка новых записей по времени публикации
        sorted_entries = sorted(
            in_feed.entries,
            key=lambda entry: parser.parse(entry.published),
            reverse=True
        )
        
        # Обработка новых записей
        new_entries = []
        for entry in sorted_entries:
            processed = process_entry(
                entry, 
                days_ago, 
                previous_links, 
                logo, 
                config["endpoint_300"], 
                config["token_300"]
            )
            if processed:
                new_entries.append(processed)
        
        LOGGER.info(f"Processed {len(new_entries)} new entries")
        
        # Создание выходного фида
        rss = create_output_feed(config, previous_entries, new_entries)
        
        # Загрузка фида в S3
        with tempfile.NamedTemporaryFile(suffix=".xml") as temp:
            temp.write(rss.encode('utf-8'))
            upload_file_to_yandex(temp.name, config["bucket_name"], s3, config["rss_file_name"])
        
        # Логирование статистики
        api_monitor.log_stats()
        
        elapsed_time = time.time() - start_time
        LOGGER.info(f"RSS summarization completed successfully in {elapsed_time:.2f} seconds")
        
    except KeyError as e:
        error_message = f"Missing configuration key: {e}"
        LOGGER.error(error_message)
        send_telegram_message(
            error_message, 
            config.get("telegram_token", ""), 
            config.get("telegram_chat_id", "")
        )
    except json.JSONDecodeError as e:
        error_message = f"JSON decode error: {e}"
        LOGGER.error(error_message)
        send_telegram_message(
            error_message, 
            config.get("telegram_token", ""), 
            config.get("telegram_chat_id", "")
        )
    except Exception as e:
        error_message = f"Application crashed with error: {e}"
        LOGGER.error(error_message, exc_info=True)
        
        # Попытка отправить уведомление в Telegram
        try:
            send_telegram_message(
                error_message, 
                config.get("telegram_token", ""), 
                config.get("telegram_chat_id", "")
            )
        except Exception as telegram_error:
            LOGGER.error(f"Failed to send Telegram notification: {telegram_error}")


if __name__ == "__main__":
    main_func()
