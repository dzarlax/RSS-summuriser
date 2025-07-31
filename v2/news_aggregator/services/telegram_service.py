"""Telegram service for sending news digests."""

import logging
from typing import Optional, Dict, Any, List
from datetime import datetime

from ..config import settings
from ..core.http_client import get_http_client
from ..core.exceptions import TelegramError


class TelegramService:
    """Service for sending messages to Telegram."""
    
    def __init__(self):
        self.bot_token = self._get_config("TELEGRAM_TOKEN")
        self.chat_id = self._get_config("TELEGRAM_CHAT_ID")
        
        if not all([self.bot_token, self.chat_id]):
            raise TelegramError("Telegram configuration incomplete")
        
        self.api_url = f"https://api.telegram.org/bot{self.bot_token}"
    
    def _get_config(self, key: str) -> Optional[str]:
        """Get config value with fallback to settings."""
        # Try legacy format first for compatibility
        if hasattr(settings, 'get_legacy_config'):
            value = settings.get_legacy_config(key)
            if value:
                return value
        
        # Try direct from environment
        import os
        return os.getenv(key)
    
    async def send_daily_digest(self, digest: str, message_part: Optional[int] = None) -> bool:
        """
        Send daily digest to Telegram.
        
        Args:
            digest: HTML formatted digest
            message_part: Optional part number for split messages
            
        Returns:
            True if sent successfully, False otherwise
        """
        try:
            # Validate message length for Telegram limits (4096 chars)
            if len(digest) > 4000:
                logging.warning(f"Digest too long ({len(digest)} chars), truncating")
                digest = digest[:3900] + "..."
            
            # Send message
            success = await self._send_message(digest)
            
            if success:
                part_info = f" (part {message_part})" if message_part else ""
                logging.info(f"Daily digest sent to Telegram{part_info}")
                return True
            else:
                logging.error("Failed to send digest to Telegram")
                return False
                
        except Exception as e:
            logging.error(f"Error sending digest to Telegram: {e}")
            return False
    
    async def send_alert(self, title: str, message: str) -> bool:
        """
        Send alert message to Telegram.
        
        Args:
            title: Alert title
            message: Alert message
            
        Returns:
            True if sent successfully, False otherwise
        """
        try:
            alert_text = f"🚨 <b>{title}</b>\n\n{message}"
            return await self._send_message(alert_text)
            
        except Exception as e:
            logging.error(f"Error sending alert to Telegram: {e}")
            return False
    
    async def send_processing_summary(self, stats: Dict[str, Any]) -> bool:
        """
        Send processing summary to Telegram.
        
        Args:
            stats: Processing statistics
            
        Returns:
            True if sent successfully, False otherwise
        """
        try:
            duration = stats.get('duration_seconds', 0)
            summary = (
                f"📊 <b>Обработка новостей завершена</b>\n\n"
                f"📥 Статей получено: {stats.get('articles_fetched', 0)}\n"
                f"🤖 Статей обработано: {stats.get('articles_processed', 0)}\n"
                f"🔗 Кластеров создано: {stats.get('clusters_created', 0)}\n"
                f"🔄 Кластеров обновлено: {stats.get('clusters_updated', 0)}\n"
                f"⏱ Время обработки: {duration:.1f}с\n"
            )
            
            if stats.get('errors'):
                summary += f"⚠️ Ошибок: {len(stats['errors'])}\n"
            
            if stats.get('telegram_digest_generated'):
                summary += f"📱 Дайджест: {stats.get('telegram_digest_length', 0)} символов\n"
                summary += f"📂 Категории: {stats.get('telegram_categories', 0)}\n"
            
            return await self._send_message(summary)
            
        except Exception as e:
            logging.error(f"Error sending processing summary to Telegram: {e}")
            return False
    
    async def _send_message(self, text: str) -> bool:
        """
        Send message to Telegram using Bot API.
        
        Args:
            text: Message text (HTML formatted)
            
        Returns:
            True if sent successfully, False otherwise
        """
        url = f"{self.api_url}/sendMessage"
        
        data = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        
        try:
            async with get_http_client() as client:
                response = await client.post(url, json=data)
                
                async with response:
                    if response.status == 200:
                        return True
                    else:
                        error_text = await response.text()
                        logging.error(f"Telegram API error {response.status}: {error_text}")
                        return False
                        
        except Exception as e:
            logging.error(f"Telegram request failed: {e}")
            return False
    
    async def test_connection(self) -> bool:
        """
        Test Telegram bot connection.
        
        Returns:
            True if connection is successful, False otherwise
        """
        try:
            test_message = f"🧪 Test message from RSS Summarizer v2\n⏰ {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC"
            return await self._send_message(test_message)
            
        except Exception as e:
            logging.error(f"Telegram connection test failed: {e}")
            return False
    
    async def send_message_with_keyboard(self, message: str, inline_keyboard: List[List[dict]]) -> bool:
        """Send message with inline keyboard."""
        if not self.bot_token or not self.chat_id:
            logging.warning("Telegram not configured for keyboard messages")
            return False
        
        if not message or not message.strip():
            logging.warning("Empty message provided")
            return False
        
        try:
            url = f"{self.api_url}/sendMessage"
            
            # Prepare payload
            payload = {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            }
            
            # Add keyboard if provided
            if inline_keyboard:
                payload["reply_markup"] = {
                    "inline_keyboard": inline_keyboard
                }
            
            async with get_http_client() as client:
                response = await client.post(url, json=payload)
                
                async with response:
                    if response.status == 200:
                        logging.info("Telegram message with keyboard sent successfully")
                        return True
                    else:
                        error_text = await response.text()
                        logging.error(f"Telegram API error {response.status}: {error_text}")
                        return False
        
        except Exception as e:
            logging.error(f"Failed to send Telegram message with keyboard: {e}")
            return False


# Global Telegram service instance
_telegram_service: Optional[TelegramService] = None


def get_telegram_service() -> TelegramService:
    """Get Telegram service instance."""
    global _telegram_service
    
    if _telegram_service is None:
        _telegram_service = TelegramService()
    
    return _telegram_service