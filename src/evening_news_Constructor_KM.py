#!/usr/bin/env python
# coding: utf-8
import datetime
import re
import sys
import argparse
import logging
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

import pandas as pd
import requests
from bs4 import BeautifulSoup
from telegraph import Telegraph

from shared import load_config, send_telegram_message, convert_markdown_to_html

def parse_args():
    parser = argparse.ArgumentParser(description="Ежедневный сбор новостей и рассылка в Telegram")
    parser.add_argument("infra", nargs="?", choices=["prod", "test"], default="prod", help="Environment (prod or test)")
    return parser.parse_args()

def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

API_URL = load_config("CONSTRUCTOR_KM_API")
API_KEY = load_config("CONSTRUCTOR_KM_API_KEY")
model = load_config("MODEL")
session = requests.Session()

def fetch_and_parse_rss_feed(url: str) -> pd.DataFrame:
    try:
        response = session.get(url)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to fetch RSS feed: {e}")
        return pd.DataFrame()
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

    response = session.post(API_URL, json=data, headers=headers)

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
        logging.error(f"API error {response.status_code}: {response.text}")
        return "Error"

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
        logging.debug(f"Processing category: {category}")
        # Используем <h3> для заголовков категорий, т.к. <h2> в списке запрещённых
        content_html += f"<hr><h3>{category}</h3>"

        for _, row in group.iterrows():
            article_title = row['headline']
            # Формирование списка ссылок в <ul>
            # Если есть поле 'links' (список), используем его, иначе - просто 'link'
            if 'links' in row and isinstance(row['links'], list):
                links_list = row['links']
            else:
                links_list = [row['link']]
            links_html = ''.join([f'<a href=https://dzarlax.dev/rss/articles/article.html?link={link}>{urlparse(link).netloc}</a>' for link in links_list])
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

def generate_daily_overview(result):
    # Prepare prompt in Russian
    prompt = (
        "Внимание: твой ответ должен быть строго не длиннее 4000 символов. "
        "Если итоговый текст превышает лимит — сократи его до 4000 символов, сохраняя основные мысли.\n"
        "Сгенерируй краткую сводку новостей на русском языке на основе следующих категорий и заголовков с описаниями:\n\n"
    )
    for category, group in result.groupby('category'):
        prompt += f"\n{category}:\n"
        for _, row in group.iterrows():
            # Get headline
            headline = row.get('headline', '')

            # Get description and truncate to 400 characters if needed
            description = row.get('description', '')

            # Add headline and description to prompt
            prompt += f"- {headline}\n"
            if description:
                prompt += f"  {description}\n"

    prompt += "\nСтрого следи за лимитом: максимум 4000 символов! Используй журналистский стиль."

    overview = process_with_gpt(prompt)
    logging.debug(f"Generated overview:\n{overview}")

    # Ensure the overview doesn't exceed 4000 characters
    if len(overview) > 4000:
        overview = overview[:3997] + "..."

    return overview

def prepare_and_send_message(result, chat_id, telegram_token, telegraph_access_token, service_chat_id):
    # Generate overview in Russian
    daily_overview = generate_daily_overview(result)
    daily_overview_html = convert_markdown_to_html(daily_overview)

    # Create Telegraph page
    telegraph_url = create_telegraph_page_with_library(result, telegraph_access_token)

    # Format message with overview and link
    current_date = datetime.datetime.now().strftime("%d.%m.%Y")
    message = f"📰 Сводка новостей за {current_date}\n\n{daily_overview_html}\n\n🔗 Подробнее: {telegraph_url}"
    logging.info(f"Daily overview:\n{daily_overview}")

    response = send_telegram_message(message, chat_id, telegram_token)
    if isinstance(response, dict) and response.get('ok'):
        send_telegram_message("Сообщение успешно отправлено", service_chat_id, telegram_token)
    else:
        send_telegram_message("Произошла ошибка при отправке", service_chat_id, telegram_token)
    return response

def job():
    global infra
    if infra is None:
        raise ValueError("infra is not defined")
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
    if data.empty:
        logging.info("No news for today")
        return
    data['category'] = generate_summary_batch(
        data['description'],
        batch_size=4
    )
    result = data
    response = prepare_and_send_message(result, chat_id, telegram_token, telegraph_access_token, service_chat_id)

    
if __name__ == "__main__":
    setup_logging()
    args = parse_args()
    infra = args.infra
    logging.info(f"Running in {infra} environment")
    job()
