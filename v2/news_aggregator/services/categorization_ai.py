"""AI client for universal news categorization and digest generation."""

import logging
from typing import List, Dict, Any, Optional

from ..config import settings
from ..core.http_client import get_http_client
from ..core.cache import cached
from ..core.exceptions import APIError


class CategorizationAI:
    """Universal AI client for news categorization and processing."""
    
    def __init__(self):
        # Load AI configuration
        self.api_url = self._get_config("CONSTRUCTOR_KM_API")
        self.api_key = self._get_config("CONSTRUCTOR_KM_API_KEY") 
        # Use specific categorization model or fallback to general MODEL
        self.model = self._get_config("CATEGORIZATION_MODEL") or self._get_config("MODEL")
        
        if not all([self.api_url, self.api_key, self.model]):
            raise APIError("Categorization AI configuration incomplete")
        
        # Rate limiting - не более 10 запросов в минуту
        import asyncio
        self._last_request_time = 0
        self._min_interval = 6  # 6 секунд между запросами (10 req/min)
    
    def _get_config(self, key: str) -> Optional[str]:
        """Get config value with fallback to settings."""
        # Try legacy format first for compatibility
        if hasattr(settings, 'get_legacy_config'):
            value = settings.get_legacy_config(key)
            if value:
                return value
        
        # Try direct from environment
        import os
        return os.getenv(key)
    
    def _get_categories(self) -> set:
        """Get valid categories from environment configuration."""
        categories_str = self._get_config("NEWS_CATEGORIES")
        if categories_str:
            # Split by comma and clean whitespace
            categories = [cat.strip() for cat in categories_str.split(",") if cat.strip()]
            return set(categories)
        # Fallback to default categories
        return {"Business", "Tech", "Science", "Nature", "Serbia", "Marketing", "Other"}
    
    def _get_default_category(self) -> str:
        """Get default category from environment configuration."""
        return self._get_config("DEFAULT_CATEGORY") or "Other"
    
    @cached(ttl=3600, key_prefix="article_category")
    async def categorize_article(self, title: str, description: str) -> str:
        """
        Categorize article into one of predefined categories.
        
        Args:
            title: Article title
            description: Article description
            
        Returns:
            Category name (Business, Tech, Science, Nature, Serbia, Marketing, Other)
        """
        print(f"    🏷️ Starting AI categorization...")
        print(f"    📝 Title: {title[:100]}{'...' if len(title) > 100 else ''}")
        
        # Clean and prepare content
        content = self._clean_html(f"{title} {description}")
        content_length = len(content)
        print(f"    📄 Content length: {content_length} characters")
        
        # Get categories from configuration
        valid_categories = self._get_categories()
        categories_list = ", ".join(sorted(valid_categories))
        
        prompt = (
            f"Choose one of the provided categories and answer with one word "
            f"({categories_list}) for the article: "
            + content
        )
        
        try:
            print(f"    🤖 Sending categorization request to AI...")
            response = await self._make_ai_request(prompt)
            print(f"    📡 AI response: '{response}'")
            
            # Extract first word and clean it
            if response and response != "Error":
                first_word = response.split()[0] if response.split() else self._get_default_category()
                cleaned_category = ''.join(c for c in first_word if c.isalpha())
                
                # Validate category
                valid_categories = self._get_categories()
                final_category = cleaned_category if cleaned_category in valid_categories else self._get_default_category()
                print(f"    ✅ Final category: '{final_category}' (from: '{cleaned_category}')")
                return final_category
            
            default_category = self._get_default_category()
            print(f"    ⚠️ Empty or error response, using default category: '{default_category}'")
            return default_category
            
        except Exception as e:
            print(f"    ❌ Category classification failed: {e}")
            logging.warning(f"Category classification failed: {e}")
            return self._get_default_category()
    
    async def generate_daily_digest(self, articles_by_category: Dict[str, List], 
                                  message_part: Optional[int] = None) -> str:
        """
        Generate daily news digest for Telegram.
        
        Args:
            articles_by_category: Dict mapping categories to list of articles
            message_part: Optional part number for split messages
            
        Returns:
            HTML formatted digest
        """
        total_articles = sum(len(articles) for articles in articles_by_category.values())
        categories_count = len(articles_by_category)
        
        # Header based on message part
        if message_part == 1:
            header_text = "Сводка новостей (часть 1)"
        elif message_part == 2:
            header_text = "Сводка новостей (часть 2)" 
        else:
            header_text = "Сводка новостей"
        
        # Character limit based on message splitting
        char_limit = 3400 if message_part else 2600
        
        prompt = self._build_digest_prompt(
            articles_by_category, 
            header_text, 
            char_limit, 
            total_articles, 
            categories_count
        )
        
        try:
            digest = await self._make_ai_request(prompt)
            
            if not digest or digest == "Error":
                # Fallback to simple digest
                return self._create_fallback_digest(articles_by_category, header_text)
            
            # Post-process to convert lists to narrative
            digest = self._convert_lists_to_narrative(digest)
            
            # Validate HTML for Telegram
            from ..utils.html_utils import validate_telegram_html
            validated_digest = validate_telegram_html(digest)
            
            if not validated_digest or len(validated_digest.strip()) < 10:
                return self._create_fallback_digest(articles_by_category, header_text)
            
            return validated_digest
            
        except Exception as e:
            logging.error(f"Digest generation failed: {e}")
            return self._create_fallback_digest(articles_by_category, header_text)
    
    def _build_digest_prompt(self, articles_by_category: Dict[str, List], 
                           header_text: str, char_limit: int, 
                           total_articles: int, categories_count: int) -> str:
        """Build prompt for digest generation."""
        
        # Build example format using actual categories with articles
        format_examples = []
        example_categories = list(articles_by_category.keys())[:2]  # Use first 2 actual categories
        
        if 'Tech' in example_categories or 'Science' in example_categories:
            format_examples.append("<b>Tech</b>\\nApple выпустила новый iPhone. Tesla показала рост продаж. Microsoft анонсировал ИИ-решения.\\n")
        elif 'Business' in example_categories:
            format_examples.append("<b>Business</b>\\nРынки выросли на 2%. Компании отчитались о прибыли.\\n")
        elif 'Nature' in example_categories or 'Science' in example_categories:
            format_examples.append("<b>Science</b>\\nУченые открыли новый вид животных. Климатические изменения влияют на экосистемы.\\n")
        else:
            # Use actual category names for examples
            for cat in example_categories:
                if cat == 'Serbia':
                    format_examples.append(f"<b>{cat}</b>\\nПолитические события в регионе. Экономические новости страны.\\n")
                elif cat == 'Other':
                    format_examples.append(f"<b>{cat}</b>\\nРазличные события дня. Социальные и культурные новости.\\n")
                else:
                    format_examples.append(f"<b>{cat}</b>\\nОсновные события категории. Важные обновления и новости.\\n")
        
        format_example = "\\n".join(format_examples)
        
        prompt = (
            f"Ты - журналист. Создай СЖАТО сводку новостей в HTML.\\n\\n"
            f"{total_articles} новостей в {categories_count} категориях.\\n\\n"
            f"ТРЕБОВАНИЯ:\\n"
            f"- HTML с <b></b> для заголовков\\n" 
            f"- Связные абзацы (НЕ списки!)\\n"
            f"- МАКСИМУМ {char_limit} символов\\n"
            f"- ТОЛЬКО категории с новостями (не добавляй пустые)\\n"
            f"- Охвати основные события по категориям\\n\\n"
            f"ФОРМАТ:\\n"
            f"<b>{header_text}</b>\\n\\n"
            f"{format_example}\\n"
            f"ЗАДАЧА: Сжатые связные абзацы ТОЛЬКО для категорий с новостями!\\n\\n"
            f"НОВОСТИ:\\n\\n"
        )
        
        # Add news data by category
        for category, articles in articles_by_category.items():
            prompt += f"\\n=== {category} ===\\n"
            for article in articles:
                prompt += f"ЗАГОЛОВОК: {article['headline']}\\n"
                if article.get('description'):
                    # Truncate description
                    description = article['description'][:500]
                    if len(article['description']) > 500:
                        description += "..."
                    prompt += f"ОПИСАНИЕ: {description}\\n"
                prompt += "---\\n"
        
        prompt += (
            "\\n\\nПРАВИЛА:\\n"
            "✅ НЕ СПИСКИ! Только связные предложения!\\n"
            "✅ НЕ используй: - • * 1. 2.\\n"
            f"✅ МАКСИМУМ {char_limit} символов - соблюдай лимит!\\n"
            f"✅ Начинай с <b>{header_text}</b>\\n"
            "✅ HTML только <b></b>\\n\\n"
            f"ВАЖНО: Не превышай {char_limit} символов!"
        )
        
        return prompt
    
    async def _make_ai_request(self, prompt: str) -> str:
        """Make request to AI API with retry and timeout."""
        import asyncio
        from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
        
        print(f"      🌐 Preparing AI request to {self.api_url}")
        print(f"      📏 Prompt length: {len(prompt)} characters")
        
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json", 
            "X-KM-AccessKey": self.api_key
        }
        
        data = {
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                    "name": "categorization_request"
                }
            ],
            "model": self.model
        }
        
        @retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=2, min=4, max=30),
            retry=retry_if_exception_type((Exception,))
        )
        async def make_request_with_retry():
            # Rate limiting - wait if needed
            import time
            current_time = time.time()
            time_since_last = current_time - self._last_request_time
            if time_since_last < self._min_interval:
                wait_time = self._min_interval - time_since_last
                print(f"      ⏰ Rate limiting: waiting {wait_time:.1f}s before AI request")
                logging.info(f"Rate limiting: waiting {wait_time:.1f}s before AI request")
                await asyncio.sleep(wait_time)
            
            self._last_request_time = time.time()
            
            try:
                # Add request timeout
                timeout = 30  # 30 seconds timeout
                print(f"      📡 Making HTTP request to AI API...")
                async with get_http_client() as client:
                    response = await asyncio.wait_for(
                        client.post(self.api_url, json=data, headers=headers),
                        timeout=timeout
                    )
                    
                    async with response:
                        print(f"      📊 Response status: {response.status}")
                        if response.status == 200:
                            response_data = await response.json()
                            content = response_data["choices"][0]["message"]["content"]
                            print(f"      ✅ AI response successful: {len(content)} characters")
                            return content
                        elif response.status in [503, 502, 504]:  # Server errors - retry
                            print(f"      🔄 Server error {response.status}, will retry")
                            raise Exception(f"Server error {response.status}, will retry")
                        else:
                            error_text = await response.text()
                            print(f"      ❌ API error {response.status}: {error_text}")
                            logging.error(f"Categorization AI API error {response.status}: {error_text}")
                            return "Error"
                            
            except asyncio.TimeoutError:
                logging.warning("AI API request timeout, will retry")
                raise Exception("Request timeout")
            except Exception as e:
                logging.warning(f"AI API request failed: {e}, will retry")
                raise
        
        try:
            return await make_request_with_retry()
        except Exception as e:
            logging.error(f"All AI API retry attempts failed: {e}")
            return "Error"
    
    def _clean_html(self, html_text: str, max_length: int = 1000) -> str:
        """Clean HTML content for AI processing."""
        from bs4 import BeautifulSoup
        
        soup = BeautifulSoup(html_text, "html.parser")
        clean_text = soup.get_text(separator=' ')
        
        if len(clean_text) > max_length:
            clean_text = clean_text[:max_length]
            
        return clean_text
    
    def _convert_lists_to_narrative(self, text: str) -> str:
        """Convert list items to narrative text."""
        if not text:
            return text
        
        lines = text.split('\\n')
        result_lines = []
        current_section = []
        current_category = None
        
        for line in lines:
            stripped = line.strip()
            
            # Check if this is a category header
            if stripped.startswith('<b>') and stripped.endswith('</b>'):
                # Convert accumulated section to narrative
                if current_section and current_category:
                    narrative = self._convert_section_to_narrative(current_section)
                    result_lines.append(narrative)
                    current_section = []
                
                current_category = stripped
                result_lines.append(line)
            
            # Check if this is a list item
            elif stripped.startswith(('- ', '• ', '* ')) or (len(stripped) > 2 and stripped[1:3] in ['. ', ') ']):
                # Clean list item
                clean_item = stripped
                for marker in ['- ', '• ', '* ']:
                    if clean_item.startswith(marker):
                        clean_item = clean_item[len(marker):].strip()
                        break
                
                if clean_item:
                    current_section.append(clean_item)
            else:
                # Regular line
                if current_section and current_category:
                    narrative = self._convert_section_to_narrative(current_section)
                    result_lines.append(narrative)
                    current_section = []
                
                result_lines.append(line)
        
        # Handle remaining section
        if current_section and current_category:
            narrative = self._convert_section_to_narrative(current_section)
            result_lines.append(narrative)
        
        return '\\n'.join(result_lines)
    
    def _convert_section_to_narrative(self, items: List[str]) -> str:
        """Convert list items to narrative text."""
        if not items:
            return ""
        
        if len(items) == 1:
            return items[0]
        
        connectors = ["Также", "Кроме того", "Дополнительно", "Более того"]
        narrative_parts = [items[0]]
        
        for i, item in enumerate(items[1:], 1):
            connector = connectors[min(i-1, len(connectors)-1)]
            narrative_parts.append(f"{connector.lower()} {item.lower()}")
        
        return " ".join(narrative_parts) + "."
    
    def _create_fallback_digest(self, articles_by_category: Dict[str, List], 
                              header_text: str) -> str:
        """Create simple fallback digest."""
        import datetime
        
        fallback_parts = [f"<b>{header_text}</b>\\n"]
        
        for category, articles in articles_by_category.items():
            if not articles:
                continue
                
            fallback_parts.append(f"\\n<b>{category}</b>")
            
            # Create narrative from article headlines
            headlines = [article['headline'] for article in articles[:3]]  # Max 3
            
            if len(headlines) == 1:
                narrative = headlines[0] + "."
            else:
                narrative_parts = [headlines[0]]
                for i, headline in enumerate(headlines[1:], 1):
                    connector = "Также" if i == 1 else "Дополнительно"
                    narrative_parts.append(f"{connector.lower()} {headline.lower()}")
                narrative = ". ".join(narrative_parts) + "."
            
            fallback_parts.append(narrative)
        
        return "\\n".join(fallback_parts)


# Global Categorization AI instance
_categorization_ai: Optional[CategorizationAI] = None


def get_categorization_ai() -> CategorizationAI:
    """Get Categorization AI client instance."""
    global _categorization_ai
    
    if _categorization_ai is None:
        _categorization_ai = CategorizationAI()
    
    return _categorization_ai


# Legacy compatibility - keep old name for backward compatibility
TelegramAI = CategorizationAI

def get_telegram_ai() -> CategorizationAI:
    """Legacy function name - use get_categorization_ai() instead."""
    return get_categorization_ai()