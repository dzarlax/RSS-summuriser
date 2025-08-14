"""Smart Filtering service for reducing unnecessary AI requests."""

import re
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timedelta


class SmartFilter:
    """
    Smart filter to determine if articles need AI processing.
    Reduces unnecessary AI requests by filtering out low-quality or inappropriate content.
    """
    
    def __init__(self):
        # Content quality thresholds
        self.min_content_length = 100  # Minimum content length for AI processing
        self.max_content_length = 50000  # Maximum content length to avoid token limits
        self.min_title_length = 10  # Minimum title length
        
        # Language detection patterns (simple heuristic)
        self.cyrillic_ratio_threshold = 0.3  # Minimum cyrillic characters for Russian content
        
        # Spam/low-quality indicators
        self.spam_patterns = [
            r'\b(?:click here|кликни здесь|жми сюда)\b',
            r'\b(?:buy now|купи сейчас|заказать сейчас)\b', 
            r'\$\$\$+',  # Multiple dollar signs
            r'!!!{3,}',  # Multiple exclamation marks
            r'\b(?:free|бесплатно)\s+(?:download|скачать)\b',
            r'\b(?:limited time|ограниченное время)\b',
            r'\b(?:act now|действуй сейчас)\b',
        ]
        
        # Navigation/boilerplate patterns to exclude
        self.navigation_patterns = [
            r'^\s*(?:home|главная|news|новости|about|о нас|contact|контакты)\s*$',
            r'^\s*(?:menu|меню|navigation|навигация)\s*',
            r'^\s*(?:cookie|куки)\s+(?:policy|политика)',
            r'^\s*(?:privacy|конфиденциальность)\s+(?:policy|политика)',
            r'^\s*(?:terms|условия)\s+(?:of service|использования)',
            r'^\s*(?:404|error|ошибка)\s*',
        ]
        
        # Duplicate detection (simple hash-based)
        self.recent_content_hashes = {}  # Hash -> timestamp
        self.duplicate_detection_window = timedelta(hours=24)
        
    def should_process_with_ai(self, title: str, content: str, url: str, 
                              source_type: str = 'rss') -> Tuple[bool, str]:
        """
        Determine if article should be processed with AI.
        
        Args:
            title: Article title
            content: Article content
            url: Article URL
            source_type: Source type (rss, telegram, etc.)
            
        Returns:
            Tuple of (should_process, reason)
        """
        # Check content length
        if not self._check_content_length(content):
            return False, f"Content too short ({len(content)} chars < {self.min_content_length})"
            
        if len(content) > self.max_content_length:
            return False, f"Content too long ({len(content)} chars > {self.max_content_length})"
        
        # Check title quality
        if not self._check_title_quality(title):
            return False, f"Title too short or low quality ({len(title)} chars)"
        
        # Check for navigation/boilerplate content
        if self._is_navigation_content(title, content):
            return False, "Navigation/boilerplate content detected"
        
        # Check language (for Russian content focus)
        if not self._is_target_language(content):
            return False, "Content not in target language (Russian/English)"
        
        # Check for spam patterns
        if self._is_spam_content(title, content):
            return False, "Spam patterns detected"
        
        # Check for duplicates
        if self._is_duplicate_content(content):
            return False, "Duplicate content detected"
        
        # Check content quality score
        quality_score = self._calculate_quality_score(title, content, source_type)
        if quality_score < 0.4:  # Threshold for minimum quality
            return False, f"Content quality too low (score: {quality_score:.2f})"
        
        return True, f"Passed all filters (quality: {quality_score:.2f})"
    
    def _check_content_length(self, content: str) -> bool:
        """Check if content length is appropriate for AI processing."""
        if not content:
            return False
        clean_content = content.strip()
        return self.min_content_length <= len(clean_content) <= self.max_content_length
    
    def _check_title_quality(self, title: str) -> bool:
        """Check if title is meaningful and not too short."""
        if not title:
            return False
        clean_title = title.strip()
        return len(clean_title) >= self.min_title_length
    
    def _is_navigation_content(self, title: str, content: str) -> bool:
        """Check if content is navigation/boilerplate."""
        text = f"{title} {content}".lower()
        
        for pattern in self.navigation_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        
        return False
    
    def _is_target_language(self, content: str) -> bool:
        """Check if content is in target language (Russian/English)."""
        if not content:
            return False
        
        # Count cyrillic characters
        cyrillic_count = len(re.findall(r'[а-яёА-ЯЁ]', content))
        latin_count = len(re.findall(r'[a-zA-Z]', content))
        total_letters = cyrillic_count + latin_count
        
        if total_letters < 50:  # Too short to determine language
            return True  # Give benefit of doubt for short content
        
        cyrillic_ratio = cyrillic_count / total_letters if total_letters > 0 else 0
        
        # Accept if significant Russian content or mostly Latin (English)
        return cyrillic_ratio >= self.cyrillic_ratio_threshold or cyrillic_ratio <= 0.1
    
    def _is_spam_content(self, title: str, content: str) -> bool:
        """Check if content contains spam patterns."""
        text = f"{title} {content}".lower()
        
        for pattern in self.spam_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        
        return False
    
    def _is_duplicate_content(self, content: str) -> bool:
        """Check if content is a duplicate of recently processed content."""
        if not content:
            return False
        
        # Simple hash-based duplicate detection
        content_hash = hash(content.strip().lower())
        current_time = datetime.now()
        
        # Clean old entries
        cutoff_time = current_time - self.duplicate_detection_window
        self.recent_content_hashes = {
            h: timestamp for h, timestamp in self.recent_content_hashes.items()
            if timestamp > cutoff_time
        }
        
        # Check if this content was seen recently
        if content_hash in self.recent_content_hashes:
            return True
        
        # Add to recent hashes
        self.recent_content_hashes[content_hash] = current_time
        return False
    
    def _calculate_quality_score(self, title: str, content: str, source_type: str) -> float:
        """Calculate content quality score (0.0 - 1.0)."""
        score = 0.5  # Base score
        
        # Title quality
        if title and len(title.strip()) > 20:
            score += 0.1
        
        # Content structure
        if content:
            # Sentence count (good structure indicator)
            sentence_count = len(re.findall(r'[.!?]+', content))
            if 3 <= sentence_count <= 50:
                score += 0.15
            elif sentence_count > 50:
                score += 0.05  # Very long articles get less bonus
            
            # Paragraph structure
            paragraph_count = len([p for p in content.split('\n\n') if p.strip()])
            if paragraph_count >= 2:
                score += 0.1
            
            # Word count
            word_count = len(content.split())
            if 50 <= word_count <= 2000:
                score += 0.1
            elif word_count > 2000:
                score += 0.05  # Very long gets less bonus
        
        # Source type bonus
        if source_type == 'rss':
            score += 0.05  # RSS usually higher quality
        elif source_type == 'telegram':
            score += 0.02  # Telegram can be more varied
        
        # Penalty for suspicious patterns
        if content and re.search(r'[A-Z]{10,}', content):  # Too much CAPS
            score -= 0.1
        
        if content and len(re.findall(r'[!]{2,}', content)) > 3:  # Too many exclamations
            score -= 0.1
        
        # Penalty for personal service patterns (likely ads)
        text = f"{title} {content}".lower()
        personal_patterns = [
            r"я\s+программист", r"мой\s+опыт", r"моя\s+компания", r"предлагаю\s+услуги",
            r"обращайтесь\s+по\s+телефону", r"консультаци[ия]\s+по\s+телефону",
            r"специализируюсь", r"оказываю\s+услуги", r"свяжитесь\s+со\s+мной"
        ]
        for pattern in personal_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                score -= 0.3  # Strong penalty for personal services
        
        return max(0.0, min(1.0, score))  # Clamp to 0-1 range
    
    def get_filter_stats(self) -> Dict[str, Any]:
        """Get statistics about filtering."""
        return {
            'recent_hashes_count': len(self.recent_content_hashes),
            'min_content_length': self.min_content_length,
            'max_content_length': self.max_content_length,
            'cyrillic_ratio_threshold': self.cyrillic_ratio_threshold,
            'spam_patterns_count': len(self.spam_patterns),
            'navigation_patterns_count': len(self.navigation_patterns)
        }


# Global smart filter instance
_smart_filter: Optional[SmartFilter] = None


def get_smart_filter() -> SmartFilter:
    """Get smart filter instance."""
    global _smart_filter
    
    if _smart_filter is None:
        _smart_filter = SmartFilter()
    
    return _smart_filter

