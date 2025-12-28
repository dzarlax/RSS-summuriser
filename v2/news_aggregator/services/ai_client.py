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
    """Client for AI summarization using external AI provider (Constructor KM or Gemini)."""
    
    def __init__(self):
        # Provider selection: "constructor" or "gemini"
        self.provider = getattr(settings, 'ai_provider', 'constructor').lower()
        
        # Task-specific models (names depend on provider)
        self.summarization_model = getattr(settings, 'summarization_model', 'gpt-4o-mini')
        self.digest_model = getattr(settings, 'digest_model', 'gpt-4.1')
        
        if self.provider == "constructor":
            # Constructor KM (OpenAI-compatible) configuration
            self.endpoint = getattr(settings, 'constructor_km_api', None)
            self.api_key = getattr(settings, 'constructor_km_api_key', None)
            self.supports_structured_output = False
            
            if not self.endpoint or not self.api_key:
                raise APIError("Constructor KM API endpoint and key must be configured")
                
        elif self.provider == "gemini":
            # Direct Gemini configuration
            self.endpoint = getattr(
                settings, 
                'gemini_api_endpoint',
                'https://generativelanguage.googleapis.com/v1/models'
            )
            self.api_key = getattr(settings, 'gemini_api_key', None)
            # Gemini 3 Flash Preview and other models support structured output
            # See: https://ai.google.dev/gemini-api/docs/structured-output
            self.supports_structured_output = True
            
            if not self.api_key:
                raise APIError("Gemini API key must be configured")
        else:
            raise APIError(f"Unknown AI provider: {self.provider}. Supported: 'constructor', 'gemini'")
        
        self.enabled = True
    
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
            from ..extraction import ContentExtractor
            
            # Try AI-enhanced extraction first
            try:
                async with ContentExtractor() as content_extractor:
                    metadata_result = await content_extractor.extract_article_content_with_metadata(article_url)
                    content = metadata_result.get('content')
                    pub_date = metadata_result.get('publication_date')
                    full_url = metadata_result.get('full_article_url')
                    
                    if pub_date:
                        print(f"  📅 Found publication date: {pub_date}")
                    if full_url and full_url != article_url:
                        print(f"  🔗 Followed link to full article: {full_url}")
                        
                    # If AI-enhanced extraction didn't get content, try standard extraction
                    if not content:
                        content = await content_extractor.extract_article_content(article_url)
                    
            except Exception as e:
                print(f"  ⚠️ Content extraction failed: {e}")
                content = None
            
            if not content:
                print(f"  ❌ Could not extract content from {article_url}")
                return {
                    'summary': None, 
                    'publication_date': metadata_result.get('publication_date'),
                    'full_article_url': metadata_result.get('full_article_url')
                }
            
            # Use unified analysis to get summary (more reliable than separate summarization)
            # Extract title from content if available, otherwise use URL as fallback
            title = "Article"  # Default title if not available
            if content:
                # Try to extract title from first line or use first sentence
                lines = content.split('\n')
                if lines:
                    title = lines[0].strip()[:200]  # Use first line as title, limit length
            
            analysis_result = await self.analyze_article_complete(title, content, article_url)
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
            
            from .prompts import NewsPrompts
            prompt = NewsPrompts.extract_publication_date(content_sample)

            # Schema for structured output (Gemini)
            schema = {
                "type": "object",
                "properties": {
                    "date_found": {"type": "boolean"},
                    "publication_date": {"type": ["string", "null"]},
                    "confidence": {"type": "number"}
                },
                "required": ["date_found", "publication_date", "confidence"]
            }

            if self.supports_structured_output:
                # Use structured output for Gemini
                response_data = await self._make_structured_ai_request(
                    prompt,
                    model=self.summarization_model,
                    schema=schema,
                    analysis_type="publication_date",
                    domain=url
                )
                result = response_data.get("result") or {}
                
                if result.get("date_found") and result.get("publication_date"):
                    pub_date = result.get("publication_date", "").strip()
                    confidence = result.get("confidence", 0.0)
                    
                    if pub_date and confidence >= 0.5:
                        from datetime import datetime
                        try:
                            datetime.strptime(pub_date, '%Y-%m-%d')
                            print(f"  ✅ AI found publication date: {pub_date} (confidence: {confidence:.2f})")
                            return pub_date
                        except ValueError:
                            print(f"  ⚠️ Invalid date format from AI: {pub_date}")
                            return None
                return None
            else:
                # Fallback for Constructor: use raw request and parse
                response_data = await self._make_raw_ai_request(
                    prompt,
                    model=self.summarization_model,
                    analysis_type="publication_date",
                    domain=url
                )
                
                if response_data and 'choices' in response_data and response_data['choices']:
                    ai_text = (response_data['choices'][0]['message']['content'] or "").strip()
                    return self._parse_date_response(ai_text)
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
            
            from .prompts import NewsPrompts
            prompt = NewsPrompts.find_full_article_link(content_sample, base_url)

            # Schema for structured output (Gemini)
            schema = {
                "type": "object",
                "properties": {
                    "link_found": {"type": "boolean"},
                    "full_article_url": {"type": ["string", "null"]},
                    "confidence": {"type": "number"}
                },
                "required": ["link_found", "full_article_url", "confidence"]
            }

            if self.supports_structured_output:
                # Use structured output for Gemini
                response_data = await self._make_structured_ai_request(
                    prompt,
                    model=self.summarization_model,
                    schema=schema,
                    analysis_type="full_article_link",
                    domain=base_url
                )
                result = response_data.get("result") or {}
                
                if result.get("link_found") and result.get("full_article_url"):
                    full_url = result.get("full_article_url", "").strip()
                    confidence = result.get("confidence", 0.0)
                    
                    if full_url and confidence >= 0.5:
                        from urllib.parse import urljoin, urlparse
                        # Make sure URL is absolute
                        if not full_url.startswith(('http://', 'https://')):
                            full_url = urljoin(base_url, full_url)
                        
                        # Validate URL format
                        parsed = urlparse(full_url)
                        if parsed.scheme and parsed.netloc:
                            print(f"  ✅ AI found full article link: {full_url} (confidence: {confidence:.2f})")
                            return full_url
                        else:
                            print(f"  ⚠️ Invalid URL from AI: {full_url}")
                            return None
                return None
            else:
                # Fallback for Constructor: use raw request and parse
                response_data = await self._make_raw_ai_request(
                    prompt,
                    model=self.summarization_model,
                    analysis_type="full_article_link",
                    domain=base_url
                )
                
                if response_data and 'choices' in response_data and response_data['choices']:
                    ai_text = (response_data['choices'][0]['message']['content'] or "").strip()
                    return self._parse_link_response(ai_text, base_url)
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

            # Use unified API for digest generation with higher temperature for creativity
            response_data = await self._make_raw_ai_request(
                prompt,
                model=self.digest_model,
                analysis_type="digest_generation",
                domain="digest",
                temperature=0.4,  # Higher temperature for more creative digest
                max_tokens=1500
            )
            
            if response_data and 'choices' in response_data and response_data['choices']:
                digest = (response_data['choices'][0]['message']['content'] or "").strip()
                return digest
            else:
                print(f"  ⚠️ No choices in digest API response")
                return None
        
        except APIError:
            raise
        except Exception as e:
            print(f"  ⚠️ Error generating digest: {e}")
            raise APIError(f"Failed to generate digest: {e}")
    
    async def _make_raw_ai_request(self, prompt: str, model: str = None,
                                    analysis_type: str = "combined_analysis",
                                    domain: str = "unknown",
                                    temperature: float = 0.1,
                                    max_tokens: int = 2000) -> dict:
        """
        Make raw AI API request for custom analysis.
        This method is provider-agnostic and always returns OpenAI-like response.

        Args:
            prompt: Raw prompt text
            model: Model to use (defaults to summarization_model)
            analysis_type: Type of analysis for tracking
            domain: Domain being analyzed for tracking
            temperature: Temperature for generation (default: 0.1)
            max_tokens: Maximum tokens to generate (default: 2000)

        Returns:
            OpenAI-like response dict with 'choices' and 'usage'
        """
        if not model:
            model = self.summarization_model

        if self.provider == "constructor":
            return await self._make_constructor_request(prompt, model, analysis_type, domain, temperature, max_tokens)
        elif self.provider == "gemini":
            return await self._make_gemini_request(prompt, model, analysis_type, domain, temperature, max_tokens)
        else:
            raise APIError(f"Unsupported AI provider: {self.provider}")
    
    async def _make_constructor_request(self, prompt: str, model: str,
                                        analysis_type: str, domain: str,
                                        temperature: float = 0.1, max_tokens: int = 2000) -> dict:
        """Make request to Constructor KM API (OpenAI-compatible)."""
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "max_tokens": max_tokens,
            "temperature": temperature
        }

        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'X-KM-AccessKey': self.api_key
        }

        print(f"  🌐 Constructor API endpoint: {self.endpoint}")
        print(f"  🤖 Model: {model}")
        print(f"  📊 Analysis type: {analysis_type}")
        print(f"  🏷️ Domain: {domain}")
        print(f"  📝 Prompt length: {len(prompt)} chars")

        async with get_http_client() as client:
            response = await client.post(str(self.endpoint), json=payload, headers=headers)

            async with response:
                if response.status == 200:
                    response_text = await response.text()
                    print(f"  📄 Response length: {len(response_text)} chars")

                    if not response_text or not response_text.strip():
                        raise APIError("Empty response from API", status_code=200, response_text="")

                    data = None
                    last_error = None

                    try:
                        data = json.loads(response_text)
                        print(f"  ✅ Raw JSON parsed successfully")
                    except json.JSONDecodeError as e:
                        last_error = e

                    if data is None:
                        try:
                            json_str = self._extract_json_from_response(response_text)
                            data = json.loads(json_str)
                            print(f"  ✅ Markdown-wrapped JSON parsed successfully")
                        except json.JSONDecodeError as e:
                            last_error = e

                    if data is None:
                        raise APIError(
                            f"Invalid JSON response from API: {last_error}",
                            status_code=200,
                            response_text=response_text
                        )

                    self._track_ai_usage(data, analysis_type, domain)
                    return data
                elif response.status == 429:
                    raise APIError("Rate limit exceeded", status_code=429)
                else:
                    error_text = await response.text()
                    print(f"  ❌ Constructor API error {response.status}: {error_text[:500]}...")
                    raise APIError(
                        f"Constructor API error: {response.status}",
                        status_code=response.status,
                        response_text=error_text
                    )
    
    def _normalize_gemini_usage(self, raw: dict) -> dict:
        """Normalize Gemini usage metadata to OpenAI-like token keys."""
        usage_meta = raw.get("usageMetadata") or {}
        prompt_tokens = usage_meta.get("promptTokenCount", 0)
        completion_tokens = usage_meta.get("candidatesTokenCount", 0)
        cached_tokens = usage_meta.get("cachedContentTokenCount", 0)
        total_tokens = usage_meta.get("totalTokenCount")

        if total_tokens is None:
            total_tokens = prompt_tokens + completion_tokens + cached_tokens

        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cached_tokens": cached_tokens,
            "total_tokens": total_tokens or 0,
        }

    async def _make_gemini_request(self, prompt: str, model: str,
                                   analysis_type: str, domain: str,
                                   temperature: float = 0.1, max_tokens: int = 2000) -> dict:
        """Make request to Gemini API and adapt response to OpenAI-like structure."""
        # Check if model is Gemini 3 (contains "gemini-3")
        is_gemini_3 = "gemini-3" in model.lower()
        
        # Use v1beta endpoint for Gemini 3, v1 for others
        if is_gemini_3:
            endpoint_base = str(self.endpoint).replace("/v1/models", "/v1beta/models")
            url = f"{endpoint_base}/{model}:generateContent"
        else:
            url = f"{self.endpoint}/{model}:generateContent"

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": prompt}
                    ]
                }
            ],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            }
        }

        params = {"key": self.api_key}

        print(f"  🌐 Gemini endpoint: {url}")
        print(f"  🤖 Gemini model: {model}")
        print(f"  📊 Analysis type: {analysis_type}")
        print(f"  🏷️ Domain: {domain}")
        print(f"  📝 Prompt length: {len(prompt)} chars")

        async with get_http_client() as client:
            response = await client.post(url, json=payload, params=params, timeout=30)

            async with response:
                if response.status == 200:
                    raw = await response.json()
                    print(f"  📄 Gemini raw response keys: {list(raw.keys())}")

                    candidates = raw.get("candidates") or []
                    if not candidates:
                        raise APIError(
                            "Empty Gemini response",
                            status_code=200,
                            response_text=json.dumps(raw)[:500]
                        )

                    first = candidates[0]
                    content = first.get("content") or {}
                    parts = content.get("parts") or []
                    text = ""
                    if parts:
                        text = (parts[0].get("text") or "").strip()

                    usage = self._normalize_gemini_usage(raw)

                    # Adapt to OpenAI-like structure
                    data = {
                        "choices": [
                            {
                                "message": {
                                    "content": text
                                }
                            }
                        ],
                        "usage": usage
                    }

                    self._track_ai_usage(data, analysis_type, domain)
                    return data
                elif response.status == 429:
                    raise APIError("Rate limit exceeded", status_code=429)
                else:
                    error_text = await response.text()
                    print(f"  ❌ Gemini API error {response.status}: {error_text[:500]}...")
                    raise APIError(
                        f"Gemini API error: {response.status}",
                        status_code=response.status,
                        response_text=error_text
                    )
    
    async def _make_structured_ai_request(self, prompt: str, model: str, schema: dict,
                                          analysis_type: str, domain: str) -> dict:
        """
        Make structured AI request. For Gemini uses native structured output,
        for other providers falls back to raw text + JSON parsing.

        Args:
            prompt: Prompt text
            model: Model to use
            schema: JSON schema for structured output (Gemini only)
            analysis_type: Type of analysis for tracking
            domain: Domain being analyzed for tracking

        Returns:
            Dict with 'result' (parsed structured data) and 'usage'
        """
        if self.provider == "gemini":
            # Check if model is Gemini 3 (contains "gemini-3")
            is_gemini_3 = "gemini-3" in model.lower()
            
            # Use v1beta endpoint for Gemini 3, v1 for others
            # See: https://ai.google.dev/gemini-api/docs/gemini-3
            if is_gemini_3:
                # Replace /v1/models with /v1beta/models for Gemini 3
                endpoint_base = str(self.endpoint).replace("/v1/models", "/v1beta/models")
                url = f"{endpoint_base}/{model}:generateContent"
            else:
                url = f"{self.endpoint}/{model}:generateContent"

            # Build payload - structured output params always go in generationConfig
            # According to: https://ai.google.dev/gemini-api/docs/structured-output?example=recipe
            payload = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {"text": prompt}
                        ]
                    }
                ],
                "generationConfig": {
                    "temperature": 0.1,
                    "maxOutputTokens": 2000,
                    "responseMimeType": "application/json",
                    "responseJsonSchema": schema
                }
            }

            params = {"key": self.api_key}

            print(f"  🌐 Gemini structured endpoint: {url}")
            print(f"  🤖 Model: {model}")
            print(f"  📊 Analysis type: {analysis_type}")
            print(f"  🏷️ Domain: {domain}")
            print(f"  📋 Using structured output with schema")
            print(f"  🔍 Is Gemini 3: {is_gemini_3}")
            print(f"  📝 Payload generationConfig keys: {list(payload['generationConfig'].keys())}")

            async with get_http_client() as client:
                response = await client.post(url, json=payload, params=params, timeout=40)

                async with response:
                    if response.status == 200:
                        raw = await response.json()

                        candidates = raw.get("candidates") or []
                        if not candidates:
                            raise APIError(
                                "Empty Gemini response",
                                status_code=200,
                                response_text=str(raw)[:500]
                            )

                        first = candidates[0]
                        content = first.get("content") or {}
                        parts = content.get("parts") or []

                        if not parts or "text" not in parts[0]:
                            raise APIError(
                                "Gemini structured response missing text",
                                status_code=200,
                                response_text=str(raw)[:500]
                            )

                        # Text should already be valid JSON according to schema
                        text_response = parts[0]["text"].strip()
                        try:
                            structured = json.loads(text_response)
                        except json.JSONDecodeError as e:
                            print(f"  ⚠️ Failed to parse JSON from Gemini structured response: {e}")
                            print(f"  📄 Response preview: {text_response[:500]}...")
                            # Fallback: try to extract JSON from markdown if needed
                            try:
                                json_str = self._extract_json_from_response(text_response)
                                structured = json.loads(json_str)
                                print(f"  ✅ Extracted JSON from markdown code block")
                            except Exception as e2:
                                raise APIError(
                                    f"Failed to parse JSON from Gemini structured response: {e2}",
                                    status_code=200,
                                    response_text=text_response[:500]
                                )

                        usage = self._normalize_gemini_usage(raw)

                        data = {
                            "result": structured,
                            "usage": usage
                        }

                        self._track_ai_usage(data, analysis_type, domain)
                        return data

                    elif response.status == 429:
                        raise APIError("Rate limit exceeded", status_code=429)
                    else:
                        error_text = await response.text()
                        print(f"  ❌ Gemini API error {response.status}: {error_text[:500]}...")
                        raise APIError(
                            f"Gemini API error: {response.status}",
                            status_code=response.status,
                            response_text=error_text
                        )

        # Fallback: provider without structured output (Constructor)
        raw_data = await self._make_raw_ai_request(
            prompt,
            model=model,
            analysis_type=analysis_type,
            domain=domain
        )

        # Expect text in choices[0].message.content and parse JSON
        text = ""
        if raw_data and "choices" in raw_data and raw_data["choices"]:
            text = (raw_data["choices"][0]["message"]["content"] or "").strip()

        try:
            json_str = self._extract_json_from_response(text)
            structured = json.loads(json_str)
        except Exception as e:
            raise APIError(
                f"Failed to parse structured JSON from provider text response: {e}",
                status_code=200,
                response_text=text[:500]
            )

        raw_data["result"] = structured
        return raw_data

    def _track_ai_usage(self, response_data: dict, analysis_type: str, domain: str):
        """Track AI API usage to database (fire-and-forget)."""
        import asyncio

        async def _do_track():
            try:
                # Extract token usage from response
                usage = response_data.get('usage', {})
                tokens_used = usage.get('total_tokens')
                prompt_tokens = usage.get('prompt_tokens', 0)
                completion_tokens = usage.get('completion_tokens', 0)
                cached_tokens = usage.get('cached_tokens', 0)

                if not tokens_used:
                    tokens_used = prompt_tokens + completion_tokens

                # Cost from config (per 1M tokens); defaults to 0 if not configured
                input_rate = getattr(settings, 'ai_input_cost_per_1m', None) or 0.0
                output_rate = getattr(settings, 'ai_output_cost_per_1m', None) or 0.0
                cached_input_rate = getattr(settings, 'ai_cached_input_cost_per_1m', None) or 0.0

                cost = (
                    (prompt_tokens * input_rate) +
                    (completion_tokens * output_rate) +
                    (cached_tokens * cached_input_rate)
                ) / 1_000_000

                from ..database import AsyncSessionLocal
                from sqlalchemy import text
                from datetime import datetime

                async with AsyncSessionLocal() as session:
                    await session.execute(
                        text("""
                            INSERT INTO ai_usage_tracking
                            (domain, analysis_type, tokens_used, credits_cost, analysis_result, created_at)
                            VALUES (:domain, :analysis_type, :tokens_used, :cost, :result, :created_at)
                        """),
                        {
                            "domain": domain,
                            "analysis_type": analysis_type,
                            "tokens_used": tokens_used,
                            "cost": cost,
                            "result": json.dumps(
                                {
                                    "prompt_tokens": prompt_tokens,
                                    "completion_tokens": completion_tokens,
                                    "cached_tokens": cached_tokens
                                }
                            ),
                            "created_at": datetime.utcnow()
                        }
                    )
                    await session.commit()
            except Exception as e:
                # Don't fail the request if tracking fails
                print(f"  ⚠️ Failed to track AI usage: {e}")

        # Fire and forget - don't block the main request
        asyncio.create_task(_do_track())
    
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

    async def _call_summary_llm(self, prompt: str, *, system_prompt: str | None = None,
                                max_tokens: int = 1000) -> Optional[str]:
        # Build full prompt with system message if provided
        full_prompt = prompt
        if system_prompt:
            full_prompt = f"{system_prompt}\n\n{prompt}"

        print(f"  🤖 Sending to AI for summarization...")
        
        # Use unified API with appropriate parameters for summarization
        response_data = await self._make_raw_ai_request(
            full_prompt,
            model=self.summarization_model,
            analysis_type="summary",
            domain="summary",
            temperature=0.2,  # Slightly higher for summarization
            max_tokens=max_tokens
        )
        
        if response_data and 'choices' in response_data and response_data['choices']:
            return (response_data['choices'][0]['message']['content'] or '').strip()
        return None

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
            # Special case for scientific sources: allow analysis of informative titles
            is_scientific_source = url and any(domain in url.lower() for domain in ['nplus1.ru', 'arxiv.org', 'nature.com', 'sciencedirect.com'])
            
            if is_scientific_source and title and len(title.strip()) > 20:
                print(f"  🧬 Scientific source detected - analyzing informative title: '{title[:50]}...'")
                # Use title as content for analysis
                content = title
            else:
                print(f"  ⚠️ Content too short for analysis: {len(content.strip()) if content else 0} chars < 30")
                return self._get_fallback_analysis()
        
        max_retries = 3
        for attempt in range(max_retries + 1):
            try:
                # Build enhanced combined prompt with dynamic category metadata
                prompt = await self._build_combined_analysis_prompt_enhanced(title, content, url)
                print(f"  🚀 Using enhanced prompt with category metadata")
                
                retry_text = f" (attempt {attempt + 1}/{max_retries + 1})" if attempt > 0 else ""
                print(f"  🧠 Combined AI analysis for article{retry_text}...")
                print(f"  📄 Content length: {len(content)} characters")
                print(f"  📝 Title: {title[:100]}...")

                # Extract domain for tracking
                from urllib.parse import urlparse
                domain = urlparse(url).netloc if url else "unknown"

                # JSON schema for structured output
                schema = {
                    "type": "object",
                    "properties": {
                        "optimized_title": {"type": ["string", "null"]},
                        "summary": {"type": ["string", "null"]},
                        "categories": {
                            "type": "array",
                            "items": {"type": "string"}
                        },
                        "category_confidences": {
                            "type": "array",
                            "items": {"type": "number"}
                        },
                        "category": {"type": ["string", "null"]},
                        "category_confidence": {"type": "number"},
                        "summary_confidence": {"type": "number"},
                        "original_categories": {
                            "type": "array",
                            "items": {"type": "string"}
                        },
                        "is_advertisement": {"type": "boolean"},
                        "ad_type": {"type": "string"},
                        "ad_confidence": {"type": "number"},
                        "ad_reasoning": {"type": "string"},
                        "publication_date": {"type": ["string", "null"]},
                        "content_quality": {"type": "number"},
                        "confidence": {"type": "number"}
                    },
                    "required": ["summary", "categories", "is_advertisement"],
                    "additionalProperties": True
                }

                if self.supports_structured_output:
                    # Gemini: use structured output for guaranteed JSON
                    response_data = await self._make_structured_ai_request(
                        prompt,
                        model=self.summarization_model,
                        schema=schema,
                        analysis_type="combined_analysis",
                        domain=domain
                    )
                    result = response_data.get("result") or {}
                    print(f"  ✅ Combined analysis (structured) successful")
                    return self._validate_analysis_result(result, title, content)

                # Constructor / other: fallback to text parsing
                response_data = await self._make_raw_ai_request(
                    prompt,
                    analysis_type="combined_analysis",
                    domain=domain
                )
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
                
                # Parse JSON response - extract from markdown code block if needed
                try:
                    json_str = self._extract_json_from_response(response)
                    result = json.loads(json_str)
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

    def _extract_json_from_response(self, response: str) -> str:
        """Extract JSON from AI response, handling markdown code blocks."""
        if not response:
            return '{}'

        text = response.strip()

        # Handle markdown code block: ```json ... ``` or ``` ... ```
        import re
        code_block_match = re.search(r'```(?:json)?\s*\n?([\s\S]*?)\n?```', text)
        if code_block_match:
            text = code_block_match.group(1).strip()

        # Try to find JSON object boundaries if not clean
        if not text.startswith('{'):
            # Find first { and last }
            start_idx = text.find('{')
            end_idx = text.rfind('}')
            if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                text = text[start_idx:end_idx + 1]

        return text

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
