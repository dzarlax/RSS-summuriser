
import asyncio
import sys
import os
from sqlalchemy import text

# Add app directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from news_aggregator.database import AsyncSessionLocal

async def check_extraction_attempts():
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT article_url, success, extraction_strategy, error_message, created_at FROM extraction_attempts WHERE article_url LIKE '%hype.replicate.dev%' ORDER BY created_at DESC LIMIT 10")
        )
        attempts = result.fetchall()
        
        if not attempts:
            print("❌ No extraction attempts found for hype.replicate.dev")
            return
            
        for attempt in attempts:
            print(f"URL: {attempt.article_url}")
            print(f"Success: {attempt.success}")
            print(f"Strategy: {attempt.extraction_strategy}")
            print(f"Error: {attempt.error_message}")
            print(f"Time: {attempt.created_at}")
            print("-" * 20)

if __name__ == "__main__":
    asyncio.run(check_extraction_attempts())
