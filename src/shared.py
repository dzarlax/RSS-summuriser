import os
from typing import Dict, Tuple, List, Optional, Union, Any
from html import escape as escape_html
import requests
import re

# Загрузка .env теперь только в entrypoint-скрипте!

def load_config(key: Optional[str] = None) -> Any:
    if key:
        value = os.getenv(key)
        if value is None or value == "":
            import logging
            logging.info(f"ENV DEBUG: '{key}' not found or empty! Actual value: '{value}'")
            raise KeyError(f"The environment variable '{key}' was not found or is empty.")
        return value
    else:
        raise Exception("Requesting the entire config is not supported when using environment variables.")


def send_telegram_message(message: str, chat_id: str, telegram_token: str) -> Dict[str, Any]:
    send_message_url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
    response = requests.post(send_message_url, data={
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    })
    return response.json()


def send_telegram_message_with_keyboard(message: str, chat_id: str, telegram_token: str, 
                                       inline_keyboard: Optional[List[List[Dict]]] = None) -> Dict[str, Any]:
    """
    Send telegram message with optional inline keyboard
    """
    send_message_url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
    
    data = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }
    
    if inline_keyboard:
        data["reply_markup"] = {
            "inline_keyboard": inline_keyboard
        }
    
    response = requests.post(send_message_url, json=data)
    return response.json()


def convert_markdown_to_html(markdown_text):
    # Convert Markdown headings to HTML
    lines = markdown_text.split('\n')
    html_lines = []

    for line in lines:
        if line.startswith('# '):
            # Level 1 heading
            html_lines.append(f"<b>{line[2:].strip()}</b>")
        elif line.startswith('## '):
            # Level 2 heading
            html_lines.append(f"<b>{line[3:].strip()}</b>")
        else:
            # Process bold text marked with **
            processed_line = line

            # Find all occurrences of bold text (text between ** pairs)
            bold_pattern = r'\*\*(.*?)\*\*'

            # Replace each occurrence with HTML bold tags
            processed_line = re.sub(bold_pattern, r'<b>\1</b>', processed_line)

            # Escape HTML characters in the non-bold parts
            # This is more complex as we need to preserve the HTML tags we just added
            # Split by HTML tags and escape only the text parts
            parts = re.split(r'(<b>.*?</b>)', processed_line)
            for i in range(len(parts)):
                if not (parts[i].startswith('<b>') and parts[i].endswith('</b>')):
                    parts[i] = escape_html(parts[i])

            processed_line = ''.join(parts)
            html_lines.append(processed_line)

    return '\n'.join(html_lines)


def validate_telegram_html(html_text):
    """
    Validate and clean HTML for Telegram
    Only allows basic tags supported by Telegram
    """
    if not html_text:
        return ""
    
    # Remove any HTML tags except <b></b>, <i></i>, <a></a>
    # For now, we'll be conservative and only allow <b></b>
    import re
    
    # First, preserve valid <b></b> tags and remove everything else
    # Simple approach: extract text and valid <b> tags only
    valid_html = re.sub(r'<(?!/?b(?:\s|>))[^>]*>', '', html_text)
    
    # Remove any malformed tags
    valid_html = re.sub(r'<b(?![>])[^>]*>', '<b>', valid_html)
    valid_html = re.sub(r'</b(?![>])[^>]*>', '</b>', valid_html)
    
    # Ensure proper tag pairing
    open_tags = valid_html.count('<b>')
    close_tags = valid_html.count('</b>')
    
    if open_tags != close_tags:
        # If tags are not balanced, remove all formatting
        valid_html = re.sub(r'</?b>', '', valid_html)
    
    return valid_html.strip()