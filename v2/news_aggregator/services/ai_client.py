"""AI API client for article summarization using Constructor KM."""

import asyncio
import json
from typing import Optional, Dict, Any

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
    
    # Note: get_article_summary() method was removed and replaced by analyze_article_complete()
    # which provides combined analysis (summarization + categorization + ad detection) in a single request.
    
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
            
            # Use unified analysis to get summary (more reliable than separate summarization)
            analysis_result = await self.analyze_article_complete(article_url, content, "Article")
            summary = analysis_result.get('summary') if analysis_result else None
            
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
            
            from .prompts import NewsPrompts
            prompt = NewsPrompts.news_digest(
                total_news=total_news, 
                categories=categories, 
                news_content=news_content,
                char_limit=char_limit, 
                detail_level=detail_level, 
                header_text=header_text
            )

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
    
    # ============================================================================
    # REMOVED: detect_advertising() - Replaced by unified analysis
    # ============================================================================
    # This method was replaced by analyze_article_complete() which includes
    # advertisement detection along with categorization and summarization
    # in a single API call for efficiency.
    
    # ============================================================================
    # REMOVED: Advertising detection helper methods - Replaced by unified analysis
    # ============================================================================
    # _parse_advertising_response() and _default_ad_response() were removed as
    # they are now handled by analyze_article_complete() unified processing.
    
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

    # Note: _summarize_content() method removed - all summarization now uses 
    # analyze_article_complete() which provides better quality results

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
        """Test AI API connectivity with minimal request."""
        try:
            # Simple test prompt to check API availability (avoids heavy content extraction)
            test_prompt = "Test connectivity. Respond briefly."
            response = await self._make_raw_ai_request(test_prompt, model=self.summarization_model)
            return bool(response and 'choices' in response and response['choices'])
        except Exception:
            return False

    async def analyze_article_complete(self, title: str, content: str, url: str) -> Dict[str, Any]:
        """
        Complete article analysis with combined prompts - categorization, summarization, 
        advertisement detection, and date extraction in one API call.
        
        Args:
            title: Article title
            content: Article content
            url: Article URL
            
        Returns:
            Dictionary with all analysis results
        """
        # Enhanced content length protection  
        if not content or not isinstance(content, str) or len(content.strip()) < 30:
            print(f"  ⚠️ Content too short for analysis: {len(content.strip()) if content else 0} chars < 30")
            return self._get_fallback_analysis()
        
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                # Build enhanced combined prompt with dynamic category metadata
                try:
                    prompt = await self._build_combined_analysis_prompt_enhanced(title, content, url)
                    print(f"  🚀 Using enhanced prompt with category metadata")
                except Exception as e:
                    print(f"  ⚠️ Failed to load enhanced prompt, falling back to standard: {e}")
                    prompt = self._build_combined_analysis_prompt(title, content, url)
                
                retry_text = f" (attempt {attempt + 1}/{max_retries + 1})" if attempt > 0 else ""
                print(f"  🧠 Combined AI analysis for article{retry_text}...")
                print(f"  📄 Content length: {len(content)} characters")
                print(f"  📝 Title: {title[:100]}...")
                
                # Make API request
                response_data = await self._make_raw_ai_request(prompt)
                response = ''
                if response_data and 'choices' in response_data and response_data['choices']:
                    response = response_data['choices'][0]['message']['content']
                
                if not response:
                    print(f"  ❌ Empty response from AI")
                    if attempt < max_retries:
                        print(f"  🔄 Retrying in 2 seconds...")
                        await asyncio.sleep(2)
                        continue
                    return self._get_fallback_analysis()
                
                # Parse JSON response
                try:
                    result = json.loads(response.strip())
                    print(f"  ✅ Combined analysis successful")
                    
                    # Validate and clean results
                    return self._validate_analysis_result(result, title, content)
                    
                except json.JSONDecodeError as e:
                    print(f"  ⚠️ JSON parsing error: {e}")
                    print(f"  📄 Raw response: {response[:200]}...")
                    if attempt < max_retries:
                        print(f"  🔄 Retrying in 2 seconds...")
                        await asyncio.sleep(2)
                        continue
                    return self._parse_fallback_response(response)
                    
            except Exception as e:
                print(f"  ❌ Error in combined analysis: {e}")
                if attempt < max_retries:
                    print(f"  🔄 Retrying in 2 seconds...")
                    await asyncio.sleep(2)
                    continue
                return self._get_fallback_analysis()
        
        # Fallback if all retries failed
        return self._get_fallback_analysis()
    
    async def _build_combined_analysis_prompt_enhanced(self, title: str, content: str, url: str) -> str:
        """Build enhanced combined prompt using dynamic category metadata."""
        from .prompts import NewsPrompts, PromptBuilder
        source_context = PromptBuilder.build_source_context(url)
        return await NewsPrompts.unified_article_analysis_enhanced(title, content, url, source_context)
    
    def _build_combined_analysis_prompt(self, title: str, content: str, url: str) -> str:
        """Build combined prompt for all analysis tasks (legacy method)."""
        # Limit content size for cost optimization
        content_preview = content[:2000] + ("..." if len(content) > 2000 else "")
        
        from .prompts import NewsPrompts, PromptBuilder
        source_context = PromptBuilder.build_source_context(url)
        return NewsPrompts.unified_article_analysis(title, content, url, source_context)
    
    def _validate_analysis_result(self, result: Dict[str, Any], title: str = None, content: str = None) -> Dict[str, Any]:
        """Validate and clean analysis result."""
        # Safe float conversion with fallback
        def safe_float(value, default=0.0):
            try:
                if value is None:
                    return default
                return float(value)
            except (TypeError, ValueError):
                return default
        
        # Import category parser
        from .category_parser import parse_category
        
        # Extract categories from new format (categories array) or fallback to old format
        categories = result.get('categories', [])
        if not categories:
            # Fallback to single category field for backward compatibility
            single_category = result.get('category')
            if single_category:
                categories = [single_category]
        
        # Get first category as primary for legacy compatibility
        primary_category = categories[0] if categories else None
        
        return {
            'optimized_title': result.get('optimized_title', '').strip() or None,  # Add optimized title support
            'summary': result.get('summary', '').strip() or None,
            'category': primary_category,  # Return primary category for processing by orchestrator
            'categories': categories,  # New: support multiple categories
            'category_confidences': result.get('category_confidences', []),  # New: confidence scores
            'category_confidence': max(0.0, min(1.0, safe_float(result.get('category_confidence'), 0.8))),
            'summary_confidence': max(0.0, min(1.0, safe_float(result.get('summary_confidence'), 0.8))),
            'categories_parsed': parse_category(primary_category, title=title, content=content[:500] if content else None, return_multiple=True),
            'original_categories': result.get('original_categories', []),  # Enhanced: AI descriptive categories before mapping
            'is_advertisement': bool(result.get('is_advertisement', False)),
            'ad_type': result.get('ad_type', 'news_article'),
            'ad_confidence': max(0.0, min(1.0, safe_float(result.get('ad_confidence'), 0.0))),
            'ad_reasoning': result.get('ad_reasoning', '').strip() or 'Combined analysis',
            'publication_date': result.get('publication_date'),
            'content_quality': max(0.0, min(1.0, safe_float(result.get('content_quality'), 0.7))),
            'confidence': max(0.0, min(1.0, safe_float(result.get('confidence'), 0.8)))  # Legacy field
        }
    
    def _get_fallback_analysis(self) -> Dict[str, Any]:
        """Get fallback analysis when AI fails."""
        return {
            'optimized_title': None,  # No title optimization in fallback
            'summary': None,
            'categories': ['Other'],  # Updated to new array format
            'category_confidences': [0.1],  # Array of confidences matching categories
            'category': 'Other',  # Keep for backward compatibility
            'category_confidence': 0.1,  # Keep for backward compatibility
            'summary_confidence': 0.0,
            'is_advertisement': False,
            'ad_type': 'news_article',
            'ad_confidence': 0.0,
            'ad_reasoning': 'Fallback analysis - AI unavailable',
            'publication_date': None,
            'content_quality': 0.2,
            'confidence': 0.1  # Legacy field
        }
    
    def _parse_fallback_response(self, response: str) -> Dict[str, Any]:
        """Try to parse non-JSON response as fallback."""
        result = self._get_fallback_analysis()
        
        # Try to extract some info from text response
        response_lower = response.lower()
        
        # Extract category
        for category in ['business', 'tech', 'science', 'serbia']:
            if category in response_lower:
                category_name = category.title()
                result['category'] = category_name  # For backward compatibility
                result['categories'] = [category_name]  # New array format
                result['category_confidences'] = [0.7]  # Moderate confidence for fallback detection
                break
        
        # Extract advertisement detection
        if any(word in response_lower for word in ['advertisement', 'promotional', 'marketing', 'ad']):
            result['is_advertisement'] = True
            result['ad_confidence'] = 0.7
        
        # Use first sentences as summary
        sentences = response.split('.')[:3]
        if sentences:
            result['summary'] = '. '.join(sentences[:2]).strip() + '.'
        
        return result


# Global AI client instance
_ai_client: Optional[AIClient] = None


def get_ai_client() -> AIClient:
    """Get AI client instance."""
    global _ai_client
    
    if _ai_client is None:
        _ai_client = AIClient()
    
    return _ai_client