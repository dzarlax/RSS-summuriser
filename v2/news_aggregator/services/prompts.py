"""
Centralized AI prompts for news aggregator system.

This module contains all AI prompts used throughout the application.
Centralizing prompts makes them easier to maintain, version, and improve.
"""

from typing import Dict, Any, Optional


class NewsPrompts:
    """Collection of all AI prompts for news processing."""
    
    # =============================================================================
    # DYNAMIC CATEGORY METADATA
    # =============================================================================
    
    @staticmethod
    async def get_available_categories():
        """Get available categories from database for prompt enhancement."""
        try:
            from ..database import AsyncSessionLocal
            from ..models import Category
            from sqlalchemy import select
            
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(Category.name, Category.display_name)
                    .order_by(Category.name)
                )
                categories = result.all()
                
                return [f"{name} ({display_name})" for name, display_name in categories]
                
        except Exception as e:
            # Fallback to default categories if database is unavailable
            return ['Business (Бизнес)', 'Tech (Технологии)', 'Science (Наука)', 'Serbia (Сербия)', 'Other (Прочее)']
    
    # =============================================================================
    # SHARED SUMMARIZATION RULES
    # =============================================================================
    
    @staticmethod
    def _get_summarization_rules(sentence_count: str = "5-6") -> str:
        """Get unified summarization rules used across different prompts."""
        return f"""
SUMMARIZATION REQUIREMENTS:
🚫 ЗАПРЕЩЕНО: ВЫДУМЫВАТЬ факты, добавлять информацию которой НЕТ в тексте, лить воду

📏 АДАПТИВНАЯ ДЛИНА на основе исходного текста:
- Длинный текст (>800 символов): {sentence_count} подробных предложений (200+ символов)
- Средний текст (300-800 символов): 3-4 предложения, сохраняя ВСЕ ключевые факты
- Короткий текст (<300 символов): 2-3 предложения, простой пересказ БЕЗ додумывания

📝 ПРАВИЛА ПЕРЕСКАЗА:
- ТОЧНО передавай ТОЛЬКО информацию из текста
- Не добавляй контекст, объяснения, предположения
- Не расширяй факты своими знаниями
- Структура: ЧТО произошло → ДЕТАЛИ из текста → РЕЗУЛЬТАТ/СЛЕДСТВИЯ (если есть в тексте)
- Сохраняй ВСЕ ключевые факты, числа, имена, даты из оригинала
- Избегай повтора заголовка, добавляй информацию из содержания
- Начинай сразу с сути (без "статья рассказывает о...")

🎯 ДЛЯ КОРОТКИХ ТЕКСТОВ:
- Если исходный текст короткий — НЕ растягивай искусственно
- Лучше краткий точный пересказ, чем длинный с выдумками
- Качество фактов важнее количества предложений"""
    
    @staticmethod
    def _get_professional_editor_system() -> str:
        """Get unified system prompt for professional news editing."""
        return """Ты профессиональный новостной редактор. 
Отвечай СТРОГО на русском языке, коротко и информативно. 
Запрещено копировать большие фрагменты исходного текста."""
    
    # =============================================================================
    # ARTICLE ANALYSIS PROMPTS (main processing)
    # =============================================================================
    
    @staticmethod
    async def unified_article_analysis_enhanced(title: str, content: str, url: str, 
                                               source_context: str = "from an UNKNOWN source") -> str:
        """
        Enhanced unified prompt that uses dynamic category list from database.
        """
        # Get available categories from database
        available_categories = await NewsPrompts.get_available_categories()
        category_names = [cat.split(' (')[0] for cat in available_categories]
        
        # Limit content size for cost optimization
        content_preview = content[:3500] + ("..." if len(content) > 3500 else "")
        
        return f"""Analyze this article and provide complete analysis in JSON format.

🇷🇺 ВАЖНО: ВСЕ результаты анализа должны быть на РУССКОМ языке!

ARTICLE INFORMATION:
Title: {title}
URL: {url}
Source: {source_context}
Content: {content_preview}

ANALYSIS TASKS:
1. TITLE OPTIMIZATION: Create clear, informative headline (max 120 characters for Telegram)
2. CATEGORIZATION: Choose from available categories below  
3. SUMMARIZATION: Create accurate summary in Russian - adapt length to content (see rules below)
4. ADVERTISEMENT DETECTION: Determine if content is promotional
5. DATE EXTRACTION: Find publication date if mentioned

AVAILABLE CATEGORIES: {', '.join(available_categories)}

CATEGORIZATION PROCESS:
1. FIRST - Create 1-2 specific descriptive categories (your own words)
2. THEN - Map to system categories: {', '.join(category_names)}
3. Include both recommended AND your improved descriptive categories in original_categories

CATEGORIZATION RULES:
- Use descriptive categories like: "financial_news", "technology_innovation", "political_analysis", etc.
- If you find better descriptive terms than standard ones, include them in original_categories
- Consider multiple categories if content spans domains (e.g., "Tech + Business" for fintech)
- Provide high confidence scores (0.8+) when categories match well

TITLE OPTIMIZATION RULES:
- ALWAYS provide optimized_title in RUSSIAN, regardless of source language
- Maximum 120 characters for Telegram readability
- Make title clear and informative
- Remove clickbait elements (BREAKING, TOP-5, etc.)
- Fix truncated titles (ending with "..." or incomplete)
- If original is already in Russian and good, you can use it as optimized_title

SUMMARIZATION:{NewsPrompts._get_summarization_rules("5-6")}

ADVERTISEMENT DETECTION:
🚨 CRITICAL: Tech/product announcements from NEWS SOURCES are NOT advertisements!

NEWS vs ADVERTISEMENT distinction:
✅ NEWS ARTICLES (is_advertisement: false):
- Product launches/releases reported by tech news sites
- Company announcements covered by journalism
- Industry analysis and reviews  
- Financial results and business updates
- Research findings and innovations
- Government/regulatory announcements

❌ ADVERTISEMENTS (is_advertisement: true):
- Direct sales offers ("купить", "заказать", "скидка")
- Promotional content with prices and deals
- Marketing materials from companies themselves
- Sponsored content clearly promoting services
- Event/webinar promotional announcements

KEY INDICATORS:
- NEWS source context (tech blogs, news sites) → likely NOT advertisement
- Journalistic tone vs promotional tone
- Third-party reporting vs first-party marketing
- Facts/analysis vs sales pitch

Promotional keywords: "купить", "заказать", "скидка", "акция", "распродажа", "цена от", "успей купить"
Business reporting keywords: "выпустила", "анонсировала", "представила", "запустила" (these are NEWS, not ads!)

DATE EXTRACTION:
Look for publication dates in content, ignore article dates.

OUTPUT FORMAT (JSON):
{{
    "optimized_title": "Краткий информативный заголовок новости",
    "original_categories": ["financial_news", "banking_sector", "investment_strategy"],
    "categories": ["Business"],
    "category_confidences": [0.95],
    "summary": "Краткий пересказ 5-6 предложений...",
    "summary_confidence": 0.90,
    "is_advertisement": false,
    "ad_type": "news_article",
    "ad_confidence": 0.1,
    "ad_reasoning": "Content focuses on news reporting...",
    "publication_date": "2024-01-15",
    "confidence": 0.85
}}

EXAMPLES:
- Single category: "categories": ["Business"], "category_confidences": [0.95]
- Multiple categories: "categories": ["Tech", "Business"], "category_confidences": [0.85, 0.75]  
- Enhanced original_categories: ["financial_analysis", "fintech_innovation", "investment_strategy"]

Answer ONLY with valid JSON, no additional text."""

    
    # Note: article_summarization() and article_summarization_system() removed
    # All summarization now uses unified_article_analysis_enhanced() with retry logic
    
    # =============================================================================
    # CATEGORY SUMMARY GENERATION (only needed for individual categories)
    # =============================================================================
    
    @staticmethod
    def category_summary(category: str, articles_text: str) -> str:
        """
        Category-specific summary generation for daily digest.
        
        Used by: Orchestrator._generate_and_save_daily_summaries()
        
        NOTE: This summary will be combined with other categories in Telegram digest
        without additional AI processing - see Orchestrator._create_combined_digest()
        """
        return f"""Ты - новостной аналитик. Создай обзор ВСЕХ новостей категории {category} за день.

🎯 ЗАДАЧА: Обозреть ВСЕ значимые новости категории {category} в едином связном тексте
📏 ЛИМИТ: Максимум 850 символов (для объединения с другими категориями в телеграм)
📝 КОНТЕКСТ: Эта сводка будет частью общего дайджеста с другими категориями

ТРЕБОВАНИЯ:
- Единый связный текст, охватывающий ВСЕ важные новости дня
- Логическая структура: от главных событий к менее значимым
- Связки между событиями через контекст и причинно-следственные связи
- Живой журналистский язык с профессиональными переходами
- Используй: "На фоне этого", "В то же время", "Кроме того", "По данным"

🚫 НЕ ИСПОЛЬЗУЙ:
- Списки и перечисления (•, -, 1., 2.)
- Отдельные абзацы для каждой новости
- Фразы типа "в категории произошло", "среди новостей дня"

НОВОСТИ ЗА ДЕНЬ:
{articles_text}

Создай целостный обзор всех новостей категории {category} одним связным текстом:"""
    
    # Note: simple_categorization() removed - all categorization now uses 
    # unified_article_analysis_enhanced() with retry logic
    
    # Note: deprecated_telegram_digest() removed - TelegramAI.generate_daily_digest() 
    # was replaced by Orchestrator._create_combined_digest() which combines pre-generated summaries


class PromptBuilder:
    """Helper class for building prompts with dynamic parameters."""
    
    @staticmethod
    def build_source_context(url: str, news_domains: Optional[list] = None) -> str:
        """Build source context string based on URL."""
        if news_domains is None:
            news_domains = [
                'balkaninsight.com', 'biznis.rs', 'rts.rs', 'b92.net', 
                'politika.rs', 'blic.rs', 'novosti.rs', 'euronews.rs'
            ]
        
        is_news_source = any(domain in url.lower() for domain in news_domains)
        return "from a NEWS source" if is_news_source else "from an UNKNOWN source"
    
    @staticmethod  
    def get_valid_categories() -> set:
        """Get list of valid news categories."""
        return {"Business", "Tech", "Science", "Nature", "Serbia", "Marketing", "Other"}
    
    @staticmethod
    def format_articles_for_summary(articles: list) -> str:
        """Format articles list for summary generation."""
        articles_text = ""
        for article in articles:
            articles_text += f"Заголовок: {article['headline']}\n"
            if article.get('description'):
                articles_text += f"Описание: {article['description'][:300]}...\n"
            articles_text += "---\n"
        return articles_text
    
    # =============================================================================
    # CONTENT EXTRACTION PROMPTS
    # =============================================================================
    
    @staticmethod
    def extract_publication_date(html_content: str) -> str:
        """Generate prompt for extracting publication date from HTML."""
        return f"""Extract the publication date from this HTML content.

HTML CONTENT:
{html_content[:3000] if len(html_content) > 3000 else html_content}

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

    @staticmethod
    def find_full_article_link(html_content: str, base_url: str) -> str:
        """Generate prompt for finding full article link."""
        return f"""Find the link to the full article content from this HTML.

BASE URL: {base_url}

HTML CONTENT:
{html_content[:4000] if len(html_content) > 4000 else html_content}

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


# =============================================================================
# GLOBAL PROMPT CONSTANTS
# =============================================================================

# Character limits for different message types
TELEGRAM_SINGLE_MESSAGE_LIMIT = 3800
TELEGRAM_SPLIT_MESSAGE_LIMIT = 3700  
TELEGRAM_MAX_MESSAGE_LENGTH = 4096

# Default categories
DEFAULT_CATEGORIES = ["Business", "Tech", "Science", "Nature", "Serbia", "Marketing", "Other"]

# News source domains for context
DEFAULT_NEWS_DOMAINS = [
    'balkaninsight.com', 'biznis.rs', 'rts.rs', 'b92.net', 
    'politika.rs', 'blic.rs', 'novosti.rs', 'euronews.rs'
]
