"""AI Processing Engine for articles."""

import time
from datetime import datetime
from typing import Dict, Any, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from ..database import AsyncSessionLocal
from ..services.ai_client import get_ai_client


class AIProcessor:
    """AI processing engine for articles."""
    
    def __init__(self):
        """Initialize AI processor with required services."""
        self.ai_client = get_ai_client()
    
    async def process_article_combined(
        self, 
        article_data: Dict[str, Any], 
        stats: Dict[str, Any], 
        force_processing: bool = False,
        db: AsyncSession = None
    ) -> Dict[str, Any]:
        """Process article with combined AI analysis - all tasks in one API call."""
        source_type = article_data.get('source_type', 'rss')
        source_name = article_data.get('source_name', 'Unknown')
        article_id = article_data['id']
        
        print(f"  📡 Source: {source_name} (type: {source_type})")
        print(f"  🔧 DEBUG: force_processing = {force_processing}")
        
        # Check what processing is needed
        needs_summary = force_processing or (not article_data.get('summary_processed', False) and not article_data.get('summary'))
        needs_category = force_processing or not article_data.get('category_processed', False)
        needs_ad_detection = force_processing or not article_data.get('ad_processed', False)
        
        # Smart Filtering: Check if article needs AI processing at all
        if needs_summary or needs_category or needs_ad_detection:
            from ..services.smart_filter import get_smart_filter
            smart_filter = get_smart_filter()
            
            article_content = article_data.get('content') or ''
            article_url = article_data.get('url') or ''
            
            if force_processing:
                should_process = True
                filter_reason = "Force processing enabled (reprocessing mode)"
                print(f"  🔄 Smart Filter: Bypassed for forced reprocessing")
            else:
                should_process, filter_reason = smart_filter.should_process_with_ai(
                    title=article_data.get('title') or '',
                    content=article_content,
                    url=article_url,
                    source_type=source_type
                )
            
            # If content is too short or empty, try to extract full content from URL
            content_too_short = (len(article_content.strip()) < 10 and source_type == 'rss') or len(article_content.strip()) < 10
            print(f"  🔍 Debug: content_too_short={content_too_short}, should_process={should_process}, filter_reason='{filter_reason}'")
            
            # Try content extraction if content is short OR metadata detected OR needs extraction OR force_processing
            should_extract = (
                force_processing or  # Always extract content during reprocessing
                (not should_process and ("Content too short" in filter_reason)) or 
                (not should_process and ("Metadata/low-quality content detected" in filter_reason)) or
                (not should_process and ("needs extraction" in filter_reason)) or
                content_too_short
            )
            
            if should_extract:
                if article_url and article_url.startswith(('http://', 'https://')):
                    # Skip URLs that are known to not have extractable content
                    skip_domains = ['t.me', 'telegram.me', 'twitter.com', 'x.com', 'instagram.com']
                    if not any(domain in article_url.lower() for domain in skip_domains):
                        try:
                            if "Metadata/low-quality content detected" in filter_reason or "needs extraction" in filter_reason:
                                print(f"  🔧 Metadata detected ({len(article_content)} chars), trying full content extraction: {article_url}")
                            else:
                                print(f"  🔍 Content empty/short ({len(article_content)} chars), trying content extraction: {article_url}")
                            
                            # Use full content extraction pipeline with all parsing schemas
                            from ..extraction import ContentExtractor
                            
                            # Try AI-enhanced extraction with metadata first
                            extracted_content = None
                            async with ContentExtractor() as content_extractor:
                                try:
                                    extraction_result = await content_extractor.extract_article_content_with_metadata(article_url, retry_count=4)
                                    extracted_content = extraction_result.get('content')
                                except Exception as e:
                                    print(f"  ⚠️ AI-enhanced extraction failed after retries, trying standard extraction: {e}")
                                    # Fallback to standard content extraction
                                    try:
                                        extracted_content = await content_extractor.extract_article_content(article_url, retry_count=3)
                                    except Exception as e2:
                                        print(f"  ❌ Standard extraction also failed after retries: {e2}")
                                        extracted_content = None
                            
                            # Check if extracted content is meaningful
                            if extracted_content and len(extracted_content.strip()) > len(article_content):
                                print(f"  ✅ Extracted {len(extracted_content)} chars from external URL using parsing schemas")
                                
                                # Update article with extracted content
                                article_data['content'] = extracted_content
                                update_fields = {'content': extracted_content}
                                await self._save_article_fields(article_id, update_fields)
                                
                                # Re-check smart filter with new content (unless force_processing is enabled)
                                if force_processing:
                                    should_process = True
                                    filter_reason = "Force processing enabled (after content extraction)"
                                    print(f"  🔄 Smart Filter: Bypassed after content extraction (forced reprocessing)")
                                else:
                                    should_process, filter_reason = smart_filter.should_process_with_ai(
                                        title=article_data.get('title') or '',
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
                    update_fields['category_processed'] = True
                if needs_ad_detection:
                    update_fields['is_advertisement'] = False
                    update_fields['ad_confidence'] = 0.0
                    update_fields['ad_type'] = 'news_article'
                    update_fields['ad_reasoning'] = f'Smart Filter: {filter_reason}'
                    update_fields['ad_processed'] = True
                
                # Mark as processed even when skipped by Smart Filter
                update_fields['processed'] = True
                
                # Extract media files even when Smart Filter skips AI processing
                print(f"  🖼️ Extracting media files (Smart Filter skip)...")
                from .media_extractor import get_media_extractor
                
                try:
                    # Check if media files already exist in article_data (e.g., from Telegram sources)
                    existing_media = article_data.get('media_files', [])
                    extracted_media = []
                    
                    if existing_media and isinstance(existing_media, list) and len(existing_media) > 0:
                        print(f"  📎 Using existing media files from article data: {len(existing_media)} files")
                        extracted_media = existing_media
                    else:
                        # Extract media files from HTML content
                        print(f"  🔍 Extracting media files from HTML content...")
                        media_extractor = get_media_extractor()
                        extracted_media = media_extractor.extract_media_files(
                            article_data.get('content', ''), 
                            base_url=article_data.get('url')
                        )
                    
                    if extracted_media:
                        # Add extracted media to update fields and article data
                        article_data['media_files'] = extracted_media
                        update_fields['media_files'] = extracted_media
                        
                        # Get media extractor for summary (if not already created)
                        if 'media_extractor' not in locals():
                            media_extractor = get_media_extractor()
                            
                        summary = media_extractor.get_media_summary(extracted_media)
                        print(f"  📎 Found {summary['total']} media files (Smart Filter skip)")
                        
                        # Save media files to database
                        await self._save_article_fields(article_id, {'media_files': extracted_media})
                    else:
                        print(f"  📭 No media files found in content (Smart Filter skip)")
                        
                except Exception as media_error:
                    print(f"  ❌ Media extraction failed (Smart Filter skip): {media_error}")
                    # Don't raise - media processing is optional
                
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
            # Ensure processed flag is set (safety check)
            if not article_data.get('processed', False):
                await self._save_article_fields(article_id, {'processed': True})
                print(f"  🔧 Safety: Set processed=True for fully processed article")
            return article_data
            
        print(f"  🔍 Processing needs: {'✅ Summary' if needs_summary else '❌ Summary'}, {'✅ Category' if needs_category else '❌ Category'}, {'✅ Ad Detection' if needs_ad_detection else '❌ Ad Detection'}")
        
        # Use combined AI analysis if we need multiple tasks
        if sum([needs_summary, needs_category, needs_ad_detection]) >= 2:
            return await self._process_with_combined_ai(
                article_id, article_data, stats, 
                needs_summary, needs_category, needs_ad_detection, db
            )
        else:
            # Use incremental processing for single tasks
            return await self.process_article_incremental(article_data, stats, force_processing)

    async def _process_with_combined_ai(
        self,
        article_id: int,
        article_data: Dict[str, Any],
        stats: Dict[str, Any],
        needs_summary: bool,
        needs_category: bool,
        needs_ad_detection: bool,
        db: AsyncSession = None
    ) -> Dict[str, Any]:
        """Process article with combined AI analysis."""
        print(f"  🧠 Using combined AI analysis for efficiency...")
        try:
            # Check if we need to extract content first
            article_content = article_data.get('content') or ''
            article_url = article_data.get('url') or ''
            source_type = article_data.get('source_type', 'rss')
            
            content_too_short = (len(article_content.strip()) < 10 and source_type == 'rss') or len(article_content.strip()) < 10
            print(f"  🔍 Debug combined: content_too_short={content_too_short}, content_len={len(article_content.strip())}")
            
            if content_too_short and article_url and article_url.startswith(('http://', 'https://')):
                # Skip URLs that are known to not have extractable content
                skip_domains = ['t.me', 'telegram.me', 'twitter.com', 'x.com', 'instagram.com']
                if not any(domain in article_url.lower() for domain in skip_domains):
                    try:
                        print(f"  🔍 Content empty/short ({len(article_content)} chars), trying content extraction: {article_url}")
                        
                        # Use full content extraction pipeline with all parsing schemas
                        from ..extraction import ContentExtractor
                        
                        # Try AI-enhanced extraction with metadata first
                        extracted_content = None
                        async with ContentExtractor() as content_extractor:
                            try:
                                extraction_result = await content_extractor.extract_article_content_with_metadata(article_url, retry_count=4)
                                extracted_content = extraction_result.get('content')
                            except Exception as e:
                                print(f"  ⚠️ AI-enhanced extraction failed after retries, trying standard extraction: {e}")
                                # Fallback to standard content extraction
                                try:
                                    extracted_content = await content_extractor.extract_article_content(article_url, retry_count=3)
                                except Exception as e2:
                                    print(f"  ❌ Standard extraction also failed after retries: {e2}")
                                    extracted_content = None
                        
                        # Check if extracted content is meaningful
                        if extracted_content and len(extracted_content.strip()) > len(article_content):
                            print(f"  ✅ Extracted {len(extracted_content)} chars from external URL using parsing schemas")
                            
                            # Update article with extracted content
                            article_data['content'] = extracted_content
                            update_fields = {'content': extracted_content}
                            await self._save_article_fields(article_id, update_fields)
                            
                        else:
                            print(f"  ⚠️ Could not extract meaningful content from external URL")
                    except Exception as e:
                        print(f"  ❌ Failed to extract content from external URL: {e}")
            
            start_time = time.time()
            
            # Get combined analysis
            ai_result = await self.ai_client.analyze_article_complete(
                title=article_data.get('title') or '',
                content=article_data.get('content') or '',
                url=article_data.get('url') or ''
            )
            
            elapsed_time = time.time() - start_time
            print(f"  ✅ Combined analysis completed in {elapsed_time:.1f}s")
            stats['api_calls_made'] += 1
            
            # Save all results at once
            update_fields = {}
            if needs_summary and ai_result.get('summary'):
                update_fields['summary'] = ai_result['summary']
                update_fields['summary_processed'] = True

            # Update title if AI provided optimized version
            optimized_title_raw = ai_result.get('optimized_title')
            current_title = article_data.get('title', '')
            print(f"  🔍 Title check: AI returned optimized_title='{optimized_title_raw}'")
            if optimized_title_raw:
                optimized_title = str(optimized_title_raw).strip()
                print(f"  🔍 Cleaned optimized title: '{optimized_title}' (len={len(optimized_title)})")
                if optimized_title and len(optimized_title) <= 200:  # Reasonable title length limit
                    if optimized_title != current_title:
                        update_fields['title'] = optimized_title
                        print(f"  📝 Title optimized: {optimized_title[:60]}...")
                    else:
                        print(f"  ✅ Title unchanged: AI returned same title")
                else:
                    print(f"  ⚠️ Title optimization skipped: empty or too long")
            else:
                print(f"  ❌ AI did not return optimized_title")
                
            if needs_category:
                # Extract categories from AI response (new format: array or fallback to single)
                categories_result = ai_result.get('categories', ai_result.get('category', ['Other']))
                if isinstance(categories_result, str):
                    categories_result = [categories_result]  # Convert single string to array
                elif not isinstance(categories_result, list):
                    categories_result = ['Other']  # Fallback for invalid format
                
                # Extract original AI categories (before mapping)
                original_categories = ai_result.get('original_categories', categories_result)
                
                # Extract category confidences (new format: array matching categories)
                confidences_result = ai_result.get('category_confidences', ai_result.get('category_confidence', [1.0]))
                if isinstance(confidences_result, (int, float)):
                    confidences_result = [float(confidences_result)]  # Convert single number to array
                elif not isinstance(confidences_result, list):
                    confidences_result = [1.0]  # Fallback for invalid format
                
                # Ensure arrays have same length
                while len(confidences_result) < len(categories_result):
                    confidences_result.append(0.8)  # Default confidence for extra categories
                confidences_result = confidences_result[:len(categories_result)]  # Trim if too long
                
                # Handle multiple categories with confidences
                try:
                    from ..services.category_service import get_category_service
                    if db:
                        category_service = await get_category_service(db)
                        
                        # Build categories with confidence data
                        categories_with_confidence = []
                        for i, category_name in enumerate(categories_result):
                            confidence = confidences_result[i] if i < len(confidences_result) else 0.8
                            # Use original AI category from original_categories array
                            ai_category = original_categories[i] if i < len(original_categories) else category_name
                            categories_with_confidence.append({
                                'name': category_name,
                                'confidence': max(0.0, min(1.0, float(confidence))),  # Clamp to 0-1 range
                                'ai_category': ai_category  # Store ACTUAL original AI category
                            })
                        
                        assigned_categories = await category_service.assign_categories_with_confidences(
                            article_id=article_id,
                            categories_with_confidence=categories_with_confidence
                        )
                        update_fields['category_processed'] = True
                        
                        if assigned_categories:
                            categories_info = [f"{c['display_name']} ({c['confidence']:.2f})" for c in assigned_categories]
                            print(f"  🏷️ Multiple categories assigned: {', '.join(categories_info)}")
                    else:
                        async with AsyncSessionLocal() as category_db:
                            category_service = await get_category_service(category_db)
                            
                            # Build categories with confidence data
                            categories_with_confidence = []
                            for i, category_name in enumerate(categories_result):
                                confidence = confidences_result[i] if i < len(confidences_result) else 0.8
                                # Use original AI category from original_categories array
                                ai_category = original_categories[i] if i < len(original_categories) else category_name
                                categories_with_confidence.append({
                                    'name': category_name,
                                    'confidence': max(0.0, min(1.0, float(confidence))),  # Clamp to 0-1 range
                                    'ai_category': ai_category  # Store ACTUAL original AI category
                                })
                            
                            assigned_categories = await category_service.assign_categories_with_confidences(
                                article_id=article_id,
                                categories_with_confidence=categories_with_confidence
                            )
                            update_fields['category_processed'] = True
                            
                            if assigned_categories:
                                categories_info = [f"{c['display_name']} ({c['confidence']:.2f})" for c in assigned_categories]
                                print(f"  🏷️ Multiple categories assigned: {', '.join(categories_info)}")
                except Exception as e:
                    print(f"  ⚠️ Multiple categories assignment failed: {e}")
                    # DO NOT set category_processed = True here - let it retry
                
            if needs_ad_detection:
                update_fields['is_advertisement'] = ai_result.get('is_advertisement', False)
                update_fields['ad_confidence'] = ai_result.get('ad_confidence', 0.0)
                update_fields['ad_type'] = ai_result.get('ad_type', 'news_article')
                update_fields['ad_reasoning'] = ai_result.get('ad_reasoning', 'Combined analysis')
                update_fields['ad_processed'] = True
                
            # Mark article as fully processed after successful AI processing
            update_fields['processed'] = True
                
            # Save all fields in one database operation
            await self._save_article_fields(article_id, update_fields)
            
            print(f"  💾 All results saved to database")
            print(f"  📊 Summary: {ai_result.get('summary', 'None')[:100]}...")
            
            # Display categories with confidences (support both old and new format)
            categories_display = ai_result.get('categories', ai_result.get('category', ['Other']))
            if isinstance(categories_display, str):
                categories_display = [categories_display]
            elif not isinstance(categories_display, list) or categories_display is None:
                categories_display = ['Other']  # Fallback if categories are None
            
            confidences_display = ai_result.get('category_confidences', ai_result.get('category_confidence', [1.0]))
            if isinstance(confidences_display, (int, float)):
                confidences_display = [float(confidences_display)]
            elif not isinstance(confidences_display, list) or confidences_display is None:
                confidences_display = [1.0] * len(categories_display)  # Default confidence for all categories
            
            # Format categories with confidences
            if len(confidences_display) >= len(categories_display):
                categories_info = [f"{cat} ({conf:.2f})" for cat, conf in zip(categories_display, confidences_display)]
                print(f"  🏷️ Categories: {', '.join(categories_info)}")
            else:
                print(f"  🏷️ Categories: {', '.join(categories_display)}")
            
            print(f"  🚨 Advertisement: {ai_result.get('is_advertisement', False)} (confidence: {ai_result.get('ad_confidence', 0.0):.2f})")
            
            # Extract media files from article content
            print(f"  🖼️ Extracting media files from content...")
            from .media_extractor import get_media_extractor
            
            try:
                # Check if media files already exist in article_data (e.g., from Telegram sources)
                existing_media = article_data.get('media_files', [])
                extracted_media = []
                
                if existing_media and isinstance(existing_media, list) and len(existing_media) > 0:
                    print(f"  📎 Using existing media files from article data: {len(existing_media)} files")
                    extracted_media = existing_media
                else:
                    # Extract media files from HTML content
                    print(f"  🔍 Extracting media files from HTML content...")
                    media_extractor = get_media_extractor()
                    extracted_media = media_extractor.extract_media_files(
                        article_data.get('content', ''), 
                        base_url=article_data.get('url')
                    )
                
                if extracted_media:
                    # Add extracted media to article data and update fields
                    article_data['media_files'] = extracted_media
                    update_fields['media_files'] = extracted_media
                    
                    # Get media extractor for summary (if not already created)
                    if 'media_extractor' not in locals():
                        media_extractor = get_media_extractor()
                        
                    summary = media_extractor.get_media_summary(extracted_media)
                    print(f"  📎 Found {summary['total']} media files: {summary['image']} images, {summary['video']} videos, {summary['document']} documents")
                    
                    # Save media files to database
                    await self._save_article_fields(article_id, {'media_files': extracted_media})
                else:
                    print(f"  📭 No media files found in content")
                    
            except Exception as media_error:
                print(f"  ❌ Media extraction failed: {media_error}")
                # Don't raise - media processing is optional
            
            # Note: processed flag already set in update_fields and saved above
            
            return {**article_data, **update_fields, 'success': True, 'content_length': len(article_data.get('content', ''))}
            
        except Exception as e:
            # Check if this is just a duplicate category error (normal during reprocessing)
            if "duplicate key value violates unique constraint" in str(e) and "article_categories" in str(e):
                print(f"  ⚠️ Combined analysis completed with duplicate category warning (normal during reprocessing)")
                
                # Extract media even with category duplication error
                print(f"  🖼️ Extracting media files (after category error)...")
                from .media_extractor import get_media_extractor
                
                try:
                    # Extract media files from content
                    media_extractor = get_media_extractor()
                    extracted_media = media_extractor.extract_media_files(
                        article_data.get('content', ''), 
                        base_url=article_data.get('url')
                    )
                    
                    if extracted_media:
                        article_data['media_files'] = extracted_media
                        summary = media_extractor.get_media_summary(extracted_media)
                        print(f"  📎 Found {summary['total']} media files")
                        
                        # Save to database
                        await self._save_article_fields(article_id, {'media_files': extracted_media})
                    
                except Exception as media_error:
                    print(f"  ❌ Media extraction failed: {media_error}")
                
                # Return success even with duplicate category error
                safe_update_fields = locals().get('update_fields', {})
                safe_update_fields['processed'] = True  # Mark as processed even with duplicate category warning
                return {**article_data, **safe_update_fields, 'success': True, 'content_length': len(article_data.get('content', ''))}
            else:
                print(f"  ❌ Combined analysis failed: {e}")
                # Fall back to incremental processing
                return await self.process_article_incremental(article_data, stats, False)

    async def process_article_incremental(
        self, 
        article_data: Dict[str, Any], 
        stats: Dict[str, Any], 
        force_processing: bool = False
    ) -> Dict[str, Any]:
        """Process article with AI, saving after each API call."""
        source_type = article_data.get('source_type', 'rss')
        source_name = article_data.get('source_name', 'Unknown')
        article_id = article_data['id']
        
        print(f"  📡 Source: {source_name} (type: {source_type})")
        print(f"  🔧 Incremental processing mode")
        
        # Check what processing is needed
        needs_summary = force_processing or (not article_data.get('summary_processed', False) and not article_data.get('summary'))
        needs_category = force_processing or not article_data.get('category_processed', False)
        needs_ad_detection = force_processing or not article_data.get('ad_processed', False)
        
        # Smart Filtering check
        if needs_summary or needs_category or needs_ad_detection:
            from ..services.smart_filter import get_smart_filter
            smart_filter = get_smart_filter()
            
            article_content = article_data.get('content') or ''
            article_url = article_data.get('url') or ''
            
            if not force_processing:
                should_process, filter_reason = smart_filter.should_process_with_ai(
                    title=article_data.get('title') or '',
                    content=article_content,
                    url=article_url,
                    source_type=source_type
                )
            else:
                should_process = True
                filter_reason = "Force processing enabled"
            
            if not should_process:
                print(f"  🚫 Smart Filter: Skipping AI processing - {filter_reason}")
                # Mark as processed with fallback values
                if needs_summary:
                    await self._save_article_fields(article_id, {
                        'summary': article_data.get('title', 'No summary available'),
                        'summary_processed': True
                    })
                if needs_category:
                    await self._save_article_fields(article_id, {'category_processed': True})
                if needs_ad_detection:
                    await self._save_article_fields(article_id, {
                        'is_advertisement': False,
                        'ad_confidence': 0.0,
                        'ad_type': 'news_article',
                        'ad_reasoning': f'Smart Filter: {filter_reason}',
                        'ad_processed': True,
                        'processed': True  # Mark as processed when skipped by Smart Filter
                    })
                
                # Extract media files even when Smart Filter skips AI processing
                print(f"  🖼️ Extracting media files (Smart Filter skip)...")
                from .media_extractor import get_media_extractor
                
                try:
                    # Check if media files already exist in article_data (e.g., from Telegram sources)
                    existing_media = article_data.get('media_files', [])
                    extracted_media = []
                    
                    if existing_media and isinstance(existing_media, list) and len(existing_media) > 0:
                        print(f"  📎 Using existing media files from article data: {len(existing_media)} files")
                        extracted_media = existing_media
                    else:
                        # Extract media files from HTML content
                        print(f"  🔍 Extracting media files from HTML content...")
                        media_extractor = get_media_extractor()
                        extracted_media = media_extractor.extract_media_files(
                            article_data.get('content', ''), 
                            base_url=article_data.get('url')
                        )
                    
                    if extracted_media:
                        # Add extracted media to article data and save to database
                        article_data['media_files'] = extracted_media
                        await self._save_article_fields(article_id, {'media_files': extracted_media})
                        
                        # Get media extractor for summary (if not already created)
                        if 'media_extractor' not in locals():
                            media_extractor = get_media_extractor()
                            
                        summary = media_extractor.get_media_summary(extracted_media)
                        print(f"  📎 Found {summary['total']} media files (Smart Filter skip)")
                    else:
                        print(f"  📭 No media files found in content (Smart Filter skip)")
                        
                except Exception as media_error:
                    print(f"  ❌ Media extraction failed (Smart Filter skip): {media_error}")
                    # Don't raise - media processing is optional
                
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
                start_time = time.time()
                # Create a temporary Article-like object for compatibility
                class TempArticle:
                    def __init__(self, data):
                        self.url = data['url']
                        self.title = data['title']
                        self.content = data['content']
                
                temp_article = TempArticle(article_data)
                summary = await self.get_summary_by_source_type(temp_article, source_type, stats)
                elapsed_time = time.time() - start_time
                print(f"  ✅ Summary generated in {elapsed_time:.1f}s: {summary[:100] if summary else 'None'}...")
                
                # Save summary immediately
                await self._save_article_fields(article_id, {
                    'summary': summary,
                    'summary_processed': True
                })
                stats['api_calls_made'] += 1
                print(f"  💾 Summary saved to database")
                
            except Exception as e:
                print(f"  ❌ Summarization failed: {e}")
                # Mark as processed even on failure to avoid retries
                await self._save_article_fields(article_id, {'summary_processed': True})
        
        # Process category if needed  
        if needs_category:
            print(f"  🏷️ Starting categorization...")
            try:
                start_time = time.time()
                categories_result = await self._categorize_by_source_type_new(TempArticle(article_data), source_type, stats)
                elapsed_time = time.time() - start_time
                
                if categories_result:
                    from ..services.category_service import get_category_service
                    if db:
                        category_service = await get_category_service(db)
                        await category_service.assign_categories_with_confidences(
                            article_id, categories_result
                        )
                        print(f"  ✅ Categorization completed in {elapsed_time:.1f}s")
                        await self._save_article_fields(article_id, {'category_processed': True})
                    else:
                        async with AsyncSessionLocal() as category_db:
                            category_service = await get_category_service(category_db)
                            await category_service.assign_categories_with_confidences(
                                article_id, categories_result
                            )
                            print(f"  ✅ Categorization completed in {elapsed_time:.1f}s")
                            await self._save_article_fields(article_id, {'category_processed': True})
                        
            except Exception as e:
                print(f"  ❌ Categorization failed: {e}")
                await self._save_article_fields(article_id, {'category_processed': True})
        
        # Ad detection moved to combined analysis - using fallback
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
        
        # Extract media files from article content
        print(f"  🖼️ Extracting media files...")
        print(f"  🔍 DEBUG: article_data keys = {list(article_data.keys())}")
        print(f"  🔍 DEBUG: media_files in article_data = {article_data.get('media_files', 'NOT_FOUND')}")
        from .media_extractor import get_media_extractor
        
        try:
            # Check if media files already exist in article_data (e.g., from Telegram sources)
            existing_media = article_data.get('media_files', [])
            extracted_media = []
            
            if existing_media and isinstance(existing_media, list) and len(existing_media) > 0:
                print(f"  📎 Using existing media files from article data: {len(existing_media)} files")
                extracted_media = existing_media
            else:
                # Extract media files from HTML content
                print(f"  🔍 Extracting media files from HTML content...")
                media_extractor = get_media_extractor()
                extracted_media = media_extractor.extract_media_files(
                    article_data.get('content', ''), 
                    base_url=article_data.get('url')
                )
            
            if extracted_media:
                # Add extracted media to article data and save to database
                article_data['media_files'] = extracted_media
                await self._save_article_fields(article_id, {'media_files': extracted_media})
                
                # Get media extractor for summary (if not already created)
                if 'media_extractor' not in locals():
                    media_extractor = get_media_extractor()
                    
                summary = media_extractor.get_media_summary(extracted_media)
                print(f"  📎 Found {summary['total']} media files")
            else:
                print(f"  📭 No media files found in content")
                
        except Exception as media_error:
            print(f"  ❌ Media extraction failed: {media_error}")
            # Don't raise - media processing is optional
        
        # Mark article as fully processed after incremental processing
        await self._save_article_fields(article_id, {'processed': True})
        print(f"  ✅ Article marked as fully processed")
        
        return {'success': True, 'content_length': len(article_data.get('content', ''))}

    async def get_summary_by_source_type(self, article, source_type: str, stats: Dict[str, Any]) -> str:
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
                
            else:
                # Other sources: use content as summary
                return article.content or article.title
                
        except Exception as e:
            print(f"  ❌ Summary generation failed for {source_type}: {e}")
            return article.content or article.title or "Summary unavailable"

    def _update_article_publication_date(self, article, pub_date: str, source_type: str):
        """Update article publication date if provided."""
        if not pub_date:
            return
            
        try:
            import dateutil.parser as date_parser
            parsed_date = date_parser.parse(pub_date, fuzzy=True)
            if parsed_date and (not article.published_at or article.published_at.year < 2020):
                # Remove timezone info to match DateTime field in database
                article.published_at = parsed_date.replace(tzinfo=None) if parsed_date.tzinfo else parsed_date
                print(f"  📅 Updated publication date from {source_type}: {parsed_date.strftime('%Y-%m-%d %H:%M')}")
        except Exception as e:
            print(f"  ⚠️ Failed to parse publication date '{pub_date}': {e}")

    async def _categorize_by_source_type_new(self, article, source_type: str, stats: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Categorize article and return categories with confidences."""
        # Implementation would go here - simplified for now
        return []

    async def _save_article_fields(self, article_id: int, fields_dict: Dict[str, Any], db: AsyncSession = None):
        """Save specific fields to article in database."""
        try:
            if db:
                # Use provided session
                from ..models import Article
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
            else:
                # Create new session  
                async with AsyncSessionLocal() as new_db:
                    from ..models import Article
                    from sqlalchemy import select
                    
                    result = await new_db.execute(select(Article).where(Article.id == article_id))
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
                    
                    await new_db.commit()
                    
        except Exception as e:
            print(f"  ❌ Failed to save article fields for {article_id}: {e}")
            raise


