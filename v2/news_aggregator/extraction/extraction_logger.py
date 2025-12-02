"""Structured logging for content extraction with telemetry."""

import logging
import time
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime
from functools import wraps

# Configure structured logger
logger = logging.getLogger('extraction')


@dataclass
class ExtractionMetrics:
    """Metrics collected during extraction."""
    domain: str
    url: str
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None

    # Strategy tracking
    strategies_tried: list = field(default_factory=list)
    successful_strategy: Optional[str] = None

    # Performance
    total_duration_ms: Optional[int] = None
    content_length: Optional[int] = None
    quality_score: Optional[float] = None

    # Errors
    errors: list = field(default_factory=list)

    def complete(self, success: bool, strategy: Optional[str] = None,
                 content_length: int = 0, quality_score: float = 0):
        """Mark extraction as complete."""
        self.end_time = time.time()
        self.total_duration_ms = int((self.end_time - self.start_time) * 1000)
        self.successful_strategy = strategy if success else None
        self.content_length = content_length
        self.quality_score = quality_score

    def add_strategy_attempt(self, strategy: str, success: bool,
                            duration_ms: int, error: Optional[str] = None):
        """Record a strategy attempt."""
        self.strategies_tried.append({
            'strategy': strategy,
            'success': success,
            'duration_ms': duration_ms,
            'error': error,
            'timestamp': datetime.utcnow().isoformat()
        })
        if error:
            self.errors.append(f"{strategy}: {error}")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging."""
        return {
            'domain': self.domain,
            'url': self.url[:100],  # Truncate long URLs
            'duration_ms': self.total_duration_ms,
            'strategies_tried': len(self.strategies_tried),
            'successful_strategy': self.successful_strategy,
            'content_length': self.content_length,
            'quality_score': self.quality_score,
            'errors_count': len(self.errors)
        }


class ExtractionLogger:
    """Structured logger for extraction operations."""

    def __init__(self):
        self._current_metrics: Dict[str, ExtractionMetrics] = {}

        # Telemetry aggregates
        self._total_extractions = 0
        self._successful_extractions = 0
        self._strategy_stats: Dict[str, Dict[str, int]] = {}
        self._domain_errors: Dict[str, int] = {}

    def start_extraction(self, url: str, domain: str) -> ExtractionMetrics:
        """Start tracking an extraction operation."""
        metrics = ExtractionMetrics(domain=domain, url=url)
        self._current_metrics[url] = metrics
        logger.info(f"Starting extraction", extra={
            'event': 'extraction_start',
            'domain': domain,
            'url': url[:80]
        })
        return metrics

    def log_strategy_attempt(self, url: str, strategy: str,
                            success: bool, duration_ms: int,
                            error: Optional[str] = None):
        """Log a strategy attempt."""
        metrics = self._current_metrics.get(url)
        if metrics:
            metrics.add_strategy_attempt(strategy, success, duration_ms, error)

        # Update strategy stats
        if strategy not in self._strategy_stats:
            self._strategy_stats[strategy] = {'attempts': 0, 'successes': 0}
        self._strategy_stats[strategy]['attempts'] += 1
        if success:
            self._strategy_stats[strategy]['successes'] += 1

        log_level = logging.DEBUG if success else logging.WARNING
        logger.log(log_level, f"Strategy {strategy}: {'success' if success else 'failed'}", extra={
            'event': 'strategy_attempt',
            'strategy': strategy,
            'success': success,
            'duration_ms': duration_ms,
            'error': error
        })

    def complete_extraction(self, url: str, success: bool,
                           strategy: Optional[str] = None,
                           content_length: int = 0,
                           quality_score: float = 0):
        """Complete an extraction and log results."""
        metrics = self._current_metrics.pop(url, None)

        self._total_extractions += 1
        if success:
            self._successful_extractions += 1
        else:
            # Track domain errors
            domain = metrics.domain if metrics else 'unknown'
            self._domain_errors[domain] = self._domain_errors.get(domain, 0) + 1

        if metrics:
            metrics.complete(success, strategy, content_length, quality_score)

            log_level = logging.INFO if success else logging.WARNING
            logger.log(log_level, f"Extraction {'completed' if success else 'failed'}", extra={
                'event': 'extraction_complete',
                **metrics.to_dict()
            })

    def log_error(self, url: str, error: str, strategy: Optional[str] = None):
        """Log an extraction error."""
        logger.error(f"Extraction error: {error}", extra={
            'event': 'extraction_error',
            'url': url[:80],
            'strategy': strategy,
            'error': error
        })

    def get_telemetry(self) -> Dict[str, Any]:
        """Get current telemetry data."""
        success_rate = (
            self._successful_extractions / self._total_extractions * 100
            if self._total_extractions > 0 else 0
        )

        strategy_performance = {}
        for strategy, stats in self._strategy_stats.items():
            rate = stats['successes'] / stats['attempts'] * 100 if stats['attempts'] > 0 else 0
            strategy_performance[strategy] = {
                'attempts': stats['attempts'],
                'successes': stats['successes'],
                'success_rate': round(rate, 1)
            }

        # Top error domains
        top_error_domains = sorted(
            self._domain_errors.items(),
            key=lambda x: x[1],
            reverse=True
        )[:10]

        return {
            'total_extractions': self._total_extractions,
            'successful_extractions': self._successful_extractions,
            'success_rate': round(success_rate, 1),
            'strategy_performance': strategy_performance,
            'top_error_domains': dict(top_error_domains),
            'active_extractions': len(self._current_metrics)
        }

    def reset_telemetry(self):
        """Reset telemetry counters."""
        self._total_extractions = 0
        self._successful_extractions = 0
        self._strategy_stats.clear()
        self._domain_errors.clear()


# Global logger instance
_extraction_logger: Optional[ExtractionLogger] = None


def get_extraction_logger() -> ExtractionLogger:
    """Get or create the extraction logger instance."""
    global _extraction_logger
    if _extraction_logger is None:
        _extraction_logger = ExtractionLogger()
    return _extraction_logger
