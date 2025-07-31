"""Background task scheduler service."""

import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional

import pytz
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import AsyncSessionLocal
from ..models import ScheduleSettings
from ..orchestrator import NewsOrchestrator
from ..services.ai_client import get_ai_client
from ..services.telegram_service import get_telegram_service


logger = logging.getLogger(__name__)


class TaskScheduler:
    """Background task scheduler."""
    
    def __init__(self):
        self.orchestrator = NewsOrchestrator()
        self.running = False
        self._tasks: Dict[str, asyncio.Task] = {}
        self._check_interval = 60  # Check every minute
        
    async def start(self):
        """Start the scheduler."""
        if self.running:
            logger.warning("Scheduler is already running")
            return
            
        self.running = True
        logger.info("Starting task scheduler")
        
        # Start main scheduler loop
        self._tasks['main'] = asyncio.create_task(self._scheduler_loop())
        
    async def stop(self):
        """Stop the scheduler."""
        if not self.running:
            return
            
        logger.info("Stopping task scheduler")
        self.running = False
        
        # Cancel all running tasks
        for task_name, task in self._tasks.items():
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        self._tasks.clear()
        
    async def _scheduler_loop(self):
        """Main scheduler loop."""
        logger.info("Scheduler loop started")
        
        while self.running:
            try:
                await self._check_and_run_tasks()
                await asyncio.sleep(self._check_interval)
                
            except asyncio.CancelledError:
                logger.info("Scheduler loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in scheduler loop: {e}", exc_info=True)
                await asyncio.sleep(self._check_interval)
                
    async def _check_and_run_tasks(self):
        """Check for tasks that need to run and execute them."""
        try:
            async with AsyncSessionLocal() as db:
                # Get all enabled schedule settings
                result = await db.execute(
                    select(ScheduleSettings).where(
                        ScheduleSettings.enabled == True,
                        ScheduleSettings.is_running == False
                    )
                )
                settings = result.scalars().all()
                
                now_utc = datetime.utcnow().replace(tzinfo=pytz.UTC)
                
                for setting in settings:
                    # Check if task should run
                    if await self._should_run_task(setting, now_utc):
                        logger.info(f"Running scheduled task: {setting.task_name}")
                        
                        # Mark as running
                        setting.is_running = True
                        setting.last_run = now_utc.replace(tzinfo=None)
                        await db.commit()
                        
                        # Run task in background
                        task_key = f"task_{setting.task_name}_{setting.id}"
                        self._tasks[task_key] = asyncio.create_task(
                            self._run_task(setting.task_name, setting.task_config, setting.id)
                        )
                        
        except Exception as e:
            logger.error(f"Error checking tasks: {e}", exc_info=True)
            
    async def _should_run_task(self, setting: ScheduleSettings, now_utc: datetime) -> bool:
        """Check if a task should run based on its schedule."""
        if not setting.next_run:
            return False
            
        # Convert next_run to UTC for comparison
        next_run_utc = setting.next_run
        if next_run_utc.tzinfo is None:
            next_run_utc = next_run_utc.replace(tzinfo=pytz.UTC)
        elif next_run_utc.tzinfo != pytz.UTC:
            next_run_utc = next_run_utc.astimezone(pytz.UTC)
            
        return now_utc >= next_run_utc
        
    async def _run_task(self, task_name: str, task_config: Dict[str, Any], setting_id: int):
        """Run a specific task."""
        try:
            logger.info(f"Executing task: {task_name}")
            
            if task_name == "news_digest":
                await self._run_news_digest_cycle(task_config)
            elif task_name == "telegram_digest":
                await self._run_telegram_digest(task_config)
            elif task_name == "news_processing":
                await self._run_news_processing(task_config)
            elif task_name == "daily_summaries":
                await self._run_daily_summaries(task_config)
            elif task_name == "backup":
                await self._run_backup_task(task_config)
            else:
                logger.warning(f"Unknown task type: {task_name}")
                
            logger.info(f"Task completed successfully: {task_name}")
            
        except Exception as e:
            logger.error(f"Error running task {task_name}: {e}", exc_info=True)
            
        finally:
            # Mark task as not running and calculate next run
            await self._update_task_schedule(setting_id)
            
    async def _run_telegram_digest(self, config: Dict[str, Any]):
        """Run telegram digest task."""
        from ..services.telegram_service import get_telegram_service
        from ..services.ai_client import get_ai_client
        from sqlalchemy import func
        
        async with AsyncSessionLocal() as db:
            # Get today's articles by published date
            today = datetime.utcnow().date()
            
            from ..models import Article
            articles_result = await db.execute(
                select(Article).where(func.date(Article.published_at) == today)
                .order_by(Article.published_at.desc())
                .limit(config.get('max_articles', 20))
            )
            articles = articles_result.scalars().all()
            
            if not articles:
                logger.info("No articles found for telegram digest")
                return
                
            # Group articles by category
            categories = {}
            for article in articles:
                category = article.category or "Other"
                if category not in categories:
                    categories[category] = []
                categories[category].append({
                    'title': article.title,
                    'summary': article.summary or article.content[:200] + "..." if article.content else article.title
                })
                
            # Generate digest
            ai_client = get_ai_client()
            digest = await ai_client.generate_digest(categories)
            
            if digest:
                # Create Telegraph page
                from ..services.telegraph_service import TelegraphService
                telegraph_service = TelegraphService()
                telegraph_url = await telegraph_service.create_news_page(categories)
                
                # Send to Telegram
                telegram_service = get_telegram_service()
                if telegraph_url:
                    inline_keyboard = [[{"text": "📖 Читать полностью", "url": telegraph_url}]]
                    await telegram_service.send_message_with_keyboard(digest, inline_keyboard)
                else:
                    await telegram_service.send_daily_digest(digest)
                    
                logger.info(f"Telegram digest sent successfully ({len(digest)} chars)")
            else:
                logger.warning("Failed to generate telegram digest")
                
    async def _run_news_processing(self, config: Dict[str, Any]):
        """Run news processing task."""
        stats = await self.orchestrator.run_full_cycle()
        logger.info(f"News processing completed: {stats.get('articles_processed', 0)} articles processed")
        
    async def _run_news_digest_cycle(self, config: Dict[str, Any]):
        """Run complete news digest cycle: sync, categorize, summarize, and send to Telegram."""
        logger.info("Starting complete news digest cycle")
        
        try:
            # Step 1: Run full news processing cycle
            stats = await self.orchestrator.run_full_cycle()
            logger.info(f"News processing completed: {stats.get('articles_processed', 0)} articles processed")
            
            # Step 2: Get today's processed articles for digest
            async with AsyncSessionLocal() as db:
                from datetime import datetime
                from sqlalchemy import func
                from ..models import Article
                
                today = datetime.utcnow().date()
                articles_result = await db.execute(
                    select(Article).where(func.date(Article.published_at) == today)
                    .order_by(Article.published_at.desc())
                    .limit(config.get('max_articles', 20))
                )
                articles = articles_result.scalars().all()
                
                if not articles:
                    logger.info("No articles found for digest")
                    return
                
                logger.info(f"Found {len(articles)} articles for digest")
                
                # Step 3: Group articles by category
                categories = {}
                for article in articles:
                    category = article.category or "Other"
                    if category not in categories:
                        categories[category] = []
                    categories[category].append({
                        'title': article.title,
                        'summary': article.summary or article.content[:200] + "..." if article.content else article.title
                    })
                
                logger.info(f"Articles grouped into categories: {list(categories.keys())}")
                
                # Step 4: Generate and save daily summaries (if enabled)
                if config.get('generate_summaries', True):
                    await self.orchestrator._generate_and_save_daily_summaries(db, today, categories)
                    logger.info("Daily summaries generated and saved")
                
                # Step 5: Send to Telegram (if enabled)
                if config.get('send_telegram', True):
                    # Generate digest using AI
                    ai_client = get_ai_client()
                    digest = await ai_client.generate_digest(categories)
                    
                    if digest:
                        logger.info(f"Generated digest ({len(digest)} chars)")
                        
                        # Create Telegraph page (if enabled)
                        telegraph_url = None
                        if config.get('create_telegraph', True):
                            from ..services.telegraph_service import TelegraphService
                            telegraph_service = TelegraphService()
                            telegraph_url = await telegraph_service.create_news_page(categories)
                            
                            if telegraph_url:
                                logger.info(f"Telegraph page created: {telegraph_url}")
                        
                        # Send to Telegram
                        telegram_service = get_telegram_service()
                        if telegraph_url:
                            inline_keyboard = [[{"text": "📖 Читать полностью", "url": telegraph_url}]]
                            success = await telegram_service.send_message_with_keyboard(digest, inline_keyboard)
                        else:
                            success = await telegram_service.send_daily_digest(digest)
                        
                        if success:
                            logger.info("Digest sent to Telegram successfully")
                        else:
                            logger.warning("Failed to send digest to Telegram")
                    else:
                        logger.warning("Failed to generate digest")
                
                logger.info("Complete news digest cycle finished successfully")
                
        except Exception as e:
            logger.error(f"Error in news digest cycle: {e}", exc_info=True)
            raise

    async def _run_daily_summaries(self, config: Dict[str, Any]):
        """Run daily summaries generation task."""
        # This is typically done as part of news processing
        # But can be run separately if needed
        logger.info("Daily summaries generation task - handled by news processing")
        
    async def _update_task_schedule(self, setting_id: int):
        """Update task schedule after completion."""
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(ScheduleSettings).where(ScheduleSettings.id == setting_id)
                )
                setting = result.scalar_one_or_none()
                
                if not setting:
                    return
                    
                # Mark as not running
                setting.is_running = False
                
                # Calculate next run time
                if setting.enabled:
                    next_run = await self._calculate_next_run(setting)
                    setting.next_run = next_run
                else:
                    setting.next_run = None
                    
                await db.commit()
                logger.info(f"Updated schedule for {setting.task_name}, next run: {setting.next_run}")
                
        except Exception as e:
            logger.error(f"Error updating task schedule: {e}", exc_info=True)
            
    async def _calculate_next_run(self, setting: ScheduleSettings) -> Optional[datetime]:
        """Calculate the next run time for a task."""
        try:
            tz = pytz.timezone(setting.timezone)
            now = datetime.now(tz)
            
            if setting.schedule_type == "daily":
                # Next run at specified time
                next_run = now.replace(
                    hour=setting.hour, 
                    minute=setting.minute, 
                    second=0, 
                    microsecond=0
                )
                
                # If time has passed today, schedule for tomorrow
                if next_run <= now:
                    next_run += timedelta(days=1)
                    
                # Check weekdays if specified
                if setting.weekdays:
                    while next_run.isoweekday() not in setting.weekdays:
                        next_run += timedelta(days=1)
                        
            elif setting.schedule_type == "hourly":
                # Next run at specified minute of next hour
                next_run = now.replace(minute=setting.minute, second=0, microsecond=0)
                if next_run <= now:
                    next_run += timedelta(hours=1)
                    
                # Check weekdays if specified
                if setting.weekdays and next_run.isoweekday() not in setting.weekdays:
                    # Skip to next valid weekday
                    while next_run.isoweekday() not in setting.weekdays:
                        next_run += timedelta(days=1)
                    next_run = next_run.replace(hour=0, minute=setting.minute)
                    
            else:
                logger.warning(f"Unknown schedule type: {setting.schedule_type}")
                return None
                
            return next_run.astimezone(pytz.UTC).replace(tzinfo=None)
            
        except Exception as e:
            logger.error(f"Error calculating next run: {e}", exc_info=True)
            return None
    
    async def _run_backup_task(self, config: Dict[str, Any]):
        """Run backup task."""
        try:
            logger.info("Starting scheduled backup")
            
            # Get project root directory
            project_root = Path(__file__).parent.parent.parent
            backup_script = project_root / "scripts" / "backup.sh"
            
            if not backup_script.exists():
                logger.error("Backup script not found")
                return
            
            # Run backup script
            process = await asyncio.create_subprocess_exec(
                str(backup_script),
                cwd=str(project_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                logger.info(f"Scheduled backup completed successfully: {stdout.decode()}")
                
                # Cleanup old backups if configured
                keep_days = config.get('keep_days', 30)
                await self._cleanup_old_backups(project_root, keep_days)
                
            else:
                logger.error(f"Scheduled backup failed: {stderr.decode()}")
                
        except Exception as e:
            logger.error(f"Error running backup task: {e}", exc_info=True)
    
    async def _cleanup_old_backups(self, project_root: Path, keep_days: int):
        """Clean up old backup files."""
        try:
            
            backups_dir = project_root / "backups"
            if not backups_dir.exists():
                return
            
            cutoff_date = datetime.utcnow() - timedelta(days=keep_days)
            
            for backup_file in backups_dir.glob("*.tar.gz"):
                if backup_file.stat().st_mtime < cutoff_date.timestamp():
                    backup_file.unlink()
                    logger.info(f"Deleted old backup: {backup_file.name}")
                    
        except Exception as e:
            logger.error(f"Error cleaning up old backups: {e}", exc_info=True)
            
    async def get_status(self) -> Dict[str, Any]:
        """Get scheduler status."""
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(ScheduleSettings))
            settings = result.scalars().all()
            
            return {
                "running": self.running,
                "active_tasks": len([s for s in settings if s.enabled]),
                "total_tasks": len(settings),
                "running_tasks": len([s for s in settings if s.is_running]),
                "next_runs": [
                    {
                        "task_name": s.task_name,
                        "next_run": s.next_run.isoformat() if s.next_run else None,
                        "enabled": s.enabled
                    }
                    for s in settings
                ]
            }


# Global scheduler instance
_scheduler: Optional[TaskScheduler] = None


def get_scheduler() -> TaskScheduler:
    """Get the global scheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = TaskScheduler()
    return _scheduler


async def start_scheduler():
    """Start the global scheduler."""
    scheduler = get_scheduler()
    await scheduler.start()


async def stop_scheduler():
    """Stop the global scheduler."""
    scheduler = get_scheduler()
    await scheduler.stop()