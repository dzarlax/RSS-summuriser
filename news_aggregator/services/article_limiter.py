"""Service for applying processing limits to articles."""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from sqlalchemy import select, func, and_
from sqlalchemy.orm import InstrumentedAttribute

from ..models import Article
from ..config import get_settings
from ..utils import get_logger

logger = get_logger(__name__, 'ARTICLE_LIMITER')


class ArticleLimiter:
    """Service for limiting article processing based on configuration."""

    def __init__(self):
        """Initialize article limiter with configuration."""
        self.settings = get_settings()
        self.limit_config = self.settings.get_news_limit_config()

    def is_enabled(self) -> bool:
        """Check if article limiting is enabled."""
        return self.limit_config.get('enabled', False)

    def get_max_articles(self) -> Optional[int]:
        """Get maximum articles per processing cycle."""
        return self.limit_config.get('max_articles')

    def get_per_source_limit(self) -> Optional[int]:
        """Get maximum articles per source."""
        return self.limit_config.get('per_source')

    def get_date_range(self) -> tuple[Optional[datetime], Optional[datetime]]:
        """
        Get date range for article filtering.

        Returns:
            Tuple of (date_from, date_to) or (None, None)
        """
        date_from = self.limit_config.get('date_from')
        date_to = self.limit_config.get('newest_date')
        return (date_from, date_to)

    def apply_limits_to_query(self, query) -> Any:
        """
        Apply limit conditions to SQLAlchemy query.

        Args:
            query: SQLAlchemy select query

        Returns:
            Modified query with limit conditions applied
        """
        if not self.is_enabled():
            logger.debug("Article limiting is disabled")
            return query

        logger.info(
            f"Applying article limits: max={self.get_max_articles()}, "
            f"per_source={self.get_per_source_limit()}"
        )

        # Apply max articles limit
        max_articles = self.get_max_articles()
        if max_articles:
            query = query.limit(max_articles)
            logger.debug(f"Applied max articles limit: {max_articles}")

        return query

    def apply_date_filters_to_query(self, query) -> Any:
        """
        Apply date-based filters to SQLAlchemy query.

        Args:
            query: SQLAlchemy select query

        Returns:
            Modified query with date filters applied
        """
        if not self.is_enabled():
            return query

        date_from, date_to = self.get_date_range()

        if date_from:
            query = query.where(Article.published_at >= date_from)
            logger.debug(f"Applied date from filter: {date_from}")

        if date_to:
            query = query.where(Article.published_at <= date_to)
            logger.debug(f"Applied date to filter: {date_to}")

        return query

    async def get_articles_with_limits(
        self,
        db,
        base_query = None,
        eager_loads: List = None
    ) -> List[Article]:
        """
        Get articles with all limits applied.

        Args:
            db: Database session
            base_query: Optional base query to build upon
            eager_loads: Optional list of eager load options

        Returns:
            List of articles matching the limit criteria
        """
        if not self.is_enabled():
            logger.debug("Article limiting is disabled, fetching all matching articles")
            if base_query:
                result = await db.execute(base_query)
            else:
                result = await db.execute(select(Article))
            return result.scalars().all()

        # Build query with limits
        if base_query is None:
            from sqlalchemy.orm import selectinload
            query = select(Article).options(
                selectinload(Article.source)
            )
        else:
            query = base_query

        # Apply date filters
        query = self.apply_date_filters_to_query(query)

        # Apply max articles limit
        query = self.apply_limits_to_query(query)

        # Execute query
        result = await db.execute(query)
        articles = result.scalars().all()

        logger.info(
            f"Retrieved {len(articles)} articles with limits applied "
            f"(max={self.get_max_articles()})"
        )

        return articles

    def filter_articles_by_source(
        self,
        articles: List[Article]
    ) -> Dict[str, List[Article]]:
        """
        Filter and group articles by source with per-source limits.

        Args:
            articles: List of articles to filter

        Returns:
            Dictionary mapping source_id to limited article lists
        """
        if not self.is_enabled():
            # No limiting, group all articles by source
            grouped = {}
            for article in articles:
                source_id = str(article.source_id) if article.source_id else 'unknown'
                if source_id not in grouped:
                    grouped[source_id] = []
                grouped[source_id].append(article)
            return grouped

        per_source_limit = self.get_per_source_limit()
        if not per_source_limit:
            # No per-source limit, return all grouped by source
            grouped = {}
            for article in articles:
                source_id = str(article.source_id) if article.source_id else 'unknown'
                if source_id not in grouped:
                    grouped[source_id] = []
                grouped[source_id].append(article)
            return grouped

        # Apply per-source limits
        grouped = {}
        for article in articles:
            source_id = str(article.source_id) if article.source_id else 'unknown'

            if source_id not in grouped:
                grouped[source_id] = []

            if len(grouped[source_id]) < per_source_limit:
                grouped[source_id].append(article)
            else:
                logger.debug(
                    f"Source {source_id} reached per-source limit "
                    f"({per_source_limit} articles)"
                )

        total_limited = sum(len(arts) for arts in grouped.values())
        logger.info(
            f"Applied per-source limits: {total_limited} articles "
            f"across {len(grouped)} sources (max {per_source_limit} per source)"
        )

        return grouped

    def get_limit_summary(self) -> Dict[str, Any]:
        """
        Get summary of current limit configuration.

        Returns:
            Dictionary with limit configuration summary
        """
        return {
            'enabled': self.is_enabled(),
            'max_articles': self.get_max_articles(),
            'per_source': self.get_per_source_limit(),
            'days': self.limit_config.get('days'),
            'date_from': self.limit_config.get('date_from'),
            'date_to': self.limit_config.get('newest_date'),
            'oldest_date': self.limit_config.get('oldest_date'),
        }

    def log_limit_status(self):
        """Log current limit configuration status."""
        if not self.is_enabled():
            logger.info("Article limiting is DISABLED - all articles will be processed")
            return

        summary = self.get_limit_summary()
        logger.info(
            f"Article limiting ENABLED: "
            f"max={summary['max_articles']} articles, "
            f"per_source={summary['per_source']}, "
            f"days={summary['days']}"
        )

        if summary.get('date_from'):
            logger.info(f"  Date from: {summary['date_from']}")
        if summary.get('date_to'):
            logger.info(f"  Date to: {summary['date_to']}")


def get_article_limiter() -> ArticleLimiter:
    """Get singleton instance of ArticleLimiter."""
    return ArticleLimiter()
