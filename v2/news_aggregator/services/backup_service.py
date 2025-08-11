"""Backup service for managing backup schedules and operations."""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, Any

import pytz
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import AsyncSessionLocal
from ..models import ScheduleSettings


logger = logging.getLogger(__name__)


class BackupService:
    """Service for managing backup schedules and operations."""
    
    def __init__(self):
        self.project_root = Path(__file__).parent.parent.parent
        self.config_file = self.project_root / "backup_schedule.json"
    
    async def get_schedule_config(self) -> Dict[str, Any]:
        """Get backup schedule configuration."""
        try:
            if self.config_file.exists():
                with open(self.config_file) as f:
                    return json.load(f)
            else:
                return {
                    "enabled": False,
                    "schedule_time": "03:00",
                    "keep_days": 30,
                    "last_backup": None,
                    "created_at": datetime.utcnow().isoformat()
                }
        except Exception as e:
            logger.error(f"Error reading backup schedule config: {e}")
            return {
                "enabled": False,
                "schedule_time": "03:00", 
                "keep_days": 30,
                "last_backup": None,
                "error": str(e)
            }
    
    async def set_schedule_config(self, enabled: bool, schedule_time: str, keep_days: int) -> Dict[str, Any]:
        """Set backup schedule configuration."""
        try:
            config = {
                "enabled": enabled,
                "schedule_time": schedule_time,
                "keep_days": keep_days,
                "updated_at": datetime.utcnow().isoformat()
            }
            
            # Save to config file
            with open(self.config_file, 'w') as f:
                json.dump(config, f, indent=2)
            
            # Update database schedule settings
            if enabled:
                await self._create_or_update_schedule_task(schedule_time, keep_days)
            else:
                await self._disable_schedule_task()
            
            logger.info(f"Backup schedule updated: enabled={enabled}, time={schedule_time}")
            return config
            
        except Exception as e:
            logger.error(f"Error setting backup schedule config: {e}")
            raise
    
    async def _create_or_update_schedule_task(self, schedule_time: str, keep_days: int):
        """Create or update backup schedule task in database."""
        try:
            async with AsyncSessionLocal() as db:
                # Check if backup task already exists
                result = await db.execute(
                    select(ScheduleSettings).where(
                        ScheduleSettings.task_name == "backup"
                    )
                )
                existing_task = result.scalar_one_or_none()
                
                # Parse schedule time
                hour, minute = map(int, schedule_time.split(':'))
                
                if existing_task:
                    # Update existing task
                    existing_task.enabled = True
                    existing_task.hour = hour
                    existing_task.minute = minute
                    existing_task.task_config = {"keep_days": keep_days}
                    existing_task.next_run = self._calculate_next_run(hour, minute)
                    existing_task.updated_at = datetime.utcnow()
                    logger.info(f"Updated existing backup task: {existing_task.id}")
                else:
                    # Create new task
                    new_task = ScheduleSettings(
                        task_name="backup",
                        schedule_type="daily",
                        enabled=True,
                        hour=hour,
                        minute=minute,
                        task_config={"keep_days": keep_days},
                        next_run=self._calculate_next_run(hour, minute),
                        created_at=datetime.utcnow(),
                        updated_at=datetime.utcnow()
                    )
                    db.add(new_task)
                    logger.info(f"Created new backup task at {schedule_time}")
                
                try:
                    await db.commit()
                except Exception as e:
                    await db.rollback()
                    logger.error(f"Failed to commit backup schedule task create/update: {e}")
                    raise
                
        except Exception as e:
            logger.error(f"Error creating/updating schedule task: {e}")
            raise
    
    async def _disable_schedule_task(self):
        """Disable backup schedule task in database."""
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(ScheduleSettings).where(
                        ScheduleSettings.task_name == "backup"
                    )
                )
                task = result.scalar_one_or_none()
                
                if task:
                    task.enabled = False
                    task.updated_at = datetime.utcnow()
                    try:
                        await db.commit()
                    except Exception as e:
                        await db.rollback()
                        logger.error(f"Failed to commit disabling schedule task: {e}")
                        raise
                    logger.info("Disabled backup schedule task")
                
        except Exception as e:
            logger.error(f"Error disabling schedule task: {e}")
            raise
    
    def _calculate_next_run(self, hour: int, minute: int) -> datetime:
        """Calculate next run time for backup task."""
        try:
            now = datetime.utcnow().replace(tzinfo=pytz.UTC)
            
            # Set to today at specified time
            next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            
            # If time has passed today, schedule for tomorrow
            if next_run <= now:
                next_run += timedelta(days=1)
            
            return next_run.replace(tzinfo=None)
            
        except Exception as e:
            logger.error(f"Error calculating next run: {e}")
            # Fallback to tomorrow at 3 AM
            return (datetime.utcnow() + timedelta(days=1)).replace(
                hour=3, minute=0, second=0, microsecond=0
            )
    
    async def get_backup_history(self) -> Dict[str, Any]:
        """Get backup history and statistics."""
        try:
            backups_dir = self.project_root / "backups"
            
            if not backups_dir.exists():
                return {
                    "total_backups": 0,
                    "total_size_mb": 0,
                    "latest_backup": None,
                    "oldest_backup": None,
                    "backups": []
                }
            
            backups = []
            total_size = 0
            
            for backup_file in backups_dir.glob("*.tar.gz"):
                stat = backup_file.stat()
                size_mb = stat.st_size / (1024 * 1024)
                total_size += size_mb
                
                backups.append({
                    "filename": backup_file.name,
                    "size_mb": round(size_mb, 2),
                    "created_at": datetime.fromtimestamp(stat.st_ctime),
                    "age_days": (datetime.utcnow() - datetime.fromtimestamp(stat.st_ctime)).days
                })
            
            # Sort by creation time
            backups.sort(key=lambda x: x["created_at"], reverse=True)
            
            return {
                "total_backups": len(backups),
                "total_size_mb": round(total_size, 2),
                "latest_backup": backups[0] if backups else None,
                "oldest_backup": backups[-1] if backups else None,
                "backups": backups[:10]  # Return latest 10
            }
            
        except Exception as e:
            logger.error(f"Error getting backup history: {e}")
            return {
                "total_backups": 0,
                "total_size_mb": 0,
                "latest_backup": None,
                "oldest_backup": None,
                "backups": [],
                "error": str(e)
            }
    
    async def cleanup_old_backups(self, keep_days: int = 30) -> Dict[str, Any]:
        """Clean up backup files older than specified days."""
        try:
            backups_dir = self.project_root / "backups"
            
            if not backups_dir.exists():
                return {"cleaned": 0, "message": "Backups directory not found"}
            
            cutoff_date = datetime.utcnow() - timedelta(days=keep_days)
            cleaned_count = 0
            cleaned_size = 0
            
            for backup_file in backups_dir.glob("*.tar.gz"):
                file_time = datetime.fromtimestamp(backup_file.stat().st_mtime)
                
                if file_time < cutoff_date:
                    file_size = backup_file.stat().st_size / (1024 * 1024)
                    backup_file.unlink()
                    cleaned_count += 1
                    cleaned_size += file_size
                    logger.info(f"Deleted old backup: {backup_file.name}")
            
            return {
                "cleaned": cleaned_count,
                "size_mb": round(cleaned_size, 2),
                "message": f"Deleted {cleaned_count} old backup files"
            }
            
        except Exception as e:
            logger.error(f"Error cleaning up old backups: {e}")
            return {"cleaned": 0, "error": str(e)}


# Global backup service instance
_backup_service: Optional[BackupService] = None


def get_backup_service() -> BackupService:
    """Get the global backup service instance."""
    global _backup_service
    if _backup_service is None:
        _backup_service = BackupService()
    return _backup_service 