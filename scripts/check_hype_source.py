
import asyncio
import sys
import os
from sqlalchemy import text

# Add app directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from news_aggregator.database import AsyncSessionLocal

async def list_all_sources():
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT id, name, url, source_type, enabled FROM sources")
        )
        sources = result.fetchall()
        
        for source in sources:
            print(f"ID: {source.id} | Name: {source.name} | Type: {source.source_type} | URL: {source.url} | Enabled: {source.enabled}")

if __name__ == "__main__":
    asyncio.run(list_all_sources())
