"""Modern modular Telegram source - facade for new architecture."""

# Import the new modular TelegramSource
from ..telegram import TelegramSource

# Re-export for backward compatibility
__all__ = ['TelegramSource']

