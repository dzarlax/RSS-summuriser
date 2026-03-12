"""Service for generating AI-powered category summaries."""

import asyncio
import logging
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..models import DailySummary, Article
from ..config import get_settings
from .ai_client import get_ai_client

logger = logging.getLogger(__name__)


class SummaryGenerator:
    """Handles AI generation of category summaries."""

    def __init__(self):
        """Initialize summary generator with configuration."""
        self.settings = get_settings()
        self.ai_client = get_ai_client()
        self.max_retries = self.settings.digest_max_summary_retries
        self.retry_delay = self.settings.digest_retry_delay
        self.max_articles = self.settings.digest_max_articles_per_category
        self.min_summary_length = self.settings.digest_min_summary_length
        self.max_tokens = self.settings.digest_max_summary_tokens

    async def generate_category_summary(
        self,
        category: str,
        articles: List[Article],
        date: Any
    ) -> Optional[str]:
        """
        Generate AI summary for a single category.

        Args:
            category: Category name
            articles: List of articles to summarize
            date: Date for the summary

        Returns:
            Generated summary text or fallback message
        """
        if not articles:
            logger.warning(f"No articles provided for category: {category}")
            return None

        try:
            logger.info(
                f"Generating summary for {category} "
                f"({len(articles)} articles)"
            )

            # Prepare article content for AI
            articles_text = self._prepare_articles_text(articles)

            if not articles_text:
                logger.warning(f"No valid article content for category: {category}")
                return None

            combined_content = "\n\n---\n\n".join(articles_text)

            # Generate summary with retry logic
            summary_text = await self._generate_with_retry(
                category, combined_content
            )

            # Validate and return summary
            if summary_text and len(summary_text.strip()) >= self.min_summary_length:
                logger.info(f"Successfully generated summary for {category}")
                return summary_text
            else:
                logger.warning(
                    f"AI returned short/empty summary for {category}, "
                    f"using fallback"
                )
                return self._create_fallback_summary(category, articles)

        except Exception as e:
            logger.error(f"Error generating summary for {category}: {e}")
            return self._create_fallback_summary(category, articles)

    def _prepare_articles_text(self, articles: List[Article]) -> List[str]:
        """Prepare articles text for AI processing."""
        articles_text = []

        for article in articles[:self.max_articles]:
            title = article.title or ""
            content = article.summary or article.content or ""

            if title and content:
                article_text = (
                    f"Заголовок: {title}\n"
                    f"Содержание: {content[:500]}"
                )
                articles_text.append(article_text)

        return articles_text

    async def _generate_with_retry(
        self,
        category: str,
        content: str
    ) -> Optional[str]:
        """Generate summary with exponential backoff retry."""
        summary_text = None

        for attempt in range(self.max_retries):
            try:
                summary_prompt = self._create_summary_prompt(category, content)

                summary_text = await self.ai_client._call_summary_llm(
                    summary_prompt,
                    max_tokens=self.max_tokens
                )

                if summary_text:
                    summary_text = self.ai_client._clean_summary_text(summary_text)

                # Check if summary is valid
                if summary_text and len(summary_text.strip()) >= self.min_summary_length:
                    return summary_text
                else:
                    logger.warning(
                        f"Attempt {attempt + 1}/{self.max_retries}: "
                        f"AI returned short summary for {category}"
                    )
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(self.retry_delay)

            except Exception as e:
                logger.warning(
                    f"Attempt {attempt + 1}/{self.max_retries}: "
                    f"Error generating summary for {category}: {e}"
                )
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay)

        return None

    def _create_summary_prompt(self, category: str, content: str) -> str:
        """Create AI prompt for category summary generation."""
        return f"""Создай краткую сводку новостей для категории "{category}" на русском языке.

Статьи:
{content}

Требования:
- Максимум 3-4 предложения
- Сосредоточься на главных событиях
- Используй деловой стиль
- Начинай с "В сфере {category.lower()}..."
- Не повторяй одну и ту же информацию
- Завершай мысль полностью
- Не обрезай слова на середине
- Избегай многоточия в конце текста"""

    def _create_fallback_summary(
        self,
        category: str,
        articles: List[Article]
    ) -> str:
        """Create fallback summary when AI generation fails."""
        return (
            f"В сфере {category.lower()} произошли важные события. "
            f"Обработано {len(articles)} новостей."
        )

    async def save_summary(
        self,
        db: AsyncSession,
        date: Any,
        category: str,
        summary_text: str,
        articles_count: int
    ) -> DailySummary:
        """
        Save or update daily summary in database.

        Args:
            db: Database session
            date: Summary date
            category: Category name
            summary_text: Generated summary text
            articles_count: Number of articles processed

        Returns:
            Created or updated DailySummary instance
        """
        existing_result = await db.execute(
            select(DailySummary).where(
                DailySummary.date == date,
                DailySummary.category == category
            )
        )
        existing_summary = existing_result.scalar_one_or_none()

        if existing_summary:
            # Update existing
            existing_summary.summary_text = summary_text
            existing_summary.articles_count = articles_count
            logger.info(f"Updated summary for {category}")
            return existing_summary
        else:
            # Create new
            new_summary = DailySummary(
                date=date,
                category=category,
                summary_text=summary_text,
                articles_count=articles_count
            )
            db.add(new_summary)
            logger.info(f"Created summary for {category}")
            return new_summary

    async def generate_and_save_summaries(
        self,
        db: AsyncSession,
        date: Any,
        categories: Dict[str, List[Article]]
    ) -> Dict[str, int]:
        """
        Generate and save summaries for all categories.

        Args:
            db: Database session
            date: Summary date
            categories: Dictionary mapping category names to article lists

        Returns:
            Dictionary with statistics about generated summaries
        """
        logger.info(f"Starting daily summary generation for {date}")

        stats = {
            "total_categories": len(categories),
            "successful": 0,
            "failed": 0,
            "fallback_used": 0
        }

        # Filter out empty categories
        valid_categories = {
            cat: arts for cat, arts in categories.items()
            if arts and len(arts) > 0
        }

        if not valid_categories:
            logger.warning("No valid categories with articles found")
            return stats

        # Process categories (parallel or sequential based on config)
        if self.settings.digest_parallel_categories:
            results = await self._process_categories_parallel(
                db, date, valid_categories
            )
        else:
            results = await self._process_categories_sequential(
                db, date, valid_categories
            )

        # Collect statistics
        for category, result in results.items():
            if result.get("success"):
                stats["successful"] += 1
                if result.get("fallback"):
                    stats["fallback_used"] += 1
            else:
                stats["failed"] += 1

        await db.commit()
        logger.info(
            f"Daily summary generation completed: "
            f"{stats['successful']} successful, "
            f"{stats['failed']} failed, "
            f"{stats['fallback_used']} fallbacks"
        )

        return stats

    async def _process_categories_parallel(
        self,
        db: AsyncSession,
        date: Any,
        categories: Dict[str, List[Article]]
    ) -> Dict[str, Dict[str, bool]]:
        """Process categories in parallel using asyncio.gather."""
        logger.info("Processing categories in parallel")

        async def process_single_category(cat: str, arts: List[Article]):
            summary = await self.generate_category_summary(cat, arts, date)
            if summary:
                await self.save_summary(db, date, cat, summary, len(arts))
                return {"category": cat, "success": True, "fallback": "В сфере" in summary}
            return {"category": cat, "success": False, "fallback": False}

        tasks = [
            process_single_category(cat, arts)
            for cat, arts in categories.items()
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Convert results to dictionary
        result_dict = {}
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Category processing failed with exception: {result}")
                continue

            if isinstance(result, dict):
                category = result.get("category", "unknown")
                result_dict[category] = {
                    "success": result.get("success", False),
                    "fallback": result.get("fallback", False)
                }

        return result_dict

    async def _process_categories_sequential(
        self,
        db: AsyncSession,
        date: Any,
        categories: Dict[str, List[Article]]
    ) -> Dict[str, Dict[str, bool]]:
        """Process categories sequentially."""
        logger.info("Processing categories sequentially")

        result_dict = {}

        for category, articles in categories.items():
            summary = await self.generate_category_summary(
                category, articles, date
            )

            if summary:
                await self.save_summary(db, date, category, summary, len(articles))
                result_dict[category] = {
                    "success": True,
                    "fallback": "В сфере" in summary
                }
            else:
                result_dict[category] = {
                    "success": False,
                    "fallback": False
                }

        return result_dict
