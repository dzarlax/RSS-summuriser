"""Media Cache Manager for articles."""

from typing import Dict, Any, List, Optional

from ..database import AsyncSessionLocal
from ..models import MediaFile


class MediaCacheManager:
    """Manager for caching article media files."""
    
    def __init__(self):
        """Initialize media cache manager."""
        pass
    
    async def try_cache_article_media(self, article_id: int, article_data: Dict[str, Any]) -> None:
        """Try to cache article media files safely."""
        try:
            media_files = article_data.get('media_files', [])
            
            # Convert image_url to media_files if media_files is empty but image_url exists
            if not media_files and article_data.get('image_url'):
                image_url = article_data['image_url']
                media_files = [{
                    'url': image_url,
                    'type': 'image',
                    'source': 'rss_image_url'
                }]
                print(f"  🔄 Converting image_url to media_files: {image_url}")
            
            if not media_files:
                return
                
            print(f"  🖼️ Attempting to cache {len(media_files)} media files...")
            
            # Import media cache service dynamically to avoid circular imports
            from ..services.media_cache_service import MediaCacheService
            
            media_cache_service = MediaCacheService()
            
            for i, media in enumerate(media_files, 1):
                media_url = media.get('url')
                media_type = media.get('type', 'image')
                
                if not media_url:
                    continue
                
                print(f"    📥 [{i}/{len(media_files)}] Caching {media_type}: {media_url[:80]}...")
                
                try:
                    # Check if already cached
                    async with AsyncSessionLocal() as db:
                        from sqlalchemy import select
                        existing = await db.execute(
                            select(MediaFile).where(
                                MediaFile.article_id == article_id,
                                MediaFile.original_url == media_url
                            )
                        )
                        existing_media = existing.scalar_one_or_none()
                        
                        if existing_media and existing_media.is_cached:
                            print(f"      ⏭️ Already cached, skipping")
                            continue
                    
                    # Cache the media file
                    cache_result = await media_cache_service.cache_media_file(
                        original_url=media_url,
                        media_type=media_type,
                        max_size_mb=50
                    )
                    
                    if cache_result:
                        # Save to database
                        async with AsyncSessionLocal() as db:
                            if not existing_media:
                                media_file = MediaFile(
                                    article_id=article_id,
                                    original_url=media_url,
                                    media_type=cache_result['media_type'],
                                    filename=cache_result['filename'],
                                    mime_type=cache_result['mime_type'],
                                    file_size=cache_result['file_size'],
                                    width=cache_result.get('width'),
                                    height=cache_result.get('height'),
                                    duration=cache_result.get('duration'),
                                    cached_original_path=cache_result['original_path'],
                                    cached_thumbnail_path=cache_result.get('thumbnail_path'),
                                    cached_optimized_path=cache_result.get('optimized_path'),
                                    cache_status='cached'
                                )
                                db.add(media_file)
                            else:
                                # Update existing
                                existing_media.filename = cache_result['filename']
                                existing_media.mime_type = cache_result['mime_type']
                                existing_media.file_size = cache_result['file_size']
                                existing_media.width = cache_result.get('width')
                                existing_media.height = cache_result.get('height')
                                existing_media.duration = cache_result.get('duration')
                                existing_media.cached_original_path = cache_result['original_path']
                                existing_media.cached_thumbnail_path = cache_result.get('thumbnail_path')
                                existing_media.cached_optimized_path = cache_result.get('optimized_path')
                                existing_media.cache_status = 'cached'
                            
                            await db.commit()
                        
                        print(f"      ✅ Cached successfully: {cache_result['filename']}")
                    else:
                        print(f"      ❌ Caching failed")
                        
                except Exception as e:
                    print(f"      ❌ Caching error: {e}")
                    continue
            
            # Update article's media_files if we converted from image_url
            if (article_data.get('media_files', []) != media_files and 
                len(media_files) == 1 and 
                media_files[0].get('source') == 'rss_image_url'):
                try:
                    async with AsyncSessionLocal() as db:
                        from sqlalchemy import update
                        from ..models import Article
                        
                        await db.execute(
                            update(Article)
                            .where(Article.id == article_id)
                            .values(media_files=media_files)
                        )
                        await db.commit()
                        print(f"  💾 Updated article {article_id} with converted media_files")
                except Exception as e:
                    print(f"  ⚠️ Failed to update article media_files: {e}")
                    
        except Exception as e:
            print(f"  ❌ Media caching failed: {e}")
            # Don't raise - media caching is optional

    async def cache_article_media(self, article_id: int, media_files: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Cache media files for a specific article."""
        stats = {
            'cached': 0,
            'failed': 0,
            'skipped': 0,
            'errors': []
        }
        
        if not media_files:
            print(f"  📷 No media files found, skipping media cache")
            return stats
        
        print(f"  📸 Caching {len(media_files)} media files for article {article_id}...")
        
        try:
            from ..services.media_cache_service import MediaCacheService
            media_cache_service = MediaCacheService()
            
            for i, media in enumerate(media_files, 1):
                media_url = media.get('url')
                media_type = media.get('type', 'image')
                
                if not media_url:
                    stats['skipped'] += 1
                    continue
                
                print(f"    📥 [{i}/{len(media_files)}] Processing {media_type}: {media_url[:80]}...")
                
                try:
                    # Check if already cached
                    async with AsyncSessionLocal() as db:
                        from sqlalchemy import select
                        existing = await db.execute(
                            select(MediaFile).where(
                                MediaFile.article_id == article_id,
                                MediaFile.original_url == media_url
                            )
                        )
                        existing_media = existing.scalar_one_or_none()
                        
                        if existing_media and existing_media.cache_status == 'cached':
                            print(f"      ⏭️ Already cached, skipping")
                            stats['skipped'] += 1
                            continue
                    
                    # Cache the media file
                    cache_result = await media_cache_service.cache_media_file(
                        original_url=media_url,
                        media_type=media_type,
                        max_size_mb=50
                    )
                    
                    if cache_result:
                        # Save to database
                        async with AsyncSessionLocal() as db:
                            if not existing_media:
                                media_file = MediaFile(
                                    article_id=article_id,
                                    original_url=media_url,
                                    media_type=cache_result['media_type'],
                                    filename=cache_result['filename'],
                                    mime_type=cache_result['mime_type'],
                                    file_size=cache_result['file_size'],
                                    width=cache_result.get('width'),
                                    height=cache_result.get('height'),
                                    duration=cache_result.get('duration'),
                                    cached_original_path=cache_result['original_path'],
                                    cached_thumbnail_path=cache_result.get('thumbnail_path'),
                                    cached_optimized_path=cache_result.get('optimized_path'),
                                    cache_status='cached'
                                )
                                db.add(media_file)
                            else:
                                # Update existing
                                existing_media.filename = cache_result['filename']
                                existing_media.mime_type = cache_result['mime_type']
                                existing_media.file_size = cache_result['file_size']
                                existing_media.width = cache_result.get('width')
                                existing_media.height = cache_result.get('height')
                                existing_media.duration = cache_result.get('duration')
                                existing_media.cached_original_path = cache_result['original_path']
                                existing_media.cached_thumbnail_path = cache_result.get('thumbnail_path')
                                existing_media.cached_optimized_path = cache_result.get('optimized_path')
                                existing_media.cache_status = 'cached'
                            
                            await db.commit()
                        
                        print(f"      ✅ Cached successfully: {cache_result['filename']}")
                        stats['cached'] += 1
                    else:
                        print(f"      ❌ Caching failed")
                        stats['failed'] += 1
                        
                except Exception as e:
                    error_msg = f"Media caching error for {media_url}: {e}"
                    print(f"      ❌ {error_msg}")
                    stats['errors'].append(error_msg)
                    stats['failed'] += 1
                    continue
            
            print(f"  📊 Media caching completed: {stats['cached']} cached, {stats['failed']} failed, {stats['skipped']} skipped")
            return stats
                    
        except Exception as e:
            error_msg = f"Media caching failed for article {article_id}: {e}"
            print(f"  ❌ {error_msg}")
            stats['errors'].append(error_msg)
            return stats

    async def cache_media_for_articles(self, article_ids: List[int] = None, limit: int = 50) -> Dict[str, Any]:
        """Cache media files for multiple articles."""
        from sqlalchemy import select, text
        from ..models import Article
        
        stats = {
            'articles_processed': 0,
            'media_cached': 0,
            'media_failed': 0,
            'media_skipped': 0,
            'errors': []
        }
        
        print(f"🎬 Starting media caching for articles...")
        
        try:
            async with AsyncSessionLocal() as db:
                # Query for articles with media that need caching
                if article_ids:
                    # Use specific article IDs
                    query = select(Article).where(
                        Article.id.in_(article_ids),
                        Article.media_files.isnot(None)
                    ).limit(limit)
                    result = await db.execute(query)
                    all_articles = result.scalars().all()
                    
                    # Filter out articles with empty media_files in Python
                    articles = []
                    for article in all_articles:
                        try:
                            import json
                            media_files = json.loads(article.media_files) if isinstance(article.media_files, str) else article.media_files
                            if media_files and len(media_files) > 0:
                                articles.append(article)
                        except (json.JSONDecodeError, TypeError):
                            continue
                else:
                    # Find articles with media_files but no cached media entries
                    query = text("""
                        SELECT a.* FROM articles a 
                        WHERE a.media_files IS NOT NULL 
                        AND a.media_files::text != '[]'
                        AND NOT EXISTS (
                            SELECT 1 FROM media_files_cache mf 
                            WHERE mf.article_id = a.id 
                            AND mf.cache_status = 'cached'
                        )
                        ORDER BY a.published_at DESC
                        LIMIT :limit
                    """)
                    result = await db.execute(query, {'limit': limit})
                    articles = [Article(**dict(row._mapping)) for row in result]
                
                print(f"  📋 Found {len(articles)} articles with media to process")
                
                for i, article in enumerate(articles, 1):
                    try:
                        print(f"  📰 [{i}/{len(articles)}] Processing article {article.id}: {article.title[:60]}...")
                        
                        # Parse media files
                        import json
                        media_files = []
                        if article.media_files:
                            try:
                                media_files = json.loads(article.media_files) if isinstance(article.media_files, str) else article.media_files
                            except (json.JSONDecodeError, TypeError):
                                print(f"    ⚠️ Invalid media_files format, skipping")
                                continue
                        
                        if not media_files:
                            print(f"    📷 No media files found, skipping")
                            continue
                        
                        # Cache media for this article
                        cache_stats = await self.cache_article_media(article.id, media_files)
                        
                        stats['articles_processed'] += 1
                        stats['media_cached'] += cache_stats['cached']
                        stats['media_failed'] += cache_stats['failed']
                        stats['media_skipped'] += cache_stats['skipped']
                        stats['errors'].extend(cache_stats['errors'])
                        
                    except Exception as e:
                        error_msg = f"Failed to process article {article.id}: {e}"
                        print(f"    ❌ {error_msg}")
                        stats['errors'].append(error_msg)
                        continue
                
        except Exception as e:
            error_msg = f"Media caching query failed: {e}"
            print(f"❌ {error_msg}")
            stats['errors'].append(error_msg)
        
        print(f"🎬 Media caching completed:")
        print(f"  📊 Articles processed: {stats['articles_processed']}")
        print(f"  ✅ Media cached: {stats['media_cached']}")
        print(f"  ❌ Media failed: {stats['media_failed']}")
        print(f"  ⏭️ Media skipped: {stats['media_skipped']}")
        
        return stats

