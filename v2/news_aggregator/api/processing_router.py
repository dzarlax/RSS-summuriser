"""Processing API router - handles news processing operations."""

import asyncio
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException

from ..orchestrator import NewsOrchestrator


router = APIRouter()


@router.post("/run")
async def trigger_processing(background_tasks: BackgroundTasks):
    """Trigger news processing cycle in background."""
    try:
        print("📰 Starting news processing cycle...")
        
        # Create orchestrator and run processing
        orchestrator = NewsOrchestrator()
        await orchestrator.start()
        
        # Run processing in background
        task = asyncio.create_task(orchestrator.run_full_cycle())
        
        return {
            "success": True,
            "message": "News processing started",
            "started_at": datetime.utcnow().isoformat(),
            "status": "running"
        }
        
    except Exception as e:
        print(f"Error starting processing: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start processing: {str(e)}")


@router.get("/status")  
async def get_processing_status():
    """Get current processing status."""
    try:
        orchestrator = NewsOrchestrator()
        stats = orchestrator.get_queue_stats()
        
        return {
            "queue_stats": stats,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        return {
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }

