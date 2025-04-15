#!/usr/bin/env python
# coding: utf-8
import datetime
import re
import sys
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

import pandas as pd
import requests
from bs4 import BeautifulSoup
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from telegraph import Telegraph

from shared import load_config, send_telegram_message, convert_markdown_to_html

API_URL = load_config("CONSTRUCTOR_KM_API")
API_KEY = load_config("CONSTRUCTOR_KM_API_KEY")
model = load_config("MODEL")

if len(sys.argv) > 1:
    # Значение первого аргумента сохраняется в переменную
    infra = sys.argv[1]
    # Теперь вы можете использовать переменную в вашем скрипте
    print(f"Переданное значение переменной: {infra}")
else:
    infra = 'prod'
    print("Аргумент не был передан.")


def fetch_and_parse_rss_feed(url: str) -> pd.DataFrame:
    response = requests.get(url)
    root = ET.fromstring(response.content)
    data = [{'headline': item.find('title').text,
             'link': item.find('link').text,
             'pubDate': datetime.datetime.strptime(item.find('pubDate').text, '%a, %d %b %Y %H:%M:%S %z').date(),
             'description': item.find('description').text} for item in root.findall('.//item')]
    return pd.DataFrame(data)


# Simple inference example

def clean_html(html_text, max_length=1000):
    soup = BeautifulSoup(html_text, "html.parser")
    clean_text = soup.get_text()
    if len(clean_text) > max_length:
        clean_text = clean_text[:max_length]
    return clean_text

def generate_summary_batch(input_texts: list, batch_size: int = 4, ) -> list:
    summaries = []
    for i in range(0, len(input_texts), batch_size):
        batch_texts = input_texts[i:i + batch_size]
        batch_prompts = ["Choose one of the provided categories and answer with one word (Business, Tech, Science, Nature, Serbia, Marketing, Other) for the article:" + clean_html(text) for text in batch_texts]
        for prompt in batch_prompts:
            summary = process_with_gpt(prompt)
            summaries.append(summary)

    return summaries


def process_with_gpt(prompt):
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-KM-AccessKey": API_KEY
    }
    data = {
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "name": "summary_request"
            }
        ],
        "model": model
    }

    response = requests.post(API_URL, json=data, headers=headers)

    if response.status_code == 200:
        response_json = response.json()
        output_text = response_json["choices"][0]["message"]["content"]

        # If generating overview, return full text
        if "Сгенерируйте краткую сводку новостей" in prompt:
            return output_text
        # For category classification, return first word
        else:
            first_word = output_text.split()[0]
            cleaned_first_word = re.sub(r'[^a-zA-Z]', '', first_word)
            return cleaned_first_word
    else:
        print(f"Ошибка API: {response.status_code} - {response.text}")
        return "Error"




def deduplication(data):
    # Вычисление TF-IDF и косинусного сходства
    tfidf_vectorizer = TfidfVectorizer()
    tfidf_matrix = tfidf_vectorizer.fit_transform(data['headline'])
    cosine_sim_matrix = cosine_similarity(tfidf_matrix)

    # Идентификация групп новостей
    threshold = 0.5
    graph = csr_matrix(cosine_sim_matrix > threshold)
    n_components, labels = connected_components(csgraph=graph, directed=False, return_labels=True)
    data['group_id'] = labels

    # Группировка данных по group_id и агрегация ссылок в списки
    links_aggregated = data.groupby('group_id')['link'].apply(list).reset_index()

    # Определение новости с самым длинным заголовком в каждой группе
    longest_headlines = data.loc[data.groupby('group_id')['headline'].apply(lambda x: x.str.len().idxmax())]

    # Объединение результатов, чтобы к каждой новости добавить список ссылок
    result = pd.merge(longest_headlines, links_aggregated, on='group_id', how='left')

    # Переименовываем колонки для ясности
    result.rename(columns={'link_x': 'link', 'link_y': 'links'}, inplace=True)

    # Удаление дубликатов, не включая столбец 'links'
    cols_for_deduplication = [col for col in result.columns if col != 'links']
    result = result.drop_duplicates(subset=cols_for_deduplication)
    return result


def escape_html(text):
    """Заменяет специальные HTML символы на их экранированные эквиваленты."""
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def format_html_telegram(row):
    # Экранирование специальных HTML символов в заголовке
    headline = escape_html(row['headline'])
    # Формирование списка форматированных ссылок для HTML из списка URL
    links_formatted = ['<a href="{0}">{1}</a>'.format('https://dzarlax.dev/rss/articles/article.html?link=' + link, urlparse(link).netloc) for link in row['links']]
    # Формирование строки HTML для заголовка и списка ссылок
    links_html = '\n'.join(links_formatted)
    return f"{headline}\n{links_html}\n"


def html4tg(result):
    # Подготовка сообщения для Telegram с использованием HTML
    html_output_telegram = ""
    for category, group in result.groupby('category'):
        category_html = category.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        html_output_telegram += f"\n\n<b>{category_html}</b>\n\n"
        html_output_telegram += '\n'.join(group.apply(format_html_telegram, axis=1))
    return html_output_telegram


def create_telegraph_page_with_library(result, access_token, author_name="Dzarlax", author_url="https://dzarlax.dev"):
    telegraph = Telegraph(access_token=access_token)
    # Подготовка контента страницы в HTML, используя только разрешенные теги
    content_html = ""
    for category, group in result.groupby('category'):
        # Используем <h3> для заголовков категорий, т.к. <h2> в списке запрещённых
        content_html += f"<hr><h3>{category}</h3>"
        print(category)

        for _, row in group.iterrows():
            article_title = row['headline']
            # Формирование списка ссылок в <ul>
            links_html = ''.join([f'<a href=https://dzarlax.dev/rss/articles/article.html?link={link}>{urlparse(link).netloc}</a>' for link in row['links']])
            # Заголовки статей оборачиваем в <p> и добавляем к ним список ссылок
            content_html += f"<ul><p>{article_title}  {links_html}</p></ul>\n"

    # Создание страницы на Telegra.ph
    response = telegraph.create_page(
        title="Новости за " + str(datetime.datetime.now().date()),
        html_content=content_html,
        author_name=author_name,
        author_url=author_url
    )
    return response['url']


# def generate_daily_overview(result):
#     # Prepare prompt in Russian
#     prompt = """Сгенерируйте краткую сводку новостей (500-4000 символов) на русском языке на основе следующих категорий и заголовков:
#
# """
#     # Add categorized headlines to prompt
#     for category, group in result.groupby('category'):
#         # Translate category names to Russian
#         category_ru = {
#             'Business': '💼 Бизнес',
#             'Tech': '💻 Технологии',
#             'Science': '🔬 Наука',
#             'Nature': '🌿 Природа',
#             'Serbia': '🇷🇸 Сербия',
#             'Marketing': '📊 Маркетинг',
#             'Other': '📌 Другое'
#         }.get(category, category)
#
#         prompt += f"\n{category_ru}:\n"
#         for _, row in group.iterrows():
#             prompt += f"- {row['headline']}\n"
#
#     prompt += "\nСоставьте информативную сводку новостей дня, сохраняя основные темы и ключевые события. Используйте журналистский стиль."
#
#     overview = process_with_gpt(prompt)
#
#     # Ensure the overview doesn't exceed 4000 characters
#     if len(overview) > 4000:
#         overview = overview[:3997] + "..."
#
#     return overview
def generate_daily_overview(result):
    # Prepare prompt in Russian
    prompt = """Сгенерируйте краткую сводку новостей (500-4000 символов) на русском языке на основе следующих категорий и заголовков с описаниями:

"""
    for category, group in result.groupby('category'):
        prompt += f"\n{category}:\n"
        for _, row in group.iterrows():
            # Get headline
            headline = row['headline']

            # Get description and truncate to 400 characters if needed
            description = row.get('description', '')
            # if description:
            #     if len(description) > 400:
            #         description = description[:397] + "..."

            # Add headline and description to prompt
            prompt += f"- {headline}\n"
            if description:
                prompt += f"  {description}\n"

    prompt += "\nСоставьте информативную сводку новостей дня, сохраняя основные темы и ключевые события. Используйте журналистский стиль."

    overview = process_with_gpt(prompt)

    # Ensure the overview doesn't exceed 4000 characters
    if len(overview) > 4000:
        overview = overview[:3997] + "..."

    return overview

# def generate_daily_overview(result):
#     # Prepare prompt with categorized news
#     prompt = "Generate a comprehensive overview of today's news (between 500-4000 characters) based on these categorized headlines:\n\n"
#
#     for category, group in result.groupby('category'):
#         prompt += f"\n{category}:\n"
#         for _, row in group.iterrows():
#             prompt += f"- {row['headline']}\n"
#
#     prompt += "\nFormat the overview as a readable summary with emoji for each category. Keep it informative but concise."
#
#     overview = process_with_gpt(prompt)
#
#     # Ensure the overview doesn't exceed 4000 characters
#     if len(overview) > 4000:
#         overview = overview[:3997] + "..."
#
#     return overview


def prepare_and_send_message(result, chat_id, telegram_token, telegraph_access_token, service_chat_id):
    # Generate overview in Russian
    daily_overview = generate_daily_overview(result)
    daily_overview_html = convert_markdown_to_html(daily_overview)

    # Create Telegraph page
    telegraph_url = create_telegraph_page_with_library(result, telegraph_access_token)

    # Format message with overview and link
    current_date = datetime.datetime.now().strftime("%d.%m.%Y")
    message = f"📰 Сводка новостей за {current_date}\n\n{daily_overview_html}\n\n🔗 Подробнее: {telegraph_url}"

    response = send_telegram_message(message, chat_id, telegram_token)
    if response.get('ok'):
        send_telegram_message("Сообщение успешно отправлено", service_chat_id, telegram_token)
    else:
        send_telegram_message("Произошла ошибка при отправке", service_chat_id, telegram_token)
    return response

def job():
    if infra == 'prod':
        chat_id = load_config("TELEGRAM_CHAT_ID_NEWS")
    elif infra == 'test':
        chat_id = load_config("TELEGRAM_CHAT_ID")

    service_chat_id = load_config("TELEGRAM_CHAT_ID")
    telegram_token = load_config("TELEGRAM_BOT_TOKEN")
    telegraph_access_token = load_config("TELEGRAPH_ACCESS_TOKEN")

    # Получаем данные фида
    data = fetch_and_parse_rss_feed(load_config("feed_url"))

    # Преобразование и фильтрация данных
    data['today'] = datetime.datetime.now().date()
    data = data[data['pubDate'] == data['today']].drop(columns=['today', 'pubDate'])
    data['category'] = generate_summary_batch(
        data['description'],
        batch_size=4
    )
    result = deduplication(data)
    response = prepare_and_send_message(result, chat_id, telegram_token, telegraph_access_token, service_chat_id)
    print(response)


job()
