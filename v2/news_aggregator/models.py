"""SQLAlchemy models."""

from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Integer, 
    String, Text, JSON, ARRAY, DECIMAL, UniqueConstraint
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .database import Base


class Source(Base):
    """News source model."""
    __tablename__ = "sources"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    source_type = Column(String(50), nullable=False)  # rss, telegram, reddit, etc.
    url = Column(Text, nullable=False)
    enabled = Column(Boolean, default=True)
    config = Column(JSON, default={})
    fetch_interval = Column(Integer, default=1800)  # seconds
    last_fetch = Column(DateTime)
    last_success = Column(DateTime)
    last_error = Column(Text)
    error_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    articles = relationship("Article", back_populates="source")


class Article(Base):
    """Article model."""
    __tablename__ = "articles"

    id = Column(Integer, primary_key=True, index=True)
    source_id = Column(Integer, ForeignKey("sources.id", ondelete="CASCADE"))
    title = Column(Text, nullable=False)
    url = Column(Text, nullable=False, unique=True)
    content = Column(Text)
    summary = Column(Text)
    category = Column(String(50))  # Business, Tech, Science, Nature, Serbia, Marketing, Other
    image_url = Column(Text)
    published_at = Column(DateTime)
    fetched_at = Column(DateTime, default=func.now())
    processed = Column(Boolean, default=False)  # Legacy field for backward compatibility
    summary_processed = Column(Boolean, default=False)  # True if AI summarization was attempted
    category_processed = Column(Boolean, default=False)  # True if AI categorization was attempted
    hash_content = Column(String(64))
    
    # Advertising detection fields
    is_advertisement = Column(Boolean, default=False, index=True)  # True if content is advertising
    ad_confidence = Column(Float, default=0.0)  # Confidence score (0.0-1.0)
    ad_type = Column(String(50))  # Type of advertising (product_promotion, affiliate_marketing, etc.)
    ad_reasoning = Column(Text)  # AI reasoning for advertising classification
    ad_markers = Column(JSON, default=list)  # List of advertising markers found
    ad_processed = Column(Boolean, default=False)  # True if advertising detection was attempted

    # Relationships
    source = relationship("Source", back_populates="articles")
    cluster_articles = relationship("ClusterArticle", back_populates="article")


class NewsCluster(Base):
    """News cluster model."""
    __tablename__ = "news_clusters"

    id = Column(Integer, primary_key=True, index=True)
    cluster_id = Column(String(255), unique=True, nullable=False)
    canonical_title = Column(Text, nullable=False)
    canonical_summary = Column(Text)
    canonical_image = Column(Text)
    topics = Column(ARRAY(String))
    similarity_threshold = Column(Float, default=0.8)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    cluster_articles = relationship("ClusterArticle", back_populates="cluster")


class ClusterArticle(Base):
    """Many-to-many relationship between clusters and articles."""
    __tablename__ = "cluster_articles"

    id = Column(Integer, primary_key=True, index=True)
    cluster_id = Column(Integer, ForeignKey("news_clusters.id", ondelete="CASCADE"))
    article_id = Column(Integer, ForeignKey("articles.id", ondelete="CASCADE"))
    similarity_score = Column(Float, nullable=False)
    is_canonical = Column(Boolean, default=False)
    added_at = Column(DateTime, default=func.now())

    # Relationships
    cluster = relationship("NewsCluster", back_populates="cluster_articles")
    article = relationship("Article", back_populates="cluster_articles")


class DailySummary(Base):
    """Daily summary by category model."""
    __tablename__ = "daily_summaries"
    
    id = Column(Integer, primary_key=True, index=True)
    date = Column(DateTime, nullable=False)
    category = Column(String(50), nullable=False)  # Business, Tech, Science, Nature, Serbia, Marketing, Other
    summary_text = Column(Text, nullable=False)
    articles_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class Setting(Base):
    """Application settings model."""
    __tablename__ = "settings"

    key = Column(String(255), primary_key=True)
    value = Column(JSON, nullable=False)
    description = Column(Text)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class ProcessingStat(Base):
    """Processing statistics model."""
    __tablename__ = "processing_stats"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(DateTime, default=func.current_date(), unique=True)
    articles_fetched = Column(Integer, default=0)
    articles_processed = Column(Integer, default=0)
    clusters_created = Column(Integer, default=0)
    clusters_updated = Column(Integer, default=0)
    api_calls_made = Column(Integer, default=0)
    errors_count = Column(Integer, default=0)
    processing_time_seconds = Column(Integer, default=0)


class TaskQueue(Base):
    """Task queue model."""
    __tablename__ = "task_queue"

    id = Column(Integer, primary_key=True, index=True)
    task_type = Column(String(100), nullable=False)
    task_data = Column(JSON, nullable=False)
    status = Column(String(20), default="pending")
    priority = Column(Integer, default=0)
    attempts = Column(Integer, default=0)
    max_attempts = Column(Integer, default=3)
    created_at = Column(DateTime, default=func.now())
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    error_message = Column(Text)


class ScheduleSettings(Base):
    """Schedule settings for automated tasks."""
    __tablename__ = "schedule_settings"

    id = Column(Integer, primary_key=True, index=True)
    task_name = Column(String(100), nullable=False, unique=True)
    enabled = Column(Boolean, default=False)
    
    # Schedule configuration
    schedule_type = Column(String(20), default="daily")  # daily, weekly, hourly, custom
    hour = Column(Integer, default=9)  # 0-23
    minute = Column(Integer, default=0)  # 0-59
    weekdays = Column(JSON, default=list)  # [1,2,3,4,5] for Mon-Fri
    timezone = Column(String(50), default="Europe/Belgrade")
    
    # Task specific settings
    task_config = Column(JSON, default=dict)
    
    last_run = Column(DateTime)
    next_run = Column(DateTime)
    is_running = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


# Extraction learning models for AI-enhanced content extraction
class ExtractionPattern(Base):
    """Extraction pattern model for tracking learned selectors."""
    __tablename__ = "extraction_patterns"
    
    id = Column(Integer, primary_key=True, index=True)
    domain = Column(String(255), nullable=False, index=True)
    selector_pattern = Column(Text, nullable=False)
    extraction_strategy = Column(String(50), nullable=False)
    success_count = Column(Integer, default=0)
    failure_count = Column(Integer, default=0)
    quality_score_avg = Column(DECIMAL(5, 2), default=0)
    content_length_avg = Column(Integer, default=0)
    discovered_by = Column(String(20), default='manual')  # 'manual', 'ai', 'heuristic'
    is_stable = Column(Boolean, default=False)
    last_ai_analysis = Column(DateTime)
    consecutive_successes = Column(Integer, default=0)
    consecutive_failures = Column(Integer, default=0)
    first_success_at = Column(DateTime)
    last_success_at = Column(DateTime)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    __table_args__ = (
        UniqueConstraint('domain', 'selector_pattern', 'extraction_strategy'),
    )


class DomainStability(Base):
    """Domain stability model for tracking extraction reliability."""
    __tablename__ = "domain_stability"
    
    id = Column(Integer, primary_key=True, index=True)
    domain = Column(String(255), unique=True, nullable=False, index=True)
    is_stable = Column(Boolean, default=False, index=True)
    success_rate_7d = Column(DECIMAL(5, 2), default=0)
    success_rate_30d = Column(DECIMAL(5, 2), default=0)
    total_attempts = Column(Integer, default=0)
    successful_attempts = Column(Integer, default=0)
    last_successful_extraction = Column(DateTime)
    last_failed_extraction = Column(DateTime)
    last_ai_analysis = Column(DateTime)
    consecutive_successes = Column(Integer, default=0)
    consecutive_failures = Column(Integer, default=0)
    stability_achieved_at = Column(DateTime)
    needs_reanalysis = Column(Boolean, default=False, index=True)
    ai_credits_saved = Column(Integer, default=0)
    reanalysis_triggers = Column(JSON, default=list)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class ExtractionAttempt(Base):
    """Extraction attempt model for detailed logging."""
    __tablename__ = "extraction_attempts"
    
    id = Column(Integer, primary_key=True, index=True)
    article_url = Column(Text, nullable=False)
    domain = Column(String(255), nullable=False, index=True)
    extraction_strategy = Column(String(50), nullable=False, index=True)
    selector_used = Column(Text)
    success = Column(Boolean, nullable=False, index=True)
    content_length = Column(Integer)
    quality_score = Column(DECIMAL(5, 2))
    extraction_time_ms = Column(Integer)
    error_message = Column(Text)
    ai_analysis_triggered = Column(Boolean, default=False)
    ai_analysis = Column(JSON)
    user_agent = Column(String(500))
    http_status_code = Column(Integer)
    created_at = Column(DateTime, default=func.now(), index=True)


class AIUsageTracking(Base):
    """AI usage tracking model for monitoring costs and effectiveness."""
    __tablename__ = "ai_usage_tracking"
    
    id = Column(Integer, primary_key=True, index=True)
    domain = Column(String(255), nullable=False, index=True)
    analysis_type = Column(String(50), nullable=False, index=True)  # 'selector_discovery', 'pattern_analysis'
    tokens_used = Column(Integer)
    credits_cost = Column(DECIMAL(10, 4))
    analysis_result = Column(JSON)
    patterns_discovered = Column(Integer, default=0)
    patterns_successful = Column(Integer, default=0)
    cost_effectiveness = Column(DECIMAL(5, 2))  # successful patterns / cost ratio
    created_at = Column(DateTime, default=func.now(), index=True)