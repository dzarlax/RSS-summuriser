# Стандартные библиотеки
import json
import logging
import tempfile
import time
import threading
import functools
import concurrent.futures
import psutil
import os
from datetime import datetime, timedelta
from dateutil import parser
from typing import Dict, Tuple, List, Optional, Union, Any
from collections import Counter, OrderedDict

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
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

# Загрузка переменных окружения
# В продакшене (GitHub Actions) переменные уже доступны
# В локальной разработке загружаем из .env файла
try:
    from dotenv import load_dotenv
    dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(dotenv_path):
        load_dotenv(dotenv_path)
        print("Environment variables loaded from .env file (local development)")
    else:
        print("No .env file found - assuming production environment (GitHub Actions)")
except ImportError:
    # В продакшене python-dotenv может быть не установлен - это нормально
    print("python-dotenv not available - using system environment variables")

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
try:
    rps_value = load_config("RPS")
    CALLS = int(rps_value)
    print(f"RPS loaded successfully: {CALLS}")
except KeyError as e:
    print(f"Warning: RPS environment variable not found. Using default value 1.")
    print("Available environment variables starting with 'R':", [k for k in os.environ.keys() if k.startswith('R')])
    CALLS = 1  # Значение по умолчанию
except ValueError as e:
    print(f"Warning: RPS value '{rps_value}' is not a valid integer. Using default value 1. Error: {e}")
    CALLS = 1  # Значение по умолчанию

PERIOD = 3

# Оптимизированный LRU кэш
class LRUCache:
    """Оптимизированный LRU кэш с поддержкой TTL."""
    
    def __init__(self, max_size=1000, ttl=86400):
        self.max_size = max_size
        self.ttl = ttl
        self.cache = OrderedDict()
        self.lock = threading.RLock()
    
    def get(self, key):
        """Получить значение из кэша."""
        with self.lock:
            if key not in self.cache:
                return None
            
            value, timestamp = self.cache[key]
            
            # Проверка TTL
            if time.time() - timestamp > self.ttl:
                del self.cache[key]
                return None
            
            # Перемещение в конец (LRU)
            self.cache.move_to_end(key)
            return value
    
    def set(self, key, value):
        """Добавить значение в кэш."""
        with self.lock:
            if key in self.cache:
                # Обновление существующего значения
                self.cache[key] = (value, time.time())
                self.cache.move_to_end(key)
            else:
                # Добавление нового значения
                if len(self.cache) >= self.max_size:
                    # Удаление самого старого элемента
                    self.cache.popitem(last=False)
                
                self.cache[key] = (value, time.time())
    
    def clear(self):
        """Очистить кэш."""
        with self.lock:
            self.cache.clear()
    
    def size(self):
        """Получить текущий размер кэша."""
        with self.lock:
            return len(self.cache)

# Улучшенный класс для кэширования результатов API
class ApiCache(LRUCache):
    """Специализированный кэш для API результатов."""
    
    def __init__(self, max_size=1000, ttl=86400):
        super().__init__(max_size, ttl)
        self.hit_count = 0
        self.miss_count = 0
    
    def get(self, key):
        """Получить значение из кэша с учетом статистики."""
        result = super().get(key)
        if result is not None:
            self.hit_count += 1
        else:
            self.miss_count += 1
        return result
    
    def get_hit_rate(self):
        """Получить коэффициент попаданий в кэш."""
        total = self.hit_count + self.miss_count
        return self.hit_count / total if total > 0 else 0

# Менеджер HTTP соединений
class ConnectionManager:
    """Менеджер HTTP соединений с пулингом и повторными попытками."""
    
    def __init__(self, max_retries=3, backoff_factor=0.3, timeout=30):
        self.session = requests.Session()
        self.timeout = timeout
        
        # Настройка повторных попыток
        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=backoff_factor,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        
        # Настройка адаптеров с пулингом соединений
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=10,
            pool_maxsize=20
        )
        
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
    
    def get(self, url, **kwargs):
        """GET запрос с автоматическими повторными попытками."""
        kwargs.setdefault('timeout', self.timeout)
        return self.session.get(url, **kwargs)
    
    def post(self, url, **kwargs):
        """POST запрос с автоматическими повторными попытками."""
        kwargs.setdefault('timeout', self.timeout)
        return self.session.post(url, **kwargs)
    
    def close(self):
        """Закрыть сессию."""
        self.session.close()

# Мониторинг использования API
class ApiMonitor:
    """Мониторинг использования API."""
    
    def __init__(self, quota_limit=10000):
        self.quota_limit = quota_limit
        self.calls_today = 0
        self.errors = Counter()
        self.response_times = []
        self.last_reset = datetime.now().date()
        self.lock = threading.Lock()
        
    def record_call(self, response_time=None, error=None):
        """Записать информацию о вызове API."""
        with self.lock:
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
        with self.lock:
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

# Класс для мониторинга производительности
class PerformanceMonitor:
    """Мониторинг производительности системы."""
    
    def __init__(self):
        self.start_time = time.time()
        self.start_memory = psutil.Process().memory_info().rss / 1024 / 1024  # MB
        self.checkpoints = []
    
    def add_checkpoint(self, name: str):
        """Добавить контрольную точку."""
        current_time = time.time()
        current_memory = psutil.Process().memory_info().rss / 1024 / 1024  # MB
        
        self.checkpoints.append({
            'name': name,
            'time': current_time - self.start_time,
            'memory': current_memory,
            'memory_delta': current_memory - self.start_memory
        })
        
        LOGGER.info(f"Checkpoint '{name}': {current_time - self.start_time:.2f}s, "
                   f"Memory: {current_memory:.1f}MB (Δ{current_memory - self.start_memory:+.1f}MB)")
    
    def get_report(self) -> Dict[str, Any]:
        """Получить отчет о производительности."""
        total_time = time.time() - self.start_time
        current_memory = psutil.Process().memory_info().rss / 1024 / 1024
        
        return {
            'total_time': total_time,
            'start_memory': self.start_memory,
            'end_memory': current_memory,
            'memory_peak': max(cp['memory'] for cp in self.checkpoints) if self.checkpoints else current_memory,
            'checkpoints': self.checkpoints,
            'system_info': {
                'cpu_percent': psutil.cpu_percent(),
                'memory_percent': psutil.virtual_memory().percent,
                'pid': os.getpid()
            }
        }

# Инициализация глобальных объектов
api_cache = ApiCache()
api_monitor = ApiMonitor()
connection_manager = ConnectionManager()
performance_monitor = PerformanceMonitor()


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
            response = connection_manager.post(
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
    # Проверка кэша для парсинга
    cached_result = api_cache.get(f"parse_{sum_link}")
    if cached_result:
        LOGGER.info(f"Using cached parsing result for: {sum_link}")
        return cached_result
    
    try:
        response = connection_manager.get(sum_link)
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
            h1_text = h1_element.get_text(strip=True)
            result_html += f'<h1>{h1_text}</h1>\n'
        
        # Получаем тезисы
        li_elements = div_element.select('ul.theses li[class*=thesis]')
        if li_elements:
            for li in li_elements:
                thesis_element = li.find('p', class_='thesis-text')
                if thesis_element:
                    li_text = thesis_element.get_text(strip=True)
                    result_html += f'<p>{li_text}</p>\n'
        else:
            LOGGER.warning("No thesis elements found in the summary")
        
        # Кэшировать результат парсинга
        if result_html:
            api_cache.set(f"parse_{sum_link}", result_html)
            
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

def process_entries_batch(entries: List[feedparser.FeedParserDict], days_ago: datetime, 
                         previous_links: List[str], logo: str, endpoint: str, token: str,
                         max_workers: int = 3) -> List[Dict[str, Union[str, Enclosure]]]:
    """
    Пакетная обработка записей RSS с контролируемым параллелизмом.
    
    Args:
        entries (List[feedparser.FeedParserDict]): Список записей RSS
        days_ago (datetime): Дата, раньше которой записи игнорируются
        previous_links (List[str]): Список ссылок из предыдущего фида
        logo (str): URL логотипа по умолчанию
        endpoint (str): Endpoint API суммаризации
        token (str): Токен авторизации API
        max_workers (int): Максимальное количество параллельных потоков
        
    Returns:
        List[Dict[str, Union[str, Enclosure]]]: Список обработанных записей
    """
    processed_entries = []
    
    # Предварительная фильтрация записей
    valid_entries = []
    for entry in entries:
        try:
            # Быстрая проверка даты без парсинга
            if hasattr(entry, 'published'):
                pub_date = parser.parse(entry.published).astimezone(pytz.utc)
                if pub_date >= days_ago and entry.get('link') not in previous_links:
                    valid_entries.append(entry)
        except Exception as e:
            LOGGER.warning(f"Error in preliminary filtering: {e}")
            continue
    
    LOGGER.info(f"Processing {len(valid_entries)} valid entries out of {len(entries)} total")
    
    # Параллельная обработка валидных записей
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_entry = {
            executor.submit(process_entry, entry, days_ago, previous_links, logo, endpoint, token): entry 
            for entry in valid_entries
        }
        
        for future in concurrent.futures.as_completed(future_to_entry):
            entry = future_to_entry[future]
            try:
                result = future.result()
                if result:
                    processed_entries.append(result)
            except Exception as exc:
                LOGGER.error(f"Entry {entry.get('link', 'unknown')} generated an exception: {exc}", exc_info=True)
    
    return processed_entries


def process_single_feed(feed_url: str) -> List[PyRSS2Gen.RSSItem]:
    """
    Обрабатывает один RSS фид.
    
    Args:
        feed_url (str): URL RSS фида
        
    Returns:
        List[PyRSS2Gen.RSSItem]: Список элементов RSS из фида
    """
    items = []
    
    if not feed_url.strip():
        return items
    
    try:
        LOGGER.info(f"Processing feed: {feed_url}")
        feed_response = connection_manager.get(feed_url)
        
        if feed_response.status_code != 200:
            LOGGER.warning(f"Failed to fetch feed {feed_url}: {feed_response.status_code}")
            return items
            
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
    
    return items

def merge_rss_feeds(url: str, max_workers: int = 5) -> List[PyRSS2Gen.RSSItem]:
    """
    Объединяет несколько RSS-фидов в один список элементов с параллельной обработкой.
    
    Args:
        url (str): URL файла со списком URL RSS-фидов
        max_workers (int): Максимальное количество параллельных потоков
        
    Returns:
        List[PyRSS2Gen.RSSItem]: Список элементов RSS
    """
    items = []
    
    try:
        # Получение списка URL
        response = connection_manager.get(url)
        if response.status_code != 200:
            LOGGER.error(f"Failed to fetch RSS list: {response.status_code}")
            return items
            
        urls = [url.strip() for url in response.text.splitlines() if url.strip()]
        LOGGER.info(f"Found {len(urls)} RSS feeds to process")
        
        # Параллельная обработка фидов
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_url = {executor.submit(process_single_feed, feed_url): feed_url for feed_url in urls}
            
            for future in concurrent.futures.as_completed(future_to_url):
                feed_url = future_to_url[future]
                try:
                    feed_items = future.result()
                    items.extend(feed_items)
                    LOGGER.info(f"Successfully processed {len(feed_items)} items from {feed_url}")
                except Exception as exc:
                    LOGGER.error(f"Feed {feed_url} generated an exception: {exc}", exc_info=True)
                
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
        performance_monitor.add_checkpoint("Config loaded")
        LOGGER.info("Configuration loaded successfully")
        
        # Инициализация S3 клиента
        s3 = init_s3_client(config)
        performance_monitor.add_checkpoint("S3 initialized")
        LOGGER.info("S3 client initialized")
        
        # Получение предыдущего фида
        previous_feed, previous_links = get_previous_feed_and_links(
            config["bucket_name"], 
            s3, 
            config["rss_file_name"]
        )
        performance_monitor.add_checkpoint("Previous feed loaded")
        LOGGER.info(f"Previous feed loaded with {len(previous_links)} entries")
        
        # Настройка параметров
        logo = config["logo_url"]
        days_ago = datetime.now(pytz.utc) - timedelta(days=config["days_to_keep"])
        
        # Получение и обработка новых записей
        items = merge_rss_feeds(config["rss_links"])
        performance_monitor.add_checkpoint("RSS feeds merged")
        LOGGER.info(f"Merged RSS feeds, got {len(items)} items")
        
        # Создание нового фида
        rss_string = create_new_rss(items, config).to_xml('utf-8')
        in_feed = feedparser.parse(rss_string)
        performance_monitor.add_checkpoint("New feed created")
        
        # Обработка предыдущих записей
        previous_entries = process_previous_entries(previous_feed, days_ago, logo)
        LOGGER.info(f"Processed {len(previous_entries)} entries from previous feed")
        
        # Сортировка новых записей по времени публикации
        sorted_entries = sorted(
            in_feed.entries,
            key=lambda entry: parser.parse(entry.published),
            reverse=True
        )
        performance_monitor.add_checkpoint("Entries sorted")
        
        # Обработка новых записей с пакетной обработкой
        new_entries = process_entries_batch(
            sorted_entries,
            days_ago,
            previous_links,
            logo,
            config["endpoint_300"],
            config["token_300"],
            max_workers=3  # Ограничиваем количество потоков для API запросов
        )
        performance_monitor.add_checkpoint("New entries processed")
        
        LOGGER.info(f"Processed {len(new_entries)} new entries")
        
        # Создание выходного фида
        rss = create_output_feed(config, previous_entries, new_entries)
        performance_monitor.add_checkpoint("Output feed created")
        
        # Загрузка фида в S3
        with tempfile.NamedTemporaryFile(suffix=".xml") as temp:
            temp.write(rss.encode('utf-8'))
            upload_file_to_yandex(temp.name, config["bucket_name"], s3, config["rss_file_name"])
        performance_monitor.add_checkpoint("Feed uploaded to S3")
        
        # Логирование статистики
        api_monitor.log_stats()
        
        # Логирование статистики кэша
        cache_hit_rate = api_cache.get_hit_rate()
        cache_size = api_cache.size()
        LOGGER.info(f"Cache statistics: Hit rate: {cache_hit_rate:.2%}, Size: {cache_size}")
        
        # Логирование отчета о производительности
        performance_report = performance_monitor.get_report()
        LOGGER.info(f"Performance report: {json.dumps(performance_report, indent=2, default=str)}")
        
        elapsed_time = time.time() - start_time
        LOGGER.info(f"RSS summarization completed successfully in {elapsed_time:.2f} seconds")
        
        # Отправка уведомления об успешном завершении с статистикой
        success_message = (f"✅ RSS обработка завершена успешно за {elapsed_time:.2f}с\n"
                          f"📊 Обработано {len(new_entries)} новых записей\n"
                          f"💾 Кэш: {cache_hit_rate:.1%} попаданий, размер: {cache_size}\n"
                          f"🔧 Память: {performance_report['memory_peak']:.1f}MB пик")
        send_telegram_message(
            success_message, 
            config.get("telegram_token", ""), 
            config.get("telegram_chat_id", "")
        )
        
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
    
    finally:
        # Очистка ресурсов
        try:
            connection_manager.close()
            LOGGER.info("Connection manager closed successfully")
        except Exception as cleanup_error:
            LOGGER.error(f"Error during cleanup: {cleanup_error}")


if __name__ == "__main__":
    main_func()
