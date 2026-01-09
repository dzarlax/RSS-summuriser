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
            
            # Use database queue for sync operation
            async def sync_operation(db):
                return await self.source_manager.fetch_from_all_sources(db)
            
            sync_result = await self.db_queue_manager.execute_write(sync_operation)
            total_articles = sum(len(articles) for articles in sync_result.values())
            stats.update({
                'sources_synced': len(sync_result),
                'articles_fetched': total_articles
            })
            
            sync_duration = time.time() - sync_start
            stats['performance']['sync_duration'] = sync_duration
            print(f"  ✅ Synced {stats['sources_synced']} sources, fetched {stats['articles_fetched']} articles in {sync_duration:.1f}s")
            
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
            error_msg = f"Error in full processing cycle: {e}"
            print(f"❌ {error_msg}")
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
                    from .models import DailySummary
                    from sqlalchemy import select

                    result = await db.execute(
                        select(DailySummary).where(DailySummary.date == today)
                        .order_by(DailySummary.articles_count.desc())
                    )
                    summaries = result.scalars().all()

                    # Filter out empty summaries
                    valid_summaries = [s for s in summaries if s.summary_text and len(s.summary_text.strip()) >= 20]

                    if not valid_summaries:
                        return {'error': 'No valid summaries found'}

                    total_articles = sum(s.articles_count for s in valid_summaries)
                    categories_count = len(valid_summaries)

                    header = f"<b>Сводка новостей за {today.strftime('%d.%m.%Y')}</b>"
                    footer = f"\n📊 Всего: {total_articles} новостей в {categories_count} категориях"

                    digest_parts = self.digest_builder.split_digest_into_parts(
                        header, valid_summaries, footer, total_articles, categories_count
                    )

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
                        category_cache[ai_key] = display.get('display_name') or display.get('name') or ai_key

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
            # Use database queue for processing operation
            async def processing_operation(db):
                # Get unprocessed articles with eager loading of source relationship
                from sqlalchemy.orm import selectinload
                unprocessed_query = select(Article).options(
                    selectinload(Article.source)  # Eager load source to avoid lazy loading issues
                ).where(
                    (Article.summary_processed == False) |
                    (Article.category_processed == False) |
                    (Article.ad_processed == False)
                ).limit(50)
                
                result = await db.execute(unprocessed_query)
                unprocessed_articles = result.scalars().all()
                
                if not unprocessed_articles:
                    return {'articles_processed': 0, 'articles_summarized': 0, 'articles_categorized': 0}
                
                print(f"  🔄 Processing {len(unprocessed_articles)} unprocessed articles...")
                
                processed_count = 0
                summarized_count = 0
                categorized_count = 0
                
                for article in unprocessed_articles:
                    try:
                        # Get source type for processing
                        source_type = 'rss'  # Default
                        if hasattr(article, 'source') and article.source:
                            source_type = article.source.source_type
                        elif article.url:
                            # Determine source type from URL if no source is linked
                            if 't.me' in article.url:
                                source_type = 'telegram'
                            elif any(domain in article.url for domain in ['reddit.com', 'redd.it']):
                                source_type = 'reddit'
                            # Add more URL-based detection as needed
                        
                        # Use unified AI processor for complete processing (includes title optimization)
                        article_data = {
                            'id': article.id,
                            'title': article.title,
                            'content': article.content,
                            'url': article.url,
                            'summary': article.summary,
                            'summary_processed': article.summary_processed,
                            'category_processed': article.category_processed,
                            'ad_processed': article.ad_processed,
                            'source_type': source_type,
                            'source_name': article.source.name if article.source else 'Unknown'
                        }
                        
                        # Process with AI processor (handles title optimization, summary, categories, ads)
                        processed_data = await self.ai_processor.process_article_combined(
                            article_data, stats, force_processing=False, db=db
                        )
                        
                        # Update article with processed data
                        if processed_data.get('optimized_title'):
                            article.title = processed_data['optimized_title']
                            print(f"  🏷️ Updated title: {processed_data['optimized_title'][:100]}...")
                        
                        if processed_data.get('summary') and not article.summary_processed:
                            article.summary = processed_data['summary']
                            article.summary_processed = True
                            summarized_count += 1
                        
                        if processed_data.get('categories') and not article.category_processed:
                            # Save AI categories directly to database (no mapping at storage level)
                            await self._save_ai_categories_to_database(db, article.id, processed_data['categories'])
                            article.category_processed = True
                            categorized_count += 1
                            
                            # Track categories found (use AI category names for stats)
                            for cat in processed_data['categories']:
                                stats['categories_found'].add(cat.get('name', 'Other'))
                        
                        if not article.ad_processed:
                            article.is_advertisement = processed_data.get('is_advertisement', False)
                            article.ad_confidence = processed_data.get('ad_confidence', 0.0)
                            article.ad_type = processed_data.get('ad_type', 'news_article')
                            article.ad_reasoning = processed_data.get('ad_reasoning', 'AI processed')
                            article.ad_processed = True
                        
                        processed_count += 1
                        
                    except Exception as e:
                        print(f"  ⚠️ Error processing article {article.id}: {e}")
                        stats['errors'].append(f"Article {article.id}: {str(e)}")
                
                # Commit will be handled by database queue
                return {
                    'articles_processed': processed_count,
                    'articles_summarized': summarized_count,
                    'articles_categorized': categorized_count
                }
            
            return await self.db_queue_manager.execute_write(processing_operation)
            
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
                        category_cache[ai_key] = display.get('display_name') or display.get('name') or ai_key

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
