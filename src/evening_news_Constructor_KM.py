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


from shared import load_config, send_telegram_message, send_telegram_message_with_keyboard, convert_markdown_to_html, validate_telegram_html

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
        if any(keyword in prompt for keyword in [
            "сводку новостей", "Сводку новостей", "сводка новостей", "Сводка новостей",
            "опытный журналист", "связную сводку", "связный рассказ"
        ]):
            logging.info(f"✅ Returning full GPT response: {len(output_text)} characters")
            return output_text
        # For category classification, return first word
        else:
            first_word = output_text.split()[0]
            cleaned_first_word = re.sub(r'[^a-zA-Z]', '', first_word)
            logging.info(f"Returning first word for category: {cleaned_first_word}")
            return cleaned_first_word
    else:
        logging.error(f"API error {response.status_code}: {response.text}")
        logging.info(f"API response status: {response.status_code}")
        logging.info(f"API response text: {response.text}")
        return "Error"

def escape_html(text):
    """Заменяет специальные HTML символы на их экранированные эквиваленты."""
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

def smart_truncate_html(text, max_length):
    """
    Smart truncation of HTML content that preserves complete categories
    """
    if len(text) <= max_length:
        return text
    
    import re
    
    # Split text into lines for better processing
    lines = text.strip().split('\n')
    result_lines = []
    current_length = 0
    
    # First, add the header if present
    if lines and lines[0].strip() == '<b>Сводка новостей</b>':
        result_lines.append(lines[0])
        current_length += len(lines[0])
        lines = lines[1:]  # Remove header from processing
    
    # Process remaining lines and group by categories
    current_category = None
    current_category_lines = []
    categories = []
    
    for line in lines:
        line = line.strip()
        if not line:  # Skip empty lines
            continue
            
        # Check if this is a category header
        if line.startswith('<b>') and line.endswith('</b>') and line != '<b>Сводка новостей</b>':
            # Save previous category if exists
            if current_category and current_category_lines:
                categories.append((current_category, current_category_lines))
            
            # Start new category
            current_category = line
            current_category_lines = []
        else:
            # Add content to current category
            if current_category:
                current_category_lines.append(line)
    
    # Don't forget the last category
    if current_category and current_category_lines:
        categories.append((current_category, current_category_lines))
    
    # Now add categories one by one until we hit the limit
    for category_header, category_content in categories:
        # Calculate space needed for this category
        category_text = f"\n\n{category_header}\n" + '\n'.join(category_content)
        potential_length = current_length + len(category_text)
        
        # Check if adding this category would exceed limit (with buffer for "...")
        if potential_length <= max_length - 20:
            result_lines.append("")  # Empty line before category
            result_lines.append(category_header)
            result_lines.extend(category_content)
            current_length = potential_length
        else:
            # Stop here to keep previous categories complete
            break
    
    # Join result
    result = '\n'.join(result_lines)
    
    # Add ellipsis if content was truncated
    if len(categories) > 0 and current_length < len(text.strip()) - 100:
        result = result.rstrip() + "..."
    
    return result

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

def convert_lists_to_narrative(text):
    """
    Convert any remaining list items to narrative text
    """
    if not text:
        return text
    
    lines = text.split('\n')
    result_lines = []
    current_section = []
    current_category = None
    
    for line in lines:
        stripped = line.strip()
        
        # Check if this is a category header
        if stripped.startswith('<b>') and stripped.endswith('</b>'):
            # If we have accumulated section content, convert it to narrative
            if current_section and current_category:
                narrative = convert_section_to_narrative(current_section, current_category)
                result_lines.append(narrative)
                current_section = []
            
            current_category = stripped
            result_lines.append(line)
        
        # Check if this is a list item
        elif stripped.startswith(('- ', '• ', '* ')) or (len(stripped) > 2 and stripped[1:3] in ['. ', ') ']):
            # This is a list item, add to current section
            clean_item = stripped
            # Remove list markers
            for marker in ['- ', '• ', '* ']:
                if clean_item.startswith(marker):
                    clean_item = clean_item[len(marker):].strip()
                    break
            # Remove numbered markers
            if len(clean_item) > 2 and clean_item[1] in ['.', ')']:
                try:
                    int(clean_item[0])
                    clean_item = clean_item[2:].strip()
                except:
                    pass
            
            if clean_item:
                current_section.append(clean_item)
        
        # Regular line (not a list item)
        else:
            # First add any accumulated section
            if current_section and current_category:
                narrative = convert_section_to_narrative(current_section, current_category)
                result_lines.append(narrative)
                current_section = []
            
            result_lines.append(line)
    
    # Handle any remaining section
    if current_section and current_category:
        narrative = convert_section_to_narrative(current_section, current_category)
        result_lines.append(narrative)
    
    return '\n'.join(result_lines)

def convert_section_to_narrative(items, category_header):
    """
    Convert a list of items to narrative text
    """
    if not items:
        return ""
    
    if len(items) == 1:
        return items[0]
    
    # Create connecting phrases
    connectors = [
        "Одновременно", "Также", "Кроме того", "В то же время", 
        "Параллельно", "Дополнительно", "Более того"
    ]
    
    narrative_parts = [items[0]]
    
    for i, item in enumerate(items[1:], 1):
        if i < len(connectors):
            connector = connectors[i-1]
        else:
            connector = "Также"
        
        narrative_parts.append(f"{connector.lower()} {item.lower()}")
    
    return " ".join(narrative_parts) + "."

def split_categories_for_messages(result):
    """
    Разделяет категории на две группы для отправки двух сообщений
    Балансирует количество новостей между группами
    """
    category_counts = result['category'].value_counts()
    total_news = len(result)
    
    # Цель: примерно 50/50 по количеству новостей
    target = total_news // 2
    
    group1_categories = []
    group1_count = 0
    group2_categories = []
    group2_count = 0
    
    # Сортируем категории по количеству (убывание)
    sorted_categories = category_counts.sort_values(ascending=False)
    
    for category, count in sorted_categories.items():
        # Добавляем в группу с меньшим количеством новостей
        if group1_count <= group2_count:
            group1_categories.append(category)
            group1_count += count
        else:
            group2_categories.append(category)
            group2_count += count
    
    logging.info(f"Разделение на группы: Группа 1 ({group1_count} новостей): {group1_categories}")
    logging.info(f"Разделение на группы: Группа 2 ({group2_count} новостей): {group2_categories}")
    
    # Создаем два DataFrame
    group1_data = result[result['category'].isin(group1_categories)]
    group2_data = result[result['category'].isin(group2_categories)]
    
    return group1_data, group2_data

def generate_daily_overview(result, message_part=None):
    # Prepare enhanced prompt for detailed HTML news summary
    total_news = len(result)
    categories = result['category'].nunique()
    
    # Заголовок и лимит зависят от части сообщения
    if message_part == 1:
        header_text = "Сводка новостей (часть 1)"
    elif message_part == 2:
        header_text = "Сводка новостей (часть 2)" 
    else:
        header_text = "Сводка новостей"
    
    # Определяем лимит символов для каждой части
    if message_part:
        char_limit = 3400  # Для разделенных сообщений - меньше лимит
        detail_level = "СЖАТО"
    else:
        char_limit = 2600  # Для одиночных сообщений
        detail_level = "СЖАТО"
    
    prompt = (
        f"Ты - журналист. Создай {detail_level} сводку новостей в HTML.\n\n"
        f"{total_news} новостей в {categories} категориях.\n\n"
        f"ТРЕБОВАНИЯ:\n"
        f"- HTML с <b></b> для заголовков\n" 
        f"- Связные абзацы (НЕ списки!)\n"
        f"- МАКСИМУМ {char_limit} символов\n"
        f"- Охвати основные события по категориям\n\n"
        f"ФОРМАТ:\n"
        f"<b>{header_text}</b>\n\n"
        f"<b>Tech</b>\n"
        f"Apple выпустила новый iPhone. Tesla показала рост продаж. Microsoft анонсировал ИИ-решения.\n\n"
        f"<b>Business</b>\n"
        f"Рынки выросли на 2%. Компании отчитались о прибыли.\n\n"
        f"ЗАДАЧА: Сжатые связные абзацы для каждой категории!\n\n"
        f"НОВОСТИ:\n\n"
    )
    for category, group in result.groupby('category'):
        prompt += f"\n=== {category} ===\n"
        for _, row in group.iterrows():
            # Get headline
            headline = row.get('headline', '')

            # Get description and truncate to 500 characters if needed
            description = row.get('description', '')
            if len(description) > 500:
                description = description[:497] + "..."

            # Add headline and description to prompt
            prompt += f"ЗАГОЛОВОК: {headline}\n"
            if description:
                prompt += f"ОПИСАНИЕ: {description}\n"
            prompt += "---\n"

    prompt += (
        "\n\nПРАВИЛА:\n"
        "✅ НЕ СПИСКИ! Только связные предложения!\n"
        "✅ НЕ используй: - • * 1. 2.\n"
        f"✅ МАКСИМУМ {char_limit} символов - соблюдай лимит!\n"
        f"✅ Начинай с <b>{header_text}</b>\n"
        "✅ HTML только <b></b>\n\n"
        f"ВАЖНО: Не превышай {char_limit} символов!"
    )

    logging.info(f"Sending prompt to GPT: {len(prompt)} characters")
    logging.info(f"Prompt preview: {prompt[:200]}...")
    
    overview = process_with_gpt(prompt)
    
    logging.info(f"GPT response received: '{overview}' (length: {len(overview) if overview else 0})")
    
    # Detailed logging for debugging
    if not overview:
        logging.error("❌ GPT returned None/empty")
    elif overview == "Error":
        logging.error("❌ GPT returned 'Error' string")
    elif overview.strip() == "":
        logging.error("❌ GPT returned empty string")
    else:
        logging.info(f"✅ GPT returned valid response: {overview[:100]}...")
    
    # Post-processing: Convert any remaining lists to narrative text
    if overview and overview != "Error":
        overview = convert_lists_to_narrative(overview)
        logging.info(f"After post-processing: {len(overview)} characters")
    
    # Better error handling with more detailed logging
    if not overview or overview == "Error" or overview.strip() == "":
        logging.error(f"GPT returned empty response. Full response: '{overview}'")
        logging.error("FALLBACK TRIGGERED - GPT не ответил или вернул пустой результат")
        
        # Create NARRATIVE fallback by categories (no lists!)
        fallback_parts = [f"<b>Сводка новостей за {datetime.datetime.now().strftime('%d.%m.%Y')}</b>\n"]
        
        for category, group in result.groupby('category'):
            category_headlines = []
            for _, row in group.iterrows():
                headline = row.get('headline', '')
                if headline:
                    # Clean headline for narrative
                    clean_headline = headline.replace('🖼', '').replace('🇷🇸', '').replace('🇩🇪', '').strip()
                    category_headlines.append(clean_headline)
            
            if category_headlines:
                fallback_parts.append(f"\n<b>{category}</b>")
                
                # Create narrative text from headlines
                if len(category_headlines) == 1:
                    narrative = category_headlines[0] + "."
                else:
                    connectors = ["Также", "Кроме того", "Дополнительно"]
                    narrative_parts = [category_headlines[0]]
                    
                    for i, headline in enumerate(category_headlines[1:3], 1):  # Max 3 headlines
                        connector = connectors[min(i-1, len(connectors)-1)]
                        narrative_parts.append(f"{connector.lower()} {headline.lower()}")
                    
                    narrative = ". ".join(narrative_parts) + "."
                
                fallback_parts.append(narrative)
        
        overview = "\n".join(fallback_parts)
        logging.info(f"FALLBACK created narrative overview: {len(overview)} characters")
    
    # Не обрезаем контент - позволяем GPT создать полную сводку
    # Система разделения сообщений разделит контент при необходимости

    # Validate HTML for Telegram
    validated_overview = validate_telegram_html(overview)
    
    # Final check - if validation failed, provide fallback with headlines
    if not validated_overview or len(validated_overview.strip()) < 10:
        logging.warning(f"HTML validation failed. Original: '{overview}', Validated: '{validated_overview}'")
        logging.warning("VALIDATION FALLBACK TRIGGERED - HTML валидация не прошла")
        
        # Create NARRATIVE fallback with actual headlines (no lists!)
        fallback_parts = [f"<b>Сводка новостей за {datetime.datetime.now().strftime('%d.%m.%Y')}</b>\n"]
        
        for category, group in result.groupby('category'):
            category_headlines = []
            for _, row in group.iterrows():
                headline = row.get('headline', '')
                if headline:
                    # Clean and truncate headline for narrative
                    clean_headline = headline.replace('🖼', '').replace('🇷🇸', '').replace('🇩🇪', '').strip()
                    if len(clean_headline) > 60:
                        clean_headline = clean_headline[:57] + "..."
                    category_headlines.append(clean_headline)
            
            if category_headlines:
                fallback_parts.append(f"\n<b>{category}</b>")
                
                # Create narrative text from headlines  
                if len(category_headlines) == 1:
                    narrative = category_headlines[0] + "."
                else:
                    # Take max 2 headlines for validation fallback
                    headlines_to_use = category_headlines[:2]
                    narrative = f"{headlines_to_use[0]}. Также {headlines_to_use[1].lower()}."
                
                fallback_parts.append(narrative)
        
        overview = "\n".join(fallback_parts)
        logging.info(f"VALIDATION FALLBACK created narrative overview: {len(overview)} characters")
    else:
        overview = validated_overview
    
    logging.info(f"Final overview length: {len(overview)} characters")
    return overview

def format_enhanced_telegram_message(daily_overview_html, telegraph_url, current_date, result):
    """
    Compact message formatting focused on content over decoration
    """
    # Simple clean header without statistics
    message_parts = [
        f"📰 <b>Новости {current_date}</b>",
        "",
        daily_overview_html
    ]
    
    # Don't add Telegraph link in text - we have button for that
    
    return "\n".join(message_parts)

def prepare_and_send_message(result, chat_id, telegram_token, telegraph_access_token, service_chat_id):
    """
    Prepare and send news message with smart splitting into multiple messages if needed
    """
    if result.empty:
        logging.warning("No data to send - result DataFrame is empty")
        error_msg = "Нет новостей для отправки - DataFrame пуст"
        send_telegram_message(error_msg, service_chat_id, telegram_token)
        return None
    
    logging.info(f"Preparing message for {len(result)} news items")
    
    # Create Telegraph page first
    try:
        telegraph_url = create_telegraph_page_with_library(result, telegraph_access_token)
        if not telegraph_url:
            logging.warning("Failed to create Telegraph page")
            telegraph_url = "Страница Telegraph недоступна"
    except Exception as e:
        logging.error(f"Error creating Telegraph page: {e}")
        telegraph_url = "Ошибка создания страницы Telegraph"

    # Try to create single message first
    try:
        daily_overview_html = generate_daily_overview(result)
        if not daily_overview_html or daily_overview_html.strip() == "":
            logging.warning("Failed to generate daily overview")
            daily_overview_html = f"<b>Сводка новостей за {datetime.datetime.now().strftime('%d.%m.%Y')}</b>\n\nПодробная сводка временно недоступна."
        
        current_date = datetime.datetime.now().strftime("%d.%m.%Y")
        message = format_enhanced_telegram_message(daily_overview_html, telegraph_url, current_date, result)
        
        logging.info(f"Single message length: {len(message)} characters")
        
        # Check if single message fits safely (considering GPT limit of 2800 chars)
        if len(message) <= 2700:
            # Send single message
            logging.info("Sending single message")
            return send_single_message(message, telegraph_url, chat_id, telegram_token, service_chat_id)
        else:
            # Split into two messages
            logging.info(f"Message too long ({len(message)} chars), splitting into two parts")
            return send_split_messages(result, telegraph_url, chat_id, telegram_token, service_chat_id)
            
    except Exception as e:
        logging.error(f"Error generating overview: {e}")
        # Fallback to simple message
        simple_message = f"<b>Сводка новостей за {datetime.datetime.now().strftime('%d.%m.%Y')}</b>\n\nОбработано {len(result)} новостей в {result['category'].nunique()} категориях.\nПодробности в полной версии."
        return send_single_message(simple_message, telegraph_url, chat_id, telegram_token, service_chat_id)

def send_single_message(message, telegraph_url, chat_id, telegram_token, service_chat_id):
    """Send single message with Telegraph button"""
    # Create inline keyboard
    inline_keyboard = []
    if telegraph_url.startswith("http"):
        inline_keyboard.append([
            {"text": "📖 Читать полностью", "url": telegraph_url}
        ])

    try:
        response = send_telegram_message_with_keyboard(message, chat_id, telegram_token, inline_keyboard)
        if isinstance(response, dict) and response.get('ok'):
            success_msg = f"Сообщение отправлено (ID: {response.get('result', {}).get('message_id', 'unknown')})"
            logging.info(success_msg)
            send_telegram_message(success_msg, service_chat_id, telegram_token)
        else:
            error_details = response.get('description', 'unknown error') if isinstance(response, dict) else str(response)
            error_msg = f"Ошибка отправки: {error_details}"
            logging.error(error_msg)
            send_telegram_message(error_msg, service_chat_id, telegram_token)
        return response
    except Exception as e:
        error_msg = f"Критическая ошибка при отправке: {e}"
        logging.error(error_msg)
        send_telegram_message(error_msg, service_chat_id, telegram_token)
        return None

def send_split_messages(result, telegraph_url, chat_id, telegram_token, service_chat_id):
    """Split news into two messages by categories"""
    try:
        # Split categories into two balanced groups
        group1_data, group2_data = split_categories_for_messages(result)
        
        # Generate two separate overviews
        overview1 = generate_daily_overview(group1_data, message_part=1)
        overview2 = generate_daily_overview(group2_data, message_part=2)
        
        current_date = datetime.datetime.now().strftime("%d.%m.%Y")
        
        # Format both messages
        message1 = format_enhanced_telegram_message(overview1, telegraph_url, current_date, group1_data)
        message2 = format_enhanced_telegram_message(overview2, telegraph_url, current_date, group2_data)
        
        logging.info(f"Split messages: Part 1: {len(message1)} chars, Part 2: {len(message2)} chars")
        
        # Create keyboards
        keyboard1 = [[{"text": "📖 Читать полностью", "url": telegraph_url}]] if telegraph_url.startswith("http") else []
        keyboard2 = [[{"text": "📖 Читать полностью", "url": telegraph_url}]] if telegraph_url.startswith("http") else []
        
        # Send first message
        logging.info(f"Sending first message ({len(message1)} chars)...")
        response1 = send_telegram_message_with_keyboard(message1, chat_id, telegram_token, keyboard1)
        logging.info(f"First message response: {response1}")
        
        # Small delay between messages
        import time
        time.sleep(1)
        
        # Send second message
        logging.info(f"Sending second message ({len(message2)} chars)...")
        response2 = send_telegram_message_with_keyboard(message2, chat_id, telegram_token, keyboard2)
        logging.info(f"Second message response: {response2}")
        
        # Check results
        success_count = 0
        if isinstance(response1, dict) and response1.get('ok'):
            success_count += 1
            logging.info("✅ First message sent successfully")
        else:
            logging.error(f"❌ First message failed: {response1}")
            
        if isinstance(response2, dict) and response2.get('ok'):
            success_count += 1
            logging.info("✅ Second message sent successfully")
        else:
            logging.error(f"❌ Second message failed: {response2}")
            
        success_msg = f"Отправлено {success_count}/2 сообщений успешно"
        logging.info(success_msg)
        send_telegram_message(success_msg, service_chat_id, telegram_token)
        
        return {"part1": response1, "part2": response2}
        
    except Exception as e:
        error_msg = f"Ошибка при разделении сообщений: {e}"
        logging.error(error_msg)
        send_telegram_message(error_msg, service_chat_id, telegram_token)
        return None

def generate_category_summary(result):
    """
    Generate a brief summary of news by categories with emojis
    """
    if result.empty:
        return "Нет новостей для отображения"
    
    category_stats = result['category'].value_counts()
    category_emojis = {
        'Tech': '💻', 'Business': '💼', 'Science': '🔬', 
        'Nature': '🌿', 'Serbia': '🇷🇸', 'Marketing': '📈',
        'Other': '📰', 'General': '📰'
    }
    
    summary_parts = []
    for category, count in category_stats.items():
        emoji = category_emojis.get(category, '📌')
        
        # Get sample headlines for this category
        category_news = result[result['category'] == category]
        sample_headlines = category_news['headline'].head(2).tolist()
        
        summary_parts.append(f"{emoji} <b>{category}</b> ({count})")
        
        # Add sample headlines for categories with more than 1 news
        if count > 1 and sample_headlines:
            for headline in sample_headlines:
                # Truncate long headlines
                truncated_headline = headline[:60] + "..." if len(headline) > 60 else headline
                summary_parts.append(f"  • {truncated_headline}")
        elif count == 1 and sample_headlines:
            truncated_headline = sample_headlines[0][:60] + "..." if len(sample_headlines[0]) > 60 else sample_headlines[0]
            summary_parts.append(f"  • {truncated_headline}")
    
    return "\n".join(summary_parts)

def demo_enhanced_formatting():
    """
    Demo function to show enhanced formatting capabilities
    """
    # Create sample data for demonstration
    import pandas as pd
    
    sample_data = pd.DataFrame([
        {'headline': 'Новый прорыв в области искусственного интеллекта', 'category': 'Tech', 
         'link': 'https://example.com/1', 'description': 'Исследователи создали новую модель ИИ'},
        {'headline': 'Экономические показатели показывают рост', 'category': 'Business', 
         'link': 'https://example.com/2', 'description': 'Положительная динамика в экономике'},
        {'headline': 'Открытие нового вида растений', 'category': 'Science', 
         'link': 'https://example.com/3', 'description': 'Ботаники обнаружили уникальный вид'},
        {'headline': 'Технологические инновации в медицине', 'category': 'Tech', 
         'link': 'https://example.com/4', 'description': 'Новые методы лечения'},
    ])
    
    # Generate category summary
    category_summary = generate_category_summary(sample_data)
    print("=== СВОДКА ПО КАТЕГОРИЯМ ===")
    print(category_summary)
    print("\n" + "="*50 + "\n")
    
    # Generate enhanced message with HTML (no Telegraph link in text)
    sample_overview = "<b>Главные события дня:</b>\n\nВ области технологий произошли значительные изменения. Искусственный интеллект продолжает развиваться.\n\nЭкономические показатели демонстрируют рост. Новые открытия в ботанике расширяют понимание природы.\n\n<b>Итог:</b> День богат на технологические и научные новости."
    
    enhanced_message = format_enhanced_telegram_message(
        sample_overview, "https://telegra.ph/news-123", "25.12.2024", sample_data
    )
    
    print("=== УЛУЧШЕННОЕ СООБЩЕНИЕ ===")
    print(enhanced_message)
    
    return True

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
        if infra == 'test':
            # В тестовом режиме берем новости за вчерашний день
            target_date = datetime.datetime.now().date() - datetime.timedelta(days=1)
            logging.info(f"Test mode: filtering news for yesterday: {target_date}")
        else:
            # В продакшене берем новости за сегодня
            target_date = datetime.datetime.now().date()
            logging.info(f"Production mode: filtering news for today: {target_date}")
        
        data['target_date'] = target_date
        filtered_data = data[data['pubDate'] == data['target_date']].drop(columns=['target_date', 'pubDate'])
        
        if filtered_data.empty:
            date_str = target_date.strftime('%d.%m.%Y')
            mode_text = "вчера" if infra == 'test' else "сегодня"
            logging.info(f"No news for {mode_text} ({date_str})")
            send_telegram_message(f"📅 Нет новостей за {date_str} ({mode_text})", service_chat_id, telegram_token)
            return
        
        date_str = target_date.strftime('%d.%m.%Y')
        logging.info(f"Found {len(filtered_data)} news items for {date_str}")

        # Generate categories
        logging.info("Generating categories for news items...")
        try:
            categories = generate_summary_batch(
                filtered_data['description'].tolist(),
                batch_size=4
            )
            filtered_data['category'] = categories
            logging.info(f"Categories generated: {set(categories)}")
        except Exception as e:
            logging.error(f"Failed to generate categories: {e}")
            # Fallback to default category
            filtered_data['category'] = 'General'
            logging.info("Using fallback category: General")

        # Send message
        logging.info("Preparing and sending message...")
        response = prepare_and_send_message(
            filtered_data, 
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
