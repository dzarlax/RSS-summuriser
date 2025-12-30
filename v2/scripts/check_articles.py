
import asyncio
import sys
import os
from sqlalchemy import text

# Add app directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from news_aggregator.database import AsyncSessionLocal

async def check_articles():
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT id, source_id, title, url FROM articles WHERE url LIKE '%hype.replicate.dev%'")
        )
        articles = result.fetchall()
        
        if not articles:
            print("❌ No articles found for hype.replicate.dev")
            return
            
        for article in articles:
            print(f"ID: {article.id} | SourceID: {article.source_id} | Title: {article.title} | URL: {article.url}")

if __name__ == "__main__":
    asyncio.run(check_articles())
