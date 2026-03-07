import logging
"""Statistics collector for processing and monitoring."""

from typing import Dict, Any, List
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Article

logger = logging.getLogger(__name__)


class StatsCollector:
    """Handles collection and analysis of processing statistics."""
    
    async def get_processing_stats(self, days: int = 7) -> Dict[str, Any]:
        """Get processing statistics for the last N days."""
        from ..processing.processing_stats_service import get_processing_stats_service
        processing_stats_service = get_processing_stats_service()
        return await processing_stats_service.get_processing_stats(days)
    
    async def reprocess_failed_extractions(self, limit: int = 50, dry_run: bool = False) -> Dict[str, Any]:
        """
        Find and reprocess articles where title equals summary (indicates failed content extraction).
        
        Args:
            limit: Maximum number of articles to reprocess
            dry_run: If True, only identify candidates without processing
            
        Returns:
            Dictionary with processing results and statistics
        """
        from ..database_helpers import fetch_all
        
        logger.info(f"🔍 Finding articles with failed content extraction (limit: {limit})...")
        # Find articles where title equals summary (indicates failed extraction)
        query = select(Article).where(
            # Title equals summary (indicates failed extraction)
            ((Article.title == Article.summary) | 
             ((Article.summary.isnot(None)) & (func.trim(Article.title) == func.trim(Article.summary)))),
            # Exclude test URLs
            ~Article.url.like('%test.example.com%'),
            # Include all articles with short content - even Telegram posts might have external links
            func.length(func.coalesce(Article.content, '')) < 1000
        ).order_by(Article.fetched_at.desc()).limit(limit)
        
        candidates = await fetch_all(query)
        
        logger.info(f"📊 Found {len(candidates)} articles needing reprocessing")
        if dry_run:
            results = {
                'found_candidates': len(candidates),
                'candidates': [
                    {
                        'id': article.id,
                        'title': article.title[:100] + '...' if len(article.title) > 100 else article.title,
                        'url': article.url,
                        'content_length': len(article.content or ''),
                        'domain': article.url.split('/')[2] if '://' in article.url else 'unknown'
                    }
                    for article in candidates
                ]
            }
            return results
        
        # Process articles
        stats = {
            'processed': 0,
            'improved': 0,
            'failed': 0,
            'errors': [],
            'improvements': []
        }
        
        for article in candidates:
            try:
                logger.info(f"\n🔧 Processing article {article.id}: {article.title[:80]}...")
                logger.info(f"   URL: {article.url}")
                logger.info(f"   Current content: {len(article.content or '')} chars")
                # Reset processing flags to force complete reprocessing
                from ..services.database_queue import get_db_queue_manager
                _article_id = article.id

                async def _reset_flags(db):
                    await db.execute(
                        text("UPDATE articles SET summary_processed = false, category_processed = false, ad_processed = false WHERE id = :article_id"),
                        {'article_id': _article_id}
                    )

                await get_db_queue_manager().execute_write(_reset_flags)
                
                # Create article data for processing
                article_data = {
                    'id': article.id,
                    'title': article.title,
                    'url': article.url,
                    'content': article.content,
                    'source_id': article.source_id,
                    'source_type': 'rss'  # Default, will be overridden by source manager if needed
                }
                
                # First: Try to extract content again with new encoding-aware method
                logger.info(f"   🔄 Step 1: Re-extracting content with encoding-aware method...")
                from ..extraction import ContentExtractor
                extractor = ContentExtractor()
                
                async with extractor:
                    try:
                        # Try to extract fresh content
                        extraction_result = await extractor.extract_article_content_with_metadata(article.url, retry_count=3)
                        new_content = extraction_result.get('content') if extraction_result else None
                        
                        if new_content and len(new_content) > len(article.content or ''):
                            logger.info(f"   ✅ Content improved: {len(article.content or '')} → {len(new_content)} chars")
                            # Update content in database
                            _new_content = new_content
                            _art_id = article.id

                            async def _update_content(db):
                                await db.execute(
                                    text("UPDATE articles SET content = :content WHERE id = :article_id"),
                                    {'content': _new_content, 'article_id': _art_id}
                                )

                            await get_db_queue_manager().execute_write(_update_content)
                            
                            article_data['content'] = new_content
                            
                            stats['improvements'].append({
                                'article_id': article.id,
                                'title': article.title[:100],
                                'old_length': len(article.content or ''),
                                'new_length': len(new_content)
                            })
                            stats['improved'] += 1
                        else:
                            logger.info(f"   📝 No content improvement, proceeding with current content")
                    except Exception as e:
                        logger.warning(f"   ⚠️ Content extraction failed: {e}")
                # Second: Run AI processing on the (potentially updated) content
                logger.info(f"   🔄 Step 2: Running AI processing...")
                # Use AIProcessor directly instead of going through orchestrator
                from .ai_processor import AIProcessor
                ai_processor = AIProcessor()
                
                processing_stats = {'api_calls_made': 0}
                result = await ai_processor.process_article_combined(article_data, processing_stats, force_processing=True)
                
                if result.get('success'):
                    logger.info(f"   ✅ AI processing successful")
                    stats['improved'] += 1
                else:
                    logger.warning(f"   ⚠️ AI processing had issues")
                stats['processed'] += 1
                
            except Exception as e:
                logger.error(f"   ❌ Error processing article {article.id}: {e}")
                stats['failed'] += 1
                stats['errors'].append({
                    'article_id': article.id,
                    'error': str(e)
                })
        
        return stats
    
    async def get_content_extraction_stats(self) -> Dict[str, Any]:
        """Get statistics about content extraction quality."""
        from ..services.database_queue import get_db_queue_manager

        async def _get_stats(db):
            # Articles with very short content (potential extraction failures)
            short_content_result = await db.execute(
                select(func.count(Article.id)).where(
                    func.length(func.coalesce(Article.content, '')) < 200
                )
            )
            short_content_count = short_content_result.scalar() or 0

            # Articles where title equals summary (likely extraction failures)
            failed_extraction_result = await db.execute(
                select(func.count(Article.id)).where(
                    Article.title == Article.summary
                )
            )
            failed_extraction_count = failed_extraction_result.scalar() or 0

            # Total articles
            total_result = await db.execute(select(func.count(Article.id)))
            total_articles = total_result.scalar() or 0

            # Success rates
            good_extraction_rate = ((total_articles - failed_extraction_count) / total_articles * 100) if total_articles > 0 else 0
            content_quality_rate = ((total_articles - short_content_count) / total_articles * 100) if total_articles > 0 else 0

            return {
                'total_articles': total_articles,
                'short_content_count': short_content_count,
                'failed_extraction_count': failed_extraction_count,
                'good_extraction_rate': round(good_extraction_rate, 2),
                'content_quality_rate': round(content_quality_rate, 2),
                'extraction_success_count': total_articles - failed_extraction_count,
                'quality_content_count': total_articles - short_content_count
            }

        return await get_db_queue_manager().execute_read(_get_stats)
    
    async def get_source_performance_stats(self) -> Dict[str, Any]:
        """Get performance statistics by source type."""
        from ..services.database_queue import get_db_queue_manager

        async def _get_perf_stats(db):
            # Articles by source type
            source_stats_result = await db.execute(
                text("""
                    SELECT
                        s.source_type,
                        COUNT(a.id) as article_count,
                        AVG(LENGTH(COALESCE(a.content, ''))) as avg_content_length,
                        COUNT(CASE WHEN a.title = a.summary THEN 1 END) as failed_extractions
                    FROM articles a
                    JOIN sources s ON a.source_id = s.id
                    GROUP BY s.source_type
                    ORDER BY article_count DESC
                """)
            )

            source_stats = []
            for row in source_stats_result.fetchall():
                source_type, count, avg_length, failed = row
                success_rate = ((count - failed) / count * 100) if count > 0 else 0

                source_stats.append({
                    'source_type': source_type,
                    'article_count': count,
                    'avg_content_length': round(avg_length or 0, 2),
                    'failed_extractions': failed,
                    'success_rate': round(success_rate, 2)
                })

            return {
                'source_stats': source_stats,
                'total_sources': len(source_stats)
            }

        return await get_db_queue_manager().execute_read(_get_perf_stats)