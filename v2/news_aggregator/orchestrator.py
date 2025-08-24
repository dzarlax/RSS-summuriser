"""Main orchestrator for RSS Summarizer v2."""

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from .database import AsyncSessionLocal
from .models import Source, Article, ProcessingStat, DailySummary
from .services.source_manager import SourceManager
from .services.ai_client import get_ai_client
from .services.telegram_service import get_telegram_service
from .services.database_queue import get_database_queue, DatabaseQueueManager
from .database_helpers import fetch_all, fetch_one, insert_one, update_query, execute_custom_read, execute_custom_write
from .core.exceptions import NewsAggregatorError
from .config import settings


# Legacy database write queue classes removed - now using universal DatabaseQueueManager



class NewsOrchestrator:
    """Main orchestrator for news processing."""
    
    def __init__(self):
        self.source_manager = SourceManager()
        self.ai_client = get_ai_client()
        self.telegram_service = get_telegram_service()
        
        # Use new universal database queue system
        self.db_queue_manager = get_database_queue()
        
        # Legacy queue for backward compatibility (will be removed)
        self.db_queue = None
        
        # Initialize AI services
        try:
            from .services.categorization_ai import CategorizationAI
            self.categorization_ai = CategorizationAI()
        except Exception as e:
            print(f"⚠️ Warning: Could not initialize categorization AI: {e}")
            self.categorization_ai = None
    
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
            'started_at': start_time,
            'articles_fetched': 0,
            'articles_processed': 0,
            'api_calls_made': 0,
            'errors': []
        }
        
        # Database queue is managed globally, no need to start/stop here
        
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
                            (Article.ad_processed.is_(False))  # Need advertising detection for ALL sources
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
                
                # Smart Filter statistics
                if 'smart_filter_skipped' in stats or 'smart_filter_approved' in stats:
                    skipped = stats.get('smart_filter_skipped', 0)
                    approved = stats.get('smart_filter_approved', 0)
                    total_filtered = skipped + approved
                    if total_filtered > 0:
                        skip_percentage = (skipped / total_filtered * 100) if total_filtered > 0 else 0
                        print(f"   Smart Filter: {skipped} skipped, {approved} approved ({skip_percentage:.1f}% filtered)")
                
                return stats
                
        except Exception as e:
            error_msg = f"Orchestrator error: {e}"
            stats['errors'].append(error_msg)
            print(f"❌ {error_msg}")
            raise NewsAggregatorError(error_msg) from e
        
        finally:
            # Database queue is managed globally, cleanup not needed here
            pass
    
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
    
    async def _process_article_ai_combined(self, article_data: Dict[str, Any], stats: Dict[str, Any]) -> Dict[str, Any]:
        """Process article with combined AI analysis - all tasks in one API call."""
        source_type = article_data.get('source_type', 'rss')
        source_name = article_data.get('source_name', 'Unknown')
        article_id = article_data['id']
        
        print(f"  📡 Source: {source_name} (type: {source_type})")
        
        # Check what processing is needed
        needs_summary = not article_data.get('summary_processed', False) and not article_data.get('summary')
        needs_category = not article_data.get('category_processed', False)
        needs_ad_detection = not article_data.get('ad_processed', False)
        
        # Smart Filtering: Check if article needs AI processing at all
        if needs_summary or needs_category or needs_ad_detection:
            from .services.smart_filter import get_smart_filter
            smart_filter = get_smart_filter()
            
            article_content = article_data.get('content', '')
            article_url = article_data.get('url', '')
            
            should_process, filter_reason = smart_filter.should_process_with_ai(
                title=article_data.get('title', ''),
                content=article_content,
                url=article_url,
                source_type=source_type
            )
            
            # If content is too short but we have external URL, try to extract full content
            if not should_process and "Content too short" in filter_reason and source_type == 'telegram':
                if article_url and not any(domain in article_url.lower() for domain in ['t.me', 'telegram.me']):
                    try:
                        print(f"  🔍 Content too short, trying to extract from external URL using full parsing pipeline: {article_url}")
                        
                        # Use full content extraction pipeline with all parsing schemas
                        from .services import get_content_extractor
                        content_extractor = await get_content_extractor()
                        
                        # Try AI-enhanced extraction with metadata first
                        extracted_content = None
                        try:
                            extraction_result = await content_extractor.extract_article_content_with_metadata(article_url)
                            extracted_content = extraction_result.get('content')
                        except Exception as e:
                            print(f"  ⚠️ AI-enhanced extraction failed, trying standard extraction: {e}")
                            # Fallback to standard content extraction
                            try:
                                extracted_content = await content_extractor.extract_article_content(article_url)
                            except Exception as e2:
                                print(f"  ❌ Standard extraction also failed: {e2}")
                                extracted_content = None
                        
                        # Check if extracted content is meaningful
                        if extracted_content and len(extracted_content.strip()) > len(article_content):
                            print(f"  ✅ Extracted {len(extracted_content)} chars from external URL using parsing schemas")
                            
                            # Update article with extracted content
                            article_data['content'] = extracted_content
                            update_fields = {'content': extracted_content}
                            await self._save_article_fields(article_id, update_fields)
                            
                            # Re-check smart filter with new content
                            should_process, filter_reason = smart_filter.should_process_with_ai(
                                title=article_data.get('title', ''),
                                content=extracted_content,
                                url=article_url,
                                source_type=source_type
                            )
                        else:
                            print(f"  ⚠️ Could not extract meaningful content from external URL")
                    except Exception as e:
                        print(f"  ❌ Failed to extract content from external URL: {e}")
            
            if not should_process:
                print(f"  🚫 Smart Filter: Skipping AI processing - {filter_reason}")
                # Mark as processed with fallback values to avoid reprocessing
                update_fields = {}
                if needs_summary:
                    update_fields['summary'] = article_data.get('title', 'No summary available')
                    update_fields['summary_processed'] = True
                if needs_category:
                    update_fields['category'] = 'Other'
                    update_fields['category_processed'] = True
                if needs_ad_detection:
                    update_fields['is_advertisement'] = False
                    update_fields['ad_confidence'] = 0.0
                    update_fields['ad_type'] = 'news_article'
                    update_fields['ad_reasoning'] = f'Smart Filter: {filter_reason}'
                    update_fields['ad_processed'] = True
                
                # Save fallback results
                await self._save_article_fields(article_id, update_fields)
                stats.setdefault('smart_filter_skipped', 0)
                stats['smart_filter_skipped'] += 1
                
                return {**article_data, **update_fields}
            else:
                print(f"  ✅ Smart Filter: Approved for AI processing - {filter_reason}")
                stats.setdefault('smart_filter_approved', 0)
                stats['smart_filter_approved'] += 1
        
        # If all processing is already done, skip
        if not (needs_summary or needs_category or needs_ad_detection):
            print(f"  ✅ All processing already completed")
            return article_data
            
        print(f"  🔍 Processing needs: {'✅ Summary' if needs_summary else '❌ Summary'}, {'✅ Category' if needs_category else '❌ Category'}, {'✅ Ad Detection' if needs_ad_detection else '❌ Ad Detection'}")
        
        # Use combined AI analysis if we need multiple tasks
        if sum([needs_summary, needs_category, needs_ad_detection]) >= 2:
            print(f"  🧠 Using combined AI analysis for efficiency...")
            try:
                import time
                start_time = time.time()
                
                # Get combined analysis
                ai_result = await self.ai_client.analyze_article_complete(
                    title=article_data.get('title', ''),
                    content=article_data.get('content', ''),
                    url=article_data.get('url', '')
                )
                
                elapsed_time = time.time() - start_time
                print(f"  ✅ Combined analysis completed in {elapsed_time:.1f}s")
                stats['api_calls_made'] += 1
                
                # Save all results at once
                update_fields = {}
                if needs_summary and ai_result.get('summary'):
                    update_fields['summary'] = ai_result['summary']
                    update_fields['summary_processed'] = True
                    
                if needs_category:
                    # Keep old category field for backward compatibility
                    update_fields['category'] = ai_result.get('category', 'Other')
                    update_fields['category_processed'] = True
                    
                    # Handle multiple categories
                    try:
                        from .services.category_service import get_category_service
                        async with AsyncSessionLocal() as db:
                            category_service = await get_category_service(db)
                            assigned_categories = await category_service.assign_categories_to_article(
                                article_id=article_id,
                                category_raw=ai_result.get('category', 'Other'),
                                title=article_data.get('title'),
                                content=article_data.get('content')
                            )
                            print(f"  🏷️ Multiple categories assigned: {[c['display_name'] for c in assigned_categories]}")
                    except Exception as e:
                        print(f"  ⚠️ Multiple categories assignment failed: {e}")
                    
                if needs_ad_detection:
                    update_fields['is_advertisement'] = ai_result.get('is_advertisement', False)
                    update_fields['ad_confidence'] = ai_result.get('ad_confidence', 0.0)
                    update_fields['ad_type'] = ai_result.get('ad_type', 'news_article')
                    update_fields['ad_reasoning'] = ai_result.get('ad_reasoning', 'Combined analysis')
                    update_fields['ad_processed'] = True
                    
                # Save all fields in one database operation
                await self._save_article_fields(article_id, update_fields)
                
                print(f"  💾 All results saved to database")
                print(f"  📊 Summary: {ai_result.get('summary', 'None')[:100]}...")
                print(f"  🏷️ Category: {ai_result.get('category', 'Other')}")
                print(f"  🚨 Advertisement: {ai_result.get('is_advertisement', False)} (confidence: {ai_result.get('ad_confidence', 0.0):.2f})")
                
                return {**article_data, **update_fields}
                
            except Exception as e:
                print(f"  ❌ Combined analysis failed: {e}")
                # Fall back to incremental processing
                return await self._process_article_ai_incremental(article_data, stats)
        else:
            # Use incremental processing for single tasks
            return await self._process_article_ai_incremental(article_data, stats)

    async def _process_article_ai_incremental(self, article_data: Dict[str, Any], stats: Dict[str, Any]) -> Dict[str, Any]:
        """Process article with AI, saving after each API call."""
        source_type = article_data.get('source_type', 'rss')
        source_name = article_data.get('source_name', 'Unknown')
        article_id = article_data['id']
        
        print(f"  📡 Source: {source_name} (type: {source_type})")
        
        # Check what processing is needed
        needs_summary = not article_data.get('summary_processed', False) and not article_data.get('summary')
        needs_category = not article_data.get('category_processed', False)
        needs_ad_detection = not article_data.get('ad_processed', False)
        
        # Smart Filtering: Check if article needs AI processing at all
        if needs_summary or needs_category or needs_ad_detection:
            from .services.smart_filter import get_smart_filter
            smart_filter = get_smart_filter()
            
            article_content = article_data.get('content', '')
            article_url = article_data.get('url', '')
            
            should_process, filter_reason = smart_filter.should_process_with_ai(
                title=article_data.get('title', ''),
                content=article_content,
                url=article_url,
                source_type=source_type
            )
            
            # If content is too short but we have external URL, try to extract full content
            if not should_process and "Content too short" in filter_reason and source_type == 'telegram':
                if article_url and not any(domain in article_url.lower() for domain in ['t.me', 'telegram.me']):
                    try:
                        print(f"  🔍 Content too short, trying to extract from external URL using full parsing pipeline: {article_url}")
                        
                        # Use full content extraction pipeline with all parsing schemas
                        from .services import get_content_extractor
                        content_extractor = await get_content_extractor()
                        
                        # Try AI-enhanced extraction with metadata first
                        extracted_content = None
                        try:
                            extraction_result = await content_extractor.extract_article_content_with_metadata(article_url)
                            extracted_content = extraction_result.get('content')
                        except Exception as e:
                            print(f"  ⚠️ AI-enhanced extraction failed, trying standard extraction: {e}")
                            # Fallback to standard content extraction
                            try:
                                extracted_content = await content_extractor.extract_article_content(article_url)
                            except Exception as e2:
                                print(f"  ❌ Standard extraction also failed: {e2}")
                                extracted_content = None
                        
                        # Check if extracted content is meaningful
                        if extracted_content and len(extracted_content.strip()) > len(article_content):
                            print(f"  ✅ Extracted {len(extracted_content)} chars from external URL using parsing schemas")
                            
                            # Update article with extracted content
                            article_data['content'] = extracted_content
                            await self._save_article_field(article_id, 'content', extracted_content)
                            
                            # Re-check smart filter with new content
                            should_process, filter_reason = smart_filter.should_process_with_ai(
                                title=article_data.get('title', ''),
                                content=extracted_content,
                                url=article_url,
                                source_type=source_type
                            )
                        else:
                            print(f"  ⚠️ Could not extract meaningful content from external URL")
                    except Exception as e:
                        print(f"  ❌ Failed to extract content from external URL: {e}")
            
            if not should_process:
                print(f"  🚫 Smart Filter: Skipping AI processing - {filter_reason}")
                # Mark individual tasks as processed with fallback values
                if needs_summary:
                    await self._save_article_field(article_id, 'summary', article_data.get('title', 'No summary available'), 'summary_processed', True)
                if needs_category:
                    await self._save_article_field(article_id, 'category', 'Other', 'category_processed', True)
                if needs_ad_detection:
                    await self._save_article_field(article_id, 'is_advertisement', False, 'ad_confidence', 0.0, 'ad_type', 'news_article', 'ad_reasoning', f'Smart Filter: {filter_reason}', 'ad_processed', True)
                
                stats.setdefault('smart_filter_skipped', 0)
                stats['smart_filter_skipped'] += 1
                return article_data
            else:
                print(f"  ✅ Smart Filter: Approved for AI processing - {filter_reason}")
                stats.setdefault('smart_filter_approved', 0)
                stats['smart_filter_approved'] += 1
        
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
                # ============================================================================
                # DEPRECATED: Individual categorization replaced by combined analysis
                # ============================================================================  
                # Categorization is now handled by analyze_article_complete() in combined
                # analysis along with summarization and ad detection for efficiency.
                #
                # Old code:
                # if self.categorization_ai:
                #     category = await self.categorization_ai.categorize_article(...)
                # ============================================================================
                
                # Use fallback categorization for incremental processing
                category = 'Other'  # Fallback category (combined analysis handles this better)
                print(f"  ✅ Category assigned (fallback): {category}")
                
                # Save category immediately
                await self._save_article_field(article_id, 'category', category, 'category_processed', True)
                stats['api_calls_made'] += 1
                print(f"  💾 Category saved to database")
                
            except Exception as e:
                print(f"  ❌ Categorization failed: {e}")
                # Set default category and mark as processed
                await self._save_article_field(article_id, 'category', 'Other', 'category_processed', True)
        
        # ============================================================================ 
        # DEPRECATED: Ad detection in incremental processing replaced by combined analysis
        # ============================================================================
        # Individual ad detection is now handled by analyze_article_complete() which does
        # advertising detection, summarization, and categorization in one API call.
        # This reduces AI requests by ~75% and improves accuracy.
        #
        # Process ad detection if needed
        if needs_ad_detection:
            print(f"  🛡️ Ad detection moved to combined analysis - using fallback...")
            # Set fallback values and mark as processed
            await self._save_article_fields(article_id, {
                'is_advertisement': False,
                'ad_confidence': 0.1,
                'ad_type': 'news_article',
                'ad_reasoning': 'Incremental processing fallback',
                'ad_processed': True,
            })
            print(f"  💾 Ad detection fallback saved to database")
        # ============================================================================
        
        return {}  # No need to return results since we save immediately
    
    async def _process_article_ai_queued(self, article_data: Dict[str, Any], stats: Dict[str, Any]) -> Dict[str, Any]:
        """Process article with AI, using optimized combined analysis when possible."""
        # Use combined analysis for efficiency
        return await self._process_article_ai_combined(article_data, stats)
        
        # ============================================================================
        # DEAD CODE WARNING: Lines below are unreachable (after return statement)
        # ============================================================================
        # This entire block was the old incremental processing logic that is now
        # replaced by the combined analysis approach (_process_article_ai_combined).
        # 
        # The old code included:
        # - Process summary if needed (using _get_summary_by_source_type)
        # - Process category if needed (using categorization_ai.categorize_article) 
        # - Process ad detection if needed (using AdDetector)
        # - Various database field updates through write queue
        #
        # All these operations are now handled efficiently by analyze_article_complete()
        # in a single AI API call, reducing requests by ~75%.
        #
        # TODO: Remove this dead code block in future cleanup.
        # ============================================================================
        
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
                from .services.ad_detector import AdDetector
                detector = AdDetector(enable_ai=True)
                result = await detector.detect(
                    title=article_data.get('title'),
                    content=article_data.get('content') or article_data.get('summary'),
                    url=article_data.get('url')
                )
                is_advertisement = bool(result.get('is_advertisement', False))
                ad_confidence = float(result.get('ad_confidence', 0.0))
                ad_type = result.get('ad_type')
                ad_reasoning = result.get('ad_reasoning')
                ad_markers = result.get('ad_markers', [])
                print(f"  ✅ Ad detection result: {'Advertisement' if is_advertisement else 'Not advertisement'} (conf {ad_confidence})")

                # Add to field updates
                field_updates['is_advertisement'] = is_advertisement
                field_updates['ad_confidence'] = ad_confidence
                field_updates['ad_type'] = ad_type
                field_updates['ad_reasoning'] = ad_reasoning
                field_updates['ad_markers'] = ad_markers
                field_updates['ad_processed'] = True
                stats['api_calls_made'] += 1
                print(f"  🔄 Ad detection result queued for write")
                
            except Exception as e:
                print(f"  ❌ Ad detection failed: {e}")
                # Set default and mark as processed
                field_updates['is_advertisement'] = False
                field_updates['ad_processed'] = True
        
        # Submit all updates through write queue
        if field_updates:
            async def update_operation(session):
                from sqlalchemy import select, update
                # Update article fields
                stmt = update(Article).where(Article.id == article_id).values(**field_updates)
                await session.execute(stmt)
                await session.commit()
                return len(field_updates)
            
            await execute_custom_write(update_operation)
            print(f"  📤 Applied {len(field_updates)} field updates through write queue")
        
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

    async def _save_article_fields(self, article_id: int, fields_dict: Dict[str, Any]):
        """Save multiple article fields to database in one operation."""
        try:
            async with AsyncSessionLocal() as db:
                from .models import Article
                from sqlalchemy import select
                
                result = await db.execute(select(Article).where(Article.id == article_id))
                article = result.scalar_one_or_none()
                
                if not article:
                    print(f"⚠️ Article {article_id} not found for fields update")
                    return
                
                # Set all fields from dictionary
                for field_name, field_value in fields_dict.items():
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
                            
                            # ============================================================================
                            # DEPRECATED: Single AI call for ad detection replaced by combined analysis
                            # ============================================================================
                            # This separate ad detection call is now handled by analyze_article_complete()
                            # in combined analysis for efficiency. Using fallback values instead.
                            #
                            # Old code:
                            # source_info = {...}
                            # ad_detection = await self.ai_client.detect_advertising(...)
                            # ============================================================================
                            
                            # Fallback values for old articles without combined analysis
                            ad_detection = {
                                'is_advertisement': False,
                                'confidence': 0.1,
                                'ad_type': 'news_article',
                                'reasoning': 'Legacy processing - no AI analysis',
                                'markers': []
                            }
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
                    article.summary = article.content or article.title
                
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
                # RSS sources: use AI to extract and summarize full article content with metadata
                ai_result = await self.ai_client.get_article_summary_with_metadata(article.url)
                stats['api_calls_made'] += 1
                
                ai_summary = ai_result.get('summary')
                pub_date = ai_result.get('publication_date')
                
                # Update published_at if we found a publication date
                self._update_article_publication_date(article, pub_date, 'RSS')
                
                if ai_summary:
                    return ai_summary
                else:
                    # Fallback to RSS content
                    return article.content or article.title
                    
            elif source_type == 'telegram':
                # Telegram sources: avoid heavy AI extraction for Telegram domains (t.me/telegram.me)
                # Prefer external original link if present and NOT a Telegram domain
                original_link = None
                try:
                    if hasattr(article, 'raw_data') and article.raw_data:
                        original_link = article.raw_data.get('original_link')
                except Exception:
                    original_link = None

                def _is_telegram_domain(url: str) -> bool:
                    try:
                        from urllib.parse import urlparse
                        host = urlparse(url).netloc.lower()
                        return ('t.me' in host) or ('telegram.me' in host)
                    except Exception:
                        return False

                # Only attempt AI metadata extraction when we have a non-Telegram external link
                if original_link and not _is_telegram_domain(original_link):
                    try:
                        ai_result = await self.ai_client.get_article_summary_with_metadata(original_link)
                        pub_date = ai_result.get('publication_date')
                        # Update published_at if we found a publication date
                        self._update_article_publication_date(article, pub_date, 'Telegram')
                        ai_summary = ai_result.get('summary')
                        if ai_summary:
                            # If AI managed to summarize external article, use it
                            return ai_summary
                    except Exception as e:
                        print(f"  ⚠️ Skipping Telegram AI extraction (external link failed): {e}")

                # Fallback: use Telegram preview content
                return article.content or article.title
                
            elif source_type == 'reddit':
                # Reddit sources: use AI to get full post content + comments context with metadata
                ai_result = await self.ai_client.get_article_summary_with_metadata(article.url)
                stats['api_calls_made'] += 1
                
                ai_summary = ai_result.get('summary')
                pub_date = ai_result.get('publication_date')
                
                # Update published_at if we found a publication date
                self._update_article_publication_date(article, pub_date, 'Reddit')
                
                if ai_summary:
                    return ai_summary
                else:
                    # Fallback to reddit content
                    return article.content or article.title
                    
            elif source_type == 'twitter':
                # Twitter sources: extract publication date if URL is available
                if article.url and article.url.startswith('http'):
                    try:
                        ai_result = await self.ai_client.get_article_summary_with_metadata(article.url)
                        pub_date = ai_result.get('publication_date')
                        
                        # Update published_at if we found a publication date
                        self._update_article_publication_date(article, pub_date, 'Twitter')
                    except Exception as e:
                        print(f"  ⚠️ Error extracting Twitter metadata: {e}")
                
                # Tweet content is usually complete, minimal processing
                return article.content or article.title
                
            elif source_type == 'news_api':
                # News API sources: use AI to get full article content with metadata
                ai_result = await self.ai_client.get_article_summary_with_metadata(article.url)
                stats['api_calls_made'] += 1
                
                ai_summary = ai_result.get('summary')
                pub_date = ai_result.get('publication_date')
                
                # Update published_at if we found a publication date
                self._update_article_publication_date(article, pub_date, 'News API')
                
                if ai_summary:
                    return ai_summary
                else:
                    # Fallback to API content
                    return article.content or article.title
                    
            else:
                # Custom or unknown source types: use AI processing with metadata
                ai_result = await self.ai_client.get_article_summary_with_metadata(article.url)
                stats['api_calls_made'] += 1
                
                ai_summary = ai_result.get('summary')
                pub_date = ai_result.get('publication_date')
                
                # Update published_at if we found a publication date
                self._update_article_publication_date(article, pub_date, source_type)
                
                if ai_summary:
                    return ai_summary
                else:
                    # Fallback to original content
                    return article.content or article.title
                    
        except Exception as e:
            print(f"  ⚠️ Error getting summary by source type: {e}")
            # Fallback to original content
            return article.content or article.title
    
    def _update_article_publication_date(self, article: Article, pub_date: str, source_type: str):
        """Update article publication date from extracted date string."""
        if not pub_date:
            return
            
        try:
            from datetime import datetime
            import dateutil.parser
            parsed_date = dateutil.parser.parse(pub_date)
            article.published_at = parsed_date
            print(f"  📅 Updated {source_type} article published_at: {parsed_date}")
        except Exception as e:
            print(f"  ⚠️ Error parsing {source_type} publication date '{pub_date}': {e}")
    
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
            # Get today's articles by published date (excluding advertisements)
            today = datetime.utcnow().date()
            articles_result = await db.execute(
                select(Article).where(
                    func.date(Article.published_at) == today,
                    Article.is_advertisement != True  # Exclude advertisements from digest
                )
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
        since_date = datetime.utcnow().date() - timedelta(days=days)
        
        query = select(ProcessingStat).where(
            ProcessingStat.date >= since_date
        ).order_by(ProcessingStat.date.desc())
        
        stats = await fetch_all(query)
        
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