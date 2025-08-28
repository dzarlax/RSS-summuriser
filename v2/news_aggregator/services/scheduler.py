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
from ..database_helpers import fetch_all, execute_custom_write
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
        
        # Start orchestrator's database queue
        await self.orchestrator.start()
        
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
        
        # Stop orchestrator's database queue
        await self.orchestrator.stop()
        
    async def _scheduler_loop(self):
        """Main scheduler loop."""
        print("🔄 Scheduler loop started (enhanced version)")
        logger.info("Scheduler loop started")
        
        while self.running:
            try:
                await self._check_and_run_tasks()
                await asyncio.sleep(self._check_interval)
                
            except asyncio.CancelledError:
                print("⏸️ Scheduler loop cancelled")
                logger.info("Scheduler loop cancelled")
                break
            except Exception as e:
                print(f"❌ Error in scheduler loop: {e}")
                logger.error(f"Error in scheduler loop: {e}", exc_info=True)
                await asyncio.sleep(self._check_interval)
                
    async def _check_and_run_tasks(self):
        """Check for tasks that need to run and execute them."""
        try:
            # Get all enabled schedule settings (quick DB query through read queue)
            query = select(ScheduleSettings).where(
                ScheduleSettings.enabled == True,
                ScheduleSettings.is_running == False
            )
            settings = await fetch_all(query)
                
            now_utc = datetime.utcnow().replace(tzinfo=pytz.UTC)
            
            # Debug output every 10 minutes or when tasks are overdue
            if now_utc.minute % 10 == 0 or any(now_utc >= (s.next_run.replace(tzinfo=pytz.UTC) if s.next_run and s.next_run.tzinfo is None else s.next_run.astimezone(pytz.UTC) if s.next_run else now_utc) for s in settings if s.next_run):
                print(f"🕐 Scheduler check at {now_utc}: {len(settings)} tasks available")
                for setting in settings:
                    if setting.next_run:
                        next_run_utc = setting.next_run.replace(tzinfo=pytz.UTC) if setting.next_run.tzinfo is None else setting.next_run.astimezone(pytz.UTC)
                        should_run = now_utc >= next_run_utc
                        delay = (now_utc - next_run_utc).total_seconds() / 60 if should_run else (next_run_utc - now_utc).total_seconds() / 60
                        status = "OVERDUE" if should_run else f"in {delay:.1f}m"
                        print(f"  {setting.task_name}: {status}")
                
            for setting in settings:
                    # Check if task should run
                    should_run = await self._should_run_task(setting, now_utc)
                    
                    if should_run:
                        print(f"🚀 Starting scheduled task: {setting.task_name}")
                        logger.info(f"Running scheduled task: {setting.task_name}")
                        
                        # Mark as running through write queue
                        async def mark_running_operation(session):
                            from sqlalchemy import update
                            stmt = update(ScheduleSettings).where(
                                ScheduleSettings.id == setting.id
                            ).values(
                                is_running=True,
                                last_run=now_utc.replace(tzinfo=None)
                            )
                            await session.execute(stmt)
                            await session.commit()
                            
                        await execute_custom_write(mark_running_operation)
                        
                        # Run task in background
                        task_key = f"task_{setting.task_name}_{setting.id}"
                        self._tasks[task_key] = asyncio.create_task(
                            self._run_task(setting.task_name, setting.task_config, setting.id)
                        )
                        
        except Exception as e:
            print(f"❌ Error checking tasks: {e}")
            logger.error(f"Error checking tasks: {e}", exc_info=True)
            
    async def _should_run_task(self, setting: ScheduleSettings, now_utc: datetime) -> bool:
        """Check if a task should run based on its schedule."""
        try:
            if not setting.next_run:
                return False
                
            # Convert next_run to UTC for comparison
            next_run_utc = setting.next_run
            if next_run_utc.tzinfo is None:
                next_run_utc = next_run_utc.replace(tzinfo=pytz.UTC)
            elif next_run_utc.tzinfo != pytz.UTC:
                next_run_utc = next_run_utc.astimezone(pytz.UTC)
                
            should_run = now_utc >= next_run_utc
            
            # Debug logging for overdue tasks
            if should_run:
                delay_minutes = (now_utc - next_run_utc).total_seconds() / 60
                if delay_minutes > 5:  # If more than 5 minutes late
                    print(f"⏰ Task {setting.task_name} is {delay_minutes:.1f} minutes overdue")
                    
            return should_run
            
        except Exception as e:
            print(f"❌ Error checking if task {setting.task_name} should run: {e}")
            logger.error(f"Error checking if task {setting.task_name} should run: {e}", exc_info=True)
            return False
        
    async def _run_task(self, task_name: str, task_config: Dict[str, Any], setting_id: int):
        """Run a specific task."""
        start_time = datetime.utcnow()
        try:
            print(f"🏃 Executing task: {task_name}")
            logger.info(f"Executing task: {task_name}")
            
            if task_name == "telegram_digest":
                await self._run_telegram_digest(task_config)
            elif task_name == "news_processing":
                await self._run_news_processing(task_config)
            elif task_name == "daily_summaries":
                await self._run_daily_summaries(task_config)
            elif task_name == "backup":
                await self._run_backup_task(task_config)
            elif task_name == "reprocess_failed":
                await self._run_reprocess_failed(task_config)
            elif task_name == "news_digest":
                await self._run_news_digest_cycle(task_config)
            else:
                print(f"⚠️ Unknown task type: {task_name}")
                logger.warning(f"Unknown task type: {task_name}")
                
            duration = (datetime.utcnow() - start_time).total_seconds()
            print(f"✅ Task completed successfully: {task_name} (took {duration:.1f}s)")
            logger.info(f"Task completed successfully: {task_name} (took {duration:.1f}s)")
            
        except Exception as e:
            duration = (datetime.utcnow() - start_time).total_seconds()
            print(f"❌ Error running task {task_name} after {duration:.1f}s: {e}")
            logger.error(f"Error running task {task_name}: {e}", exc_info=True)
            
        finally:
            # Mark task as not running and calculate next run
            await self._update_task_schedule(setting_id)
            
    async def _run_telegram_digest(self, config: Dict[str, Any]):
        """Run telegram digest task using unified orchestrator logic."""
        try:
            print(f"📱 Starting telegram digest task...")
            logger.info("Starting telegram digest task via orchestrator")
            
            # Use the same logic as button-triggered digest for consistency
            stats = await self.orchestrator.send_telegram_digest()
            
            if stats.get('telegram_digest_sent'):
                articles = stats.get('telegram_articles', 0)
                categories = stats.get('telegram_categories', 0)
                length = stats.get('telegram_digest_length', 0)
                print(f"📱 Telegram digest sent: {articles} articles in {categories} categories ({length} chars)")
                logger.info(f"Telegram digest sent successfully: {length} chars, {articles} articles in {categories} categories")
            else:
                print(f"❌ Failed to send telegram digest")
                logger.warning("Failed to send telegram digest")
                
        except Exception as e:
            print(f"❌ Error in telegram digest task: {e}")
            logger.error(f"Error in telegram digest task: {e}", exc_info=True)
            raise
                
    async def _run_news_processing(self, config: Dict[str, Any]):
        """Run news processing task."""
        try:
            print(f"📰 Starting news processing cycle...")
            stats = await self.orchestrator.run_full_cycle()
            processed = stats.get('articles_processed', 0)
            print(f"📰 News processing completed: {processed} articles processed")
            logger.info(f"News processing completed: {processed} articles processed")
        except Exception as e:
            print(f"❌ News processing failed: {e}")
            logger.error(f"News processing failed: {e}", exc_info=True)
            raise
        
    async def _run_news_digest_cycle(self, config: Dict[str, Any]):
        """Run complete news digest cycle using unified orchestrator logic."""
        logger.info("Starting complete news digest cycle")
        
        try:
            # Step 1: Run full news processing cycle (if enabled)
            if config.get('run_processing', True):
                processing_stats = await self.orchestrator.run_full_cycle()
                logger.info(f"News processing completed: {processing_stats.get('articles_processed', 0)} articles processed")
            
            # Step 2: Send digest using unified logic (if enabled)
            if config.get('send_telegram', True):
                digest_stats = await self.orchestrator.send_telegram_digest()
                
                if digest_stats.get('telegram_digest_sent'):
                    logger.info(f"Digest sent successfully: {digest_stats.get('telegram_digest_length', 0)} chars, "
                               f"{digest_stats.get('telegram_articles', 0)} articles in {digest_stats.get('telegram_categories', 0)} categories")
                else:
                    logger.warning("Failed to send telegram digest")
            
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
            async def update_operation(db: AsyncSession):
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
                    
                try:
                    await db.commit()
                except Exception as e:
                    await db.rollback()
                    logger.error(f"Failed to commit schedule update for {setting.task_name}: {e}")
                    raise
                logger.info(f"Updated schedule for {setting.task_name}, next run: {setting.next_run}")
                return setting
                
            await execute_custom_write(update_operation)
            
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
            elif setting.schedule_type == "interval":
                # Generic interval in minutes stored in task_config.interval_minutes (default 30)
                try:
                    interval_minutes = int((setting.task_config or {}).get('interval_minutes', 30))
                except Exception:
                    interval_minutes = 30
                interval_minutes = max(1, min(interval_minutes, 24*60))
                next_run = now + timedelta(minutes=interval_minutes)
                    
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
    
    async def _run_reprocess_failed(self, config: Dict[str, Any]):
        """Run reprocess failed extractions task."""
        try:
            print(f"🔄 Starting failed extraction reprocessing task...")
            logger.info("Starting failed extraction reprocessing task")
            
            # Get configuration
            limit = config.get('limit', 20)  # Process max 20 articles per run by default
            dry_run = config.get('dry_run', False)
            
            print(f"  📊 Reprocessing up to {limit} failed extractions (dry_run={dry_run})")
            
            # Run the reprocessing
            results = await self.orchestrator.reprocess_failed_extractions(limit=limit, dry_run=dry_run)
            
            # Log results
            candidates_count = results.get('total_candidates', 0)
            processed_count = results.get('processed', 0)
            improved_count = results.get('improved', 0)
            failed_count = results.get('failed', 0)
            
            if dry_run:
                print(f"  📋 Dry run completed: {candidates_count} articles would be reprocessed")
                logger.info(f"Reprocess dry run: {candidates_count} candidates found")
            else:
                print(f"  ✅ Reprocessing completed: {processed_count} processed, {improved_count} improved, {failed_count} failed")
                logger.info(f"Reprocessing completed: processed={processed_count}, improved={improved_count}, failed={failed_count}")
                
                # Log any errors
                errors = results.get('errors', [])
                if errors:
                    print(f"  ⚠️ {len(errors)} errors during reprocessing")
                    for error in errors:
                        logger.warning(f"Reprocessing error: {error}")
                        
        except Exception as e:
            print(f"❌ Error in failed extraction reprocessing task: {e}")
            logger.error(f"Error in failed extraction reprocessing task: {e}", exc_info=True)
            raise
            
    async def get_status(self) -> Dict[str, Any]:
        """Get scheduler status."""
        query = select(ScheduleSettings)
        settings = await fetch_all(query)
        
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