"""Media extraction utilities for articles."""

import re
from typing import List, Dict, Any, Optional
from urllib.parse import urljoin, urlparse
import logging

logger = logging.getLogger(__name__)


class MediaExtractor:
    """Extract media files from article content."""
    
    # Common image extensions
    IMAGE_EXTENSIONS = {
        '.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.bmp', '.tiff', '.ico'
    }
    
    # Common video extensions
    VIDEO_EXTENSIONS = {
        '.mp4', '.avi', '.mov', '.webm', '.mkv', '.flv', '.wmv', '.m4v'
    }
    
    # Common document extensions
    DOCUMENT_EXTENSIONS = {
        '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.txt', '.rtf'
    }
    
    def __init__(self):
        """Initialize media extractor."""
        pass
    
    def extract_media_files(self, content: str, base_url: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Extract media files from article content.
        
        Args:
            content: Article HTML content
            base_url: Base URL for resolving relative URLs
            
        Returns:
            List of media file dictionaries with url, type, and additional metadata
        """
        if not content:
            return []
        
        media_files = []
        
        # Extract images from img tags
        img_media = self._extract_images_from_html(content, base_url)
        media_files.extend(img_media)
        
        # Extract videos from video tags
        video_media = self._extract_videos_from_html(content, base_url)
        media_files.extend(video_media)
        
        # Extract additional media from links
        link_media = self._extract_media_from_links(content, base_url)
        media_files.extend(link_media)
        
        # Remove duplicates and filter valid URLs
        media_files = self._deduplicate_and_filter(media_files)
        
        logger.info(f"📎 Extracted {len(media_files)} media files from content")
        return media_files
    
    def _extract_images_from_html(self, content: str, base_url: Optional[str] = None) -> List[Dict[str, Any]]:
        """Extract images from img tags."""
        images = []
        
        # Regex to find img tags with src attributes
        img_pattern = r'<img[^>]+src\s*=\s*["\']([^"\']+)["\'][^>]*>'
        matches = re.finditer(img_pattern, content, re.IGNORECASE)
        
        for match in matches:
            src = match.group(1).strip()
            img_tag = match.group(0)
            
            # Skip data URLs and invalid URLs
            if src.startswith('data:') or not src:
                continue
            
            # Resolve relative URLs
            if base_url and not src.startswith(('http://', 'https://')):
                src = urljoin(base_url, src)
            
            # Extract additional attributes
            alt_match = re.search(r'alt\s*=\s*["\']([^"\']*)["\']', img_tag, re.IGNORECASE)
            alt = alt_match.group(1) if alt_match else ''
            
            # Detect image type from URL
            parsed_url = urlparse(src)
            path = parsed_url.path.lower()
            media_type = 'image'
            
            for ext in self.IMAGE_EXTENSIONS:
                if path.endswith(ext):
                    media_type = f'image/{ext[1:]}'  # e.g., 'image/png'
                    break
            
            images.append({
                'url': src,
                'type': 'image',
                'media_type': media_type,
                'alt_text': alt,
                'source': 'img_tag'
            })
        
        return images
    
    def _extract_videos_from_html(self, content: str, base_url: Optional[str] = None) -> List[Dict[str, Any]]:
        """Extract videos from video tags and embedded video URLs."""
        videos = []
        
        # Extract from video tags
        video_pattern = r'<video[^>]+src\s*=\s*["\']([^"\']+)["\'][^>]*>'
        matches = re.finditer(video_pattern, content, re.IGNORECASE)
        
        for match in matches:
            src = match.group(1).strip()
            
            if not src or src.startswith('data:'):
                continue
            
            if base_url and not src.startswith(('http://', 'https://')):
                src = urljoin(base_url, src)
            
            videos.append({
                'url': src,
                'type': 'video',
                'media_type': 'video',
                'source': 'video_tag'
            })
        
        # Extract from source tags within video elements
        source_pattern = r'<source[^>]+src\s*=\s*["\']([^"\']+)["\'][^>]*>'
        matches = re.finditer(source_pattern, content, re.IGNORECASE)
        
        for match in matches:
            src = match.group(1).strip()
            
            if not src or src.startswith('data:'):
                continue
            
            if base_url and not src.startswith(('http://', 'https://')):
                src = urljoin(base_url, src)
            
            videos.append({
                'url': src,
                'type': 'video',
                'media_type': 'video',
                'source': 'source_tag'
            })
        
        # Extract YouTube, Vimeo, and other video embeds
        embed_patterns = [
            r'https?://(?:www\.)?youtube\.com/watch\?v=([a-zA-Z0-9_-]+)',
            r'https?://(?:www\.)?youtu\.be/([a-zA-Z0-9_-]+)',
            r'https?://(?:www\.)?vimeo\.com/(\d+)',
            r'https?://(?:www\.)?dailymotion\.com/video/([a-zA-Z0-9]+)',
        ]
        
        for pattern in embed_patterns:
            matches = re.finditer(pattern, content, re.IGNORECASE)
            for match in matches:
                full_url = match.group(0)
                videos.append({
                    'url': full_url,
                    'type': 'video',
                    'media_type': 'video/embed',
                    'source': 'embedded_video'
                })
        
        return videos
    
    def _extract_media_from_links(self, content: str, base_url: Optional[str] = None) -> List[Dict[str, Any]]:
        """Extract media files from href links."""
        media_files = []
        
        # Find all links
        link_pattern = r'<a[^>]+href\s*=\s*["\']([^"\']+)["\'][^>]*>'
        matches = re.finditer(link_pattern, content, re.IGNORECASE)
        
        for match in matches:
            href = match.group(1).strip()
            
            if not href or href.startswith(('mailto:', 'tel:', '#', 'javascript:')):
                continue
            
            if base_url and not href.startswith(('http://', 'https://')):
                href = urljoin(base_url, href)
            
            # Check if URL points to a media file
            parsed_url = urlparse(href)
            path = parsed_url.path.lower()
            
            # Check for image files
            for ext in self.IMAGE_EXTENSIONS:
                if path.endswith(ext):
                    media_files.append({
                        'url': href,
                        'type': 'image',
                        'media_type': f'image/{ext[1:]}',
                        'source': 'href_link'
                    })
                    break
            
            # Check for video files
            for ext in self.VIDEO_EXTENSIONS:
                if path.endswith(ext):
                    media_files.append({
                        'url': href,
                        'type': 'video',
                        'media_type': f'video/{ext[1:]}',
                        'source': 'href_link'
                    })
                    break
            
            # Check for document files
            for ext in self.DOCUMENT_EXTENSIONS:
                if path.endswith(ext):
                    media_files.append({
                        'url': href,
                        'type': 'document',
                        'media_type': f'document/{ext[1:]}',
                        'source': 'href_link'
                    })
                    break
        
        return media_files
    
    def _deduplicate_and_filter(self, media_files: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Remove duplicates and filter out invalid media files."""
        seen_urls = set()
        filtered_files = []
        
        for media in media_files:
            url = media.get('url', '')
            
            # Skip invalid URLs
            if not url or not url.startswith(('http://', 'https://')):
                continue
            
            # Skip duplicates
            if url in seen_urls:
                continue
            
            seen_urls.add(url)
            filtered_files.append(media)
        
        return filtered_files
    
    def get_media_summary(self, media_files: List[Dict[str, Any]]) -> Dict[str, int]:
        """Get summary counts of media types."""
        summary = {'image': 0, 'video': 0, 'document': 0, 'total': len(media_files)}
        
        for media in media_files:
            media_type = media.get('type', 'unknown')
            if media_type in summary:
                summary[media_type] += 1
        
        return summary


# Global instance
_media_extractor: Optional[MediaExtractor] = None


def get_media_extractor() -> MediaExtractor:
    """Get global media extractor instance."""
    global _media_extractor
    
    if _media_extractor is None:
        _media_extractor = MediaExtractor()
    
    return _media_extractor