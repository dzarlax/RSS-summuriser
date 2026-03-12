import asyncio
import json
from unittest.mock import MagicMock, AsyncMock
from news_aggregator.processing.ai_processor import AIProcessor
from news_aggregator.services.ai_client import AIClient

async def test_translation_fallback():
    print("🚀 Testing translation fallback...")
    
    # Mock article data (Serbian title)
    article_data = {
        'id': 9999,
        'title': 'Ovo je test na srpskom jeziku', # "This is a test in Serbian"
        'url': 'https://test.com/serbian-news',
        'content': 'Kratak sadržaj koji će biti filtriran.',
        'source_type': 'telegram',
        'source_name': 'Test Source'
    }
    
    # Initialize processor
    processor = AIProcessor()
    
    # Mock database saving to avoid actual DB calls
    processor._save_article_fields = AsyncMock()
    
    # Mock SmartFilter to trigger skip
    from news_aggregator.services.smart_filter import SmartFilter
    mock_filter = MagicMock(spec=SmartFilter)
    mock_filter.should_process_with_ai.return_value = (False, "Content too short")
    
    import news_aggregator.services.smart_filter
    news_aggregator.services.smart_filter.get_smart_filter = lambda: mock_filter
    
    # Run processing
    stats = {'api_calls_made': 0}
    result = await processor.process_article_combined(article_data, stats)
    
    print(f"✅ Processing completed")
    print(f"📊 Summary in result: {result.get('summary')}")
    
    # Check if summary has Cyrillic
    summary = result.get('summary', '')
    has_cyrillic = any('а' <= ch.lower() <= 'я' for ch in summary)
    
    if has_cyrillic:
        print("🎉 SUCCESS: Summary translated to Russian!")
    else:
        print("❌ FAILURE: Summary still in Serbian.")

if __name__ == "__main__":
    asyncio.run(test_translation_fallback())
