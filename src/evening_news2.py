#!/usr/bin/env python
# coding: utf-8
import datetime
import sys
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

from openai import OpenAI
import pandas as pd
import requests
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from telegraph import Telegraph

from shared import load_config, send_telegram_message


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


from llama_cpp import Llama


llm = Llama(
  model_path="./Phi3.gguf",  # path to GGUF file
  n_ctx=512,  # The max sequence length to use - note that longer sequence lengths require much more resources
  n_threads=2, # The number of CPU threads to use, tailor to your system and the resulting performance
  n_gpu_layers=0, # The number of layers to offload to GPU, if you have GPU acceleration available. Set to 0 if no GPU acceleration is available on your system.
)

# Simple inference example


def generate_summary_batch(input_texts: list, batch_size: int = 4, ) -> list:
    summaries = []
    for i in range(0, len(input_texts), batch_size):
        batch_texts = input_texts[i:i + batch_size]
        batch_prompts = ["You must use one of the provided categories (Business, Tech, Science, Nature, Serbia, Other) to respond with a single word to the news headline:" + text for text in batch_texts]
        for prompt in batch_prompts:
            summary = process_with_gpt(prompt)
            summaries.append(summary)

    return summaries


def process_with_gpt(prompt):
    output = llm(
        f"<|user|>\n{prompt}<|end|>\n<|assistant|>",
        max_tokens=2,  # Generate up to 256 tokens
        stop=["<|end|>"],
        echo=False,  # Whether to echo the prompt
    )

    summary = (output['choices'][0]['text'])
    print(summary)
    return summary


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


# Подготовка и отправка сообщения
def prepare_and_send_message(result, chat_id, telegram_token, telegraph_access_token, service_chat_id):
    if len(html4tg(result)) <= 4096:
        # Если длина сообщения не превышает 4096 символов, отправляем напрямую через Telegram
        response = send_telegram_message(html4tg(result), chat_id, telegram_token)
        if response.get('ok'):
            send_telegram_message("Сообщение успешно отправлено", service_chat_id, telegram_token)
        else:
            send_telegram_message("Произошла ошибка при отправке", service_chat_id, telegram_token)
    else:
        telegraph_url = create_telegraph_page_with_library(result, telegraph_access_token)
        message = f"{telegraph_url}"
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
    data['category'] = generate_summary_batch(data['headline'].tolist(), batch_size=4)
    result = deduplication(data)
    response = prepare_and_send_message(result, chat_id, telegram_token, telegraph_access_token, service_chat_id)
    print(response)


job()
