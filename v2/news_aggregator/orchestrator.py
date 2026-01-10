"""Refactored main orchestrator for Evening News v2."""

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text

from .database import get_db
from .database import AsyncSessionLocal
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
        """Run complete news processing cycle without clustering."""
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
            print(f"🚀 Starting full news processing cycle at {start_time.strftime('%H:%M:%S')}")
            
            # Step 1: Sync sources and fetch articles
            print("📥 Step 1: Syncing sources and fetching articles...")
            sync_start = time.time()

            # Step 1a: Get sources list (quick DB read)
            print("  📋 Getting enabled sources...")
            sources = await self.source_manager.get_sources_from_db()
            print(f"  ✅ Found {len(sources)} enabled sources")

            # Step 1b: HTTP fetching (NO DB transaction - semaphore free!)
            print("  🌐 Fetching articles via HTTP (no DB lock)...")
            fetch_start = time.time()

            # HTTP fetching happens here WITHOUT database lock
            raw_articles = await self.source_manager.fetch_from_all_sources_no_db(sources)

            fetch_duration = time.time() - fetch_start
            print(f"  ✅ HTTP fetching completed in {fetch_duration:.1f}s")

            # Step 1c: Save articles to database (quick DB write)
            print("  💾 Saving articles to database...")
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
            print(f"  ✅ Saved {total_articles} articles in {save_duration:.1f}s")

            stats.update({
                'sources_synced': len(sync_result),
                'articles_fetched': total_articles
            })

            sync_duration = time.time() - sync_start
            stats['performance']['sync_duration'] = sync_duration
            print(f"  ✅ Total sync: {stats['sources_synced']} sources, {stats['articles_fetched']} articles in {sync_duration:.1f}s")
            
            # Step 2: Process articles with AI
            print("🤖 Step 2: Processing articles with AI...")
            process_start = time.time()
            
            processing_result = await self._process_unprocessed_articles(stats)
            stats.update(processing_result)
            
            process_duration = time.time() - process_start
            stats['performance']['processing_duration'] = process_duration
            print(f"  ✅ Processed {stats['articles_processed']} articles in {process_duration:.1f}s")
            
            # Calculate total duration
            end_time = datetime.utcnow()
            total_duration = (end_time - start_time).total_seconds()
            stats['end_time'] = end_time.isoformat()
            stats['total_duration'] = total_duration
            stats['duration_seconds'] = total_duration
            
            # Summary
            print(f"Processing cycle completed in {total_duration:.1f}s")
            print(f"   {stats['articles_processed']} articles processed")
            print(f"   {len(stats['categories_found'])} categories found")
            print(f"   {stats['api_calls_made']} API calls made")

            # Persist processing stats for dashboard
            try:
                from .processing.processing_stats_service import get_processing_stats_service
                processing_stats_service = get_processing_stats_service()
                async with AsyncSessionLocal() as stats_db:
                    await processing_stats_service.update_processing_stats(stats_db, stats)
            except Exception as e:
                print(f"  Failed to update processing stats: {e}")

            return stats
            
        except Exception as e:
            import traceback
            error_msg = f"Error in full processing cycle: {str(e)}"
            print(f"❌ {error_msg}")
            print(f"📍 Traceback:\n{traceback.format_exc()}")
            stats['errors'].append(error_msg)
            return stats
    
    async def send_telegram_digest(self) -> Dict[str, Any]:
        """Generate and send Telegram digest."""
        try:
            print("📱 Generating and sending Telegram digest...")
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
                print("📊 No daily summaries found for today - generating them first...")
                summary_result = await self._generate_daily_summaries(timeout=300.0)
                print(f"  ✅ Generated {summary_result.get('summaries_generated', 0)} daily summaries")
            else:
                print(f"📊 Using existing {summaries_count} daily summaries for today")

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
                from .models import ArticleCategory
                from .services.category_display_service import get_category_display_service

                result = await db.execute(
                    select(Article, ArticleCategory.ai_category, ArticleCategory.confidence)
                    .join(ArticleCategory, Article.id == ArticleCategory.article_id)
                    .where(Article.fetched_at >= today)
                    .order_by(Article.fetched_at.desc())
                )

                category_display_service = await get_category_display_service(db)
                category_cache = {}
                best_by_article = {}

                for article, ai_category, confidence in result.all():
                    current = best_by_article.get(article.id)
                    if current is None or (confidence or 0) > (current['confidence'] or 0):
                        best_by_article[article.id] = {
                            'article': article,
                            'ai_category': ai_category or 'Other',
                            'confidence': confidence or 0
                        }

                articles_by_category = {}
                for item in best_by_article.values():
                    article = item['article']
                    ai_key = (item['ai_category'] or 'Other').strip() or 'Other'
                    if ai_key not in category_cache:
                        display = await category_display_service.map_ai_category_to_display(ai_key)
                        # Use English name for database storage, not display_name (Russian)
                        category_cache[ai_key] = display.get('name') or display.get('display_name') or ai_key

                    category_name = category_cache[ai_key]
                    if category_name not in articles_by_category:
                        articles_by_category[category_name] = []

                    if len(articles_by_category[category_name]) >= 10:
                        continue

                    articles_by_category[category_name].append({
                        "headline": article.title,
                        "description": article.summary or article.content or "",
                        "links": [article.url] if article.url else [],
                        "image_url": article.primary_image or article.image_url
                    })

                return articles_by_category

            telegraph_url = None
            try:
                from .services.telegraph_service import TelegraphService
                telegraph_service = TelegraphService()
                telegraph_payload = await self.db_queue_manager.execute_read(build_telegraph_payload, timeout=30.0)
                telegraph_url = await telegraph_service.create_news_page(telegraph_payload)
            except Exception as e:
                print(f"⚠️ Telegraph generation failed: {e}")

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
            print(f"❌ {error_msg}")
            return {'success': False, 'error': error_msg}
    
    async def _process_unprocessed_articles(self, stats: Dict[str, Any]) -> Dict[str, Any]:
        """Process unprocessed articles using specialized processors."""
        try:
            # Step 1: Get articles from database (quick transaction)
            print("  📋 Fetching unprocessed articles from database...")
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

            print(f"  🔄 Processing {len(articles_data)} unprocessed articles (transaction closed)...")

            # Step 2: Process with AI (NO database transaction - semaphore is free!)
            processed_count = 0
            summarized_count = 0
            categorized_count = 0

            for article_data in articles_data:
                try:
                    source_type = article_data['source_type']
                    article_url = article_data['url']
                    article_id = article_data['id']

                    # Process summary if needed
                    if not article_data['summary_processed']:
                        stats['api_calls_made'] += 1

                        # Create temp article object for compatibility
                        class TempArticle:
                            def __init__(self, data):
                                self.id = data['id']
                                self.url = data['url']
                                self.title = data['title']
                                self.content = data['content']
                                self.summary = data['summary']
                                self.published_at = data['published_at']

                        temp_article = TempArticle(article_data)
                        summary = await self.ai_processor.get_summary_by_source_type(
                            temp_article, source_type, stats
                        )

                        if summary:
                            article_data['summary'] = summary
                            summarized_count += 1

                    # Process category if needed
                    if not article_data['category_processed']:
                        stats['api_calls_made'] += 1

                        class TempArticle2:
                            def __init__(self, data):
                                self.id = data['id']
                                self.url = data['url']
                                self.title = data['title']
                                self.content = data['content']
                                self.summary = data.get('summary') or data['content']
                                self.published_at = data['published_at']

                        temp_article2 = TempArticle2(article_data)
                        categories = await self.categorization_processor.categorize_by_source_type_new(
                            temp_article2, source_type, stats
                        )

                        if categories:
                            article_data['categories'] = categories
                            categorized_count += 1

                    article_data['summary_processed'] = True
                    article_data['category_processed'] = True
                    article_data['ad_processed'] = True  # Mark as processed
                    processed_count += 1

                except Exception as e:
                    print(f"  ⚠️ Error processing article {article_url}: {e}")
                    continue

            print(f"  ✅ AI processing completed: {processed_count} articles, {summarized_count} summaries, {categorized_count} categories")

            # Step 3: Save results to database (new transaction, only writes)
            print("  💾 Saving processed results to database...")

            async def save_results_operation(db):
                updated_count = 0
                for article_data in articles_data:
                    try:
                        # Get article
                        article = await db.get(Article, article_data['id'])
                        if not article:
                            continue

                        # Update fields (don't update categories - handled separately)
                        if article_data.get('summary') and article_data['summary'] != article.summary:
                            article.summary = article_data['summary']

                        article.summary_processed = article_data['summary_processed']
                        article.category_processed = article_data['category_processed']
                        article.ad_processed = article_data['ad_processed']
                        article.processed = all([
                            article_data['summary_processed'],
                            article_data['category_processed'],
                            article_data['ad_processed']
                        ])

                        updated_count += 1

                    except Exception as e:
                        print(f"  ⚠️ Error saving article {article_data['id']}: {e}")
                        continue

                return updated_count

            saved_count = await self.db_queue_manager.execute_write(save_results_operation, timeout=30.0)
            print(f"  ✅ Saved {saved_count} processed articles to database")

            return {
                'articles_processed': processed_count,
                'articles_summarized': summarized_count,
                'articles_categorized': categorized_count
            }

        except Exception as e:
            error_msg = f"Error processing unprocessed articles: {e}"
            print(f"  ❌ {error_msg}")
            stats['errors'].append(error_msg)
            return {'articles_processed': 0, 'articles_summarized': 0, 'articles_categorized': 0}
    
    async def _generate_daily_summaries(self, timeout: float = 60.0) -> Dict[str, Any]:
        """Generate daily summaries using digest builder."""
        try:
            today = datetime.utcnow().date()
            
            # Use database queue for summary generation
            async def summary_operation(db):
                # Get today's articles with AI categories and confidence
                from .models import ArticleCategory
                from .services.category_display_service import get_category_display_service

                result = await db.execute(
                    select(Article, ArticleCategory.ai_category, ArticleCategory.confidence)
                    .join(ArticleCategory, Article.id == ArticleCategory.article_id)
                    .where(Article.fetched_at >= today)
                    .order_by(Article.fetched_at.desc())
                )

                category_display_service = await get_category_display_service(db)
                category_cache = {}
                best_by_article = {}

                for article, ai_category, confidence in result.all():
                    current = best_by_article.get(article.id)
                    if current is None or (confidence or 0) > (current['confidence'] or 0):
                        best_by_article[article.id] = {
                            'article': article,
                            'ai_category': ai_category or 'Other',
                            'confidence': confidence or 0
                        }

                # Group articles by mapped category (best confidence only)
                categories = {}
                for item in best_by_article.values():
                    article = item['article']
                    ai_key = (item['ai_category'] or 'Other').strip() or 'Other'
                    if ai_key not in category_cache:
                        display = await category_display_service.map_ai_category_to_display(ai_key)
                        # Use English name for database storage, not display_name (Russian)
                        category_cache[ai_key] = display.get('name') or display.get('display_name') or ai_key

                    category_name = category_cache[ai_key]
                    categories.setdefault(category_name, []).append(article)

                # Generate summaries using digest builder
                await self.digest_builder.generate_and_save_daily_summaries(db, today, categories)

                return {'summaries_generated': len(categories)}
            
            return await self.db_queue_manager.execute_write(summary_operation, timeout=timeout)
                
        except Exception as e:
            error_msg = f"Error generating daily summaries: {e}"
            print(f"  ❌ {error_msg}")
            return {'summaries_generated': 0, 'error': error_msg}
    
    async def _save_ai_categories_to_database(self, db: AsyncSession, article_id: int, ai_categories: List[Dict[str, Any]]):
        """Save AI categories directly to database without mapping (mapping happens at display time)."""
        try:
            from .models import ArticleCategory
            from sqlalchemy import text
            
            # Clear existing categories for this article
            await db.execute(
                text("DELETE FROM article_categories WHERE article_id = :article_id"),
                {'article_id': article_id}
            )
            
            # Save AI categories directly with NULL category_id (will be mapped at display time)
            for cat_data in ai_categories:
                ai_category_name = cat_data.get('name', 'Other')
                confidence = cat_data.get('confidence', 1.0)
                
                # Create article-category relationship with AI category name stored
                article_category = ArticleCategory(
                    article_id=article_id,
                    category_id=None,  # No fixed category assignment at storage
                    confidence=confidence,
                    ai_category=ai_category_name  # Store original AI category
                )
                db.add(article_category)
                
            print(f"  🏷️ Saved {len(ai_categories)} AI categories for article {article_id}")
            for cat in ai_categories:
                print(f"    - {cat.get('name', 'Unknown')} (confidence: {cat.get('confidence', 1.0)})")
                
        except Exception as e:
            print(f"  ⚠️ Error saving AI categories: {e}")
    
    async def _save_article_categories(self, article_id: int, categories: List[Dict[str, Any]]):
        """Save article categories using new system (creates own session for backwards compatibility)."""
        try:
            async def category_operation(db):
                await self._save_article_categories_in_session(db, article_id, categories)
                return {'success': True}
            
            await self.db_queue_manager.execute_write(category_operation)
                
        except Exception as e:
            print(f"  ⚠️ Error saving article categories: {e}")
    
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
