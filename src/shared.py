import os
from typing import Dict, Tuple, List, Optional, Union, Any
from html import escape as escape_html
import requests
import re
from dotenv import load_dotenv, find_dotenv

# Load environment variables from .env file if it exists
dotenv_path = find_dotenv()
if dotenv_path:
    load_dotenv(dotenv_path)

def load_config(key: Optional[str] = None) -> Any:
    if key:
        value = os.getenv(key)  # Read from environment variable
        if value is None:
            raise KeyError(f"The environment variable '{key}' was not found.")
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