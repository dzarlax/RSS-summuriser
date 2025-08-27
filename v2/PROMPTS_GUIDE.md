# AI Prompts Guide

## Overview

All AI prompts have been centralized in `news_aggregator/services/prompts.py` for better maintainability and version control.

## Architecture

### Main Classes

- **`NewsPrompts`** - Static methods for all AI prompts
- **`PromptBuilder`** - Helper methods for building dynamic prompts

### Prompt Categories

1. **Article Analysis** - Unified analysis for categorization, summarization, ad detection (PRIMARY)
2. **Category Summaries** - Category-specific summaries for database storage

Note: 
- Standalone summarization and fallback categorization prompts were removed in favor of unified analysis with retry logic
- AI-based digest generation was removed - Telegram digest is assembled from pre-generated category summaries WITHOUT additional AI processing

## Usage Examples

### Unified Article Analysis
```python
from news_aggregator.services.prompts import NewsPrompts, PromptBuilder

# Build source context
source_context = PromptBuilder.build_source_context(url)

# Generate unified analysis prompt
prompt = NewsPrompts.unified_article_analysis(title, content, url, source_context)
```

### Category Summary
```python
# Format articles for summary
articles_text = PromptBuilder.format_articles_for_summary(articles)

# Generate category summary prompt
prompt = NewsPrompts.category_summary(category, articles_text)
```

## Migration Guide

### Before (scattered prompts)
```python
# Old way - prompts scattered across files
prompt = f"Ты - журналист. Создай сводку..."  # in ai_client.py
prompt = f"Choose category..."                 # in telegram_ai.py  
prompt = f"Анализируй статью..."               # in orchestrator.py
```

### After (centralized)
```python
# New way - all prompts centralized
from news_aggregator.services.prompts import NewsPrompts

prompt = NewsPrompts.news_digest(...)
prompt = NewsPrompts.simple_categorization(...)
prompt = NewsPrompts.unified_article_analysis(...)
```

## Configuration

### Constants
- `TELEGRAM_SINGLE_MESSAGE_LIMIT = 3800`
- `TELEGRAM_SPLIT_MESSAGE_LIMIT = 3700`
- `DEFAULT_CATEGORIES = ["Business", "Tech", "Science", ...]`
- `DEFAULT_NEWS_DOMAINS = ["rts.rs", "b92.net", ...]`

### Valid Categories
```python
categories = PromptBuilder.get_valid_categories()
# Returns: {"Business", "Tech", "Science", "Nature", "Serbia", "Marketing", "Other"}
```

## Benefits

### ✅ Maintainability
- All prompts in one place
- Easy to version and track changes
- Consistent formatting and structure

### ✅ Simplicity  
- **Single unified prompt** for all article analysis
- **Retry logic** instead of fallback prompts
- **Reduced complexity** - fewer moving parts

### ✅ Quality
- **Higher accuracy** - unified analysis sees full context
- **Consistent results** - same prompt for all scenarios
- **Better error handling** - retry instead of degraded fallbacks

### ✅ Performance
- **Fewer API calls** - one prompt does everything
- **Faster processing** - no cascade of fallback attempts
- **Lower costs** - reduced token usage

## File Structure

```
news_aggregator/services/
├── prompts.py              # 📝 All AI prompts (NEW)
├── ai_client.py           # 🔄 Updated to use centralized prompts
└── orchestrator.py        # 🔄 Updated to use centralized prompts
```

## Deprecated Prompts

All deprecated prompts have been removed from the codebase:

- ✅ `deprecated_telegram_digest()` - **REMOVED** (use `news_digest()` instead)  
- ✅ `generate_daily_digest()` - **REMOVED** (use `Orchestrator._create_combined_digest()`)
- ✅ `article_summarization()` - **REMOVED** (use unified analysis with retry)
- ✅ `simple_categorization()` - **REMOVED** (use unified analysis with retry)
- ✅ **`TelegramAI` class** - **REMOVED** (redundant layer, use `AIClient` directly)
- ✅ All fallback prompts - **REMOVED** (unified analysis handles all scenarios)

## Future Improvements

1. **Prompt Versioning** - Track prompt changes over time
2. **A/B Testing** - Compare different prompt versions
3. **Localization** - Support for multiple languages
4. **Dynamic Adjustment** - AI model-specific prompt optimization

---

*This guide was created as part of the AI prompts centralization effort.*
