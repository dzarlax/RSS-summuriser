import asyncio
import sys
from pathlib import Path
from datetime import datetime

# Add project root to python path
project_root = str(Path(__file__).parent.parent)
sys.path.append(project_root)

from sqlalchemy import select, update
from news_aggregator.database import AsyncSessionLocal
from news_aggregator.models import ScheduleSettings

async def reset_stuck_tasks():
    print("🔄 Checking for stuck tasks...")
    async with AsyncSessionLocal() as session:
        # Find tasks that are running
        result = await session.execute(
            select(ScheduleSettings).where(ScheduleSettings.is_running == True)
        )
        running_tasks = result.scalars().all()
        
        if not running_tasks:
            print("✅ No running tasks found.")
            return

        print(f"⚠️ Found {len(running_tasks)} running tasks:")
        for task in running_tasks:
            print(f"  - {task.task_name} (Last run: {task.last_run})")
            
        # Reset them
        print("\n🔧 Resetting tasks...")
        for task in running_tasks:
            task.is_running = False
            # Force next run to be in the past to trigger immediate execution if enabled
            if task.enabled:
                print(f"  Requesting immediate run for {task.task_name}")
                # We don't change next_run here, the scheduler will pick it up if it's in the past
                # or we can force it:
                # task.next_run = datetime.utcnow() 
        
        await session.commit()
        print("✅ Tasks reset successfully.")

if __name__ == "__main__":
    asyncio.run(reset_stuck_tasks())
