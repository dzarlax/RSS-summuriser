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
from dotenv import load_dotenv
import os
import pathlib

# Явно указываем путь к .env относительно текущего файла
dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
print(f"DEBUG: .env path: {dotenv_path}, exists: {os.path.exists(dotenv_path)}")
load_dotenv(dotenv_path=dotenv_path, override=False)


from shared import load_config, send_telegram_message, convert_markdown_to_html

# Load configuration safely
def load_config_safe(key: str, default=None):
    """Safely load configuration with fallback"""
    try:
        return load_config(key)
    except KeyError as e:
        if default is not None:
            logging.warning(f"Using default value for {key}: {default}")
            return default
        raise e

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

# Initialize global variables
API_URL = None
API_KEY = None
model = None
session = requests.Session()

def init_config():
    """Initialize configuration - called at runtime"""
    global API_URL, API_KEY, model
    API_URL = load_config("CONSTRUCTOR_KM_API")
    API_KEY = load_config("CONSTRUCTOR_KM_API_KEY")
    model = load_config("MODEL")
    
    # Configure session with timeout and retry settings
    session.mount('http://', requests.adapters.HTTPAdapter(max_retries=3))
    session.mount('https://', requests.adapters.HTTPAdapter(max_retries=3))

def fetch_and_parse_rss_feed(url: str) -> pd.DataFrame:
    """
    Fetch and parse RSS feed with improved error handling
    """
    try:
        logging.info(f"Fetching RSS feed from: {url}")
        response = session.get(url, timeout=30)
        response.raise_for_status()
        
        if not response.content:
            logging.warning("Empty RSS feed content received")
            return pd.DataFrame()
            
        logging.info(f"RSS feed fetched successfully, size: {len(response.content)} bytes")
        
    except requests.exceptions.Timeout:
        logging.error("RSS feed request timed out")
        return pd.DataFrame()
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to fetch RSS feed: {e}")
        return pd.DataFrame()
    
    try:
        root = ET.fromstring(response.content)
    except ET.ParseError as e:
        logging.error(f"Failed to parse RSS XML: {e}")
        return pd.DataFrame()

    # Extract data with better error handling
    data = []
    items = root.findall('.//item')
    logging.info(f"Found {len(items)} items in RSS feed")
    
    for i, item in enumerate(items):
        try:
            # Extract title safely
            title_elem = item.find('title')
            title = title_elem.text if title_elem is not None and title_elem.text else f"No title {i+1}"
            
            # Extract link safely
            link_elem = item.find('link')
            link = link_elem.text if link_elem is not None and link_elem.text else ""
            
            # Extract description safely
            desc_elem = item.find('description')
            description = desc_elem.text if desc_elem is not None and desc_elem.text else ""
            
            # Extract and parse date safely
            date_elem = item.find('pubDate')
            if date_elem is not None and date_elem.text:
                try:
                    pub_date = datetime.datetime.strptime(date_elem.text, '%a, %d %b %Y %H:%M:%S %z').date()
                except ValueError as date_err:
                    logging.warning(f"Failed to parse date '{date_elem.text}' for item {i+1}: {date_err}")
                    pub_date = datetime.datetime.now().date()
            else:
                logging.warning(f"No date found for item {i+1}, using current date")
                pub_date = datetime.datetime.now().date()
            
            # Only add item if we have at least title and link
            if title and link:
                data.append({
                    'headline': title,
                    'link': link,
                    'pubDate': pub_date,
                    'description': description
                })
            else:
                logging.warning(f"Skipping item {i+1}: missing title or link")
                
        except Exception as e:
            logging.warning(f"Error processing RSS item {i+1}: {e}")
            continue
    
    logging.info(f"Successfully parsed {len(data)} valid items from RSS feed")
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
        if "Сгенерируй краткую сводку новостей" in prompt or "Сгенерируйте краткую сводку новостей" in prompt:
            return output_text
        # For category classification, return first word
        else:
            first_word = output_text.split()[0]
            cleaned_first_word = re.sub(r'[^a-zA-Z]', '', first_word)
            return cleaned_first_word
    else:
        logging.error(f"API error {response.status_code}: {response.text}")
        logging.info(f"API response status: {response.status_code}")
        logging.info(f"API response text: {response.text}")
        return "Error"

def escape_html(text):
    """Заменяет специальные HTML символы на их экранированные эквиваленты."""
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

def sanitize_html_for_telegraph(html_content):
    """
    Removes HTML tags that are not allowed by Telegraph API.
    Telegraph allows: a, aside, b, blockquote, br, code, em, figcaption, figure, h3, h4, hr, i, iframe, img, li, ol, p, pre, s, strong, u, ul, video
    """
    if not html_content or not isinstance(html_content, str):
        return html_content or ""
    
    # If it's plain text, return as is
    if '<' not in html_content:
        return html_content
    
    try:
        # List of tags that are NOT allowed by Telegraph
        forbidden_tags = [
            'blink', 'marquee', 'script', 'style', 'meta', 'link', 'head', 'title', 
            'body', 'html', 'div', 'span', 'table', 'tr', 'td', 'th', 'tbody', 'thead',
            'h1', 'h2', 'h5', 'h6', 'form', 'input', 'button', 'select', 'option',
            'textarea', 'label', 'fieldset', 'legend', 'nav', 'header', 'footer',
            'section', 'article', 'main', 'canvas', 'svg', 'audio', 'source', 'track'
        ]
        
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Remove forbidden tags but keep their content
        for tag_name in forbidden_tags:
            for tag in soup.find_all(tag_name):
                tag.unwrap()  # Remove the tag but keep its content
        
        # Remove any script content
        for script in soup.find_all(['script', 'style']):
            script.decompose()
        
        # Convert back to string
        cleaned_html = str(soup)
        
        # Remove any remaining problematic tags with regex
        cleaned_html = re.sub(r'</?html[^>]*>', '', cleaned_html)
        cleaned_html = re.sub(r'</?body[^>]*>', '', cleaned_html)
        cleaned_html = re.sub(r'</?head[^>]*>', '', cleaned_html)
        
        # Remove empty lines and excessive whitespace
        lines = [line.strip() for line in cleaned_html.split('\n') if line.strip()]
        cleaned_html = '\n'.join(lines)
        
        return cleaned_html.strip()
        
    except Exception as e:
        logging.warning(f"Error sanitizing HTML: {e}")
        # Fallback: strip all HTML tags
        return BeautifulSoup(html_content, 'html.parser').get_text(strip=True)

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
    """
    Create Telegraph page with improved error handling and validation
    """
    if result.empty:
        logging.warning("Cannot create Telegraph page: no data provided")
        return None
    
    try:
        telegraph = Telegraph(access_token=access_token)
        logging.info("Telegraph instance created successfully")
    except Exception as e:
        logging.error(f"Failed to create Telegraph instance: {e}")
        return None
    
    # Подготовка контента страницы в HTML, используя только разрешенные теги
    content_html = ""
    categories_processed = 0
    
    for category, group in result.groupby('category'):
        logging.debug(f"Processing category: {category} with {len(group)} items")
        categories_processed += 1
        
        # Escape category name for safe HTML
        safe_category = escape_html(str(category))
        content_html += f"<hr><h3>{safe_category}</h3>"

        for idx, row in group.iterrows():
            try:
                article_title = escape_html(str(row.get('headline', 'No title')))
                
                # Формирование списка ссылок в <ul>
                # Если есть поле 'links' (список), используем его, иначе - просто 'link'
                if 'links' in row and isinstance(row['links'], list):
                    links_list = row['links']
                else:
                    link = row.get('link', '')
                    links_list = [link] if link else []
                
                # Validate and format links
                valid_links = []
                for link in links_list:
                    if link and link.startswith(('http://', 'https://')):
                        try:
                            domain = urlparse(link).netloc
                            if domain:
                                valid_links.append(f'<a href="https://dzarlax.dev/rss/articles/article.html?link={link}">{domain}</a>')
                        except Exception as link_err:
                            logging.warning(f"Invalid link format: {link}, error: {link_err}")
                
                links_html = ' | '.join(valid_links) if valid_links else 'Нет ссылок'
                
                # Заголовки статей оборачиваем в <p> и добавляем к ним список ссылок
                content_html += f"<p><strong>{article_title}</strong><br/>{links_html}</p>\n"
                
            except Exception as e:
                logging.warning(f"Error processing article in category {category}: {e}")
                continue

    logging.info(f"Processed {categories_processed} categories for Telegraph page")
    
    # Sanitize HTML content before sending to Telegraph
    content_html = sanitize_html_for_telegraph(content_html)
    
    if not content_html.strip():
        logging.warning("No valid content generated for Telegraph page")
        return None
    
    # Создание страницы на Telegra.ph
    try:
        current_date = datetime.datetime.now().strftime("%d.%m.%Y")
        page_title = f"Новости за {current_date}"
        
        logging.info(f"Creating Telegraph page with title: {page_title}")
        
        response = telegraph.create_page(
            title=page_title,
            html_content=content_html,
            author_name=author_name,
            author_url=author_url
        )
        
        telegraph_url = response.get('url')
        if telegraph_url:
            logging.info(f"Telegraph page created successfully: {telegraph_url}")
            return telegraph_url
        else:
            logging.error("Telegraph API returned no URL")
            return None
            
    except Exception as e:
        logging.error(f"Failed to create Telegraph page: {e}")
        return None

def generate_daily_overview(result):
    # Prepare prompt in Russian
    prompt = (
        "Внимание: твой ответ должен быть строго не длиннее 4000 символов. "
        "Если итоговый текст превышает лимит — сократи его до 4000 символов, сохраняя основные мысли.\n"
        "Сгенерируй краткую сводку новостей на русском языке на основе следующих категорий и заголовков с описаниями. "
        "НЕ ИСПОЛЬЗУЙ HTML теги в ответе, только обычный текст и markdown форматирование:\n\n"
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

    prompt += "\nСтрого следи за лимитом: максимум 4000 символов! Используй журналистский стиль. НЕ используй HTML теги!"

    overview = process_with_gpt(prompt)
    logging.debug(f"Generated overview:\n{overview}")
    if not overview or overview == "Error":
        logging.warning(f"Overview is empty or Error. Overview: '{overview}'")

    # Ensure the overview doesn't exceed 4000 characters
    if len(overview) > 4000:
        overview = overview[:3997] + "..."

    # Remove any potential HTML tags that might have been generated
    overview = sanitize_html_for_telegraph(overview)

    return overview

def prepare_and_send_message(result, chat_id, telegram_token, telegraph_access_token, service_chat_id):
    """
    Prepare and send news message with improved error handling
    """
    if result.empty:
        logging.warning("No data to send - result DataFrame is empty")
        error_msg = "Нет новостей для отправки - DataFrame пуст"
        send_telegram_message(error_msg, service_chat_id, telegram_token)
        return None
    
    logging.info(f"Preparing message for {len(result)} news items")
    
    # Generate overview in Russian
    try:
        daily_overview = generate_daily_overview(result)
        if not daily_overview or daily_overview == "Error":
            logging.warning("Failed to generate daily overview, using fallback")
            daily_overview = f"Сводка новостей за {datetime.datetime.now().strftime('%d.%m.%Y')} недоступна"
        
        daily_overview_html = convert_markdown_to_html(daily_overview)
        # Sanitize HTML to remove any potentially problematic tags
        daily_overview_html = sanitize_html_for_telegraph(daily_overview_html)
        
    except Exception as e:
        logging.error(f"Error generating overview: {e}")
        daily_overview_html = f"Ошибка при генерации обзора новостей"

    # Create Telegraph page
    try:
        telegraph_url = create_telegraph_page_with_library(result, telegraph_access_token)
        if not telegraph_url:
            logging.warning("Failed to create Telegraph page")
            telegraph_url = "Страница Telegraph недоступна"
    except Exception as e:
        logging.error(f"Error creating Telegraph page: {e}")
        telegraph_url = "Ошибка создания страницы Telegraph"

    # Format message with overview and link
    current_date = datetime.datetime.now().strftime("%d.%m.%Y")
    
    if telegraph_url.startswith("http"):
        message = f"📰 Сводка новостей за {current_date}\n\n{daily_overview_html}\n\n🔗 Подробнее: {telegraph_url}"
    else:
        message = f"📰 Сводка новостей за {current_date}\n\n{daily_overview_html}\n\n⚠️ {telegraph_url}"
    
    # Ensure message is not too long for Telegram (max 4096 characters)
    if len(message) > 4090:
        truncated_overview = daily_overview_html[:3800] + "..."
        if telegraph_url.startswith("http"):
            message = f"📰 Сводка новостей за {current_date}\n\n{truncated_overview}\n\n🔗 Подробнее: {telegraph_url}"
        else:
            message = f"📰 Сводка новостей за {current_date}\n\n{truncated_overview}\n\n⚠️ {telegraph_url}"
    
    logging.info(f"Daily overview generated, message length: {len(message)} characters")

    # Send message
    try:
        response = send_telegram_message(message, chat_id, telegram_token)
        if isinstance(response, dict) and response.get('ok'):
            success_msg = f"Сообщение успешно отправлено (ID: {response.get('result', {}).get('message_id', 'unknown')})"
            logging.info(success_msg)
            send_telegram_message(success_msg, service_chat_id, telegram_token)
        else:
            error_details = response.get('description', 'unknown error') if isinstance(response, dict) else str(response)
            error_msg = f"Произошла ошибка при отправке: {error_details}"
            logging.error(error_msg)
            send_telegram_message(error_msg, service_chat_id, telegram_token)
        return response
    except Exception as e:
        error_msg = f"Критическая ошибка при отправке сообщения: {e}"
        logging.error(error_msg)
        send_telegram_message(error_msg, service_chat_id, telegram_token)
        return None

def job():
    """
    Main job function with improved error handling and logging
    """
    global infra
    if infra is None:
        raise ValueError("infra is not defined")
    
    logging.info(f"Starting news processing job in {infra} environment")
    
    try:
        # Initialize configuration
        init_config()
        logging.info("Configuration initialized successfully")
        
        # Load environment-specific settings
        if infra == 'prod':
            chat_id = load_config("TELEGRAM_CHAT_ID_NEWS")
            logging.info("Using production chat ID")
        elif infra == 'test':
            chat_id = load_config("TELEGRAM_CHAT_ID")
            logging.info("Using test chat ID")
        else:
            raise ValueError(f"Unknown infrastructure environment: {infra}")

        service_chat_id = load_config("TELEGRAM_CHAT_ID")
        telegram_token = load_config("TELEGRAM_BOT_TOKEN")
        telegraph_access_token = load_config("TELEGRAPH_ACCESS_TOKEN")
        feed_url = load_config("feed_url")
        
        logging.info("All configuration loaded successfully")

        # Получаем данные фида
        logging.info("Fetching RSS feed data...")
        data = fetch_and_parse_rss_feed(feed_url)
        
        if data.empty:
            logging.warning("No data received from RSS feed")
            send_telegram_message("⚠️ RSS фид не содержит данных", service_chat_id, telegram_token)
            return

        logging.info(f"Received {len(data)} items from RSS feed")

        # Преобразование и фильтрация данных
        today = datetime.datetime.now().date()
        logging.info(f"Filtering news for today: {today}")
        
        data['today'] = today
        today_data = data[data['pubDate'] == data['today']].drop(columns=['today', 'pubDate'])
        
        if today_data.empty:
            logging.info("No news for today")
            send_telegram_message(f"📅 Нет новостей за {today.strftime('%d.%m.%Y')}", service_chat_id, telegram_token)
            return
        
        logging.info(f"Found {len(today_data)} news items for today")

        # Generate categories
        logging.info("Generating categories for news items...")
        try:
            categories = generate_summary_batch(
                today_data['description'].tolist(),
                batch_size=4
            )
            today_data['category'] = categories
            logging.info(f"Categories generated: {set(categories)}")
        except Exception as e:
            logging.error(f"Failed to generate categories: {e}")
            # Fallback to default category
            today_data['category'] = 'General'
            logging.info("Using fallback category: General")

        # Send message
        logging.info("Preparing and sending message...")
        response = prepare_and_send_message(
            today_data, 
            chat_id, 
            telegram_token, 
            telegraph_access_token, 
            service_chat_id
        )
        
        if response:
            logging.info("Job completed successfully")
        else:
            logging.warning("Job completed with warnings")
            
    except KeyError as e:
        error_msg = f"Configuration error: {e}"
        logging.error(error_msg)
        try:
            service_chat_id = load_config("TELEGRAM_CHAT_ID")
            telegram_token = load_config("TELEGRAM_BOT_TOKEN")
            send_telegram_message(f"🔧 {error_msg}", service_chat_id, telegram_token)
        except:
            pass  # If we can't even load basic config, just log
        raise
    except Exception as e:
        error_msg = f"Unexpected error in job: {e}"
        logging.error(error_msg, exc_info=True)
        try:
            service_chat_id = load_config("TELEGRAM_CHAT_ID")
            telegram_token = load_config("TELEGRAM_BOT_TOKEN")
            send_telegram_message(f"❌ {error_msg}", service_chat_id, telegram_token)
        except:
            pass  # If we can't even load basic config, just log
        raise

    
if __name__ == "__main__":
    setup_logging()
    args = parse_args()
    infra = args.infra
    logging.info(f"Running in {infra} environment")
    try:
        job()
        logging.info("Script completed successfully")
    except Exception as e:
        logging.error(f"Script failed: {e}")
        sys.exit(1)
