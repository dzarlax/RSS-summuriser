"""Dead Letter Queue for failed article processing."""

import json
import time
import asyncio
from pathlib import Path
from typing import Any, Optional, List, Dict
from datetime import datetime
from enum import Enum
import aiofiles

from ..config import settings


class FailureReason(Enum):
    """Reasons for article processing failure."""
    AI_SERVICE_UNAVAILABLE = "ai_service_unavailable"
    EXTRACTION_FAILED = "extraction_failed"
    CONTENT_TOO_SHORT = "content_too_short"
    INVALID_URL = "invalid_url"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    UNKNOWN_ERROR = "unknown_error"


class DeadLetterQueue:
    """
    Dead Letter Queue for storing failed article processing attempts.

    Features:
    - Persistent storage on disk
    - Automatic retry with exponential backoff
    - Max retry attempts to prevent infinite loops
    - Categorization by failure reason
    - Automatic cleanup of old entries
    """

    def __init__(self, queue_dir: Optional[str] = None, max_retries: int = 3):
        """
        Initialize Dead Letter Queue.

        Args:
            queue_dir: Directory for queue storage (default: cache_dir/dlq)
            max_retries: Maximum retry attempts before permanent failure
        """
        base_dir = Path(queue_dir or settings.cache_dir)
        self.queue_dir = base_dir / "dlq"
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        self.max_retries = max_retries
        self._lock = asyncio.Lock()

    def _get_queue_file(self, reason: FailureReason) -> Path:
        """Get queue file path for failure reason."""
        return self.queue_dir / f"{reason.value}.jsonl"

    async def add(
        self,
        article_data: Dict[str, Any],
        reason: FailureReason,
        error_message: str = "",
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Add failed article to queue.

        Args:
            article_data: Article data that failed processing
            reason: Reason for failure
            error_message: Error message/description
            metadata: Additional metadata about the failure
        """
        entry = {
            "article_data": article_data,
            "reason": reason.value,
            "error_message": error_message,
            "metadata": metadata or {},
            "first_failed_at": time.time(),
            "last_retry_at": None,
            "retry_count": 0,
            "created_at": datetime.utcnow().isoformat()
        }

        queue_file = self._get_queue_file(reason)

        async with self._lock:
            try:
                async with aiofiles.open(queue_file, 'a', encoding='utf-8') as f:
                    await f.write(json.dumps(entry, ensure_ascii=False) + '\n')
            except Exception as e:
                print(f"  ⚠️ Failed to add to DLQ: {e}")

    async def get_retryable_entries(
        self,
        reason: Optional[FailureReason] = None,
        min_delay: float = 300.0  # 5 minutes default
    ) -> List[Dict[str, Any]]:
        """
        Get entries ready for retry.

        Args:
            reason: Filter by failure reason (None = all reasons)
            min_delay: Minimum seconds since last retry

        Returns:
            List of retryable entries with article data
        """
        now = time.time()
        retryable = []

        queue_files = (
            [self._get_queue_file(reason)] if reason
            else list(self.queue_dir.glob("*.jsonl"))
        )

        for queue_file in queue_files:
            try:
                async with aiofiles.open(queue_file, 'r', encoding='utf-8') as f:
                    async for line in f:
                        try:
                            entry = json.loads(line.strip())

                            # Check if max retries exceeded
                            if entry.get('retry_count', 0) >= self.max_retries:
                                continue

                            # Check if enough time has passed since last retry
                            last_retry = entry.get('last_retry_at') or entry.get('first_failed_at', 0)
                            if now - last_retry < min_delay:
                                continue

                            retryable.append(entry)

                        except (json.JSONDecodeError, KeyError):
                            continue

            except FileNotFoundError:
                continue

        return retryable

    async def mark_retry(self, entry: Dict[str, Any]) -> None:
        """
        Mark entry as retried.

        Args:
            entry: Queue entry to mark
        """
        entry['retry_count'] = entry.get('retry_count', 0) + 1
        entry['last_retry_at'] = time.time()

        # Remove from queue and re-add with updated count
        reason = FailureReason(entry.get('reason', FailureReason.UNKNOWN_ERROR.value))
        await self._remove_entry(entry, reason)

        if entry['retry_count'] < self.max_retries:
            # Re-add for future retry
            await self.add(
                entry['article_data'],
                reason,
                entry.get('error_message', ''),
                entry.get('metadata', {})
            )
        else:
            # Max retries reached - archive permanently failed
            await self._archive_permanent_failure(entry)

    async def _remove_entry(self, entry: Dict[str, Any], reason: FailureReason) -> bool:
        """Remove entry from queue file."""
        queue_file = self._get_queue_file(reason)
        entry_id = self._get_entry_id(entry)

        try:
            # Read all entries
            entries = []
            async with aiofiles.open(queue_file, 'r', encoding='utf-8') as f:
                async for line in f:
                    try:
                        entry_data = json.loads(line.strip())
                        if self._get_entry_id(entry_data) != entry_id:
                            entries.append(line.strip())
                    except json.JSONDecodeError:
                        entries.append(line.strip())

            # Write back without the removed entry
            async with aiofiles.open(queue_file, 'w', encoding='utf-8') as f:
                for line in entries:
                    await f.write(line + '\n')

            return True

        except FileNotFoundError:
            return False

    async def _archive_permanent_failure(self, entry: Dict[str, Any]) -> None:
        """Archive permanently failed entries."""
        archive_file = self.queue_dir / "permanent_failures.jsonl"

        try:
            async with aiofiles.open(archive_file, 'a', encoding='utf-8') as f:
                await f.write(json.dumps(entry, ensure_ascii=False) + '\n')
        except Exception as e:
            print(f"  ⚠️ Failed to archive permanent failure: {e}")

    def _get_entry_id(self, entry: Dict[str, Any]) -> str:
        """Generate unique ID for entry based on article data."""
        article = entry.get('article_data', {})
        # Use URL or ID as identifier
        identifier = article.get('url') or article.get('id') or str(article)
        import hashlib
        return hashlib.md5(str(identifier).encode()).hexdigest()

    async def get_stats(self) -> Dict[str, Any]:
        """Get queue statistics."""
        stats = {
            'total_entries': 0,
            'by_reason': {},
            'ready_for_retry': 0,
            'permanent_failures': 0
        }

        for queue_file in self.queue_dir.glob("*.jsonl"):
            if queue_file.name == "permanent_failures.jsonl":
                continue

            reason = queue_file.stem
            count = 0

            try:
                async with aiofiles.open(queue_file, 'r', encoding='utf-8') as f:
                    async for line in f:
                        count += 1

                stats['by_reason'][reason] = count
                stats['total_entries'] += count

            except FileNotFoundError:
                pass

        # Count permanent failures
        permanent_file = self.queue_dir / "permanent_failures.jsonl"
        if permanent_file.exists():
            try:
                async with aiofiles.open(permanent_file, 'r', encoding='utf-8') as f:
                    async for line in f:
                        stats['permanent_failures'] += 1
            except FileNotFoundError:
                pass

        # Count retryable entries
        retryable = await self.get_retryable_entries()
        stats['ready_for_retry'] = len(retryable)

        return stats

    async def clear_old_entries(self, max_age_days: int = 7) -> int:
        """
        Clear entries older than specified days.

        Args:
            max_age_days: Maximum age in days

        Returns:
            Number of entries removed
        """
        now = time.time()
        max_age_seconds = max_age_days * 24 * 3600
        removed = 0

        for queue_file in self.queue_dir.glob("*.jsonl"):
            if queue_file.name == "permanent_failures.jsonl":
                continue

            try:
                entries = []
                async with aiofiles.open(queue_file, 'r', encoding='utf-8') as f:
                    async for line in f:
                        try:
                            entry = json.loads(line.strip())
                            first_failed = entry.get('first_failed_at', 0)

                            if now - first_failed > max_age_seconds:
                                removed += 1
                            else:
                                entries.append(line.strip())

                        except json.JSONDecodeError:
                            entries.append(line.strip())

                # Write back filtered entries
                async with aiofiles.open(queue_file, 'w', encoding='utf-8') as f:
                    for line in entries:
                        await f.write(line + '\n')

            except FileNotFoundError:
                continue

        if removed > 0:
            print(f"  🗑️ Cleared {removed} old entries from DLQ (older than {max_age_days} days)")

        return removed


# Global DLQ instance
_dlq: Optional[DeadLetterQueue] = None


def get_dead_letter_queue() -> DeadLetterQueue:
    """Get global Dead Letter Queue instance."""
    global _dlq

    if _dlq is None:
        _dlq = DeadLetterQueue()

    return _dlq
