"""Refactored main orchestrator for Evening News v2."""

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text

from .models import Source, Article, ProcessingStat, DailySummary
from .services.source_manager import SourceManager
from .processing.ai_processor import AIProcessor
from .processing.summarization_processor import SummarizationProcessor
from .processing.categorization_processor import CategorizationProcessor
from .processing.digest_builder import DigestBuilder
from .processing.stats_collector import StatsCollector
from .services.ai_client import get_ai_client
from .services.telegram_service import get_telegram_service
from .services.database_queue import get_database_queue, DatabaseQueueManager
from .services.article_limiter import get_article_limiter, ArticleLimiter
from .core.exceptions import NewsAggregatorError
from .config import settings

logger = logging.getLogger(__name__)


@dataclass
class ArticleDTO:
    """Lightweight article data transfer object for AI processing."""
    id: int
    url: str
    title: str
    content: Optional[str]
    summary: Optional[str]
    published_at: Optional[datetime]

    @classmethod
    def for_summarization(cls, data: Dict[str, Any]) -> "ArticleDTO":
        return cls(
            id=data['id'],
            url=data['url'],
            title=data['title'],
            content=data['content'],
            summary=data['summary'],
            published_at=data['published_at'],
        )

    @classmethod
    def for_categorization(cls, data: Dict[str, Any]) -> "ArticleDTO":
        return cls(
            id=data['id'],
            url=data['url'],
            title=data['title'],
            content=data['content'],
            summary=data.get('summary') or data['content'],
            published_at=data['published_at'],
        )


class NewsOrchestrator:
    """Main orchestrator for news processing - refactored with modular processors."""
    
    def __init__(self):
        self.source_manager = SourceManager()
        self.ai_processor = AIProcessor()
        self.ai_client = get_ai_client()
        self.telegram_service = get_telegram_service()

        # Use new universal database queue system
        self.db_queue_manager = get_database_queue()

        # Initialize specialized processors
        self.summarization_processor = SummarizationProcessor()
        self.categorization_processor = CategorizationProcessor()
        self.digest_builder = DigestBuilder()
        self.stats_collector = StatsCollector()

        # Article limiter for processing limits
        self.article_limiter = get_article_limiter()
        # Log limit status on startup
        self.article_limiter.log_limit_status()

        # Legacy queue for backward compatibility (will be removed)
        self.db_queue = None
    
    async def start(self):
        """Start the orchestrator and its database queue."""
        await self.db_queue_manager.start()
        
    async def stop(self):
        """Stop the orchestrator and its database queue."""
        await self.db_queue_manager.stop()
        
    def get_queue_stats(self) -> Dict[str, Any]:
        """Get database queue statistics."""
        return self.db_queue_manager.get_stats()
        
    async def run_full_cycle(self) -> Dict[str, Any]:
        """Run complete news processing cycle."""
        start_time = datetime.utcnow()
        stats = {
            'start_time': start_time.isoformat(),
            'sources_synced': 0,
            'articles_fetched': 0,
            'articles_processed': 0,
            'articles_summarized': 0,
            'articles_categorized': 0,
            'categories_found': set(),
            'api_calls_made': 0,
            'errors': [],
            'performance': {}
        }
        
        try:
            logger.info(f"🚀 Starting full news processing cycle at {start_time.strftime('%H:%M:%S')}")
            # Step 1: Sync sources and fetch articles
            logger.info("📥 Step 1: Syncing sources and fetching articles...")
            sync_start = time.time()

            # Step 1a: Get sources list (quick DB read)
            logger.info("  📋 Getting enabled sources...")
            sources = await self.source_manager.get_sources_from_db()
            logger.info(f"  ✅ Found {len(sources)} enabled sources")
            # Step 1b: HTTP fetching (NO DB transaction - semaphore free!)
            logger.info("  🌐 Fetching articles via HTTP (no DB lock)...")
            fetch_start = time.time()

            # HTTP fetching happens here WITHOUT database lock
            raw_articles = await self.source_manager.fetch_from_all_sources_no_db(sources)

            fetch_duration = time.time() - fetch_start
            logger.info(f"  ✅ HTTP fetching completed in {fetch_duration:.1f}s")
            # Step 1c: Save articles to database (quick DB write)
            logger.info("  💾 Saving articles to database...")
            save_start = time.time()

            async def save_operation(db):
                # Refresh sources with DB session
                from sqlalchemy import select
                source_query = select(Source).where(Source.enabled == True)
                result = await db.execute(source_query)
                sources_db = result.scalars().all()

                # Create source name -> source mapping
                source_map = {s.name: s for s in sources_db}

                return await self.source_manager.save_fetched_articles_with_sources(raw_articles, source_map, db)

            sync_result = await self.db_queue_manager.execute_write(save_operation, timeout=30.0)
            total_articles = sum(len(articles) for articles in sync_result.values())

            save_duration = time.time() - save_start
            logger.info(f"  ✅ Saved {total_articles} articles in {save_duration:.1f}s")
            stats.update({
                'sources_synced': len(sync_result),
                'articles_fetched': total_articles
            })

            sync_duration = time.time() - sync_start
            stats['performance']['sync_duration'] = sync_duration
            logger.info(f"  ✅ Total sync: {stats['sources_synced']} sources, {stats['articles_fetched']} articles in {sync_duration:.1f}s")
            # Step 2: Process articles with AI
            logger.info("🤖 Step 2: Processing articles with AI...")
            process_start = time.time()
            
            processing_result = await self._process_unprocessed_articles(stats)
            stats.update(processing_result)
            
            process_duration = time.time() - process_start
            stats['performance']['processing_duration'] = process_duration
            logger.info(f"  ✅ Processed {stats['articles_processed']} articles in {process_duration:.1f}s")
            # Calculate total duration
            end_time = datetime.utcnow()
            total_duration = (end_time - start_time).total_seconds()
            stats['end_time'] = end_time.isoformat()
            stats['total_duration'] = total_duration
            stats['duration_seconds'] = total_duration
            
            # Summary
            logger.info(f"Processing cycle completed in {total_duration:.1f}s")
            logger.info(f"   {stats['articles_processed']} articles processed")
            logger.info(f"   {len(stats['categories_found'])} categories found")
            logger.info(f"   {stats['api_calls_made']} API calls made")
            # Persist processing stats for dashboard
            try:
                from .processing.processing_stats_service import get_processing_stats_service
                processing_stats_service = get_processing_stats_service()
                await self.db_queue_manager.execute_write(
                    lambda db: processing_stats_service.update_processing_stats(db, stats)
                )
            except Exception as e:
                logger.info(f"  Failed to update processing stats: {e}")
            return stats
            
        except Exception as e:
            import traceback
            error_msg = f"Error in full processing cycle: {str(e)}"
            logger.error(f"❌ {error_msg}")
            logger.info(f"📍 Traceback:\n{traceback.format_exc()}")
            stats['errors'].append(error_msg)
            return stats
    
    async def send_telegram_digest(self) -> Dict[str, Any]:
        """Generate and send Telegram digest."""
        try:
            logger.info("📱 Generating and sending Telegram digest...")
            today = datetime.utcnow().date()

            # Step 1: Check if daily summaries exist (fast read)
            async def check_summaries_operation(db):
                from .models import DailySummary
                from sqlalchemy import select, func

                result = await db.execute(
                    select(func.count(DailySummary.id)).where(DailySummary.date == today)
                )
                return int(result.scalar() or 0)

            summaries_count = await self.db_queue_manager.execute_read(check_summaries_operation, timeout=30.0)

            # Step 2: Generate missing daily summaries (potentially slow write + AI)
            if summaries_count == 0:
                logger.info("📊 No daily summaries found for today - generating them first...")
                summary_result = await self._generate_daily_summaries(timeout=300.0)
                logger.info(f"  ✅ Generated {summary_result.get('summaries_generated', 0)} daily summaries")
            else:
                logger.info(f"📊 Using existing {summaries_count} daily summaries for today")
            # Step 3: Build digest (read-only operation)
            async def build_digest_operation(db):
                digest_content = await self.digest_builder.create_combined_digest(db, today)

                if digest_content == "SPLIT_NEEDED":
                    # Use new method that handles splitting internally
                    digest_parts = await self.digest_builder.create_digest_parts(db, today)

                    if not digest_parts or digest_parts[0] == "Сводки новостей пока не готовы.":
                        return {'error': 'No valid summaries found'}

                    return {'digest_parts': digest_parts, 'split': True}

                return {'digest_content': digest_content, 'split': False}

            digest_result = await self.db_queue_manager.execute_read(build_digest_operation, timeout=30.0)

            # Step 4: Build Telegraph page (read-only operation)
            async def build_telegraph_payload(db):
                grouped = await self._group_articles_by_category(db, today)
                articles_by_category = {}
                for category_name, articles in grouped.items():
                    articles_by_category[category_name] = [
                        {
                            "headline": a.title,
                            "description": a.summary or a.content or "",
                            "links": [a.url] if a.url else [],
                            "image_url": a.primary_image or a.image_url,
                        }
                        for a in articles[:10]
                    ]
                return articles_by_category

            telegraph_url = None
            try:
                from .services.telegraph_service import TelegraphService
                telegraph_service = TelegraphService()
                telegraph_payload = await self.db_queue_manager.execute_read(build_telegraph_payload, timeout=30.0)
                telegraph_url = await telegraph_service.create_news_page(telegraph_payload)
            except Exception as e:
                logger.warning(f"⚠️ Telegraph generation failed: {e}")
            if digest_result.get('split'):
                # Send multiple parts
                if telegraph_url:
                    link_line = f"\n<b>Полная версия:</b> <a href=\"{telegraph_url}\">Telegraph</a>"
                    digest_result['digest_parts'][0] = digest_result['digest_parts'][0] + link_line

                sent_ok = 0
                for part in digest_result['digest_parts']:
                    if await self.telegram_service.send_message(part):
                        sent_ok += 1
                return {'success': sent_ok == len(digest_result['digest_parts']), 'parts_sent': sent_ok}
            else:
                # Send single message
                digest_content = digest_result['digest_content']
                if telegraph_url:
                    digest_content += f"\n<b>Полная версия:</b> <a href=\"{telegraph_url}\">Telegraph</a>"
                ok = await self.telegram_service.send_message(digest_content)
                return {'success': bool(ok), 'parts_sent': 1 if ok else 0}
                
        except Exception as e:
            error_msg = f"Error sending Telegram digest ({type(e).__name__}): {e}"
            logger.error(f"❌ {error_msg}")
            return {'success': False, 'error': error_msg}
    
    async def _process_unprocessed_articles(self, stats: Dict[str, Any]) -> Dict[str, Any]:
        """Process unprocessed articles using specialized processors."""
        try:
            # Step 1: Get articles from database (quick transaction)
            logger.info("  📋 Fetching unprocessed articles from database...")
            from sqlalchemy.orm import selectinload

            async def fetch_articles_operation(db):
                # Build base query
                unprocessed_query = select(Article).options(
                    selectinload(Article.source)  # Eager load source
                ).where(
                    (Article.processed == False) |
                    (Article.summary_processed == False) |
                    (Article.category_processed == False) |
                    (Article.ad_processed == False)
                )

                # Apply limits
                unprocessed_query = self.article_limiter.apply_limits_to_query(unprocessed_query)
                unprocessed_query = self.article_limiter.apply_date_filters_to_query(unprocessed_query)

                result = await db.execute(unprocessed_query)
                articles = result.scalars().all()

                # Convert to list of dicts for processing outside transaction
                return [
                    {
                        'id': a.id,
                        'title': a.title,
                        'url': a.url,
                        'content': a.content,
                        'summary': a.summary,
                        'source_id': a.source_id,
                        'source_type': a.source.source_type if a.source else 'rss',
                        'published_at': a.published_at,
                        'summary_processed': a.summary_processed,
                        'category_processed': a.category_processed,
                        'ad_processed': a.ad_processed,
                    }
                    for a in articles
                ]

            articles_data = await self.db_queue_manager.execute_read(fetch_articles_operation, timeout=10.0)

            if not articles_data:
                return {'articles_processed': 0, 'articles_summarized': 0, 'articles_categorized': 0}

            logger.info(f"  🔄 Processing {len(articles_data)} unprocessed articles (transaction closed)...")
            # Step 2: Process with AI in parallel (NO database transaction - semaphore is free!)
            processed_count = 0
            summarized_count = 0
            categorized_count = 0
            _lock = asyncio.Lock()

            # Max 5 articles processed concurrently to avoid hammering the AI API
            _ai_semaphore = asyncio.Semaphore(5)

            async def _process_one(article_data: dict) -> bool:
                nonlocal processed_count, summarized_count, categorized_count
                async with _ai_semaphore:
                    try:
                        source_type = article_data['source_type']
                        article_url = article_data['url']

                        if not article_data['summary_processed']:
                            async with _lock:
                                stats['api_calls_made'] += 1
                            summary_result = await self.ai_processor.get_summary_by_source_type(
                                ArticleDTO.for_summarization(article_data), source_type, stats
                            )
                            summary = summary_result.get('summary') if isinstance(summary_result, dict) else summary_result
                            optimized_title = summary_result.get('optimized_title') if isinstance(summary_result, dict) else None
                            if summary:
                                article_data['summary'] = summary
                                async with _lock:
                                    summarized_count += 1
                            if optimized_title and optimized_title != article_data.get('title'):
                                article_data['title'] = optimized_title

                        if not article_data['category_processed']:
                            async with _lock:
                                stats['api_calls_made'] += 1
                            categories = await self.categorization_processor.categorize_by_source_type_new(
                                ArticleDTO.for_categorization(article_data), source_type, stats
                            )
                            if categories:
                                article_data['categories'] = categories
                                async with _lock:
                                    categorized_count += 1

                        article_data['summary_processed'] = True
                        article_data['category_processed'] = True
                        article_data['ad_processed'] = True
                        async with _lock:
                            processed_count += 1
                        return True

                    except Exception as e:
                        logger.warning(f"  ⚠️ Error processing article {article_data.get('url')}: {e}")
                        return False

            await asyncio.gather(*[_process_one(a) for a in articles_data])
            logger.info(f"  ✅ AI processing completed: {processed_count} articles, {summarized_count} summaries, {categorized_count} categories")
            # Step 3: Save results to database (new transaction, only writes)
            logger.info("  💾 Saving processed results to database...")
            async def save_results_operation(db):
                updated_count = 0

                # Batch-load all articles in one query instead of N×db.get()
                article_ids = [a['id'] for a in articles_data]
                result = await db.execute(select(Article).where(Article.id.in_(article_ids)))
                articles_by_id = {a.id: a for a in result.scalars().all()}

                # Pre-load categories once for all articles
                from .models import Category
                cat_result = await db.execute(select(Category))
                categories_by_name: Dict[str, int] = {
                    c.name.lower(): c.id for c in cat_result.scalars().all()
                }

                for article_data in articles_data:
                    try:
                        article = articles_by_id.get(article_data['id'])
                        if not article:
                            continue

                        if article_data.get('summary') and article_data['summary'] != article.summary:
                            article.summary = article_data['summary']

                        if article_data.get('title') and article_data['title'] != article.title:
                            article.title = article_data['title']

                        article.summary_processed = article_data['summary_processed']
                        article.category_processed = article_data['category_processed']
                        article.ad_processed = article_data['ad_processed']
                        article.processed = all([
                            article_data['summary_processed'],
                            article_data['category_processed'],
                            article_data['ad_processed']
                        ])

                        # Save categories in the same transaction
                        categories = article_data.get('categories')
                        if categories:
                            await self._save_ai_categories_to_database(
                                db, article_data['id'], categories,
                                preloaded_categories=categories_by_name
                            )

                        updated_count += 1

                    except Exception as e:
                        logger.warning(f"  ⚠️ Error saving article {article_data['id']}: {e}")
                        continue

                return updated_count

            saved_count = await self.db_queue_manager.execute_write(save_results_operation, timeout=30.0)
            logger.info(f"  ✅ Saved {saved_count} processed articles to database")
            return {
                'articles_processed': processed_count,
                'articles_summarized': summarized_count,
                'articles_categorized': categorized_count
            }

        except Exception as e:
            error_msg = f"Error processing unprocessed articles: {e}"
            logger.error(f"  ❌ {error_msg}")
            stats['errors'].append(error_msg)
            return {'articles_processed': 0, 'articles_summarized': 0, 'articles_categorized': 0}
    
    async def _generate_daily_summaries(self, timeout: float = 60.0) -> Dict[str, Any]:
        """Generate daily summaries: read articles, generate AI summaries, save to DB."""
        try:
            today = datetime.utcnow().date()

            # Step 1: Read articles grouped by category (fast read, no AI)
            async def read_op(db):
                return await self._group_articles_by_category(db, today)

            categories = await self.db_queue_manager.execute_read(read_op, timeout=30.0)

            if not categories:
                logger.info("  📭 No articles found for daily summary generation")
                return {'summaries_generated': 0}

            # Step 2: Generate AI summaries outside any DB lock
            summary_generator = self.digest_builder.summary_generator
            generated: Dict[str, Any] = {}
            for category, articles in categories.items():
                if not articles:
                    continue
                summary_text = await summary_generator.generate_category_summary(
                    category, articles, today
                )
                if summary_text:
                    generated[category] = (summary_text, len(articles))

            if not generated:
                logger.warning("  ⚠️ No summaries generated by AI")
                return {'summaries_generated': 0}

            # Step 3: Save summaries to DB (fast write, no AI)
            async def write_op(db):
                for cat, (text, count) in generated.items():
                    await summary_generator.save_summary(db, today, cat, text, count)
                return {'summaries_generated': len(generated)}

            return await self.db_queue_manager.execute_write(write_op, timeout=30.0)

        except Exception as e:
            error_msg = f"Error generating daily summaries: {e}"
            logger.error(f"  ❌ {error_msg}")
            return {'summaries_generated': 0, 'error': error_msg}
    
    async def _group_articles_by_category(self, db: AsyncSession, date) -> Dict[str, List[Article]]:
        """Fetch today's articles and group them by mapped display category (best confidence per article)."""
        from .models import ArticleCategory
        from .services.category_display_service import get_category_display_service

        result = await db.execute(
            select(Article, ArticleCategory.ai_category, ArticleCategory.confidence)
            .join(ArticleCategory, Article.id == ArticleCategory.article_id)
            .where(func.date(Article.fetched_at) == date)
            .order_by(Article.fetched_at.desc())
        )

        category_display_service = await get_category_display_service(db)
        category_cache: Dict[str, str] = {}
        best_by_article: Dict[int, Dict] = {}

        for article, ai_category, confidence in result.all():
            current = best_by_article.get(article.id)
            if current is None or (confidence or 0) > (current['confidence'] or 0):
                best_by_article[article.id] = {
                    'article': article,
                    'ai_category': ai_category or 'Other',
                    'confidence': confidence or 0,
                }

        grouped: Dict[str, List[Article]] = {}
        for item in best_by_article.values():
            article = item['article']
            ai_key = (item['ai_category'] or 'Other').strip() or 'Other'
            if ai_key not in category_cache:
                display = await category_display_service.map_ai_category_to_display(ai_key)
                category_cache[ai_key] = display.get('name') or display.get('display_name') or ai_key
            grouped.setdefault(category_cache[ai_key], []).append(article)

        return grouped

    async def _save_ai_categories_to_database(self, db: AsyncSession, article_id: int,
                                              ai_categories: List[Dict[str, Any]],
                                              preloaded_categories: Optional[Dict[str, int]] = None):
        """Save AI categories to database, resolving category_id via display service mapping.

        Pass preloaded_categories to avoid repeated SELECT Category queries when saving
        multiple articles in the same transaction.
        """
        try:
            from sqlalchemy import text
            from .services.category_display_service import get_category_display_service

            # Clear existing categories for this article
            await db.execute(
                text("DELETE FROM article_categories WHERE article_id = :article_id"),
                {'article_id': article_id}
            )

            category_display_service = await get_category_display_service(db)

            # Use preloaded categories if provided, otherwise load from DB
            if preloaded_categories is not None:
                categories_by_name = preloaded_categories
            else:
                from .models import Category
                result = await db.execute(select(Category))
                categories_by_name = {c.name.lower(): c.id for c in result.scalars().all()}

            other_id = categories_by_name.get('other')

            for cat_data in ai_categories:
                ai_category_name = cat_data.get('name', 'Other')
                confidence = cat_data.get('confidence', 1.0)

                display = await category_display_service.map_ai_category_to_display(ai_category_name)
                display_name = (display.get('name') or display.get('display_name') or ai_category_name).lower()
                category_id = categories_by_name.get(display_name) or other_id

                if category_id is None:
                    logger.warning(f"  ⚠️ No category found for '{ai_category_name}', skipping")
                    continue

                await db.execute(
                    text(
                        "INSERT IGNORE INTO article_categories "
                        "(article_id, category_id, confidence, ai_category, created_at) "
                        "VALUES (:article_id, :category_id, :confidence, :ai_category, now())"
                    ),
                    {
                        'article_id': article_id,
                        'category_id': category_id,
                        'confidence': confidence,
                        'ai_category': ai_category_name,
                    }
                )

            logger.debug(f"  Saved {len(ai_categories)} AI categories for article {article_id}")
        except Exception as e:
            logger.warning(f"  ⚠️ Error saving AI categories: {e}")
    # Delegate methods to specialized processors
    async def get_processing_stats(self, days: int = 7) -> Dict[str, Any]:
        """Get processing statistics."""
        return await self.stats_collector.get_processing_stats(days)
    
    async def reprocess_failed_extractions(self, limit: int = 50, dry_run: bool = False) -> Dict[str, Any]:
        """Reprocess failed content extractions."""
        return await self.stats_collector.reprocess_failed_extractions(limit, dry_run)
    
    # Legacy method compatibility (delegate to processors)
    async def _get_summary_by_source_type(self, article: Article, source_type: str, stats: Dict[str, Any]) -> str:
        """Legacy method - delegate to summarization processor."""
        return await self.summarization_processor.get_summary_by_source_type(article, source_type, stats)
    
    async def _categorize_by_source_type_new(self, article: Article, source_type: str, stats: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Legacy method - delegate to categorization processor."""
        return await self.categorization_processor.categorize_by_source_type_new(article, source_type, stats)
    
    async def _create_combined_digest(self, db: AsyncSession, date) -> str:
        """Legacy method - delegate to digest builder."""
        return await self.digest_builder.create_combined_digest(db, date)
