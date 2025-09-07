"""Utility functions for content extraction."""

import re
import unicodedata
from typing import Dict
from urllib.parse import urlparse

from ..services.extraction_constants import MAX_CONTENT_LENGTH, MIN_CONTENT_LENGTH, MIN_QUALITY_SCORE


class ExtractionUtils:
    """Utility functions for content extraction and processing."""
    
    def __init__(self):
        self.max_content_length = MAX_CONTENT_LENGTH
        self.min_content_length = MIN_CONTENT_LENGTH
    
    def extract_domain(self, url: str) -> str:
        """Extract domain from URL."""
        try:
            parsed = urlparse(url)
            return parsed.netloc.lower()
        except:
            return "unknown"
    
    def clean_url(self, url: str) -> str:
        """Clean URL from invisible and problematic characters."""
        # Remove common invisible/problematic characters
        # Including: zero-width space, word joiner, etc.
        problematic_chars = [
            '\u200B',  # Zero Width Space
            '\u200C',  # Zero Width Non-Joiner  
            '\u200D',  # Zero Width Joiner
            '\u2060',  # Word Joiner
            '\uFEFF',  # Zero Width No-Break Space (BOM)
            '\u00A0',  # Non-breaking space
        ]
        
        cleaned_url = url
        for char in problematic_chars:
            cleaned_url = cleaned_url.replace(char, '')
        
        # Normalize unicode characters
        cleaned_url = unicodedata.normalize('NFKC', cleaned_url)
        
        # Remove any control characters
        cleaned_url = ''.join(char for char in cleaned_url if not unicodedata.category(char).startswith('C'))
        
        return cleaned_url.strip()
    
    def is_good_content(self, content: str) -> bool:
        """Check if extracted content meets basic quality standards."""
        if not content or len(content) < self.min_content_length:
            return False
        
        # Simple quality checks
        # 1. Must have reasonable length (already checked above)
        # 2. Must contain some sentences (basic structure check)
        sentence_count = len([s for s in content.split('.') if len(s.strip()) > 20])
        if sentence_count < 2:
            return False
        
        # 3. Must not be mostly repetitive (basic spam check)
        words = content.split()
        if len(words) < 10:
            return False
            
        # 4. Basic navigation/menu detection
        nav_indicators = ['menu', 'navigation', 'footer', 'sidebar', 'advertisement', 'cookie']
        nav_word_count = sum(1 for word in words if any(indicator in word.lower() for indicator in nav_indicators))
        if nav_word_count > len(words) * 0.1:  # More than 10% navigation words
            return False
        
        return True
    
    def finalize_content(self, content: str) -> str:
        """Final content processing and truncation."""
        if not content:
            return ""
        
        # Smart truncation by sentences
        return self.smart_truncate(content, self.max_content_length)
    
    def smart_truncate(self, text: str, max_length: int) -> str:
        """Intelligently truncate text at sentence boundaries."""
        if len(text) <= max_length:
            return text
        
        # Find last complete sentence within limit
        truncated = text[:max_length]
        
        # Look for sentence endings
        sentence_endings = ['. ', '! ', '? ']
        last_sentence_end = -1
        
        for ending in sentence_endings:
            pos = truncated.rfind(ending)
            if pos > last_sentence_end:
                last_sentence_end = pos + len(ending) - 1
        
        if last_sentence_end > max_length // 2:  # If we found a good break point
            return text[:last_sentence_end + 1].rstrip()
        else:
            # Fallback to word boundary
            words = truncated.split()
            return ' '.join(words[:-1]) + '...' if len(words) > 1 else truncated + '...'
    
    def assess_content_quality(self, text: str) -> float:
        """
        Assess content quality based on various metrics.
        Returns a score from 0.0 to 1.0 (higher is better).
        """
        if not text or len(text) < 50:
            return 0.0
        
        score = 0.0
        
        # Length factor (optimal around 500-2000 characters)
        length = len(text)
        if 200 <= length <= 3000:
            score += 0.3
        elif 100 <= length <= 5000:
            score += 0.2
        elif length >= 50:
            score += 0.1
        
        # Sentence structure (look for proper sentences)
        sentences = re.split(r'[.!?]+', text)
        valid_sentences = [s.strip() for s in sentences if len(s.strip()) > 10]
        
        if len(valid_sentences) >= 3:
            score += 0.2
        elif len(valid_sentences) >= 1:
            score += 0.1
        
        # Punctuation ratio (should have reasonable punctuation)
        punctuation_chars = len(re.findall(r'[.!?,:;]', text))
        punctuation_ratio = punctuation_chars / length if length > 0 else 0
        
        if 0.02 <= punctuation_ratio <= 0.15:  # Reasonable punctuation density
            score += 0.2
        elif 0.01 <= punctuation_ratio <= 0.25:
            score += 0.1
        
        # Word variety (avoid repetitive content)
        words = re.findall(r'\b\w+\b', text.lower())
        unique_words = set(words)
        
        if len(words) > 0:
            variety_ratio = len(unique_words) / len(words)
            if variety_ratio >= 0.4:
                score += 0.2
            elif variety_ratio >= 0.2:
                score += 0.1
        
        # Avoid content that looks like navigation/menus
        nav_indicators = ['click here', 'read more', 'subscribe', 'follow us', 
                         'menu', 'navigation', 'sidebar', 'footer', 'header']
        
        text_lower = text.lower()
        nav_count = sum(1 for indicator in nav_indicators if indicator in text_lower)
        
        if nav_count == 0:
            score += 0.1
        elif nav_count <= 2:
            score += 0.05
        
        return min(1.0, score)
    
    def get_headers(self) -> Dict[str, str]:
        """Get standard HTTP headers for web scraping."""
        return {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9,ru;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache'
        }
