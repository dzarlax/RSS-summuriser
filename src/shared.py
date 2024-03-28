import os
from typing import Dict, Tuple, List, Optional, Union, Any
import requests


def load_config(key: Optional[str] = None):
    if key:
        value = os.getenv(key)  # Чтение из переменной окружения
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
