import requests
import feedparser
import PyRSS2Gen
import datetime

def generate_aggregated_rss(url):
    # Считывание списка RSS-каналов из файла
    response = requests.get(url)
    rss_urls = response.text.splitlines()

    # Функция для сбора и объединения записей из списка RSS-каналов
    def aggregate_rss_feeds(rss_urls):
        aggregated_entries = []
        for rss_url in rss_urls:
            feed = feedparser.parse(rss_url)
            if feed.entries:
                aggregated_entries.extend(feed.entries)
        return aggregated_entries

    # Получение и объединение данных из RSS-каналов
    aggregated_entries = aggregate_rss_feeds(rss_urls)

    # Создание структуры агрегированной ленты
    aggregated_feed = {
        'feed': {
            'title': 'Aggregated feed',
            'link': 'https://dzarlax.dev',
            'description': 'Агрегированные новости из различных источников',
        },
        'entries': []
    }

    # Добавление каждой записи в структурированный список
    for entry in aggregated_entries:
        aggregated_feed['entries'].append({
            'title': entry.title,
            'link': entry.link,
            'published': entry.published if hasattr(entry, 'published') else 'Дата неизвестна',
            'summary': entry.summary if hasattr(entry, 'summary') else '',
        })

    # Преобразование aggregated_feed в RSS
    rss_items = []
    for entry in aggregated_feed['entries']:
        # Попытка преобразовать дату публикации в объект datetime, если это возможно
        try:
            pubDate = datetime.datetime.strptime(entry['published'], '%Y-%m-%d %H:%M:%S')
        except ValueError:
            pubDate = None
        
        rss_items.append(PyRSS2Gen.RSSItem(
            title = entry['title'],
            link = entry['link'],
            description = entry['summary'],
            pubDate = pubDate
        ))

    rss_feed = PyRSS2Gen.RSS2(
        title = aggregated_feed['feed']['title'],
        link = aggregated_feed['feed']['link'],
        description = aggregated_feed['feed']['description'],
        lastBuildDate = datetime.datetime.now(),
        items = rss_items
    )

    # Сериализация RSS-ленты в строку XML
    return rss_feed.to_xml('utf-8')