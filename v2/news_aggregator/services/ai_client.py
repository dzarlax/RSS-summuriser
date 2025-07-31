"""AI API client for article summarization using Constructor KM."""

import json
from typing import Optional

from ..config import settings
from ..core.http_client import get_http_client
from ..core.cache import cached
from ..core.exceptions import APIError
from .content_integration import get_content_service


class AIClient:
    """Client for AI summarization using Constructor KM API."""
    
    def __init__(self):
        # Use Constructor KM API for everything
        self.endpoint = getattr(settings, 'constructor_km_api', None)
        self.api_key = getattr(settings, 'constructor_km_api_key', None)
        self.summarization_model = getattr(settings, 'model', 'gpt-4o-mini')
        
        if not self.endpoint or not self.api_key:
            raise APIError("Constructor KM API endpoint and key must be configured")
        
        self.enabled = True
        
        self.content_service = None
    
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
            # Step 1: Extract article content using enhanced extractor
            if not self.content_service:
                self.content_service = await get_content_service()
            
            content = await self.content_service.extract_content(article_url)
            if not content:
                print(f"  ⚠️ Could not extract content from {article_url}")
                return None
            
            content_length = len(content)
            print(f"  📝 Extracted content: {content_length} characters")
            
            # Step 2: Summarize with Constructor KM API using 4.1-mini
            print(f"  🤖 Sending to AI for summarization...")
            prompt = f"""Пожалуйста, создайте краткое содержание этой статьи на русском языке. 
Выделите основные тезисы в виде списка пунктов. Сохраните важную информацию, но сделайте текст более сжатым.

Статья:
{content}"""

            payload = {
                "model": self.summarization_model,
                "messages": [
                    {
                        "role": "user", 
                        "content": prompt
                    }
                ],
                "max_tokens": 1000,
                "temperature": 0.3
            }
            
            headers = {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'X-KM-AccessKey': self.api_key
            }
            
            async with get_http_client() as client:
                print(f"  🌐 Making API request to {self.endpoint}")
                response = await client.post(
                    str(self.endpoint),
                    json=payload,
                    headers=headers
                )
                
                async with response:
                    print(f"  📡 API response status: {response.status}")
                    if response.status == 200:
                        data = await response.json()
                        if 'choices' in data and data['choices']:
                            summary = data['choices'][0]['message']['content'].strip()
                            summary_length = len(summary)
                            print(f"  ✅ AI summarization successful: {summary_length} characters")
                            return summary
                        else:
                            print(f"  ⚠️ No choices in API response for {article_url}")
                            return None
                    elif response.status == 429:
                        print(f"  ⏰ Rate limit exceeded for {article_url}")
                        raise APIError("Rate limit exceeded", status_code=429)
                    else:
                        error_text = await response.text()
                        print(f"  ❌ API error {response.status} for {article_url}: {error_text}")
                        raise APIError(
                            f"API error: {response.status}",
                            status_code=response.status,
                            response_text=error_text
                        )
        
        except APIError:
            raise
        except Exception as e:
            print(f"  ⚠️ Error getting summary for {article_url}: {e}")
            raise APIError(f"Failed to get summary for {article_url}: {e}")
    
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
                "model": "gpt-4.1",  # Full model for final digest
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