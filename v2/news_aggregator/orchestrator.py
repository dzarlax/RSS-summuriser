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
from .core.exceptions import NewsAggregatorError
from .config import settings


class NewsOrchestrator:
    """Main orchestrator for news processing."""
    
    def __init__(self):
        self.source_manager = SourceManager()
        self.ai_client = get_ai_client()
        self.telegram_service = get_telegram_service()
        
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
        
        try:
            async with AsyncSessionLocal() as db:
                # Step 1: Fetch new articles from all sources
                print("📥 Fetching articles from sources...")
                fetch_results = await self.source_manager.fetch_from_all_sources(db)
                
                all_articles = []
                for source_name, articles in fetch_results.items():
                    print(f"  • {source_name}: {len(articles)} articles")
                    all_articles.extend(articles)
                    stats['articles_fetched'] += len(articles)
                
                # Step 2: Get articles that need processing (new + unprocessed + without categories)
                from sqlalchemy import select, or_
                from sqlalchemy.orm import selectinload
                unprocessed_result = await db.execute(
                    select(Article).options(selectinload(Article.source)).where(
                        or_(
                            (Article.summary.is_(None)) | (Article.summary == ''),  # No summary
                            (Article.category.is_(None)) | (Article.category == '') | (Article.category == 'Other')  # No category or default
                        )
                    ).limit(200)  # Process max 200 at once (increased for category processing)
                )
                unprocessed_articles = list(unprocessed_result.scalars().all())
                
                # Combine new and unprocessed articles (removing duplicates)
                articles_to_process = list({article.id: article for article in (all_articles + unprocessed_articles)}.values())
                
                if not articles_to_process:
                    print("ℹ️ No articles to process")
                    return stats
                
                # Count different types of articles to process
                new_count = len(all_articles)
                no_summary_count = len([a for a in unprocessed_articles if not a.summary or a.summary == ''])
                # Count articles that need processing based on new flags
                no_summary_count = len([a for a in unprocessed_articles if not getattr(a, 'summary_processed', False)])
                no_category_count = len([a for a in unprocessed_articles if not getattr(a, 'category_processed', False)])
                
                print(f"🤖 Processing {len(articles_to_process)} articles with AI:")
                print(f"   • {new_count} new articles")
                print(f"   • {no_summary_count} articles without summary") 
                print(f"   • {no_category_count} articles needing categorization")
                
                processed_articles = await self._process_articles_with_ai(db, articles_to_process, stats)
                stats['articles_processed'] = len(processed_articles)
                
                # Step 3: Skip Telegram digest generation in sync - will be done separately
                print("📊 Sync completed - digest can be sent separately")
                
                # Step 4: Update statistics
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
                
                print(f"  🔍 Processing needs: {'✅ Summary' if needs_summary else '❌ Summary'}, {'✅ Category' if needs_category else '❌ Category'}")
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
                    'category': category
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