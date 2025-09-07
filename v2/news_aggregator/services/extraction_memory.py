"""Simple extraction memory service without complex database operations."""

import json
import asyncio
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class ExtractionMemoryEntry:
    """Memory entry for extraction patterns."""
    domain: str
    selector_pattern: str
    extraction_strategy: str
    success_count: int = 0
    failure_count: int = 0
    success_rate: float = 0.0
    quality_score_avg: float = 0.0
    content_length_avg: int = 0
    discovered_by: str = "manual"
    is_stable: bool = False
    consecutive_successes: int = 0
    consecutive_failures: int = 0
    first_success_at: Optional[datetime] = None
    last_success_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class ExtractionAttempt:
    """Record of an extraction attempt."""
    article_url: str
    domain: str
    extraction_strategy: str
    selector_used: Optional[str] = None
    success: bool = False
    content_length: Optional[int] = None
    quality_score: Optional[float] = None
    extraction_time_ms: Optional[int] = None
    error_message: Optional[str] = None
    ai_analysis_triggered: bool = False
    ai_analysis: Optional[Dict] = None
    user_agent: Optional[str] = None
    http_status_code: Optional[int] = None


class ExtractionMemoryService:
    """Simple in-memory extraction learning service."""
    
    def __init__(self):
        # In-memory storage for now
        self._patterns: Dict[str, List[ExtractionMemoryEntry]] = {}
        self._attempts: List[ExtractionAttempt] = []
        self._domain_stats: Dict[str, Dict] = {}
    
    async def record_extraction_attempt(self, attempt: ExtractionAttempt) -> bool:
        """Record an extraction attempt."""
        try:
            self._attempts.append(attempt)
            
            # Update in-memory stats
            domain = attempt.domain
            if domain not in self._domain_stats:
                self._domain_stats[domain] = {
                    'total_attempts': 0,
                    'successful_attempts': 0,
                    'methods': {}
                }
            
            stats = self._domain_stats[domain]
            stats['total_attempts'] += 1
            
            if attempt.success:
                stats['successful_attempts'] += 1
                
                # Update method stats
                method = attempt.extraction_strategy
                if method not in stats['methods']:
                    stats['methods'][method] = {'attempts': 0, 'successes': 0}
                
                stats['methods'][method]['attempts'] += 1
                stats['methods'][method]['successes'] += 1
                
                # Add pattern if selector was used
                if attempt.selector_used:
                    await self._add_successful_pattern(
                        domain, attempt.selector_used, attempt.extraction_strategy,
                        attempt.quality_score or 0, attempt.content_length or 0
                    )
            else:
                # Update method stats for failures
                method = attempt.extraction_strategy
                if method not in stats['methods']:
                    stats['methods'][method] = {'attempts': 0, 'successes': 0}
                
                stats['methods'][method]['attempts'] += 1
            
            print(f"  📝 Recorded {attempt.extraction_strategy} {'success' if attempt.success else 'failure'} for {domain}")
            return True
            
        except Exception as e:
            print(f"❌ Error recording extraction attempt: {e}")
            return False
    
    async def _add_successful_pattern(
        self, domain: str, selector: str, strategy: str,
        quality_score: float, content_length: int
    ):
        """Add or update successful pattern."""
        if domain not in self._patterns:
            self._patterns[domain] = []
        
        # Find existing pattern
        existing = None
        for pattern in self._patterns[domain]:
            if pattern.selector_pattern == selector and pattern.extraction_strategy == strategy:
                existing = pattern
                break
        
        if existing:
            # Update existing pattern
            existing.success_count += 1
            existing.consecutive_successes += 1
            existing.consecutive_failures = 0
            
            # Update averages
            total_successes = existing.success_count
            existing.quality_score_avg = (
                (existing.quality_score_avg * (total_successes - 1) + quality_score) / 
                total_successes
            )
            existing.content_length_avg = int(
                (existing.content_length_avg * (total_successes - 1) + content_length) / 
                total_successes
            )
            
            # Recalculate success rate
            total_attempts = existing.success_count + existing.failure_count
            existing.success_rate = (existing.success_count / total_attempts) * 100 if total_attempts > 0 else 0
            
            existing.is_stable = existing.consecutive_successes >= 3
            existing.last_success_at = datetime.utcnow()
        else:
            # Create new pattern
            pattern = ExtractionMemoryEntry(
                domain=domain,
                selector_pattern=selector,
                extraction_strategy=strategy,
                success_count=1,
                failure_count=0,
                success_rate=100.0,
                quality_score_avg=quality_score,
                content_length_avg=content_length,
                consecutive_successes=1,
                consecutive_failures=0,
                is_stable=False,
                first_success_at=datetime.utcnow(),
                last_success_at=datetime.utcnow(),
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            self._patterns[domain].append(pattern)
        
        print(f"  🎯 Updated pattern: {selector[:40]}... for {domain}")

    async def _add_failed_pattern(
        self, domain: str, selector: str, strategy: str
    ) -> None:
        """Record failed usage of an existing pattern to decrease its weight."""
        if not selector:
            return
        if domain not in self._patterns:
            self._patterns[domain] = []
        # Find existing pattern or create a new failed one
        existing = None
        for pattern in self._patterns[domain]:
            if pattern.selector_pattern == selector and pattern.extraction_strategy == strategy:
                existing = pattern
                break
        if existing:
            existing.failure_count += 1
            existing.consecutive_failures += 1
            existing.consecutive_successes = 0
            total_attempts = existing.success_count + existing.failure_count
            existing.success_rate = (existing.success_count / total_attempts) * 100 if total_attempts > 0 else 0
            existing.is_stable = False
            existing.updated_at = datetime.utcnow()
        else:
            # Create a new record with one failure to track negatives
            self._patterns[domain].append(
                ExtractionMemoryEntry(
                    domain=domain,
                    selector_pattern=selector,
                    extraction_strategy=strategy,
                    success_count=0,
                    failure_count=1,
                    success_rate=0.0,
                    is_stable=False,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )
            )

    async def degrade_pattern(self, domain: str, selector: str, strategy: str) -> None:
        """Public API to decrease a selector's weight after poor result."""
        try:
            await self._add_failed_pattern(domain, selector, strategy)
            print(f"  ⬇️ Degraded pattern for {domain}: {selector[:40]}... ({strategy})")
        except Exception as e:
            print(f"❌ Error degrading pattern: {e}")

    async def record_date_selector_success(self, domain: str, selector: str) -> None:
        """Record successful date extraction using a selector (stored as 'date_selector')."""
        await self._add_successful_pattern(domain, selector, 'date_selector', quality_score=0.0, content_length=0)

    async def record_date_selector_failure(self, domain: str, selector: str) -> None:
        """Record failed date extraction for a selector (stored as 'date_selector')."""
        await self._add_failed_pattern(domain, selector, 'date_selector')

    async def get_best_date_selectors_for_domain(self, domain: str, limit: int = 5) -> List[ExtractionMemoryEntry]:
        """Return best date selectors learned for the domain."""
        return await self.get_best_patterns_for_domain(domain, strategy='date_selector', limit=limit)
    
    async def get_best_patterns_for_domain(
        self, domain: str, strategy: Optional[str] = None, limit: int = 5
    ) -> List[ExtractionMemoryEntry]:
        """Get best extraction patterns for a domain."""
        if domain not in self._patterns:
            return []
        
        patterns = self._patterns[domain]
        
        if strategy:
            patterns = [p for p in patterns if p.extraction_strategy == strategy]
        
        # Sort by success rate, then by consecutive successes
        patterns = sorted(
            patterns,
            key=lambda p: (p.success_rate, p.consecutive_successes, p.success_count),
            reverse=True
        )
        
        return patterns[:limit]
    
    async def get_domain_extraction_stats(self, domain: str) -> Dict:
        """Get extraction statistics for a domain."""
        if domain not in self._domain_stats:
            return {
                'domain': domain,
                'total_attempts': 0,
                'successful_attempts': 0,
                'success_rate': 0.0,
                'avg_extraction_time_ms': 0,
                'avg_quality_score': 0,
                'last_attempt': None,
                'methods': []
            }
        
        stats = self._domain_stats[domain]
        success_rate = (
            (stats['successful_attempts'] / stats['total_attempts'] * 100) 
            if stats['total_attempts'] > 0 else 0
        )
        
        methods = []
        for method_name, method_stats in stats['methods'].items():
            method_success_rate = (
                (method_stats['successes'] / method_stats['attempts'] * 100) 
                if method_stats['attempts'] > 0 else 0
            )
            methods.append({
                'strategy': method_name,
                'attempts': method_stats['attempts'],
                'successes': method_stats['successes'],
                'success_rate': method_success_rate,
                'avg_time_ms': 0  # Not tracked in simple version
            })
        
        return {
            'domain': domain,
            'total_attempts': stats['total_attempts'],
            'successful_attempts': stats['successful_attempts'],
            'success_rate': success_rate,
            'avg_extraction_time_ms': 0,  # Not tracked in simple version
            'avg_quality_score': 0,  # Not tracked in simple version
            'last_attempt': None,  # Not tracked in simple version
            'methods': methods
        }
    
    async def record_ai_pattern_discovery(
        self, domain: str, patterns: List[Dict], analysis_type: str = "selector_discovery"
    ) -> bool:
        """Record AI-discovered patterns."""
        try:
            for pattern_data in patterns:
                selector = pattern_data.get('selector')
                strategy = pattern_data.get('strategy', 'ai_discovered')
                confidence = pattern_data.get('confidence', 0.5)
                
                if selector:
                    if domain not in self._patterns:
                        self._patterns[domain] = []
                    
                    # Add AI-discovered pattern
                    pattern = ExtractionMemoryEntry(
                        domain=domain,
                        selector_pattern=selector,
                        extraction_strategy=strategy,
                        success_count=0,
                        failure_count=0,
                        success_rate=confidence * 100,
                        discovered_by='ai',
                        created_at=datetime.utcnow(),
                        updated_at=datetime.utcnow()
                    )
                    self._patterns[domain].append(pattern)
            
            print(f"  🤖 Recorded {len(patterns)} AI-discovered patterns for {domain}")
            return True
            
        except Exception as e:
            print(f"❌ Error recording AI patterns: {e}")
            return False
    
    async def get_domains_needing_ai_analysis(self, limit: int = 10) -> List[str]:
        """Get domains that need AI analysis."""
        domains_needing_help = []
        
        for domain, stats in self._domain_stats.items():
            success_rate = (
                (stats['successful_attempts'] / stats['total_attempts'] * 100) 
                if stats['total_attempts'] > 0 else 0
            )
            
            # Domains with low success rate or many attempts need help
            if (success_rate < 50 and stats['total_attempts'] >= 3) or stats['total_attempts'] == 0:
                domains_needing_help.append(domain)
        
        return domains_needing_help[:limit]
    
    async def get_extraction_efficiency_stats(self) -> Dict:
        """Get overall extraction efficiency statistics."""
        if not self._domain_stats:
            return {
                'period': '7 days',
                'total_attempts': 0,
                'successful_attempts': 0,
                'success_rate': 0,
                'domains_processed': 0,
                'avg_extraction_time_ms': 0,
                'ai_analyses': 0,
                'patterns_discovered': 0,
                'patterns_successful': 0,
                'ai_cost_effectiveness': 0
            }
        
        total_attempts = sum(stats['total_attempts'] for stats in self._domain_stats.values())
        total_successes = sum(stats['successful_attempts'] for stats in self._domain_stats.values())
        success_rate = (total_successes / total_attempts * 100) if total_attempts > 0 else 0
        
        ai_patterns_count = sum(
            len([p for p in patterns if p.discovered_by == 'ai'])
            for patterns in self._patterns.values()
        )
        
        return {
            'period': 'session',
            'total_attempts': total_attempts,
            'successful_attempts': total_successes,
            'success_rate': success_rate,
            'domains_processed': len(self._domain_stats),
            'avg_extraction_time_ms': 0,
            'ai_analyses': 0,  # Not tracked in simple version
            'patterns_discovered': ai_patterns_count,
            'patterns_successful': 0,  # Not tracked in simple version
            'ai_cost_effectiveness': 0  # Not tracked in simple version
        }
    
    async def get_successful_pattern(self, domain: str) -> Optional[ExtractionMemoryEntry]:
        """Get the most successful pattern for a domain."""
        if domain not in self._patterns:
            return None
        
        # Find patterns with success rate > 50% and success count > 0
        successful_patterns = [
            pattern for pattern in self._patterns[domain]
            if pattern.success_count > 0 and pattern.success_rate > 50.0
        ]
        
        if not successful_patterns:
            return None
        
        # Sort by success rate, then by success count
        successful_patterns.sort(
            key=lambda p: (p.success_rate, p.success_count), 
            reverse=True
        )
        
        return successful_patterns[0]


# Global instance
_extraction_memory_service = None

async def get_extraction_memory() -> ExtractionMemoryService:
    """Get or create extraction memory service instance."""
    global _extraction_memory_service
    if _extraction_memory_service is None:
        _extraction_memory_service = ExtractionMemoryService()
    return _extraction_memory_service