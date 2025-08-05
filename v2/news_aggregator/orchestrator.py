"""Main orchestrator for RSS Summarizer v2."""

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from asyncio import Queue, Semaphore

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from .database import AsyncSessionLocal
from .models import Source, Article, ProcessingStat, DailySummary
from .services.source_manager import SourceManager
from .services.ai_client import get_ai_client
from .services.telegram_service import get_telegram_service
from .core.exceptions import NewsAggregatorError
from .config import settings


@dataclass
class DatabaseWriteTask:
    """Task for database write queue."""
    article_id: int
    field_updates: Dict[str, Any]
    timestamp: float
    retry_count: int = 0


class DatabaseWriteQueue:
    """Asynchronous database write queue with connection-based concurrency control."""
    
    def __init__(self, max_queue_size: int = 1000, max_concurrent_writes: int = 3, max_workers: int = 5):
        self.queue: Queue[DatabaseWriteTask] = Queue(maxsize=max_queue_size)
        self.max_concurrent_writes = max_concurrent_writes
        self.max_workers = max_workers
        
        # Semaphore to limit concurrent database connections
        self.db_semaphore = Semaphore(max_concurrent_writes)
        
        # Worker management
        self.worker_tasks: List[asyncio.Task] = []
        self.running = False
        
        # Statistics
        self.active_writes = 0
        self.total_writes = 0
        self.total_articles_updated = 0
        
    async def start(self):
        """Start multiple background workers."""
        if self.running:
            return
            
        self.running = True
        
        # Start multiple worker tasks
        for i in range(self.max_workers):
            worker_task = asyncio.create_task(self._worker_loop(worker_id=i))
            self.worker_tasks.append(worker_task)
            
        print(f"🚀 Database write queue started with {self.max_workers} workers, max {self.max_concurrent_writes} concurrent DB connections")
        
    async def stop(self):
        """Stop all background workers and process remaining tasks."""
        if not self.running:
            return
            
        print(f"🛑 Stopping database write queue ({self.queue.qsize()} tasks pending)...")
        self.running = False
        
        # Cancel all worker tasks
        for task in self.worker_tasks:
            if not task.done():
                task.cancel()
                
        # Wait for workers to finish
        await asyncio.gather(*self.worker_tasks, return_exceptions=True)
        self.worker_tasks.clear()
        
        # Process any remaining tasks in queue
        remaining_tasks = []
        while not self.queue.empty():
            try:
                task = self.queue.get_nowait()
                remaining_tasks.append(task)
            except asyncio.QueueEmpty:
                break
                
        if remaining_tasks:
            print(f"  📝 Processing {len(remaining_tasks)} remaining tasks...")
            await self._process_tasks_batch(remaining_tasks)
            
        print(f"✅ Database write queue stopped. Total processed: {self.total_writes} writes, {self.total_articles_updated} articles")
        
    async def add_update(self, article_id: int, field_updates: Dict[str, Any]):
        """Add field updates to queue."""
        try:
            task = DatabaseWriteTask(
                article_id=article_id,
                field_updates=field_updates,
                timestamp=time.time()
            )
            await self.queue.put(task)
        except asyncio.QueueFull:
            print(f"⚠️ Database write queue full ({self.queue.qsize()}/{self.queue.maxsize}), dropping update for article {article_id}")
            
    async def _worker_loop(self, worker_id: int):
        """Background worker that processes write tasks using semaphore for connection control."""
        while self.running:
            try:
                # Wait for a task from the queue
                task = await self.queue.get()
                
                # Acquire semaphore to limit concurrent database connections
                async with self.db_semaphore:
                    self.active_writes += 1
                    try:
                        await self._process_single_task(task, worker_id)
                        self.total_writes += 1
                        self.total_articles_updated += 1
                    finally:
                        self.active_writes -= 1
                        
                # Mark task as done
                self.queue.task_done()
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"❌ Database write worker {worker_id} error: {e}")
                await asyncio.sleep(0.1)  # Brief pause before retrying
                
    async def _process_single_task(self, task: DatabaseWriteTask, worker_id: int):
        """Process a single database write task."""
        try:
            async with AsyncSessionLocal() as db:
                from .models import Article
                
                # Get the article
                result = await db.execute(
                    select(Article).where(Article.id == task.article_id)
                )
                article = result.scalar_one_or_none()
                
                if not article:
                    print(f"  ⚠️ Worker {worker_id}: Article {task.article_id} not found")
                    return
                
                # Apply all field updates
                updates_applied = 0
                for field_name, value in task.field_updates.items():
                    if hasattr(article, field_name):
                        setattr(article, field_name, value)
                        updates_applied += 1
                    else:
                        print(f"  ⚠️ Worker {worker_id}: Article has no field '{field_name}'")
                
                await db.commit()
                print(f"  ✅ Worker {worker_id}: Applied {updates_applied} updates to article {task.article_id}")
                
        except Exception as e:
            print(f"  ❌ Worker {worker_id}: Failed to update article {task.article_id}: {e}")
            raise
    
    async def _process_tasks_batch(self, tasks: List[DatabaseWriteTask]):
        """Process multiple tasks in a single database session (for cleanup)."""
        if not tasks:
            return
            
        try:
            async with AsyncSessionLocal() as db:
                from .models import Article
                
                # Get all articles that need updates
                article_ids = [task.article_id for task in tasks]
                result = await db.execute(
                    select(Article).where(Article.id.in_(article_ids))
                )
                articles = {article.id: article for article in result.scalars().all()}
                
                # Apply all updates
                updates_applied = 0
                for task in tasks:
                    if task.article_id in articles:
                        article = articles[task.article_id]
                        for field_name, value in task.field_updates.items():
                            if hasattr(article, field_name):
                                setattr(article, field_name, value)
                                updates_applied += 1
                
                await db.commit()
                self.total_writes += len(tasks)  
                self.total_articles_updated += len(articles)
                print(f"  ✅ Cleanup: Applied {updates_applied} field updates to {len(articles)} articles")
                
        except Exception as e:
            print(f"  ❌ Cleanup batch failed: {e}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get queue statistics."""
        return {
            'queue_size': self.queue.qsize(),
            'active_writes': self.active_writes,
            'total_writes': self.total_writes,
            'total_articles_updated': self.total_articles_updated,
            'max_concurrent_writes': self.max_concurrent_writes,
            'worker_count': len(self.worker_tasks),
            'running': self.running
        }



class NewsOrchestrator:
    """Main orchestrator for news processing."""
    
    def __init__(self):
        self.source_manager = SourceManager()
        self.ai_client = get_ai_client()
        self.telegram_service = get_telegram_service()
        self.db_queue = DatabaseWriteQueue(
            max_queue_size=1000, 
            max_concurrent_writes=3,  # Limit concurrent DB connections
            max_workers=5  # Worker threads to process queue
        )
        
        # Initialize AI services
        try:
            from .services.categorization_ai import CategorizationAI
            self.categorization_ai = CategorizationAI()
        except Exception as e:
            print(f"⚠️ Warning: Could not initialize categorization AI: {e}")
            self.categorization_ai = None
    
    async def start(self):
        """Start the orchestrator and its database queue."""
        await self.db_queue.start()
        
    async def stop(self):
        """Stop the orchestrator and its database queue."""
        await self.db_queue.stop()
        
    def get_queue_stats(self) -> Dict[str, Any]:
        """Get database queue statistics."""
        return self.db_queue.get_stats()
        
    async def run_full_cycle(self) -> Dict[str, Any]:
        """Run complete news processing cycle without clustering."""
        start_time = datetime.utcnow()
        stats = {
            'started_at': start_time,
            'articles_fetched': 0,
            'articles_processed': 0,
            'api_calls_made': 0,
            'errors': []
        }
        
        # Start database write queue
        await self.db_queue.start()
        
        try:
            # Step 1: Fetch new articles from all sources (короткая сессия)
            print("📥 Fetching articles from sources...")
            articles_to_process = []
            async with AsyncSessionLocal() as db:
                fetch_results = await self.source_manager.fetch_from_all_sources(db)
                
                all_articles = []
                for source_name, articles in fetch_results.items():
                    print(f"  • {source_name}: {len(articles)} articles")
                    all_articles.extend(articles)
                    stats['articles_fetched'] += len(articles)
                
                # Step 2: Get articles that need processing (короткая сессия)
                from sqlalchemy import select, or_, and_
                from sqlalchemy.orm import selectinload
                unprocessed_result = await db.execute(
                    select(Article).options(selectinload(Article.source)).where(
                        or_(
                            (Article.summary.is_(None)) | (Article.summary == ''),  # No summary
                            (Article.category.is_(None)) | (Article.category == '') | (Article.category == 'Other'),  # No category or default
                            and_(
                                Article.ad_processed.is_(False),  # Need advertising detection
                                Article.source.has(Source.source_type == 'telegram')  # Only for Telegram sources
                            )
                        )
                    ).limit(200)  # Process max 200 at once
                )
                unprocessed_articles = list(unprocessed_result.scalars().all())
                
                # Combine new and unprocessed articles (removing duplicates) - work with IDs only
                all_article_ids = [article.id for article in all_articles]
                unprocessed_article_ids = [article.id for article in unprocessed_articles]
                article_ids_to_process = list(set(all_article_ids + unprocessed_article_ids))
            
            if not article_ids_to_process:
                print("ℹ️ No articles to process")
                return stats
            
            # Count different types of articles to process
            new_count = len(all_articles)
            no_summary_count = len([a for a in unprocessed_articles if not a.summary or a.summary == ''])
            # Count articles that need processing based on new flags
            no_summary_count = len([a for a in unprocessed_articles if not getattr(a, 'summary_processed', False)])
            no_category_count = len([a for a in unprocessed_articles if not getattr(a, 'category_processed', False)])
            
            print(f"🤖 Processing {len(article_ids_to_process)} articles with AI:")
            print(f"   • {new_count} new articles")
            print(f"   • {no_summary_count} articles without summary") 
            print(f"   • {no_category_count} articles needing categorization")
            
            # Step 3: Process articles with AI (каждая статья в отдельной сессии)
            processed_articles = await self._process_articles_with_ai_separate_sessions(article_ids_to_process, stats)
            stats['articles_processed'] = len(processed_articles)
            
            # Step 4: Skip Telegram digest generation in sync - will be done separately
            print("📊 Sync completed - digest can be sent separately")
            
            # Step 5: Update statistics (короткая сессия)
            async with AsyncSessionLocal() as db:
                await self._update_processing_stats(db, stats)
                
                stats['completed_at'] = datetime.utcnow()
                stats['duration_seconds'] = (stats['completed_at'] - start_time).total_seconds()
                
                print(f"✅ Processing completed in {stats['duration_seconds']:.1f}s")
                print(f"   Articles: {stats['articles_fetched']} fetched, {stats['articles_processed']} processed")
                
                return stats
                
        except Exception as e:
            error_msg = f"Orchestrator error: {e}"
            stats['errors'].append(error_msg)
            print(f"❌ {error_msg}")
            raise NewsAggregatorError(error_msg) from e
        
        finally:
            # Always stop the database write queue
            await self.db_queue.stop()
    
    async def send_telegram_digest(self) -> Dict[str, Any]:
        """Send Telegram digest separately from sync."""
        start_time = datetime.utcnow()
        stats = {
            'started_at': start_time,
            'errors': []
        }
        
        try:
            async with AsyncSessionLocal() as db:
                print("📱 Generating Telegram digest...")
                await self._generate_telegram_digest(db, stats)
                
                stats['completed_at'] = datetime.utcnow()
                stats['duration_seconds'] = (stats['completed_at'] - start_time).total_seconds()
                
                print(f"✅ Digest sent in {stats['duration_seconds']:.1f}s")
                return stats
                
        except Exception as e:
            error_msg = f"Digest sending error: {e}"
            stats['errors'].append(error_msg)
            print(f"❌ {error_msg}")
            raise NewsAggregatorError(error_msg) from e
    
    async def _process_articles_with_ai_separate_sessions(self, article_ids: List[int], 
                                                       stats: Dict[str, Any]) -> List[Dict]:
        """Process articles with AI using NO database sessions during AI calls."""
        processed_articles = []
        
        # Process articles sequentially, completely separating DB and AI operations
        for i, article_id in enumerate(article_ids, 1):
            article_data = {}
            try:
                # Step 1: Quickly get article data (short DB session)
                async with AsyncSessionLocal() as db:
                    from .models import Article, Source
                    from sqlalchemy import select
                    from sqlalchemy.orm import selectinload
                    
                    # Get article with source info
                    result = await db.execute(
                        select(Article).options(selectinload(Article.source)).where(Article.id == article_id)
                    )
                    article = result.scalar_one_or_none()
                    
                    if not article:
                        print(f"⚠️ Article {article_id} not found, skipping...")
                        continue
                        
                    print(f"📝 Processing article {i}/{len(article_ids)}: {article.title[:60]}...")
                    
                    article_data = {
                        'id': article.id,
                        'title': article.title,
                        'url': article.url,
                        'content': article.content,
                        'source_id': article.source_id,
                        'summary': article.summary,
                        'category': article.category,
                        'is_advertisement': article.is_advertisement,
                        'summary_processed': getattr(article, 'summary_processed', False),
                        'category_processed': getattr(article, 'category_processed', False),
                        'ad_processed': getattr(article, 'ad_processed', False)
                    }
                    
                    # Get source info
                    if article.source:
                        article_data['source_type'] = article.source.source_type
                        article_data['source_name'] = article.source.name
                    else:
                        article_data['source_type'] = 'rss'
                        article_data['source_name'] = 'Unknown'
                
                # Step 2: Do AI processing with queued saves
                await self._process_article_ai_queued(article_data, stats)
                
                # Step 4: Add to processed list
                processed_articles.append(article_data)
                        
            except Exception as e:
                error_msg = f"Error processing article {article_data.get('id', article_id)}: {e}"
                stats['errors'].append(error_msg)
                print(f"❌ {error_msg}")
                continue
                
        return processed_articles
    
    async def _process_article_ai_incremental(self, article_data: Dict[str, Any], stats: Dict[str, Any]) -> Dict[str, Any]:
        """Process article with AI, saving after each API call."""
        source_type = article_data.get('source_type', 'rss')
        source_name = article_data.get('source_name', 'Unknown')
        article_id = article_data['id']
        
        print(f"  📡 Source: {source_name} (type: {source_type})")
        
        # Check what processing is needed
        needs_summary = not article_data.get('summary_processed', False) and not article_data.get('summary')
        needs_category = not article_data.get('category_processed', False)
        needs_ad_detection = not article_data.get('ad_processed', False) and source_type == 'telegram'
        
        print(f"  🔍 Processing needs: {'✅ Summary' if needs_summary else '❌ Summary'}, {'✅ Category' if needs_category else '❌ Category'}, {'✅ Ad Detection' if needs_ad_detection else '❌ Ad Detection'}")
        
        # Process summary if needed
        if needs_summary:
            print(f"  📄 Starting summarization...")
            try:
                import time
                start_time = time.time()
                # Create a temporary Article-like object for compatibility
                class TempArticle:
                    def __init__(self, data):
                        self.url = data['url']
                        self.title = data['title']
                        self.content = data['content']
                
                temp_article = TempArticle(article_data)
                summary = await self._get_summary_by_source_type(temp_article, source_type, stats)
                elapsed_time = time.time() - start_time
                print(f"  ✅ Summary generated in {elapsed_time:.1f}s: {summary[:100] if summary else 'None'}...")
                
                # Save summary immediately
                await self._save_article_field(article_id, 'summary', summary, 'summary_processed', True)
                stats['api_calls_made'] += 1
                print(f"  💾 Summary saved to database")
                
            except Exception as e:
                print(f"  ❌ Summarization failed: {e}")
                # Mark as processed even on failure to avoid retries
                await self._save_article_field(article_id, 'summary_processed', True)
        
        # Process category if needed  
        if needs_category:
            print(f"  🏷️ Starting categorization...")
            try:
                # Get current summary - use fresh summary if we just generated it
                current_summary = article_data.get('summary')
                if needs_summary and 'summary' in locals() and summary is not None:
                    current_summary = summary
                
                # Use AI for categorization
                if self.categorization_ai:
                    category = await self.categorization_ai.categorize_article(
                        article_data['title'], current_summary or article_data['content']
                    )
                else:
                    category = 'Other'  # Fallback category
                print(f"  ✅ Category assigned: {category}")
                
                # Save category immediately
                await self._save_article_field(article_id, 'category', category, 'category_processed', True)
                stats['api_calls_made'] += 1
                print(f"  💾 Category saved to database")
                
            except Exception as e:
                print(f"  ❌ Categorization failed: {e}")
                # Set default category and mark as processed
                await self._save_article_field(article_id, 'category', 'Other', 'category_processed', True)
        
        # Process ad detection if needed
        if needs_ad_detection:
            print(f"  🛡️ Starting advertising detection...")
            try:
                # TODO: Implement advertisement detection
                # For now, set to False (not advertisement)
                is_advertisement = False
                print(f"  ✅ Ad detection result: {'Advertisement' if is_advertisement else 'Not advertisement'}")
                
                # Save ad detection result immediately
                await self._save_article_field(article_id, 'is_advertisement', is_advertisement, 'ad_processed', True)
                stats['api_calls_made'] += 1
                print(f"  💾 Ad detection result saved to database")
                
            except Exception as e:
                print(f"  ❌ Ad detection failed: {e}")
                # Set default and mark as processed
                await self._save_article_field(article_id, 'is_advertisement', False, 'ad_processed', True)
        
        return {}  # No need to return results since we save immediately
    
    async def _process_article_ai_queued(self, article_data: Dict[str, Any], stats: Dict[str, Any]) -> Dict[str, Any]:
        """Process article with AI, using database write queue for saves."""
        source_type = article_data.get('source_type', 'rss')
        source_name = article_data.get('source_name', 'Unknown')
        article_id = article_data['id']
        
        print(f"  📡 Source: {source_name} (type: {source_type})")
        
        # Check what processing is needed
        needs_summary = not article_data.get('summary_processed', False) and not article_data.get('summary')
        needs_category = not article_data.get('category_processed', False)
        needs_ad_detection = not article_data.get('ad_processed', False) and source_type == 'telegram'
        
        print(f"  🔍 Processing needs: {'✅ Summary' if needs_summary else '❌ Summary'}, {'✅ Category' if needs_category else '❌ Category'}, {'✅ Ad Detection' if needs_ad_detection else '❌ Ad Detection'}")
        
        # Collect all field updates for this article
        field_updates = {}
        
        # Process summary if needed
        if needs_summary:
            print(f"  📄 Starting summarization...")
            try:
                import time
                start_time = time.time()
                # Create a temporary Article-like object for compatibility
                class TempArticle:
                    def __init__(self, data):
                        self.url = data['url']
                        self.title = data['title']
                        self.content = data['content']
                
                temp_article = TempArticle(article_data)
                summary = await self._get_summary_by_source_type(temp_article, source_type, stats)
                elapsed_time = time.time() - start_time
                print(f"  ✅ Summary generated in {elapsed_time:.1f}s: {summary[:100] if summary else 'None'}...")
                
                # Add to field updates
                field_updates['summary'] = summary
                field_updates['summary_processed'] = True
                stats['api_calls_made'] += 1
                print(f"  🔄 Summary queued for write")
                
            except Exception as e:
                print(f"  ❌ Summarization failed: {e}")
                # Mark as processed even on failure to avoid retries
                field_updates['summary_processed'] = True
        
        # Process category if needed  
        if needs_category:
            print(f"  🏷️ Starting categorization...")
            try:
                # Get current summary - use fresh summary if we just generated it
                current_summary = article_data.get('summary')
                if needs_summary and 'summary' in field_updates:
                    current_summary = field_updates['summary']
                
                # Use AI for categorization
                if self.categorization_ai:
                    category = await self.categorization_ai.categorize_article(
                        article_data['title'], current_summary or article_data['content']
                    )
                else:
                    category = 'Other'  # Fallback category
                print(f"  ✅ Category assigned: {category}")
                
                # Add to field updates
                field_updates['category'] = category
                field_updates['category_processed'] = True
                stats['api_calls_made'] += 1
                print(f"  🔄 Category queued for write")
                
            except Exception as e:
                print(f"  ❌ Categorization failed: {e}")
                # Set default category and mark as processed
                field_updates['category'] = 'Other'
                field_updates['category_processed'] = True
        
        # Process ad detection if needed
        if needs_ad_detection:
            print(f"  🛡️ Starting advertising detection...")
            try:
                # TODO: Implement advertisement detection
                # For now, set to False (not advertisement)
                is_advertisement = False
                print(f"  ✅ Ad detection result: {'Advertisement' if is_advertisement else 'Not advertisement'}")
                
                # Add to field updates
                field_updates['is_advertisement'] = is_advertisement
                field_updates['ad_processed'] = True
                stats['api_calls_made'] += 1
                print(f"  🔄 Ad detection result queued for write")
                
            except Exception as e:
                print(f"  ❌ Ad detection failed: {e}")
                # Set default and mark as processed
                field_updates['is_advertisement'] = False
                field_updates['ad_processed'] = True
        
        # Submit all updates to queue at once
        if field_updates:
            await self.db_queue.add_update(article_id, field_updates)
            print(f"  📤 Submitted {len(field_updates)} field updates to write queue")
        
        return {}
    
    async def _save_article_field(self, article_id: int, *field_value_pairs):
        """Save article field(s) to database in a short session."""
        try:
            async with AsyncSessionLocal() as db:
                from .models import Article
                from sqlalchemy import select
                
                result = await db.execute(select(Article).where(Article.id == article_id))
                article = result.scalar_one_or_none()
                
                if not article:
                    print(f"⚠️ Article {article_id} not found for field update")
                    return
                
                if len(field_value_pairs) % 2 != 0:
                    print(f"⚠️ Invalid field_value_pairs count: {len(field_value_pairs)}")
                    return
                
                # Set fields in pairs: field_name, value, field_name, value, ...
                for i in range(0, len(field_value_pairs), 2):
                    field_name = field_value_pairs[i]
                    field_value = field_value_pairs[i + 1]
                    if hasattr(article, field_name):
                        setattr(article, field_name, field_value)
                    else:
                        print(f"⚠️ Article has no field '{field_name}'")
                
                await db.commit()
                
        except Exception as e:
            print(f"❌ Error saving article {article_id} fields: {e}")

    async def _process_single_article_with_ai(self, db: AsyncSession, article: Article, 
                                            stats: Dict[str, Any]) -> Optional[Article]:
        """Process a single article with AI in an already open session."""
        # Get source info to determine processing strategy
        source_type = 'rss'  # Default
        source_name = 'Unknown'
        if hasattr(article, 'source') and article.source:
            source_type = article.source.source_type
            source_name = article.source.name
        elif article.source_id:
            # If source is not loaded, get it from database
            from .models import Source
            from sqlalchemy import select
            source_result = await db.execute(
                select(Source).where(Source.id == article.source_id)
            )
            source = source_result.scalar_one_or_none()
            if source:
                source_type = source.source_type
                source_name = source.name
        
        print(f"  📡 Source: {source_name} (type: {source_type})")
        
        # Check what processing is needed
        needs_summary = not getattr(article, 'summary_processed', False) and (not article.summary or article.summary == '')
        needs_category = not getattr(article, 'category_processed', False)
        needs_ad_detection = not getattr(article, 'ad_processed', False) and source_type == 'telegram'
        
        print(f"  🔍 Processing needs: {'✅ Summary' if needs_summary else '❌ Summary'}, {'✅ Category' if needs_category else '❌ Category'}, {'✅ Ad Detection' if needs_ad_detection else '❌ Ad Detection'}")
        
        # Process summary if needed
        if needs_summary:
            print(f"  📄 Starting summarization...")
            try:
                import time
                start_time = time.time()
                article.summary = await self._get_summary_by_source_type(
                    article.url, source_type, article.content
                )
                elapsed_time = time.time() - start_time
                print(f"  ✅ Summary generated in {elapsed_time:.1f}s: {article.summary[:100]}...")
                
                # Mark as processed
                article.summary_processed = True
                stats['api_calls_made'] += 1
                
            except Exception as e:
                print(f"  ❌ Summarization failed: {e}")
                article.summary_processed = True  # Mark as processed to avoid retries
        
        # Process category if needed
        if needs_category:
            print(f"  🏷️ Starting categorization...")
            try:
                # Use AI for categorization
                if self.categorization_ai:
                    article.category = await self.categorization_ai.categorize_article(
                        article.title, article.summary or article.content
                    )
                else:
                    article.category = 'Other'  # Fallback category
                print(f"  ✅ Category assigned: {article.category}")
                
                # Mark as processed
                article.category_processed = True
                stats['api_calls_made'] += 1
                
            except Exception as e:
                print(f"  ❌ Categorization failed: {e}")
                article.category_processed = True  # Mark as processed to avoid retries
        
        # Process ad detection if needed
        if needs_ad_detection:
            print(f"  🛡️ Starting advertising detection...")
            try:
                article.is_advertisement = await self._detect_advertisement(
                    article.title, article.content
                )
                print(f"  ✅ Ad detection result: {'Advertisement' if article.is_advertisement else 'Not advertisement'}")
                
                # Mark as processed
                article.ad_processed = True
                stats['api_calls_made'] += 1
                
            except Exception as e:
                print(f"  ❌ Ad detection failed: {e}")
                article.ad_processed = True  # Mark as processed to avoid retries
        
        return article

    async def _process_articles_with_ai(self, db: AsyncSession, articles: List[Article], 
                                      stats: Dict[str, Any]) -> List[Article]:
        """Process articles with AI summarization."""
        processed_articles = []
        
        # Process articles sequentially to avoid SQLAlchemy async issues
        for i, article in enumerate(articles, 1):
            try:
                print(f"📝 Processing article {i}/{len(articles)}: {article.title[:60]}...")
                
                # Get source info to determine processing strategy
                # Use getattr to safely access source without triggering lazy loading
                source_type = 'rss'  # Default
                source_name = 'Unknown'
                if hasattr(article, 'source') and article.source:
                    source_type = article.source.source_type
                    source_name = article.source.name
                elif article.source_id:
                    # If source is not loaded, get it from database
                    from .models import Source
                    source_result = await db.execute(
                        select(Source).where(Source.id == article.source_id)
                    )
                    source = source_result.scalar_one_or_none()
                    if source:
                        source_type = source.source_type
                        source_name = source.name
                
                print(f"  📡 Source: {source_name} (type: {source_type})")
                
                # Check if article needs summary (not processed yet or no summary)
                needs_summary = not getattr(article, 'summary_processed', False) and (not article.summary or article.summary == '')
                # Check if article needs categorization (not processed yet)
                needs_category = not getattr(article, 'category_processed', False)
                # Check if article needs advertising detection (not processed yet and is from telegram)
                needs_ad_detection = not getattr(article, 'ad_processed', False) and source_type == 'telegram'
                
                print(f"  🔍 Processing needs: {'✅ Summary' if needs_summary else '❌ Summary'}, {'✅ Category' if needs_category else '❌ Category'}, {'✅ Ad Detection' if needs_ad_detection else '❌ Ad Detection'}")
                if getattr(article, 'summary_processed', False):
                    print(f"  ⏭️ Skipping summarization - already processed")
                if getattr(article, 'category_processed', False):
                    print(f"  ⏭️ Skipping categorization - already processed (current: {article.category or 'None'})")
                
                # Get summary based on source type
                if needs_summary:
                    print(f"  📄 Starting summarization...")
                    try:
                        start_time = time.time()
                        article.summary = await self._get_summary_by_source_type(
                            article, source_type, stats
                        )
                        duration = time.time() - start_time
                        article.summary_processed = True  # Mark as processed regardless of result
                        if article.summary:
                            summary_length = len(article.summary)
                            print(f"  ✅ Summarization completed in {duration:.2f}s (length: {summary_length} chars)")
                        else:
                            print(f"  ⚠️ Summarization returned empty result in {duration:.2f}s")
                    except Exception as e:
                        print(f"  ❌ AI summarization failed: {str(e)}")
                        logging.warning(f"AI summarization failed for {article.url}: {e}")
                        # Fallback to content as summary
                        content = article.content or article.title or ""
                        if len(content) > 500:
                            article.summary = content[:500] + "..."
                        else:
                            article.summary = content
                        
                        if article.url:
                            article.summary += f" <a href='{article.url}'>Читать оригинал</a>"
                        article.summary_processed = True  # Mark as processed even with fallback
                        print(f"  🔄 Using fallback summary (length: {len(article.summary)} chars)")
                
                # Categorize article based on source type
                if needs_category:
                    print(f"  🏷️ Starting categorization...")
                    try:
                        start_time = time.time()
                        category = await self._categorize_by_source_type(
                            article, source_type, stats
                        )
                        duration = time.time() - start_time
                        article.category = category
                        article.category_processed = True  # Mark as processed only on successful AI categorization
                        print(f"  ✅ Categorization completed in {duration:.2f}s: '{category}'")
                    except Exception as e:
                        print(f"  ❌ AI categorization failed: {str(e)}")
                        logging.warning(f"AI categorization failed for {article.url}: {e}")
                        # Fallback to simple rule-based categorization
                        article.category = self._get_fallback_category(article.title)
                        # Do NOT mark as processed - allow retry on next run
                        print(f"  🔄 Using fallback categorization: '{article.category}' (will retry AI next time)")
                
                # Process advertising detection for Telegram sources
                if needs_ad_detection:
                    print(f"  🎯 Processing advertising detection from raw_data...")
                    try:
                        # Advertising detection should already be done in TelegramSource
                        # Just extract the data from raw_data and save to database columns
                        ad_detection = None
                        if hasattr(article, 'raw_data') and article.raw_data:
                            ad_detection = article.raw_data.get('advertising_detection')
                        
                        if ad_detection:
                            # Save advertising detection results to database columns
                            article.is_advertisement = ad_detection.get('is_advertisement', False)
                            article.ad_confidence = ad_detection.get('confidence', 0.0)
                            article.ad_type = ad_detection.get('ad_type')
                            article.ad_reasoning = ad_detection.get('reasoning', '')
                            article.ad_markers = ad_detection.get('markers', [])
                            article.ad_processed = True
                            
                            if article.is_advertisement:
                                print(f"  🚨 Advertising data found: {article.ad_type} (confidence: {article.ad_confidence:.2f})")
                            else:
                                print(f"  ✅ No advertising detected (confidence: {article.ad_confidence:.2f})")
                        else:
                            # No detection data available - this might be an old article
                            # For existing articles without detection, run AI analysis once
                            print(f"  🎯 No raw_data found, running AI detection for existing article...")
                            start_time = time.time()
                            
                            source_info = {
                                'channel': source_name,
                                'source_name': source_name,
                                'source_type': source_type
                            }
                            ad_detection = await self.ai_client.detect_advertising(
                                article.content or article.title or '', 
                                source_info
                            )
                            stats['api_calls_made'] += 1
                            
                            # Save results to database columns
                            article.is_advertisement = ad_detection.get('is_advertisement', False)
                            article.ad_confidence = ad_detection.get('confidence', 0.0)
                            article.ad_type = ad_detection.get('ad_type')
                            article.ad_reasoning = ad_detection.get('reasoning', '')
                            article.ad_markers = ad_detection.get('markers', [])
                            article.ad_processed = True
                            
                            duration = time.time() - start_time
                            
                            if article.is_advertisement:
                                print(f"  🚨 Advertising detected in {duration:.2f}s: {article.ad_type} (confidence: {article.ad_confidence:.2f})")
                            else:
                                print(f"  ✅ No advertising detected in {duration:.2f}s (confidence: {article.ad_confidence:.2f})")
                            
                    except Exception as e:
                        print(f"  ❌ Advertising detection processing failed: {str(e)}")
                        logging.warning(f"Advertising detection processing failed for {article.url}: {e}")
                        # Mark as processed with default values to avoid retry
                        article.is_advertisement = False
                        article.ad_confidence = 0.0
                        article.ad_processed = True
                        print(f"  🔄 Using default advertising detection values")
                
                article.processed = True
                processed_articles.append(article)
                    
            except Exception as e:
                error_msg = f"Error processing article {article.url}: {e}"
                stats['errors'].append(error_msg)
                print(f"  ⚠️ {error_msg}")
                
                # Use fallback summary if needed
                if not article.summary or article.summary == '':
                    article.summary = f"{article.content or article.title} <a href='{article.url}'>Читать оригинал</a>"
                
                # Set default category on error if needed
                if not article.category or article.category == '' or article.category == self._get_default_category():
                    article.category = self._get_fallback_category(article.title)
                
                article.processed = True
                processed_articles.append(article)
        
        # Update database with simple commit
        try:
            await db.commit()
        except Exception as commit_error:
            logging.error(f"Database commit failed: {commit_error}")
            await db.rollback()
            stats['errors'].append(f"Database commit error: {commit_error}")
        
        return processed_articles
    
    async def _get_summary_by_source_type(self, article: Article, source_type: str, stats: Dict[str, Any]) -> str:
        """Get article summary based on source type."""
        try:
            if source_type == 'rss':
                # RSS sources: use AI to extract and summarize full article content
                ai_summary = await self.ai_client.get_article_summary(article.url)
                stats['api_calls_made'] += 1
                
                if ai_summary:
                    return ai_summary
                else:
                    # Fallback to RSS content
                    return f"{article.content or article.title} <a href='{article.url}'>Читать оригинал</a>"
                    
            elif source_type == 'telegram':
                # Telegram sources: use original message content as-is
                return f"{article.content or article.title} <a href='{article.url}'>Читать оригинал</a>"
                
            elif source_type == 'reddit':
                # Reddit sources: use AI to get full post content + comments context
                ai_summary = await self.ai_client.get_article_summary(article.url)
                stats['api_calls_made'] += 1
                
                if ai_summary:
                    return ai_summary
                else:
                    # Fallback to reddit content
                    return f"{article.content or article.title} <a href='{article.url}'>Читать оригинал</a>"
                    
            elif source_type == 'twitter':
                # Twitter sources: tweet content is usually complete, minimal processing
                return f"{article.content or article.title} <a href='{article.url}'>Читать оригинал</a>"
                
            elif source_type == 'news_api':
                # News API sources: use AI to get full article content
                ai_summary = await self.ai_client.get_article_summary(article.url)
                stats['api_calls_made'] += 1
                
                if ai_summary:
                    return ai_summary
                else:
                    # Fallback to API content
                    return f"{article.content or article.title} <a href='{article.url}'>Читать оригинал</a>"
                    
            else:
                # Custom or unknown source types: use AI processing
                ai_summary = await self.ai_client.get_article_summary(article.url)
                stats['api_calls_made'] += 1
                
                if ai_summary:
                    return ai_summary
                else:
                    # Fallback to original content
                    return f"{article.content or article.title} <a href='{article.url}'>Читать оригинал</a>"
                    
        except Exception as e:
            print(f"  ⚠️ Error getting summary by source type: {e}")
            # Fallback to original content
            return f"{article.content or article.title} <a href='{article.url}'>Читать оригинал</a>"
    
    async def _categorize_by_source_type(self, article: Article, source_type: str, stats: Dict[str, Any]) -> str:
        """Categorize article using AI for all source types."""
        try:
            # All source types use AI categorization
            from .services.telegram_ai import get_telegram_ai
            telegram_ai = get_telegram_ai()
            content_for_categorization = article.summary or article.title or ""
            
            # Ensure we have content to categorize
            if not content_for_categorization.strip():
                return "Other"
            
            category = await telegram_ai.categorize_article(
                article.title or "",
                content_for_categorization
            )
            stats['api_calls_made'] += 1
            return category or "Other"
                
        except Exception as e:
            logging.error(f"Error categorizing article {article.url}: {e}")
            return "Other"
    
    def _get_default_category(self) -> str:
        """Get default category."""
        return "Other"
    
    def _get_fallback_category(self, title: str) -> str:
        """Get fallback category based on title keywords."""
        title_lower = title.lower()
        
        # Simple keyword-based categorization
        if any(word in title_lower for word in ['tech', 'technology', 'software', 'AI', 'artificial intelligence', 'digital', 'computer', 'internet']):
            return "Tech"
        elif any(word in title_lower for word in ['business', 'economy', 'market', 'finance', 'money', 'investment', 'stock']):
            return "Business"
        elif any(word in title_lower for word in ['science', 'research', 'study', 'scientist', 'discovery']):
            return "Science"
        elif any(word in title_lower for word in ['nature', 'environment', 'climate', 'wildlife', 'ecology']):
            return "Nature"
        elif any(word in title_lower for word in ['serbia', 'serbian', 'belgrade', 'novi sad', 'srbija']):
            return "Serbia"
        elif any(word in title_lower for word in ['marketing', 'advertising', 'brand', 'campaign']):
            return "Marketing"
        else:
            return self._get_default_category()
    
    
    async def _generate_telegram_digest(self, db: AsyncSession, stats: Dict[str, Any]):
        """Generate Telegram digest from articles directly (like old version)."""
        try:
            # Get today's articles by published date (all new articles, not limited)
            today = datetime.utcnow().date()
            articles_result = await db.execute(
                select(Article).where(func.date(Article.published_at) == today)
                .order_by(Article.published_at.desc())
                # No limit - process all new articles for today
            )
            articles = articles_result.scalars().all()
            
            if not articles:
                print("  ℹ️ No articles found for today")
                return
            
            # Group articles by category (like old version)
            categories = {}
            for article in articles:
                category = article.category or "Other"
                
                if category not in categories:
                    categories[category] = []
                
                # Structure like old version for compatibility
                categories[category].append({
                    'headline': article.title,
                    'link': article.url,
                    'links': [article.url],  # For Telegraph compatibility
                    'description': article.summary or article.content[:500] + "..." if article.content else "",
                    'category': category,
                    'image_url': article.image_url  # Add image URL for Telegraph
                })
            
            # Generate and save daily summaries by category
            await self._generate_and_save_daily_summaries(db, today, categories)
            
            print(f"  📊 Categories found: {list(categories.keys())}")
            
            # Create Telegraph page first (using old version format)
            from .services.telegraph_service import TelegraphService
            telegraph_service = TelegraphService()
            telegraph_url = await telegraph_service.create_news_page(categories)
            
            if not telegraph_url or not telegraph_url.startswith("http"):
                telegraph_url = None
                print("  ⚠️ Telegraph page creation failed")
            else:
                print(f"  📖 Telegraph page created: {telegraph_url}")
            
            # Generate digest using Telegram AI (like old version)
            from .services.telegram_ai import get_telegram_ai
            telegram_ai = get_telegram_ai()
            digest = await telegram_ai.generate_daily_digest(categories)
            
            if digest and len(digest.strip()) > 10:
                print(f"  ✅ Generated digest ({len(digest)} chars)")
                
                # Send digest to Telegram with Telegraph button
                if telegraph_url:
                    # Send with Telegraph button
                    inline_keyboard = [[{"text": "📖 Читать полностью", "url": telegraph_url}]]
                    telegram_sent = await self.telegram_service.send_message_with_keyboard(digest, inline_keyboard)
                else:
                    # Send regular message if Telegraph failed
                    telegram_sent = await self.telegram_service.send_daily_digest(digest)
                
                stats['telegram_digest_generated'] = True
                stats['telegram_digest_sent'] = telegram_sent
                stats['telegram_digest_length'] = len(digest)
                stats['telegram_articles'] = len(articles)
                stats['telegram_categories'] = len(categories)
                
                if telegram_sent:
                    print(f"  📱 Digest sent to Telegram successfully")
                else:
                    print(f"  ⚠️ Failed to send digest to Telegram")
            else:
                print("  ⚠️ Failed to generate meaningful digest")
                stats['telegram_digest_generated'] = False
                
        except Exception as e:
            error_msg = f"Error generating Telegram digest: {e}"
            stats['errors'].append(error_msg)
            print(f"  ❌ {error_msg}")
    
    async def _generate_and_save_daily_summaries(self, db: AsyncSession, date, categories: Dict[str, List]):
        """Generate and save daily summaries by category."""
        from .models import DailySummary
        from .services.telegram_ai import get_telegram_ai
        
        telegram_ai = get_telegram_ai()
        
        for category, articles in categories.items():
            if not articles:
                continue
                
            try:
                print(f"  📝 Generating summary for {category} ({len(articles)} articles)")
                
                # Prepare articles data for summary generation (use headline/description like old version)
                articles_text = ""
                for article in articles:
                    articles_text += f"Заголовок: {article['headline']}\n"
                    if article.get('description'):
                        articles_text += f"Описание: {article['description'][:300]}...\n"
                    articles_text += "---\n"
                
                # Generate category summary using AI
                summary_prompt = (
                    f"Создай краткую сводку новостей в категории {category} на русском языке. "
                    f"Максимум 500 символов. Основные события и тренды:\n\n{articles_text}"
                )
                
                summary_text = await telegram_ai._make_ai_request(summary_prompt)
                
                if not summary_text or summary_text == "Error":
                    # Fallback summary
                    summary_text = f"В категории {category} за сегодня: {len(articles)} новостей. " + \
                                 ", ".join([article['headline'][:50] + "..." for article in articles[:3]])
                
                # Save or update daily summary
                existing_summary = await db.execute(
                    select(DailySummary).where(
                        DailySummary.date == date,
                        DailySummary.category == category
                    )
                )
                existing = existing_summary.scalar_one_or_none()
                
                if existing:
                    existing.summary_text = summary_text
                    existing.articles_count = len(articles)
                else:
                    daily_summary = DailySummary(
                        date=date,
                        category=category,
                        summary_text=summary_text,
                        articles_count=len(articles)
                    )
                    db.add(daily_summary)
                
                await db.commit()
                print(f"  ✅ Summary saved for {category}")
                
            except Exception as e:
                print(f"  ⚠️ Error generating summary for {category}: {e}")
                continue
    
    async def _generate_output(self, db: AsyncSession, stats: Dict[str, Any]):
        """Generate output files (JSON, web data)."""
        # TODO: Implement output generation
        # This would generate:
        # - JSON API files for web interface
        # - Static HTML pages
        # - RSS feed for compatibility
        # - Upload to S3 if configured
        pass
    
    async def _update_processing_stats(self, db: AsyncSession, stats: Dict[str, Any]):
        """Update processing statistics in database."""
        today = datetime.utcnow().date()
        
        # Get or create today's stats
        existing_stats = await db.execute(
            select(ProcessingStat).where(ProcessingStat.date == today)
        )
        existing_stats = existing_stats.scalar_one_or_none()
        
        if existing_stats:
            # Update existing stats
            existing_stats.articles_fetched += stats['articles_fetched']
            existing_stats.articles_processed += stats['articles_processed']
            existing_stats.api_calls_made += stats['api_calls_made']
            existing_stats.errors_count += len(stats['errors'])
            existing_stats.processing_time_seconds += int(stats.get('duration_seconds', 0))
        else:
            # Create new stats
            processing_stat = ProcessingStat(
                date=today,
                articles_fetched=stats['articles_fetched'],
                articles_processed=stats['articles_processed'],
                api_calls_made=stats['api_calls_made'],
                errors_count=len(stats['errors']),
                processing_time_seconds=int(stats.get('duration_seconds', 0))
            )
            db.add(processing_stat)
        
        await db.commit()
    
    async def get_processing_stats(self, days: int = 7) -> Dict[str, Any]:
        """Get processing statistics for the last N days."""
        async with AsyncSessionLocal() as db:
            since_date = datetime.utcnow().date() - timedelta(days=days)
            
            result = await db.execute(
                select(ProcessingStat)
                .where(ProcessingStat.date >= since_date)
                .order_by(ProcessingStat.date.desc())
            )
            
            stats = result.scalars().all()
            
            return {
                'daily_stats': [
                    {
                        'date': stat.date.isoformat(),
                        'articles_fetched': stat.articles_fetched,
                        'articles_processed': stat.articles_processed,
                        'api_calls_made': stat.api_calls_made,
                        'errors_count': stat.errors_count,
                        'processing_time_seconds': stat.processing_time_seconds
                    }
                    for stat in stats
                ],
                'totals': {
                    'articles_fetched': sum(s.articles_fetched for s in stats),
                    'articles_processed': sum(s.articles_processed for s in stats),
                    'api_calls_made': sum(s.api_calls_made for s in stats),
                    'errors_count': sum(s.errors_count for s in stats),
                    'total_processing_time': sum(s.processing_time_seconds for s in stats)
                }
            }