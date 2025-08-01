#!/usr/bin/env python3
"""Test script for content extraction from N+1 article."""

import asyncio
import sys
import os

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from news_aggregator.services.content_extractor import ContentExtractor


async def test_nplus1_extraction():
    """Test extraction from N+1 article."""
    url = "https://nplus1.ru/news/2025/07/31/cyborg-insect-factory"
    
    print(f"Testing content extraction from: {url}")
    print("=" * 80)
    
    async with ContentExtractor() as extractor:
        try:
            content = await extractor.extract_article_content(url)
            
            if content:
                print(f"✅ Extraction successful!")
                print(f"Content length: {len(content)} characters")
                print(f"Content preview (first 500 chars):")
                print("-" * 40)
                print(content[:500])
                print("-" * 40)
                
                # Show last 200 chars to see how it ends
                if len(content) > 500:
                    print(f"Content ending (last 200 chars):")
                    print("-" * 40)
                    print("..." + content[-200:])
                    print("-" * 40)
                
                # Basic content quality checks
                print(f"\nContent analysis:")
                print(f"- Length: {len(content)} chars")
                print(f"- Words: {len(content.split())} words")
                print(f"- Lines: {len(content.splitlines())} lines")
                
                # Check for key terms that should be in the article
                expected_terms = [
                    "киборг", "таракан", "сингапур", "автоматизировали", 
                    "производство", "манипулятор", "электроника"
                ]
                
                found_terms = []
                for term in expected_terms:
                    if term.lower() in content.lower():
                        found_terms.append(term)
                
                print(f"- Found key terms: {len(found_terms)}/{len(expected_terms)}")
                print(f"  Terms found: {', '.join(found_terms)}")
                
                if len(found_terms) >= len(expected_terms) * 0.7:  # 70% of terms found
                    print("✅ Content quality looks good!")
                else:
                    print("⚠️ Content quality may be poor - missing key terms")
                
            else:
                print("❌ Extraction failed - no content returned")
                
        except Exception as e:
            print(f"❌ Extraction failed with error: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_nplus1_extraction())