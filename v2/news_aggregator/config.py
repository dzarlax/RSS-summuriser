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
    
    # Processing
    max_workers: int = Field(default=5, alias="MAX_WORKERS")
    cache_ttl: int = Field(default=86400, alias="CACHE_TTL")
    cache_dir: str = Field(default="/tmp/rss_cache", alias="CACHE_DIR")
    
    
    class Config:
        env_file = ".env"
        case_sensitive = False
        
    @field_validator('api_endpoint', 'constructor_km_api', 's3_endpoint', mode='before')
    @classmethod
    def empty_str_to_none(cls, v):
        """Convert empty strings to None for optional URL fields."""
        if v == '' or v is None:
            return None
        return v
        
    def get_legacy_config(self, key: str) -> Optional[str]:
        """Метод для совместимости со старой системой load_config."""
        legacy_mapping = {
            "endpoint_300": self.api_endpoint,
            "token_300": self.api_token.get_secret_value() if self.api_token else None,
            "RPS": str(self.api_rate_limit),
            "BUCKET_NAME": self.s3_bucket,
            "ENDPOINT_URL": self.s3_endpoint,
            "ACCESS_KEY": self.s3_access_key,
            "SECRET_KEY": self.s3_secret_key.get_secret_value() if self.s3_secret_key else None,
            "TELEGRAM_BOT_TOKEN": self.telegram_token.get_secret_value() if self.telegram_token else None,
            "TELEGRAM_TOKEN": self.telegram_token.get_secret_value() if self.telegram_token else None,
            "TELEGRAM_CHAT_ID": self.telegram_chat_id,
            "RSS_LINKS": self.rss_links,
            "logo_url": self.logo_url,
        }
        return legacy_mapping.get(key)


# Глобальный экземпляр настроек
settings = Settings()