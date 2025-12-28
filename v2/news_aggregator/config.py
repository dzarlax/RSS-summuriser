"""Configuration management."""

import os
from typing import Optional, List

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings."""
    
    # Database
    database_url: str = Field(default="postgresql://newsuser:newspass123@localhost:5432/newsdb")
    
    # AI Provider selection
    ai_provider: str = Field(default="constructor", alias="AI_PROVIDER")  # "constructor" or "gemini"
    
    # Constructor KM API (primary AI)
    constructor_km_api: Optional[str] = Field(default=None, alias="CONSTRUCTOR_KM_API") 
    constructor_km_api_key: Optional[str] = Field(default=None, alias="CONSTRUCTOR_KM_API_KEY")
    model: str = Field(default="gpt-4o-mini", alias="MODEL")
    
    # Gemini API configuration
    gemini_api_key: Optional[str] = Field(default=None, alias="GEMINI_API_KEY")
    gemini_api_endpoint: str = Field(
        default="https://generativelanguage.googleapis.com/v1/models",
        alias="GEMINI_API_ENDPOINT"
    )
    
    # Specific AI models for different tasks
    summarization_model: str = Field(default="gpt-4o-mini", alias="SUMMARIZATION_MODEL")
    categorization_model: str = Field(default="gpt-4o-mini", alias="CATEGORIZATION_MODEL") 
    digest_model: str = Field(default="gpt-4.1", alias="DIGEST_MODEL")

    # AI usage pricing (per 1M tokens) - optional, configure per provider/model
    ai_input_cost_per_1m: Optional[float] = Field(default=None, alias="AI_INPUT_COST_PER_1M")
    ai_output_cost_per_1m: Optional[float] = Field(default=None, alias="AI_OUTPUT_COST_PER_1M")
    ai_cached_input_cost_per_1m: Optional[float] = Field(default=None, alias="AI_CACHED_INPUT_COST_PER_1M")
    
    # Telegram
    telegram_token: Optional[SecretStr] = Field(default=None, alias="TELEGRAM_TOKEN")
    telegram_chat_id: Optional[str] = Field(default=None, alias="TELEGRAM_CHAT_ID")
    telegraph_access_token: Optional[str] = Field(default=None, alias="TELEGRAPH_ACCESS_TOKEN")
    
    # Application
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    development: bool = Field(default=False, alias="DEVELOPMENT")
    use_custom_parsers: bool = Field(default=False, alias="USE_CUSTOM_PARSERS")
    
    # Admin authentication
    admin_username: str = Field(default="admin", alias="ADMIN_USERNAME")
    admin_password: Optional[str] = Field(default=None, alias="ADMIN_PASSWORD")
    jwt_secret: Optional[str] = Field(default=None, alias="JWT_SECRET")
    
    # Processing
    max_workers: int = Field(default=5, alias="MAX_WORKERS")
    cache_ttl: int = Field(default=86400, alias="CACHE_TTL")
    cache_dir: str = Field(default="/tmp/rss_cache", alias="CACHE_DIR")
    
    # API Rate Limiting
    api_rate_limit: int = Field(default=3, alias="RPS")  # Requests per second
    
    
    # Database Connection Pool
    db_pool_size: int = Field(default=5, alias="DB_POOL_SIZE")  # Base pool size
    db_max_overflow: int = Field(default=10, alias="DB_MAX_OVERFLOW")  # Allow burst connections
    db_pool_timeout: int = Field(default=30, alias="DB_POOL_TIMEOUT")  # Reasonable timeout
    
    # Database Query Optimization (агрессивная очистка)
    db_statement_timeout: int = Field(default=15000, alias="DB_STATEMENT_TIMEOUT")  # 15s per query
    db_pool_pre_ping: bool = Field(default=True, alias="DB_POOL_PRE_PING")
    db_pool_recycle: int = Field(default=300, alias="DB_POOL_RECYCLE")  # 5min aggressive recycle

    # HTTP / proxy / CORS
    allowed_origins: Optional[str] = Field(
        default="http://localhost:8000,http://127.0.0.1:8000,https://news.dzarlax.dev",
        alias="ALLOWED_ORIGINS"
    )
    trusted_hosts: Optional[str] = Field(
        default="localhost,127.0.0.1,news.dzarlax.dev",
        alias="TRUSTED_HOSTS"
    )

    # Database init safety
    allow_create_all: bool = Field(default=True, alias="ALLOW_CREATE_ALL")
    
    
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
    
    def get_allowed_origins_list(self) -> List[str]:
        """Return allowed origins as list."""
        if not self.allowed_origins:
            return []
        return [item.strip() for item in str(self.allowed_origins).split(',') if item.strip()]
    
    def get_trusted_hosts_list(self) -> List[str]:
        """Return trusted hosts as list."""
        if not self.trusted_hosts:
            return []
        return [item.strip() for item in str(self.trusted_hosts).split(',') if item.strip()]
        
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


def get_settings() -> Settings:
    """Get application settings instance."""
    return settings
