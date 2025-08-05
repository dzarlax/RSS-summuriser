"""Configuration management."""

import os
from typing import Optional

from pydantic import Field, HttpUrl, SecretStr, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings."""
    
    # Database
    database_url: str = Field(default="postgresql://newsuser:newspass123@localhost:5432/newsdb")
    
    # Constructor KM API (primary AI)
    constructor_km_api: Optional[str] = Field(default=None, alias="CONSTRUCTOR_KM_API") 
    constructor_km_api_key: Optional[str] = Field(default=None, alias="CONSTRUCTOR_KM_API_KEY")
    model: str = Field(default="gpt-4o-mini", alias="MODEL")
    
    # Specific AI models for different tasks
    summarization_model: str = Field(default="gpt-4o-mini", alias="SUMMARIZATION_MODEL")
    categorization_model: str = Field(default="gpt-4o-mini", alias="CATEGORIZATION_MODEL") 
    digest_model: str = Field(default="gpt-4.1", alias="DIGEST_MODEL")
    
    # Telegram
    telegram_token: Optional[SecretStr] = Field(default=None, alias="TELEGRAM_TOKEN")
    telegram_chat_id: Optional[str] = Field(default=None, alias="TELEGRAM_CHAT_ID")
    telegraph_access_token: Optional[str] = Field(default=None, alias="TELEGRAPH_ACCESS_TOKEN")
    
    # Application
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    development: bool = Field(default=False, alias="DEVELOPMENT")
    
    # Admin authentication
    admin_username: str = Field(default="admin", alias="ADMIN_USERNAME")
    admin_password: Optional[str] = Field(default=None, alias="ADMIN_PASSWORD")
    
    # Processing
    max_workers: int = Field(default=5, alias="MAX_WORKERS")
    cache_ttl: int = Field(default=86400, alias="CACHE_TTL")
    cache_dir: str = Field(default="/tmp/rss_cache", alias="CACHE_DIR")
    
    # API Rate Limiting
    api_rate_limit: int = Field(default=3, alias="RPS")  # Requests per second
    
    # Database Connection Pool (увеличенные настройки для стабильности)
    db_pool_size: int = Field(default=5, alias="DB_POOL_SIZE") 
    db_max_overflow: int = Field(default=10, alias="DB_MAX_OVERFLOW")
    db_pool_timeout: int = Field(default=60, alias="DB_POOL_TIMEOUT")
    
    
    class Config:
        env_file = ".env"
        case_sensitive = False
        
    @field_validator('constructor_km_api', mode='before')
    @classmethod
    def empty_str_to_none(cls, v):
        """Convert empty strings to None for optional URL fields."""
        if v == '' or v is None:
            return None
        return v
        
    def get_legacy_config(self, key: str) -> Optional[str]:
        """Метод для совместимости со старой системой load_config."""
        legacy_mapping = {
            "CONSTRUCTOR_KM_API": self.constructor_km_api,
            "CONSTRUCTOR_KM_API_KEY": self.constructor_km_api_key,
            "MODEL": self.model,
            "TELEGRAM_BOT_TOKEN": self.telegram_token.get_secret_value() if self.telegram_token else None,
            "TELEGRAM_TOKEN": self.telegram_token.get_secret_value() if self.telegram_token else None,
            "TELEGRAM_CHAT_ID": self.telegram_chat_id,
            "TELEGRAPH_ACCESS_TOKEN": self.telegraph_access_token,
        }
        return legacy_mapping.get(key)


# Глобальный экземпляр настроек
settings = Settings()