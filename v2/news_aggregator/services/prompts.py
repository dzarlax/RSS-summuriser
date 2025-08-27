"""
Centralized AI prompts for news aggregator system.

This module contains all AI prompts used throughout the application.
Centralizing prompts makes them easier to maintain, version, and improve.
"""

from typing import Dict, Any, Optional


class NewsPrompts:
    """Collection of all AI prompts for news processing."""
    
    # =============================================================================
    # SHARED SUMMARIZATION RULES
    # =============================================================================
    
    @staticmethod
    def _get_summarization_rules(sentence_count: str = "5-6") -> str:
        """Get unified summarization rules used across different prompts."""
        return f"""
SUMMARIZATION REQUIREMENTS:
- Create {sentence_count} informative sentences in Russian
- Start directly with main content (no introductory phrases like "статья рассказывает о...")
- Structure: ЧТО произошло → ГДЕ → КОГДА → КТО участвовал → ПОЧЕМУ важно → РЕЗУЛЬТАТ/ПОСЛЕДСТВИЯ
- Preserve key facts, numbers, names, dates
- Each sentence should carry new information
- Logical connections between sentences
- Concise and informative, avoid filler words"""
    
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
    def unified_article_analysis(title: str, content: str, url: str, 
                                source_context: str = "from an UNKNOWN source") -> str:
        """
        Main unified prompt for complete article analysis.
        
        Handles: categorization, summarization, ad detection, date extraction.
        Used by: AIClient.analyze_article_complete()
        """
        # Limit content size for cost optimization
        content_preview = content[:2000] + ("..." if len(content) > 2000 else "")
        
        return f"""Analyze this article and provide complete analysis in JSON format.

ARTICLE INFORMATION:
Title: {title}
URL: {url}
Source: {source_context}
Content: {content_preview}

ANALYSIS TASKS:
1. TITLE OPTIMIZATION: Create clear, informative headline (max 120 characters for Telegram)
2. CATEGORIZATION: Choose one or more relevant categories (if content spans multiple domains)
3. SUMMARIZATION: Create 5-6 sentence summary in Russian with structured approach
4. ADVERTISEMENT DETECTION: Determine if content is promotional
5. DATE EXTRACTION: Find publication date if mentioned

GUIDELINES:
- NEWS articles report facts, events, research, government actions
- ADVERTISEMENTS promote products, services, events, or attract customers  
- News sources have lower advertisement probability
- Prices/statistics alone don't indicate advertisements

CATEGORIES:
Choose from: Business, Tech, Science, Nature, Serbia, Marketing, Other
- Choose 1-2 most relevant categories
- Use multiple categories when content clearly relates to different domains
- Examples: Serbian bank news → "Serbia", "Business"; Russian tech startup → "Tech", "Business"

TITLE OPTIMIZATION RULES:
- ALWAYS provide optimized_title field (even if keeping original)
- Maximum 120 characters for Telegram readability
- Make title clear and informative
- Remove clickbait elements (BREAKING, TOP-5, etc.)
- Fix truncated titles (ending with "..." or incomplete)
- Keep language consistent with content (Russian for Russian content, English for English)
- If original is good and under 120 chars, return it as optimized_title

2. ENHANCED SUMMARIZATION:{NewsPrompts._get_summarization_rules("5-6")}

ADVERTISEMENT DETECTION:
Promotional keywords: "купить", "заказать", "скидка", "акция", "распродажа", "цена", "от ... рублей"
Business keywords: "продает", "покупает", "инвестирует", "сделка", "контракт", "партнерство"

DATE EXTRACTION:
Look for publication dates in content, ignore article dates.

OUTPUT FORMAT (JSON):
{{
    "optimized_title": "Краткий информативный заголовок новости",
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
- Multiple categories: "categories": ["Serbia", "Business"], "category_confidences": [0.90, 0.85]
- Serbian tech news: "categories": ["Serbia", "Tech"], "category_confidences": [0.95, 0.80]

TITLE EXAMPLES:
- Original: "В декабре 2025 года в Сербии в очередной раз" → Optimized: "В Сербии повысят пенсии с января 2026 года"
- Original: "BREAKING: Компания X объявила о..." → Optimized: "Компания X запустила новый продукт"
- Original: "ТОП-5 способов заработать..." → Optimized: "Эксперты назвали способы увеличения доходов"

IMPORTANT: Arrays "categories" and "category_confidences" must have the same length!

Return ONLY valid JSON without additional text."""
    
    # Note: article_summarization() and article_summarization_system() removed
    # All summarization now uses unified_article_analysis() with retry logic
    
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
    # unified_article_analysis() with retry logic
    
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
