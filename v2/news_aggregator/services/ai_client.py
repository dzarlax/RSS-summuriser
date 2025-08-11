"""AI API client for article summarization using Constructor KM."""

import json
from typing import Optional, Dict

from ..config import settings
from ..core.http_client import get_http_client
from ..core.cache import cached
from ..core.exceptions import APIError
# Removed direct import to avoid circular dependency


class AIClient:
    """Client for AI summarization using Constructor KM API."""
    
    def __init__(self):
        # Use Constructor KM API for everything
        self.endpoint = getattr(settings, 'constructor_km_api', None)
        self.api_key = getattr(settings, 'constructor_km_api_key', None)
        self.summarization_model = getattr(settings, 'summarization_model', 'gpt-4o-mini')
        self.digest_model = getattr(settings, 'digest_model', 'gpt-4.1')
        
        if not self.endpoint or not self.api_key:
            raise APIError("Constructor KM API endpoint and key must be configured")
        
        self.enabled = True
        
        self.content_extractor = None
    
    @cached(ttl=86400, key_prefix="ai_summary")
    async def get_article_summary(self, article_url: str) -> Optional[str]:
        """
        Get AI summary for article URL using Constructor KM API with 4.1-mini.
        
        Args:
            article_url: URL of the article to summarize
            
        Returns:
            Article summary text or None if failed
        """
        if not article_url:
            return None
        
        try:
            print(f"  🔗 Extracting content from URL: {article_url}")
            # Step 1: Extract article content using enhanced extractor with metadata
            if not self.content_extractor:
                # Import dynamically to avoid circular import
                from .content_extractor import get_content_extractor
                self.content_extractor = await get_content_extractor()
            
            # Try AI-enhanced extraction first
            try:
                metadata_result = await self.content_extractor.extract_article_content_with_metadata(article_url)
                content = metadata_result.get('content')
                pub_date = metadata_result.get('publication_date')
                full_url = metadata_result.get('full_article_url')
                
                if pub_date:
                    print(f"  📅 AI found publication date: {pub_date}")
                if full_url:
                    print(f"  🔗 AI followed link to full article: {full_url}")
                    
            except Exception as e:
                print(f"  ⚠️ AI-enhanced extraction failed, using fallback: {e}")
                content = None
            
            # If AI-enhanced extraction didn't get content, try standard extraction
            if not content:
                content = await self.content_extractor.extract_article_content(article_url)
            
            if not content:
                print(f"  ❌ Could not extract content from {article_url}")
                return None
            
            content_length = len(content)
            print(f"  📝 Extracted content: {content_length} characters")
            
            # Step 2: Summarize extracted content
            summary = await self._summarize_content(content)
            return summary
        
        except APIError:
            raise
        except Exception as e:
            print(f"  ⚠️ Error getting summary for {article_url}: {e}")
            raise APIError(f"Failed to get summary for {article_url}: {e}")
    
    async def get_article_summary_with_metadata(self, article_url: str) -> Dict[str, Optional[str]]:
        """
        Get AI summary with metadata for article URL.
        
        Args:
            article_url: URL of the article to summarize
            
        Returns:
            Dictionary with 'summary', 'publication_date', and other metadata
        """
        if not article_url:
            return {'summary': None, 'publication_date': None}
        
        metadata_result = {'publication_date': None, 'full_article_url': None}
        
        try:
            print(f"  🔗 Extracting content with metadata from URL: {article_url}")
            # Step 1: Extract article content using enhanced extractor with metadata
            if not self.content_extractor:
                # Import dynamically to avoid circular import
                from .content_extractor import get_content_extractor
                self.content_extractor = await get_content_extractor()
            
            # Try AI-enhanced extraction first
            try:
                metadata_result = await self.content_extractor.extract_article_content_with_metadata(article_url)
                content = metadata_result.get('content')
                pub_date = metadata_result.get('publication_date')
                full_url = metadata_result.get('full_article_url')
                
                if pub_date:
                    print(f"  📅 Found publication date: {pub_date}")
                if full_url and full_url != article_url:
                    print(f"  🔗 Followed link to full article: {full_url}")
                    
            except Exception as e:
                print(f"  ⚠️ AI-enhanced extraction failed, using fallback: {e}")
                content = None
            
            # If AI-enhanced extraction didn't get content, try standard extraction
            if not content:
                content = await self.content_extractor.extract_article_content(article_url)
            
            if not content:
                print(f"  ❌ Could not extract content from {article_url}")
                return {
                    'summary': None, 
                    'publication_date': metadata_result.get('publication_date'),
                    'full_article_url': metadata_result.get('full_article_url')
                }
            
            # Summarize the already extracted content to avoid double extraction
            summary = await self._summarize_content(content)
            
            return {
                'summary': summary,
                'publication_date': metadata_result.get('publication_date'),
                'full_article_url': metadata_result.get('full_article_url')
            }
            
        except Exception as e:
            print(f"  ❌ Error getting article summary with metadata: {e}")
            return {
                'summary': None,
                'publication_date': metadata_result.get('publication_date'),
                'full_article_url': metadata_result.get('full_article_url')
            }
    
    async def extract_publication_date(self, html_content: str, url: str) -> Optional[str]:
        """
        Extract publication date from HTML content using AI.
        
        Args:
            html_content: HTML content of the page
            url: URL of the article (for context)
            
        Returns:
            Publication date in ISO format (YYYY-MM-DD) or None if not found
        """
        if not html_content or len(html_content) < 100:
            return None
        
        try:
            print(f"  🗓️ AI extracting publication date for {url}")
            
            # Truncate HTML to manageable size
            content_sample = html_content[:3000] if len(html_content) > 3000 else html_content
            
            prompt = f"""Extract the publication date from this HTML content.

URL: {url}

HTML CONTENT:
{content_sample}

TASK: Find the publication date/time when this article was published.

Look for:
- Published date/time metadata
- Article timestamps  
- Date in structured markup (JSON-LD, microdata, etc.)
- Visible date/time near article title
- Time elements with datetime attributes

RESPONSE FORMAT (JSON):
{{
  "date_found": true,
  "publication_date": "2025-01-15",
  "confidence": 0.8,
  "source": "meta tag with property='article:published_time'",
  "raw_text": "January 15, 2025"
}}

If no date found, respond with:
{{
  "date_found": false,
  "confidence": 0.0,
  "reason": "No publication date indicators found"
}}

Focus on finding the actual publication date, not update dates or other timestamps."""

            payload = {
                "model": self.summarization_model,
                "messages": [
                    {
                        "role": "user", 
                        "content": prompt
                    }
                ],
                "max_tokens": 200,
                "temperature": 0.1
            }
            
            headers = {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'X-KM-AccessKey': self.api_key
            }
            
            async with get_http_client() as client:
                response = await client.post(
                    str(self.endpoint),
                    json=payload,
                    headers=headers,
                    timeout=15
                )
                
                async with response:
                    if response.status == 200:
                        data = await response.json()
                        if 'choices' in data and data['choices']:
                            ai_text = data['choices'][0]['message']['content'].strip()
                            return self._parse_date_response(ai_text)
                    else:
                        print(f"  ❌ Date extraction API error {response.status}")
                        return None
        
        except Exception as e:
            print(f"  ⚠️ Error extracting publication date: {e}")
            return None
    
    def _parse_date_response(self, ai_response: str) -> Optional[str]:
        """Parse AI response for publication date."""
        try:
            import re
            import json
            from datetime import datetime
            
            # Try to extract JSON from response
            json_match = re.search(r'\{[\s\S]*\}', ai_response)
            if not json_match:
                return None
            
            data = json.loads(json_match.group())
            
            if not data.get('date_found', False):
                return None
            
            publication_date = data.get('publication_date', '').strip()
            confidence = data.get('confidence', 0.0)
            
            if publication_date and confidence >= 0.5:
                # Validate date format
                try:
                    datetime.strptime(publication_date, '%Y-%m-%d')
                    print(f"  ✅ AI found publication date: {publication_date} (confidence: {confidence:.2f})")
                    return publication_date
                except ValueError:
                    print(f"  ⚠️ Invalid date format from AI: {publication_date}")
                    return None
            
            return None
            
        except (json.JSONDecodeError, Exception) as e:
            print(f"  ⚠️ Failed to parse date response: {e}")
            return None
    
    async def extract_full_article_link(self, html_content: str, base_url: str) -> Optional[str]:
        """
        Extract link to full article content using AI.
        
        Args:
            html_content: HTML content of the current page
            base_url: Base URL for resolving relative links
            
        Returns:
            Full article URL or None if not found
        """
        if not html_content or len(html_content) < 100:
            return None
        
        try:
            print(f"  🔗 AI extracting full article link for {base_url}")
            
            # Truncate HTML to manageable size
            content_sample = html_content[:4000] if len(html_content) > 4000 else html_content
            
            prompt = f"""Find the link to the full article content from this HTML.

BASE URL: {base_url}

HTML CONTENT:
{content_sample}

TASK: Find a link that leads to the full article content (not summary/excerpt).

Look for:
- "Read more", "Continue reading", "Full article" links
- Links in article cards that point to detailed pages
- Main article title links
- Links with text like "Read full story", "See more", etc.

RESPONSE FORMAT (JSON):
{{
  "link_found": true,
  "full_article_url": "https://example.com/full-article",
  "confidence": 0.8,
  "link_text": "Read more",
  "selector": "a.read-more-link"
}}

If no link found, respond with:
{{
  "link_found": false,
  "confidence": 0.0,
  "reason": "No full article link found"
}}

Return the complete, absolute URL. If the link is relative, make it absolute using the base URL."""

            payload = {
                "model": self.summarization_model,
                "messages": [
                    {
                        "role": "user", 
                        "content": prompt
                    }
                ],
                "max_tokens": 300,
                "temperature": 0.1
            }
            
            headers = {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'X-KM-AccessKey': self.api_key
            }
            
            async with get_http_client() as client:
                response = await client.post(
                    str(self.endpoint),
                    json=payload,
                    headers=headers,
                    timeout=15
                )
                
                async with response:
                    if response.status == 200:
                        data = await response.json()
                        if 'choices' in data and data['choices']:
                            ai_text = data['choices'][0]['message']['content'].strip()
                            return self._parse_link_response(ai_text, base_url)
                    else:
                        print(f"  ❌ Link extraction API error {response.status}")
                        return None
        
        except Exception as e:
            print(f"  ⚠️ Error extracting full article link: {e}")
            return None
    
    def _parse_link_response(self, ai_response: str, base_url: str) -> Optional[str]:
        """Parse AI response for full article link."""
        try:
            import re
            import json
            from urllib.parse import urljoin, urlparse
            
            # Try to extract JSON from response
            json_match = re.search(r'\{[\s\S]*\}', ai_response)
            if not json_match:
                return None
            
            data = json.loads(json_match.group())
            
            if not data.get('link_found', False):
                return None
            
            full_article_url = data.get('full_article_url', '').strip()
            confidence = data.get('confidence', 0.0)
            
            if full_article_url and confidence >= 0.5:
                # Make sure URL is absolute
                if not full_article_url.startswith(('http://', 'https://')):
                    full_article_url = urljoin(base_url, full_article_url)
                
                # Validate URL format
                parsed = urlparse(full_article_url)
                if parsed.scheme and parsed.netloc:
                    print(f"  ✅ AI found full article link: {full_article_url} (confidence: {confidence:.2f})")
                    return full_article_url
                else:
                    print(f"  ⚠️ Invalid URL from AI: {full_article_url}")
                    return None
            
            return None
            
        except (json.JSONDecodeError, Exception) as e:
            print(f"  ⚠️ Failed to parse link response: {e}")
            return None
    
    async def generate_digest(self, result_data: dict, message_part: Optional[int] = None) -> Optional[str]:
        """
        Generate final digest using Constructor KM API with 4.1 (full model).
        
        Args:
            result_data: Dictionary with categories and their news items
            message_part: Part number for splitting (1, 2, or None for single message)
            
        Returns:
            Final digest text or None if failed
        """
        if not result_data:
            return None
        
        try:
            # Calculate totals
            total_news = sum(len(articles) for articles in result_data.values())
            categories = len(result_data)
            
            # Header and limits depend on message part
            if message_part == 1:
                header_text = "Сводка новостей (часть 1)"
            elif message_part == 2:
                header_text = "Сводка новостей (часть 2)" 
            else:
                header_text = "Сводка новостей"
            
            # Character limits for each part
            if message_part:
                char_limit = 3400  # For split messages
                detail_level = "СЖАТО"
            else:
                char_limit = 2600  # For single messages
                detail_level = "СЖАТО"
            
            # Prepare news content
            news_content = ""
            for category, articles in result_data.items():
                news_content += f"\n{category}:\n"
                for article in articles:
                    title = article.get('title', article.get('canonical_title', ''))
                    summary = article.get('summary', article.get('canonical_summary', ''))
                    news_content += f"- {title}\n"
                    if summary:
                        news_content += f"  {summary[:200]}...\n"
            
            prompt = f"""Ты - опытный журналист. Создай {detail_level} связную сводку новостей в HTML.

{total_news} новостей в {categories} категориях.

ТРЕБОВАНИЯ:
- HTML с <b></b> для заголовков категорий
- Связные абзацы (НЕ списки!)
- МАКСИМУМ {char_limit} символов
- Охвати основные события по категориям
- Пиши как связный рассказ, а не перечисления

ФОРМАТ:
<b>{header_text}</b>

Материалы:
{news_content}

Создай связную сводку главных событий дня в виде единого текста."""

            payload = {
                "model": self.digest_model,  # Configurable model for final digest
                "messages": [
                    {
                        "role": "user", 
                        "content": prompt
                    }
                ],
                "max_tokens": 1500,
                "temperature": 0.4
            }
            
            headers = {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'X-KM-AccessKey': self.api_key
            }
            
            async with get_http_client() as client:
                response = await client.post(
                    str(self.endpoint),
                    json=payload,
                    headers=headers
                )
                
                async with response:
                    if response.status == 200:
                        data = await response.json()
                        if 'choices' in data and data['choices']:
                            digest = data['choices'][0]['message']['content'].strip()
                            return digest
                        else:
                            print(f"  ⚠️ No choices in digest API response")
                            return None
                    elif response.status == 429:
                        raise APIError("Rate limit exceeded", status_code=429)
                    else:
                        error_text = await response.text()
                        print(f"  ⚠️ Digest API error {response.status}: {error_text}")
                        raise APIError(
                            f"Digest API error: {response.status}",
                            status_code=response.status,
                            response_text=error_text
                        )
        
        except APIError:
            raise
        except Exception as e:
            print(f"  ⚠️ Error generating digest: {e}")
            raise APIError(f"Failed to generate digest: {e}")
    
    async def _make_raw_ai_request(self, prompt: str, model: str = None) -> dict:
        """
        Make raw AI API request for custom analysis (like DOM structure analysis).
        
        Args:
            prompt: Raw prompt text
            model: Model to use (defaults to summarization_model)
            
        Returns:
            Raw API response dict
        """
        if not model:
            model = self.summarization_model
        
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user", 
                    "content": prompt
                }
            ],
            "max_tokens": 2000,
            "temperature": 0.1  # Low temperature for consistent analysis
        }
        
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'X-KM-AccessKey': self.api_key
        }
        
        async with get_http_client() as client:
            response = await client.post(
                str(self.endpoint),
                json=payload,
                headers=headers
            )
            
            async with response:
                if response.status == 200:
                    data = await response.json()
                    return data
                elif response.status == 429:
                    raise APIError("Rate limit exceeded", status_code=429)
                else:
                    error_text = await response.text()
                    raise APIError(
                        f"AI API error: {response.status}",
                        status_code=response.status,
                        response_text=error_text
                    )
    
    async def detect_advertising(self, content: str, source_info: dict = None) -> dict:
        """
        Detect advertising content in messages using AI.
        
        Args:
            content: Message content to analyze
            source_info: Optional source information (channel name, etc.)
            
        Returns:
            Dictionary with detection results including confidence, reasoning, and classification
        """
        if not content or len(content.strip()) < 10:
            return {
                'is_advertisement': False,
                'confidence': 0.0,
                'reasoning': 'Content too short for analysis',
                'ad_type': None,
                'markers': []
            }
        
        try:
            print(f"  🎯 AI analyzing content for advertising...")
            
            # Build context information
            context_info = ""
            if source_info:
                channel_name = source_info.get('channel', 'unknown')
                context_info = f"Channel: {channel_name}\n"
            
            prompt = f"""Analyze this message content for advertising/promotional characteristics.

{context_info}
MESSAGE CONTENT:
{content}

TASK: Determine if this is advertising, promotional content, or spam.

ADVERTISING INDICATORS TO LOOK FOR:
1. Direct product/service sales pitches
2. Affiliate links or referral codes
3. "Call to action" phrases (buy now, subscribe, join, etc.)
4. Price mentions with currency symbols
5. Promotional language (limited time, special offer, discount, etc.)
6. Contact information for business purposes (telegram channels, websites for sales)
7. Crypto trading signals or investment advice for profit
8. Multi-level marketing or pyramid scheme language
9. Excessive use of promotional emojis (💰, 🔥, ⚡, 💎, 🚀, etc.)
10. Sponsored content mentions

NEWS/LEGITIMATE CONTENT INDICATORS:
1. Factual reporting without sales intent
2. Educational or informational content
3. News updates or current events
4. Technical analysis without direct trading signals
5. General discussion or opinion pieces
6. Government or official announcements

RESPONSE FORMAT (JSON):
{{
  "is_advertisement": true,
  "confidence": 0.85,
  "ad_type": "product_promotion",
  "reasoning": "Contains direct sales pitch with call-to-action and price mention",
  "markers": ["call_to_action", "price_mention", "promotional_language"],
  "suspected_intent": "Direct product sales"
}}

AD_TYPES:
- "product_promotion" - Direct product/service advertising
- "affiliate_marketing" - Affiliate links or referral schemes  
- "crypto_signals" - Trading signals or investment advice
- "channel_promotion" - Promoting other channels/communities
- "spam" - Generic spam or low-quality promotional content
- "sponsored_content" - Paid promotional posts

If not advertising, respond with:
{{
  "is_advertisement": false,
  "confidence": 0.0,
  "reasoning": "Content appears to be legitimate news/information",
  "ad_type": null,
  "markers": []
}}

Focus on detecting content that's primarily promotional rather than informational."""

            payload = {
                "model": self.summarization_model,
                "messages": [
                    {
                        "role": "user", 
                        "content": prompt
                    }
                ],
                "max_tokens": 300,
                "temperature": 0.1
            }
            
            headers = {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'X-KM-AccessKey': self.api_key
            }
            
            async with get_http_client() as client:
                response = await client.post(
                    str(self.endpoint),
                    json=payload,
                    headers=headers,
                    timeout=15
                )
                
                async with response:
                    if response.status == 200:
                        data = await response.json()
                        if 'choices' in data and data['choices']:
                            ai_text = data['choices'][0]['message']['content'].strip()
                            return self._parse_advertising_response(ai_text)
                    else:
                        print(f"  ❌ Advertising detection API error {response.status}")
                        return self._default_ad_response()
        
        except Exception as e:
            print(f"  ⚠️ Error detecting advertising: {e}")
            return self._default_ad_response()
    
    def _parse_advertising_response(self, ai_response: str) -> dict:
        """Parse AI response for advertising detection."""
        try:
            import re
            import json
            
            # Try to extract JSON from response
            json_match = re.search(r'\{[\s\S]*\}', ai_response)
            if not json_match:
                return self._default_ad_response()
            
            data = json.loads(json_match.group())
            
            # Validate and normalize response
            result = {
                'is_advertisement': bool(data.get('is_advertisement', False)),
                'confidence': float(data.get('confidence', 0.0)),
                'reasoning': data.get('reasoning', 'No reasoning provided').strip(),
                'ad_type': data.get('ad_type'),
                'markers': data.get('markers', []),
                'suspected_intent': data.get('suspected_intent', '')
            }
            
            # Ensure confidence is between 0 and 1
            result['confidence'] = max(0.0, min(1.0, result['confidence']))
            
            # Only consider it advertising if confidence is above threshold
            if result['is_advertisement'] and result['confidence'] < 0.6:
                result['is_advertisement'] = False
                result['reasoning'] += ' (Low confidence threshold not met)'
            
            if result['is_advertisement']:
                print(f"  🚨 Advertising detected: {result['ad_type']} (confidence: {result['confidence']:.2f})")
            else:
                print(f"  ✅ Content appears legitimate (confidence: {result['confidence']:.2f})")
            
            return result
            
        except (json.JSONDecodeError, Exception) as e:
            print(f"  ⚠️ Failed to parse advertising response: {e}")
            return self._default_ad_response()
    
    def _default_ad_response(self) -> dict:
        """Return default response when advertising detection fails."""
        return {
            'is_advertisement': False,
            'confidence': 0.0,
            'reasoning': 'Analysis failed - defaulting to non-advertising',
            'ad_type': None,
            'markers': [],
            'suspected_intent': ''
        }
    
    def _clean_summary_text(self, raw_summary: str) -> str:
        """Clean AI-generated summary from service text and prompt repetition."""
        if not raw_summary:
            return ""
        
        import re
        
        # Remove common service phrases that AI sometimes includes
        service_phrases = [
            r'^Краткое содержание статьи на русском языке с основными тезисами:\s*',
            r'^Краткое содержание статьи на русском языке:\s*',
            r'^Краткое содержание:\s*',
            r'^Основные тезисы статьи:\s*',
            r'^Основные тезисы:\s*',
            r'^Суммаризация статьи:\s*',
            r'^Пересказ статьи:\s*',
            r'^Содержание статьи:\s*',
            r'^Вот краткое содержание:\s*',
            r'^Вот основные тезисы:\s*',
            r'^Статья содержит следующие основные моменты:\s*',
            r'^Статья рассказывает о следующем:\s*'
        ]
        
        cleaned_summary = raw_summary
        
        # Remove service phrases from the beginning
        for phrase_pattern in service_phrases:
            cleaned_summary = re.sub(phrase_pattern, '', cleaned_summary, flags=re.IGNORECASE | re.MULTILINE)
        
        # Remove leading/trailing whitespace and newlines
        cleaned_summary = cleaned_summary.strip()
        
        # Remove empty bullet points or dashes at the beginning
        cleaned_summary = re.sub(r'^[-•·*]\s*', '', cleaned_summary, flags=re.MULTILINE)
        cleaned_summary = re.sub(r'^\d+\.\s*$', '', cleaned_summary, flags=re.MULTILINE)
        
        # Clean up multiple newlines
        cleaned_summary = re.sub(r'\n\s*\n', '\n\n', cleaned_summary)
        
        # Remove trailing periods/colons if they look like service text endings
        cleaned_summary = re.sub(r':\s*$', '', cleaned_summary)
        
        return cleaned_summary.strip()

    async def _summarize_content(self, content: str) -> Optional[str]:
        """Summarize plain article content with robust empty-output fallback."""
        if not content:
            return None
        # Build prompt
        base_prompt = (
            "Прочитай статью и создай краткий пересказ на русском языке.\n\n"
            "ТРЕБОВАНИЯ:\n"
            "- Сразу начинай с основного содержания (без вводных фраз)\n"
            "- Используй 3-5 ключевых пунктов\n"
            "- Сохрани важные факты и цифры\n"
            "- Пиши кратко и информативно\n\n"
            "СТАТЬЯ:\n"
            f"{content[:8000]}\n\n"  # защитимся от сверхдлинных текстов
            "ПЕРЕСКАЗ:"
        )

        # First attempt
        system_prompt = (
            "Ты профессиональный новостной редактор. \n"
            "Отвечай СТРОГО на русском языке, коротко и информативно. \n"
            "Запрещено копировать большие фрагменты исходного текста."
        )
        first = await self._call_summary_llm(base_prompt, system_prompt=system_prompt)
        cleaned = self._clean_summary_text(first or "") if first is not None else ""

        if not self._is_summary_valid(cleaned, content):
            # Retry with stricter prompt
            strict_prompt = (
                "Перескажи статью СВОИМИ СЛОВАМИ на русском языке. НЕЛЬЗЯ копировать фразы из текста.\n"
                "Сделай 3–5 лаконичных пунктов (каждый 1–2 предложения). Без вступлений, без списков исходного текста.\n\n"
                "СТАТЬЯ:\n"
                f"{content[:8000]}\n\n"
                "СТРОГИЙ ПЕРЕСКАЗ:"
            )
            second = await self._call_summary_llm(strict_prompt, system_prompt=system_prompt)
            cleaned2 = self._clean_summary_text(second or "") if second is not None else ""
            if self._is_summary_valid(cleaned2, content):
                print(f"  ✅ AI summarization successful after retry: {len(cleaned2)} characters")
                return cleaned2
            # Final fallback: simple extractive summary
            fallback = self._simple_extractive_summary(content)
            print(f"  ✅ Fallback summarization used: {len(fallback)} characters")
            return fallback

        print(f"  ✅ AI summarization successful: {len(cleaned)} characters")
        return cleaned

    async def _call_summary_llm(self, prompt: str, *, system_prompt: str | None = None) -> Optional[str]:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.summarization_model,
            "messages": messages,
            "max_tokens": 1000,
            "temperature": 0.2,
            "top_p": 0.9,
            "presence_penalty": 0.0,
            "frequency_penalty": 0.1,
        }
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'X-KM-AccessKey': self.api_key,
        }
        async with get_http_client() as client:
            print(f"  🤖 Sending to AI for summarization...")
            print(f"  🌐 Making API request to {self.endpoint}")
            response = await client.post(str(self.endpoint), json=payload, headers=headers)
            async with response:
                print(f"  📡 API response status: {response.status}")
                if response.status == 200:
                    data = await response.json()
                    if 'choices' in data and data['choices']:
                        return (data['choices'][0]['message']['content'] or '').strip()
                    return None
                elif response.status == 429:
                    raise APIError("Rate limit exceeded", status_code=429)
                else:
                    error_text = await response.text()
                    print(f"  ❌ API error {response.status}: {error_text}")
                    raise APIError(
                        f"API error: {response.status}",
                        status_code=response.status,
                        response_text=error_text,
                    )

    def _is_summary_valid(self, summary: str, original: str) -> bool:
        if not summary or len(summary) < 60:
            return False
        # Check for Russian (presence of Cyrillic)
        has_cyrillic = any('а' <= ch.lower() <= 'я' for ch in summary)
        if not has_cyrillic:
            return False
        # Similarity check: avoid copies
        try:
            import difflib
            ratio = difflib.SequenceMatcher(None, summary[:1000], original[:1000]).ratio()
            if ratio > 0.80:
                return False
        except Exception:
            pass
        return True

    def _simple_extractive_summary(self, content: str) -> str:
        # Возьмём 3-4 первых информативных предложения до 600 символов
        import re
        sentences = re.split(r"(?<=[\.!?])\s+", content.strip())
        picked = []
        total = 0
        for s in sentences:
            if len(s) < 15:
                continue
            picked.append(s)
            total += len(s)
            if len(picked) >= 4 or total > 600:
                break
        text = " ".join(picked).strip()
        return text[:700] + ('...' if len(text) > 700 else '')

    async def test_connection(self) -> bool:
        """Test AI API connectivity."""
        try:
            test_url = "https://example.com"  # Safe test URL
            summary = await self.get_article_summary(test_url)
            return summary is not None
        except Exception:
            return False


# Global AI client instance
_ai_client: Optional[AIClient] = None


def get_ai_client() -> AIClient:
    """Get AI client instance."""
    global _ai_client
    
    if _ai_client is None:
        _ai_client = AIClient()
    
    return _ai_client