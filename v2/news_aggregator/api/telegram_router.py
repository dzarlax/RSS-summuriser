"""Telegram API router - handles Telegram digest operations."""

from datetime import datetime

from fastapi import APIRouter, HTTPException

from ..orchestrator import NewsOrchestrator


router = APIRouter()


@router.post("/send-digest")
async def send_telegram_digest():
    """Generate and send Telegram digest."""
    try:
        print("📱 Generating Telegram digest...")
        
        orchestrator = NewsOrchestrator()
        await orchestrator.start()
        
        # Generate and send digest
        result = await orchestrator.send_telegram_digest()
        
        await orchestrator.stop()
        
        success = result.get('success', False)
        return {
            "success": success,
            "message": "Telegram digest sent successfully" if success else "Digest generation failed",
            "result": result,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        print(f"Error sending Telegram digest: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to send digest: {str(e)}")

