"""Extraction memory service for persistent learning and optimization."""

import json
import asyncio
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta

import asyncpg
from ..config import settings
from ..core.exceptions import DatabaseError


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
    """Service for managing extraction learning and memory."""
    
    def __init__(self):
        self.cache_ttl = 3600  # 1 hour cache
        self._domain_cache: Dict[str, List[ExtractionMemoryEntry]] = {}
        self._cache_timestamps: Dict[str, datetime] = {}
    
    async def record_extraction_attempt(self, attempt: ExtractionAttempt) -> bool:
        """Record an extraction attempt in the database."""
        try:
            # Use asyncpg connection
            conn = await asyncpg.connect(settings.database_url)
            try:
                # Insert extraction attempt
                query = """
                    INSERT INTO extraction_attempts (
                        article_url, domain, extraction_strategy, selector_used,
                        success, content_length, quality_score, extraction_time_ms,
                        error_message, ai_analysis_triggered, ai_analysis,
                        user_agent, http_status_code
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                """
                
                await conn.execute(
                    query,
                    attempt.article_url,
                    attempt.domain,
                    attempt.extraction_strategy,
                    attempt.selector_used,
                    attempt.success,
                    attempt.content_length,
                    attempt.quality_score,
                    attempt.extraction_time_ms,
                    attempt.error_message,
                    attempt.ai_analysis_triggered,
                    json.dumps(attempt.ai_analysis) if attempt.ai_analysis else None,
                    attempt.user_agent,
                    attempt.http_status_code
                )
                
                # Update extraction patterns if selector was used
                if attempt.selector_used:
                    await self._update_extraction_pattern(
                        conn, attempt.domain, attempt.selector_used,
                        attempt.extraction_strategy, attempt.success,
                        attempt.quality_score, attempt.content_length
                    )
                
                # asyncpg auto-commits
                
                # Invalidate cache for this domain
                if attempt.domain in self._domain_cache:
                    del self._domain_cache[attempt.domain]
                    del self._cache_timestamps[attempt.domain]
                
                return True
            finally:
                await conn.close()
                
        except Exception as e:
            print(f"❌ Error recording extraction attempt: {e}")
            return False
    
    async def _update_extraction_pattern(
        self, conn, domain: str, selector: str, strategy: str,
        success: bool, quality_score: Optional[float], content_length: Optional[int]
    ):
        """Update or create extraction pattern record."""
        # Check if pattern exists
        check_query = """
            SELECT id, success_count, failure_count, quality_score_avg, 
                   content_length_avg, consecutive_successes, consecutive_failures
            FROM extraction_patterns 
            WHERE domain = $1 AND selector_pattern = $2 AND extraction_strategy = $3
        """
        
        result = await conn.fetchrow(check_query, domain, selector, strategy)
        
        if result:
            # Update existing pattern
            new_success_count = result['success_count'] + (1 if success else 0)
            new_failure_count = result['failure_count'] + (0 if success else 1)
            
            # Update averages
            if success and quality_score is not None:
                total_successes = new_success_count
                if total_successes > 1:
                    new_quality_avg = (
                        (result['quality_score_avg'] * (total_successes - 1) + quality_score) / 
                        total_successes
                    )
                else:
                    new_quality_avg = quality_score
            else:
                new_quality_avg = result['quality_score_avg']
            
            if success and content_length is not None:
                total_successes = new_success_count
                if total_successes > 1:
                    new_content_avg = int(
                        (result['content_length_avg'] * (total_successes - 1) + content_length) / 
                        total_successes
                    )
                else:
                    new_content_avg = content_length
            else:
                new_content_avg = result['content_length_avg']
            
            # Update consecutive counts
            if success:
                new_consecutive_successes = result['consecutive_successes'] + 1
                new_consecutive_failures = 0
            else:
                new_consecutive_successes = 0
                new_consecutive_failures = result['consecutive_failures'] + 1
            
            # Determine stability (5+ consecutive successes)
            is_stable = new_consecutive_successes >= 5
            
            update_query = """
                UPDATE extraction_patterns SET
                    success_count = $1,
                    failure_count = $2,
                    quality_score_avg = $3,
                    content_length_avg = $4,
                    consecutive_successes = $5,
                    consecutive_failures = $6,
                    is_stable = $7,
                    last_success_at = CASE WHEN $8 THEN NOW() ELSE last_success_at END,
                    updated_at = NOW()
                WHERE id = $9
            """
            
            await session.execute(
                update_query,
                new_success_count, new_failure_count, new_quality_avg, new_content_avg,
                new_consecutive_successes, new_consecutive_failures, is_stable,
                success, result['id']
            )
        else:
            # Create new pattern
            insert_query = """
                INSERT INTO extraction_patterns (
                    domain, selector_pattern, extraction_strategy,
                    success_count, failure_count, quality_score_avg, content_length_avg,
                    consecutive_successes, consecutive_failures, is_stable,
                    first_success_at, last_success_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            """
            
            success_count = 1 if success else 0
            failure_count = 0 if success else 1
            quality_avg = quality_score if success and quality_score else 0.0
            content_avg = content_length if success and content_length else 0
            consecutive_successes = 1 if success else 0
            consecutive_failures = 0 if success else 1
            is_stable = False  # New patterns are not stable yet
            
            now = datetime.utcnow() if success else None
            
            await session.execute(
                insert_query,
                domain, selector, strategy,
                success_count, failure_count, quality_avg, content_avg,
                consecutive_successes, consecutive_failures, is_stable,
                now, now
            )
    
    async def get_best_patterns_for_domain(
        self, domain: str, strategy: Optional[str] = None, limit: int = 5
    ) -> List[ExtractionMemoryEntry]:
        """Get best extraction patterns for a domain."""
        # Check cache first
        cache_key = f"{domain}_{strategy or 'all'}"
        if (cache_key in self._domain_cache and 
            cache_key in self._cache_timestamps and
            datetime.utcnow() - self._cache_timestamps[cache_key] < timedelta(seconds=self.cache_ttl)):
            return self._domain_cache[cache_key][:limit]
        
        try:
            # Use asyncpg connection
            conn = await asyncpg.connect(settings.database_url)
            try:
                if strategy:
                    query = """
                        SELECT domain, selector_pattern, extraction_strategy,
                               success_count, failure_count, success_rate,
                               quality_score_avg, content_length_avg, discovered_by,
                               is_stable, consecutive_successes, consecutive_failures,
                               first_success_at, last_success_at, created_at, updated_at
                        FROM extraction_patterns
                        WHERE domain = $1 AND extraction_strategy = $2
                        ORDER BY success_rate DESC, consecutive_successes DESC, success_count DESC
                        LIMIT $3
                    """
                    rows = await conn.fetch(query, domain, strategy, limit)
                else:
                    query = """
                        SELECT domain, selector_pattern, extraction_strategy,
                               success_count, failure_count, success_rate,
                               quality_score_avg, content_length_avg, discovered_by,
                               is_stable, consecutive_successes, consecutive_failures,
                               first_success_at, last_success_at, created_at, updated_at
                        FROM extraction_patterns
                        WHERE domain = $1
                        ORDER BY success_rate DESC, consecutive_successes DESC, success_count DESC
                        LIMIT $2
                    """
                    rows = await conn.fetch(query, domain, limit)
                
                patterns = []
                for row in rows:
                    pattern = ExtractionMemoryEntry(
                        domain=row['domain'],
                        selector_pattern=row['selector_pattern'],
                        extraction_strategy=row['extraction_strategy'],
                        success_count=row['success_count'],
                        failure_count=row['failure_count'],
                        success_rate=float(row['success_rate']) if row['success_rate'] else 0.0,
                        quality_score_avg=float(row['quality_score_avg']) if row['quality_score_avg'] else 0.0,
                        content_length_avg=row['content_length_avg'],
                        discovered_by=row['discovered_by'],
                        is_stable=row['is_stable'],
                        consecutive_successes=row['consecutive_successes'],
                        consecutive_failures=row['consecutive_failures'],
                        first_success_at=row['first_success_at'],
                        last_success_at=row['last_success_at'],
                        created_at=row['created_at'],
                        updated_at=row['updated_at']
                    )
                    patterns.append(pattern)
                
                # Cache results
                self._domain_cache[cache_key] = patterns
                self._cache_timestamps[cache_key] = datetime.utcnow()
                
                return patterns
            finally:
                await conn.close()
                
        except Exception as e:
            print(f"❌ Error getting patterns for domain {domain}: {e}")
            return []
    
    async def get_domain_extraction_stats(self, domain: str) -> Dict:
        """Get extraction statistics for a domain."""
        try:
            # Use asyncpg connection
            conn = await asyncpg.connect(settings.database_url)
            try:
                stats_query = """
                    SELECT 
                        COUNT(*) as total_attempts,
                        SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful_attempts,
                        AVG(CASE WHEN success THEN extraction_time_ms END) as avg_extraction_time,
                        AVG(CASE WHEN success THEN quality_score END) as avg_quality_score,
                        MAX(created_at) as last_attempt
                    FROM extraction_attempts
                    WHERE domain = $1
                        AND created_at > NOW() - INTERVAL '30 days'
                """
                
                stats = await conn.fetchrow(stats_query, domain)
                
                methods_query = """
                    SELECT 
                        extraction_strategy,
                        COUNT(*) as attempts,
                        SUM(CASE WHEN success THEN 1 ELSE 0 END) as successes,
                        AVG(CASE WHEN success THEN extraction_time_ms END) as avg_time
                    FROM extraction_attempts
                    WHERE domain = $1
                        AND created_at > NOW() - INTERVAL '7 days'
                    GROUP BY extraction_strategy
                    ORDER BY successes DESC
                """
                
                methods = await conn.fetch(methods_query, domain)
                
                return {
                    'domain': domain,
                    'total_attempts': stats['total_attempts'] or 0,
                    'successful_attempts': stats['successful_attempts'] or 0,
                    'success_rate': (
                        (stats['successful_attempts'] or 0) / max(1, stats['total_attempts'] or 1) * 100
                    ),
                    'avg_extraction_time_ms': float(stats['avg_extraction_time']) if stats['avg_extraction_time'] else 0,
                    'avg_quality_score': float(stats['avg_quality_score']) if stats['avg_quality_score'] else 0,
                    'last_attempt': stats['last_attempt'],
                    'methods': [
                        {
                            'strategy': method['extraction_strategy'],
                            'attempts': method['attempts'],
                            'successes': method['successes'],
                            'success_rate': method['successes'] / max(1, method['attempts']) * 100,
                            'avg_time_ms': float(method['avg_time']) if method['avg_time'] else 0
                        }
                        for method in methods
                    ]
                }
                
        except Exception as e:
            print(f"❌ Error getting domain stats for {domain}: {e}")
            return {
                'domain': domain,
                'total_attempts': 0,
                'successful_attempts': 0,
                'success_rate': 0,
                'methods': []
            }
    
    async def record_ai_pattern_discovery(
        self, domain: str, patterns: List[Dict], analysis_type: str = "selector_discovery"
    ) -> bool:
        """Record AI-discovered patterns."""
        try:
            # Use asyncpg connection
            conn = await asyncpg.connect(settings.database_url)
            try:
                # Record AI usage
                ai_query = """
                    INSERT INTO ai_usage_tracking (
                        domain, analysis_type, analysis_result, patterns_discovered
                    ) VALUES ($1, $2, $3, $4)
                """
                
                await conn.execute(
                    ai_query,
                    domain,
                    analysis_type,
                    json.dumps(patterns),
                    len(patterns)
                )
                
                # Add discovered patterns to extraction_patterns
                for pattern in patterns:
                    selector = pattern.get('selector')
                    strategy = pattern.get('strategy', 'ai_discovered')
                    
                    if selector:
                        pattern_query = """
                            INSERT INTO extraction_patterns (
                                domain, selector_pattern, extraction_strategy,
                                discovered_by
                            ) VALUES ($1, $2, $3, $4)
                            ON CONFLICT (domain, selector_pattern, extraction_strategy) 
                            DO NOTHING
                        """
                        
                        await conn.execute(
                            pattern_query,
                            domain,
                            selector,
                            strategy,
                            'ai'
                        )
                
                # asyncpg auto-commits
                
                # Invalidate cache
                cache_keys_to_remove = [key for key in self._domain_cache.keys() if key.startswith(domain)]
                for key in cache_keys_to_remove:
                    del self._domain_cache[key]
                    if key in self._cache_timestamps:
                        del self._cache_timestamps[key]
                
                return True
            finally:
                await conn.close()
                
        except Exception as e:
            print(f"❌ Error recording AI pattern discovery: {e}")
            return False
    
    async def get_domains_needing_ai_analysis(self, limit: int = 10) -> List[str]:
        """Get domains that need AI analysis."""
        try:
            # Use asyncpg connection
            conn = await asyncpg.connect(settings.database_url)
            try:
                query = """
                    SELECT DISTINCT ds.domain
                    FROM domain_stability ds
                    LEFT JOIN ai_usage_tracking aut ON ds.domain = aut.domain
                    WHERE (
                        ds.needs_reanalysis = true
                        OR ds.consecutive_failures >= 3
                        OR (ds.success_rate_7d < 50 AND ds.total_attempts >= 5)
                        OR aut.domain IS NULL
                    )
                    AND (
                        ds.last_ai_analysis IS NULL 
                        OR ds.last_ai_analysis < NOW() - INTERVAL '7 days'
                    )
                    ORDER BY ds.consecutive_failures DESC, ds.success_rate_7d ASC
                    LIMIT $1
                """
                
                rows = await conn.fetch(query, limit)
                return [row['domain'] for row in rows]
                
        except Exception as e:
            print(f"❌ Error getting domains needing AI analysis: {e}")
            return []
    
    async def get_extraction_efficiency_stats(self) -> Dict:
        """Get overall extraction efficiency statistics."""
        try:
            # Use asyncpg connection
            conn = await asyncpg.connect(settings.database_url)
            try:
                overall_query = """
                    SELECT 
                        COUNT(*) as total_attempts,
                        SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful_attempts,
                        COUNT(DISTINCT domain) as domains_processed,
                        AVG(CASE WHEN success THEN extraction_time_ms END) as avg_extraction_time
                    FROM extraction_attempts
                    WHERE created_at > NOW() - INTERVAL '7 days'
                """
                
                overall = await conn.fetchrow(overall_query)
                
                ai_query = """
                    SELECT 
                        COUNT(*) as ai_analyses,
                        SUM(patterns_discovered) as total_patterns_discovered,
                        SUM(patterns_successful) as total_patterns_successful,
                        AVG(cost_effectiveness) as avg_cost_effectiveness
                    FROM ai_usage_tracking
                    WHERE created_at > NOW() - INTERVAL '7 days'
                """
                
                ai_stats = await conn.fetchrow(ai_query)
                
                return {
                    'period': '7 days',
                    'total_attempts': overall['total_attempts'] or 0,
                    'successful_attempts': overall['successful_attempts'] or 0,
                    'success_rate': (
                        (overall['successful_attempts'] or 0) / 
                        max(1, overall['total_attempts'] or 1) * 100
                    ),
                    'domains_processed': overall['domains_processed'] or 0,
                    'avg_extraction_time_ms': float(overall['avg_extraction_time']) if overall['avg_extraction_time'] else 0,
                    'ai_analyses': ai_stats['ai_analyses'] or 0,
                    'patterns_discovered': ai_stats['total_patterns_discovered'] or 0,
                    'patterns_successful': ai_stats['total_patterns_successful'] or 0,
                    'ai_cost_effectiveness': float(ai_stats['avg_cost_effectiveness']) if ai_stats['avg_cost_effectiveness'] else 0
                }
                
        except Exception as e:
            print(f"❌ Error getting efficiency stats: {e}")
            return {}


# Global instance
_extraction_memory_service = None

async def get_extraction_memory() -> ExtractionMemoryService:
    """Get or create extraction memory service instance."""
    global _extraction_memory_service
    if _extraction_memory_service is None:
        _extraction_memory_service = ExtractionMemoryService()
    return _extraction_memory_service