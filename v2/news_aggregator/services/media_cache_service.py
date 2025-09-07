"""Media caching service for downloading and optimizing media files."""

import asyncio
import hashlib
import os
import aiohttp
import aiofiles
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
import logging
import time
from datetime import datetime, timedelta
from urllib.parse import urlparse, unquote

# Image processing (will be optional)
try:
    from PIL import Image, ImageOps
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False
    print("⚠️ PIL/Pillow not available, image optimization disabled")

from ..config import get_settings

logger = logging.getLogger(__name__)


class MediaCacheService:
    """Service for caching and optimizing media files."""
    
    # Map singular media types to plural folder names
    MEDIA_TYPE_MAPPING = {
        'image': 'images',
        'video': 'videos', 
        'document': 'documents',
        # Also support plural forms (for consistency)
        'images': 'images',
        'videos': 'videos',
        'documents': 'documents'
    }
    
    def __init__(self, cache_dir: Optional[str] = None):
        settings = get_settings()
        self.cache_dir = Path(cache_dir or settings.media_cache_dir)
        self.thumbnail_size = settings.media_thumbnail_size
        self.optimized_max_width = settings.media_optimized_max_width
        self.max_file_size_mb = settings.max_media_file_size_mb
        self.retention_days = settings.media_cache_retention_days
        
        self.ensure_cache_structure()
    
    def _normalize_media_type(self, media_type: str) -> str:
        """Convert media type to normalized folder name."""
        normalized = self.MEDIA_TYPE_MAPPING.get(media_type.lower())
        if not normalized:
            # Default fallback for unknown types
            if media_type.lower() in ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg']:
                return 'images'
            elif media_type.lower() in ['mp4', 'avi', 'mov', 'webm', 'mkv']:
                return 'videos'
            else:
                return 'documents'
        return normalized
    
    def ensure_cache_structure(self):
        """Create cache directory structure."""
        try:
            for media_type in ['images', 'videos', 'documents']:
                for subdir in ['original', 'thumbnails', 'optimized']:
                    path = self.cache_dir / media_type / subdir
                    path.mkdir(parents=True, exist_ok=True)
            logger.info(f"📁 Media cache structure created at {self.cache_dir}")
        except Exception as e:
            logger.error(f"❌ Failed to create cache structure: {e}")
            raise
    
    async def cache_media_file(self, original_url: str, media_type: str, max_size_mb: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """
        Cache media file with optimized versions.
        
        Args:
            original_url: URL of the original media file
            media_type: Type of media (image, video, document)
            max_size_mb: Optional max file size limit
            
        Returns:
            Dictionary with cached file information or None if failed
        """
        try:
            max_size = (max_size_mb or self.max_file_size_mb) * 1024 * 1024
            
            # Normalize media type to folder name
            normalized_media_type = self._normalize_media_type(media_type)
            logger.info(f"🔧 Media type '{media_type}' normalized to '{normalized_media_type}'")
            
            # Generate unique filename based on URL
            file_hash = self._generate_file_hash(original_url)
            logger.info(f"🔄 Caching media: {original_url} -> {file_hash}")
            
            # 1. Download original file
            download_result = await self._download_file(original_url, normalized_media_type, file_hash, max_size)
            if not download_result:
                return None
            
            original_path, file_info = download_result
            
            # 2. Create optimized versions
            thumbnail_path = await self._create_thumbnail(original_path, normalized_media_type, file_hash)
            optimized_path = await self._create_optimized_version(original_path, normalized_media_type, file_hash)
            
            # 3. Extract additional metadata
            metadata = await self._extract_metadata(original_path, normalized_media_type)
            
            result = {
                'original_path': str(original_path.relative_to(self.cache_dir)),
                'thumbnail_path': str(thumbnail_path.relative_to(self.cache_dir)) if thumbnail_path else None,
                'optimized_path': str(optimized_path.relative_to(self.cache_dir)) if optimized_path else None,
                'file_size': file_info['size'],
                'mime_type': file_info['mime_type'],
                'filename': file_info['filename'],
                'media_type': normalized_media_type,  # Add missing media_type field
                'width': metadata.get('width'),
                'height': metadata.get('height'),
                'duration': metadata.get('duration')
            }
            
            logger.info(f"✅ Media cached successfully: {original_url}")
            return result
            
        except Exception as e:
            logger.error(f"❌ Media caching failed for {original_url}: {e}")
            return None
    
    async def _download_file(self, url: str, media_type: str, file_hash: str, max_size: int) -> Optional[Tuple[Path, Dict[str, Any]]]:
        """Download file and save to cache."""
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
                # First, get file info with HEAD request
                async with session.head(url) as response:
                    if response.status != 200:
                        logger.warning(f"⚠️ HEAD request failed for {url}: {response.status}")
                        # Try direct download anyway
                    
                    content_type = response.headers.get('Content-Type', '')
                    content_length = response.headers.get('Content-Length')
                    
                    # Check file size limit
                    if content_length and int(content_length) > max_size:
                        logger.warning(f"⚠️ File too large: {content_length} bytes > {max_size} bytes")
                        return None
                
                # Get file extension from URL or content type
                extension = self._get_extension_from_url_or_mime(url, content_type, media_type)
                
                # Create file path
                filename = f"{file_hash}{extension}"
                file_path = self.cache_dir / media_type / 'original' / filename
                
                # Download file
                async with session.get(url) as response:
                    if response.status == 200:
                        downloaded_size = 0
                        async with aiofiles.open(file_path, 'wb') as f:
                            async for chunk in response.content.iter_chunked(8192):
                                downloaded_size += len(chunk)
                                if downloaded_size > max_size:
                                    logger.warning(f"⚠️ File too large during download: {downloaded_size} bytes")
                                    await f.close()
                                    file_path.unlink(missing_ok=True)  # Delete partial file
                                    return None
                                await f.write(chunk)
                        
                        # Get actual file info
                        file_info = {
                            'size': file_path.stat().st_size,
                            'mime_type': self._get_mime_type(file_path),
                            'filename': filename  # Use short hash-based filename to avoid DB length limits
                        }
                        
                        logger.info(f"📥 Downloaded {file_info['size']} bytes to {file_path}")
                        return file_path, file_info
                    else:
                        logger.error(f"❌ Download failed: HTTP {response.status}")
                        return None
            
        except Exception as e:
            logger.error(f"❌ Download error for {url}: {e}")
            return None
    
    async def _create_thumbnail(self, original_path: Path, media_type: str, file_hash: str) -> Optional[Path]:
        """Create thumbnail for media file."""
        try:
            thumbnail_path = self.cache_dir / media_type / 'thumbnails' / f"{file_hash}.jpg"
            
            if media_type == 'images' and PILLOW_AVAILABLE:
                return await self._create_image_thumbnail(original_path, thumbnail_path)
            elif media_type == 'videos':
                return await self._create_video_thumbnail(original_path, thumbnail_path)
            elif media_type == 'documents':
                return await self._create_document_thumbnail(original_path, thumbnail_path)
            
            return None
            
        except Exception as e:
            logger.error(f"❌ Thumbnail creation failed: {e}")
            return None
    
    async def _create_image_thumbnail(self, original_path: Path, thumbnail_path: Path) -> Optional[Path]:
        """Create image thumbnail using PIL."""
        if not PILLOW_AVAILABLE:
            return None
        
        try:
            def _resize_image():
                with Image.open(original_path) as img:
                    # Apply EXIF orientation
                    img = ImageOps.exif_transpose(img)
                    
                    # Create square thumbnail
                    size = (self.thumbnail_size, self.thumbnail_size)
                    img.thumbnail(size, Image.Resampling.LANCZOS)
                    
                    # Convert to RGB if needed
                    if img.mode in ('RGBA', 'LA', 'P'):
                        background = Image.new('RGB', img.size, (255, 255, 255))
                        if img.mode == 'P':
                            img = img.convert('RGBA')
                        if img.mode == 'RGBA':
                            background.paste(img, mask=img.split()[-1])
                        else:
                            background.paste(img)
                        img = background
                    
                    # Save optimized thumbnail
                    img.save(thumbnail_path, 'JPEG', quality=85, optimize=True)
            
            # Run in thread pool to avoid blocking
            await asyncio.get_event_loop().run_in_executor(None, _resize_image)
            
            if thumbnail_path.exists():
                logger.info(f"🖼️ Created image thumbnail: {thumbnail_path}")
                return thumbnail_path
            
            return None
            
        except Exception as e:
            logger.error(f"❌ Image thumbnail failed: {e}")
            return None
    
    async def _create_video_thumbnail(self, original_path: Path, thumbnail_path: Path) -> Optional[Path]:
        """Create video thumbnail using ffmpeg (if available)."""
        try:
            # Check if ffmpeg is available
            process = await asyncio.create_subprocess_exec(
                'ffmpeg', '-version',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await process.communicate()
            
            if process.returncode != 0:
                logger.warning("⚠️ ffmpeg not available, skipping video thumbnail")
                return None
            
            # Extract thumbnail frame
            cmd = [
                'ffmpeg', '-i', str(original_path),
                '-vf', f'thumbnail,scale={self.thumbnail_size}:{self.thumbnail_size}:force_original_aspect_ratio=increase,crop={self.thumbnail_size}:{self.thumbnail_size}',
                '-frames:v', '1', '-y', str(thumbnail_path)
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            await process.communicate()
            
            if process.returncode == 0 and thumbnail_path.exists():
                logger.info(f"🎬 Created video thumbnail: {thumbnail_path}")
                return thumbnail_path
            
            return None
            
        except Exception as e:
            logger.warning(f"⚠️ Video thumbnail failed (ffmpeg not available?): {e}")
            return None
    
    async def _create_document_thumbnail(self, original_path: Path, thumbnail_path: Path) -> Optional[Path]:
        """Create document thumbnail (placeholder for now)."""
        # For now, we'll skip document thumbnails
        # Could be implemented with LibreOffice, ImageMagick, or similar tools
        return None
    
    async def _create_optimized_version(self, original_path: Path, media_type: str, file_hash: str) -> Optional[Path]:
        """Create optimized version of media file."""
        try:
            if media_type == 'images' and PILLOW_AVAILABLE:
                return await self._create_optimized_image(original_path, file_hash)
            
            # For videos and documents, optimized version = original for now
            # Could be implemented with ffmpeg for videos
            return None
            
        except Exception as e:
            logger.error(f"❌ Optimization failed: {e}")
            return None
    
    async def _create_optimized_image(self, original_path: Path, file_hash: str) -> Optional[Path]:
        """Create optimized image with WebP format and size limits."""
        if not PILLOW_AVAILABLE:
            return None
        
        try:
            optimized_path = self.cache_dir / 'images' / 'optimized' / f"{file_hash}.webp"
            
            def _optimize_image():
                with Image.open(original_path) as img:
                    # Apply EXIF orientation
                    img = ImageOps.exif_transpose(img)
                    
                    # Resize if too large
                    if img.width > self.optimized_max_width:
                        ratio = self.optimized_max_width / img.width
                        new_height = int(img.height * ratio)
                        img = img.resize((self.optimized_max_width, new_height), Image.Resampling.LANCZOS)
                    
                    # Convert to RGB if needed for WebP
                    if img.mode in ('RGBA', 'LA', 'P'):
                        if img.mode == 'P':
                            img = img.convert('RGBA')
                        
                        # Keep transparency for WebP
                        if img.mode == 'RGBA':
                            img.save(optimized_path, 'WebP', quality=80, optimize=True)
                        else:
                            background = Image.new('RGB', img.size, (255, 255, 255))
                            background.paste(img)
                            background.save(optimized_path, 'WebP', quality=80, optimize=True)
                    else:
                        img.save(optimized_path, 'WebP', quality=80, optimize=True)
            
            await asyncio.get_event_loop().run_in_executor(None, _optimize_image)
            
            if optimized_path.exists():
                logger.info(f"🔧 Created optimized image: {optimized_path}")
                return optimized_path
            
            return None
            
        except Exception as e:
            logger.error(f"❌ Image optimization failed: {e}")
            return None
    
    async def _extract_metadata(self, file_path: Path, media_type: str) -> Dict[str, Any]:
        """Extract media metadata."""
        metadata = {}
        
        try:
            if media_type == 'images' and PILLOW_AVAILABLE:
                def _get_image_metadata():
                    with Image.open(file_path) as img:
                        return {'width': img.width, 'height': img.height}
                
                img_meta = await asyncio.get_event_loop().run_in_executor(None, _get_image_metadata)
                metadata.update(img_meta)
            
            elif media_type == 'videos':
                # Could use ffprobe to get video metadata
                pass
            
        except Exception as e:
            logger.warning(f"⚠️ Metadata extraction failed: {e}")
        
        return metadata
    
    def _generate_file_hash(self, url: str) -> str:
        """Generate unique hash for file based on URL."""
        return hashlib.md5(url.encode('utf-8')).hexdigest()
    
    def _get_extension_from_url_or_mime(self, url: str, content_type: str, media_type: str) -> str:
        """Get file extension from URL or MIME type."""
        # Try to get from URL first
        parsed_url = urlparse(url)
        path = unquote(parsed_url.path)
        
        if '.' in path:
            ext = '.' + path.split('.')[-1].lower()
            # Validate extension
            if self._is_valid_extension(ext, media_type):
                return ext
        
        # Fall back to MIME type
        mime_extensions = {
            'image/jpeg': '.jpg',
            'image/jpg': '.jpg',
            'image/png': '.png',
            'image/gif': '.gif',
            'image/webp': '.webp',
            'image/bmp': '.bmp',
            'video/mp4': '.mp4',
            'video/avi': '.avi',
            'video/mov': '.mov',
            'video/wmv': '.wmv',
            'application/pdf': '.pdf',
            'application/msword': '.doc',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
        }
        
        return mime_extensions.get(content_type.lower(), '.bin')
    
    def _is_valid_extension(self, ext: str, media_type: str) -> bool:
        """Check if extension is valid for media type."""
        valid_extensions = {
            'images': ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tiff', '.svg'],
            'videos': ['.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm', '.mkv'],
            'documents': ['.pdf', '.doc', '.docx', '.txt', '.rtf', '.xls', '.xlsx', '.ppt', '.pptx']
        }
        
        return ext.lower() in valid_extensions.get(media_type, [])
    
    def _get_mime_type(self, file_path: Path) -> str:
        """Get MIME type of file."""
        try:
            # Try to use python-magic if available
            import magic
            return magic.from_file(str(file_path), mime=True)
        except:
            # Fallback to extension-based detection
            ext = file_path.suffix.lower()
            mime_map = {
                '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
                '.png': 'image/png', '.gif': 'image/gif',
                '.webp': 'image/webp', '.bmp': 'image/bmp',
                '.mp4': 'video/mp4', '.avi': 'video/avi',
                '.pdf': 'application/pdf', '.txt': 'text/plain'
            }
            return mime_map.get(ext, 'application/octet-stream')
    
    def _get_filename_from_url(self, url: str) -> Optional[str]:
        """Extract filename from URL."""
        try:
            parsed_url = urlparse(url)
            path = unquote(parsed_url.path)
            if '/' in path:
                filename = path.split('/')[-1]
                if filename and '.' in filename:
                    return filename
        except:
            pass
        return None
    
    async def cleanup_old_cache(self) -> Dict[str, Any]:
        """Clean up old cached files based on retention policy."""
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=self.retention_days)
            cleaned_files = 0
            freed_bytes = 0
            
            for media_type in ['images', 'videos', 'documents']:
                for subdir in ['original', 'thumbnails', 'optimized']:
                    dir_path = self.cache_dir / media_type / subdir
                    if not dir_path.exists():
                        continue
                    
                    for file_path in dir_path.iterdir():
                        if file_path.is_file():
                            # Check file age
                            file_age = datetime.fromtimestamp(file_path.stat().st_mtime)
                            if file_age < cutoff_date:
                                file_size = file_path.stat().st_size
                                file_path.unlink()
                                cleaned_files += 1
                                freed_bytes += file_size
            
            freed_mb = round(freed_bytes / (1024 * 1024), 2)
            logger.info(f"🧹 Cleanup completed: {cleaned_files} files, {freed_mb} MB freed")
            
            return {
                'cleaned_files': cleaned_files,
                'freed_bytes': freed_bytes,
                'freed_mb': freed_mb
            }
            
        except Exception as e:
            logger.error(f"❌ Cache cleanup failed: {e}")
            return {'error': str(e)}
    
    async def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache usage statistics."""
        try:
            stats = {
                'total_files': 0,
                'total_size_bytes': 0,
                'by_type': {}
            }
            
            for media_type in ['images', 'videos', 'documents']:
                type_stats = {'files': 0, 'size_bytes': 0, 'by_variant': {}}
                
                for subdir in ['original', 'thumbnails', 'optimized']:
                    dir_path = self.cache_dir / media_type / subdir
                    variant_stats = {'files': 0, 'size_bytes': 0}
                    
                    if dir_path.exists():
                        for file_path in dir_path.iterdir():
                            if file_path.is_file():
                                file_size = file_path.stat().st_size
                                variant_stats['files'] += 1
                                variant_stats['size_bytes'] += file_size
                    
                    type_stats['by_variant'][subdir] = variant_stats
                    type_stats['files'] += variant_stats['files']
                    type_stats['size_bytes'] += variant_stats['size_bytes']
                
                stats['by_type'][media_type] = type_stats
                stats['total_files'] += type_stats['files']
                stats['total_size_bytes'] += type_stats['size_bytes']
            
            stats['total_size_mb'] = round(stats['total_size_bytes'] / (1024 * 1024), 2)
            stats['cache_dir'] = str(self.cache_dir)
            
            return stats
            
        except Exception as e:
            logger.error(f"❌ Cache stats failed: {e}")
            return {'error': str(e)}


# Global instance
_media_cache_service: Optional[MediaCacheService] = None


def get_media_cache_service() -> MediaCacheService:
    """Get media cache service instance."""
    global _media_cache_service
    
    if _media_cache_service is None:
        _media_cache_service = MediaCacheService()
    
    return _media_cache_service
