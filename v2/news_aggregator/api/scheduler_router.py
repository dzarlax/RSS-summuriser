"""Scheduler API router - handles task scheduling operations."""

from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from ..database import get_db
from ..models import ScheduleSettings


router = APIRouter()


# ============================================================================
# Pydantic Models for Scheduler
# ============================================================================

class ScheduleUpdateRequest(BaseModel):
    enabled: Optional[bool] = None
    schedule_type: Optional[str] = None
    hour: Optional[int] = None
    minute: Optional[int] = None
    weekdays: Optional[str] = None
    timezone: Optional[str] = None


# ============================================================================
# Scheduler Endpoints
# ============================================================================

@router.get("/settings")
async def get_schedule_settings(db: AsyncSession = Depends(get_db)):
    """Get all scheduled task settings."""
    try:
        result = await db.execute(select(ScheduleSettings))
        settings = result.scalars().all()
        
        return {
            "settings": [
                {
                    "id": setting.id,
                    "task_name": setting.task_name,
                    "enabled": setting.enabled,
                    "schedule_type": setting.schedule_type,
                    "hour": setting.hour,
                    "minute": setting.minute,
                    "weekdays": setting.weekdays,
                    "timezone": setting.timezone,
                    "last_run": setting.last_run.isoformat() if setting.last_run else None,
                    "next_run": setting.next_run.isoformat() if setting.next_run else None,
                    "is_running": setting.is_running,
                    "created_at": setting.created_at.isoformat() if setting.created_at else None,
                    "updated_at": setting.updated_at.isoformat() if setting.updated_at else None
                }
                for setting in settings
            ],
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get settings: {str(e)}")


@router.put("/settings/{task_name}")
async def update_schedule_setting(
    task_name: str,
    request: ScheduleUpdateRequest,
    db: AsyncSession = Depends(get_db)
):
    """Update schedule settings for a task."""
    try:
        # Get existing setting
        result = await db.execute(
            select(ScheduleSettings).where(ScheduleSettings.task_name == task_name)
        )
        setting = result.scalar_one_or_none()
        
        if not setting:
            raise HTTPException(status_code=404, detail="Schedule setting not found")
        
        # Update fields
        update_data = {}
        if request.enabled is not None:
            update_data['enabled'] = request.enabled
        if request.schedule_type is not None:
            update_data['schedule_type'] = request.schedule_type
        if request.hour is not None:
            update_data['hour'] = request.hour
        if request.minute is not None:
            update_data['minute'] = request.minute
        if request.weekdays is not None:
            update_data['weekdays'] = request.weekdays
        if request.timezone is not None:
            update_data['timezone'] = request.timezone
        
        if update_data:
            update_data['updated_at'] = datetime.utcnow()
            
            await db.execute(
                update(ScheduleSettings)
                .where(ScheduleSettings.task_name == task_name)
                .values(**update_data)
            )
            await db.commit()
        
        # Get updated setting
        result = await db.execute(
            select(ScheduleSettings).where(ScheduleSettings.task_name == task_name)
        )
        updated_setting = result.scalar_one()
        
        return {
            "id": updated_setting.id,
            "task_name": updated_setting.task_name,
            "enabled": updated_setting.enabled,
            "schedule_type": updated_setting.schedule_type,
            "hour": updated_setting.hour,
            "minute": updated_setting.minute,
            "weekdays": updated_setting.weekdays,
            "timezone": updated_setting.timezone,
            "updated_at": updated_setting.updated_at.isoformat(),
            "message": "Schedule updated successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update schedule: {str(e)}")


@router.get("/status")
async def get_schedule_status(db: AsyncSession = Depends(get_db)):
    """Get current scheduler status."""
    try:
        # Get all enabled tasks
        result = await db.execute(
            select(ScheduleSettings).where(ScheduleSettings.enabled == True)
        )
        enabled_tasks = result.scalars().all()
        
        # Get running tasks
        running_result = await db.execute(
            select(ScheduleSettings).where(ScheduleSettings.is_running == True)
        )
        running_tasks = running_result.scalars().all()
        
        return {
            "enabled_tasks": len(enabled_tasks),
            "running_tasks": len(running_tasks),
            "tasks": [
                {
                    "task_name": task.task_name,
                    "enabled": task.enabled,
                    "is_running": task.is_running,
                    "last_run": task.last_run.isoformat() if task.last_run else None,
                    "next_run": task.next_run.isoformat() if task.next_run else None
                }
                for task in enabled_tasks
            ],
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get status: {str(e)}")

