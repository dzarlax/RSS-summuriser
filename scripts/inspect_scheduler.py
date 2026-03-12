import asyncio
import sys
from pathlib import Path

# Add project root to python path
project_root = str(Path(__file__).parent.parent)
sys.path.append(project_root)

from sqlalchemy import select
from news_aggregator.database import AsyncSessionLocal
from news_aggregator.models import ScheduleSettings

async def inspect_schedule_settings():
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(ScheduleSettings))
        settings = result.scalars().all()
        
        print(f"Found {len(settings)} scheduled tasks:")
        for s in settings:
            print(f"\nTask: {s.task_name}")
            print(f"  Enabled: {s.enabled}")
            print(f"  Schedule Type: {s.schedule_type}")
            print(f"  Next Run: {s.next_run}")
            print(f"  Last Run: {s.last_run}")
            print(f"  Is Running: {s.is_running}")
            print(f"  Task Config: {s.task_config}")

if __name__ == "__main__":
    asyncio.run(inspect_schedule_settings())
