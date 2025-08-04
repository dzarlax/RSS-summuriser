-- Migration: Add tables for AI-enhanced extraction learning system
-- Version: 001
-- Date: 2025-01-01
-- Author: AI Assistant  
-- Description: Tables for tracking extraction patterns, domain stability, and AI usage

-- 1. Extraction patterns - stores learned extraction patterns with success metrics
CREATE TABLE IF NOT EXISTS extraction_patterns (
    id SERIAL PRIMARY KEY,
    domain VARCHAR(255) NOT NULL,
    selector_pattern TEXT NOT NULL,
    extraction_strategy VARCHAR(50) NOT NULL,
    success_count INTEGER DEFAULT 0,
    failure_count INTEGER DEFAULT 0,
    success_rate DECIMAL(5,2) GENERATED ALWAYS AS (
        CASE WHEN (success_count + failure_count) > 0 
        THEN (success_count::decimal / (success_count + failure_count)) * 100
        ELSE 0 END
    ) STORED,
    quality_score_avg DECIMAL(5,2) DEFAULT 0,
    content_length_avg INTEGER DEFAULT 0,
    discovered_by VARCHAR(20) DEFAULT 'manual', -- 'manual', 'ai', 'heuristic'
    is_stable BOOLEAN DEFAULT FALSE,
    last_ai_analysis TIMESTAMP,
    consecutive_successes INTEGER DEFAULT 0,
    consecutive_failures INTEGER DEFAULT 0,
    first_success_at TIMESTAMP,
    last_success_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    
    UNIQUE(domain, selector_pattern, extraction_strategy)
);

-- Indexes for extraction_patterns
CREATE INDEX idx_extraction_patterns_domain ON extraction_patterns(domain);
CREATE INDEX idx_extraction_patterns_success_rate ON extraction_patterns(success_rate DESC);
CREATE INDEX idx_extraction_patterns_stable ON extraction_patterns(is_stable);
CREATE INDEX idx_extraction_patterns_strategy ON extraction_patterns(extraction_strategy);
CREATE INDEX idx_extraction_patterns_discovered_by ON extraction_patterns(discovered_by);

-- 2. Domain stability - tracks domain extraction stability to optimize AI credit usage
CREATE TABLE IF NOT EXISTS domain_stability (
    id SERIAL PRIMARY KEY,
    domain VARCHAR(255) UNIQUE NOT NULL,
    is_stable BOOLEAN DEFAULT FALSE,
    success_rate_7d DECIMAL(5,2) DEFAULT 0,
    success_rate_30d DECIMAL(5,2) DEFAULT 0,
    total_attempts INTEGER DEFAULT 0,
    successful_attempts INTEGER DEFAULT 0,
    last_successful_extraction TIMESTAMP,
    last_failed_extraction TIMESTAMP,
    last_ai_analysis TIMESTAMP,
    consecutive_successes INTEGER DEFAULT 0,
    consecutive_failures INTEGER DEFAULT 0,
    stability_achieved_at TIMESTAMP,
    needs_reanalysis BOOLEAN DEFAULT FALSE,
    ai_credits_saved INTEGER DEFAULT 0,
    reanalysis_triggers JSONB DEFAULT '[]',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for domain_stability  
CREATE INDEX idx_domain_stability_domain ON domain_stability(domain);
CREATE INDEX idx_domain_stability_stable ON domain_stability(is_stable);
CREATE INDEX idx_domain_stability_needs_reanalysis ON domain_stability(needs_reanalysis);
CREATE INDEX idx_domain_stability_success_rate_7d ON domain_stability(success_rate_7d DESC);
CREATE INDEX idx_domain_stability_consecutive_failures ON domain_stability(consecutive_failures DESC);

-- 3. Extraction attempts - detailed log of all extraction attempts for analytics
CREATE TABLE IF NOT EXISTS extraction_attempts (
    id SERIAL PRIMARY KEY,
    article_url TEXT NOT NULL,
    domain VARCHAR(255) NOT NULL,
    extraction_strategy VARCHAR(50) NOT NULL,
    selector_used TEXT,
    success BOOLEAN NOT NULL,
    content_length INTEGER,
    quality_score DECIMAL(5,2),
    extraction_time_ms INTEGER,
    error_message TEXT,
    ai_analysis_triggered BOOLEAN DEFAULT FALSE,
    ai_analysis JSONB,
    user_agent VARCHAR(500),
    http_status_code INTEGER,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for extraction_attempts
CREATE INDEX idx_extraction_attempts_domain ON extraction_attempts(domain);
CREATE INDEX idx_extraction_attempts_success ON extraction_attempts(success);
CREATE INDEX idx_extraction_attempts_created_at ON extraction_attempts(created_at DESC);
CREATE INDEX idx_extraction_attempts_strategy ON extraction_attempts(extraction_strategy);
CREATE INDEX idx_extraction_attempts_domain_success ON extraction_attempts(domain, success);
CREATE INDEX idx_extraction_attempts_ai_triggered ON extraction_attempts(ai_analysis_triggered);

-- 4. AI usage tracking - tracks AI API usage, costs and effectiveness
CREATE TABLE IF NOT EXISTS ai_usage_tracking (
    id SERIAL PRIMARY KEY,
    domain VARCHAR(255) NOT NULL,
    analysis_type VARCHAR(50) NOT NULL, -- 'selector_discovery', 'pattern_analysis', 'dom_structure'
    tokens_used INTEGER,
    credits_cost DECIMAL(10,4),
    analysis_result JSONB,
    patterns_discovered INTEGER DEFAULT 0,
    patterns_successful INTEGER DEFAULT 0,
    cost_effectiveness DECIMAL(5,2), -- successful patterns / cost ratio
    created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for ai_usage_tracking
CREATE INDEX idx_ai_usage_domain ON ai_usage_tracking(domain);
CREATE INDEX idx_ai_usage_created_at ON ai_usage_tracking(created_at DESC);
CREATE INDEX idx_ai_usage_analysis_type ON ai_usage_tracking(analysis_type);
CREATE INDEX idx_ai_usage_cost_effectiveness ON ai_usage_tracking(cost_effectiveness DESC);

-- Create useful views for analytics and monitoring
CREATE OR REPLACE VIEW domain_extraction_stats AS
SELECT 
    ds.domain,
    ds.is_stable,
    ds.success_rate_7d,
    ds.success_rate_30d,
    ds.consecutive_successes,
    ds.consecutive_failures,
    ds.last_successful_extraction,
    ds.last_ai_analysis,
    ds.ai_credits_saved,
    COUNT(ep.id) as learned_patterns_count,
    COALESCE(AVG(ep.success_rate), 0) as avg_pattern_success_rate,
    MAX(ep.last_success_at) as last_pattern_success
FROM domain_stability ds
LEFT JOIN extraction_patterns ep ON ds.domain = ep.domain
GROUP BY ds.id, ds.domain, ds.is_stable, ds.success_rate_7d, ds.success_rate_30d, 
         ds.consecutive_successes, ds.consecutive_failures, ds.last_successful_extraction,
         ds.last_ai_analysis, ds.ai_credits_saved;

-- View for recent extraction performance (last 7 days)
CREATE OR REPLACE VIEW recent_extraction_performance AS
SELECT 
    domain,
    extraction_strategy,
    COUNT(*) as total_attempts,
    COUNT(CASE WHEN success THEN 1 END) as successful_attempts,
    ROUND(COUNT(CASE WHEN success THEN 1 END)::decimal / COUNT(*) * 100, 2) as success_rate,
    ROUND(AVG(extraction_time_ms)) as avg_extraction_time_ms,
    ROUND(AVG(quality_score), 2) as avg_quality_score,
    COUNT(CASE WHEN ai_analysis_triggered THEN 1 END) as ai_analyses_triggered
FROM extraction_attempts 
WHERE created_at >= NOW() - INTERVAL '7 days'
GROUP BY domain, extraction_strategy
ORDER BY success_rate DESC, total_attempts DESC;

-- View for AI usage analytics
CREATE OR REPLACE VIEW ai_usage_analytics AS
SELECT 
    domain,
    analysis_type,
    COUNT(*) as total_analyses,
    SUM(tokens_used) as total_tokens,
    SUM(credits_cost) as total_cost,
    SUM(patterns_discovered) as total_patterns_discovered,
    SUM(patterns_successful) as total_patterns_successful,
    ROUND(AVG(cost_effectiveness), 2) as avg_cost_effectiveness,
    MAX(created_at) as last_analysis
FROM ai_usage_tracking
GROUP BY domain, analysis_type
ORDER BY total_cost DESC;

-- View for extraction patterns effectiveness
CREATE OR REPLACE VIEW extraction_patterns_effectiveness AS
SELECT 
    domain,
    extraction_strategy,
    discovered_by,
    COUNT(*) as patterns_count,
    ROUND(AVG(success_rate), 2) as avg_success_rate,
    SUM(success_count) as total_successes,
    SUM(failure_count) as total_failures,
    COUNT(CASE WHEN is_stable THEN 1 END) as stable_patterns_count
FROM extraction_patterns
GROUP BY domain, extraction_strategy, discovered_by
ORDER BY avg_success_rate DESC, total_successes DESC;

-- Add triggers for updated_at fields (reusing existing function)
CREATE TRIGGER update_extraction_patterns_updated_at 
    BEFORE UPDATE ON extraction_patterns 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_domain_stability_updated_at 
    BEFORE UPDATE ON domain_stability 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Insert some initial test data for popular Russian news domains
INSERT INTO extraction_patterns (domain, selector_pattern, extraction_strategy, success_count, failure_count, discovered_by)
VALUES 
    ('habr.com', '.post__text', 'css_selector', 15, 2, 'manual'),
    ('habr.com', '.tm-article-body', 'css_selector', 12, 1, 'manual'),
    ('lenta.ru', '.b-text', 'css_selector', 12, 3, 'manual'),
    ('lenta.ru', '.topic-body__content', 'css_selector', 8, 2, 'manual'),
    ('ria.ru', '.article__text', 'css_selector', 18, 1, 'manual'),
    ('ria.ru', '.article-body', 'css_selector', 14, 2, 'manual'),
    ('tass.ru', '.text-block', 'css_selector', 20, 0, 'manual'),
    ('tass.ru', '.formatted-text', 'css_selector', 16, 1, 'manual'),
    ('rbc.ru', '.article__text', 'css_selector', 14, 4, 'manual'),
    ('rbc.ru', '.article-text', 'css_selector', 10, 3, 'manual'),
    ('interfax.ru', '.text', 'css_selector', 11, 2, 'manual'),
    ('rt.com', '.article__text', 'css_selector', 13, 3, 'manual'),
    ('gazeta.ru', '.b-material-text__text', 'css_selector', 9, 4, 'manual')
ON CONFLICT (domain, selector_pattern, extraction_strategy) DO NOTHING;

-- Insert initial domain stability data
INSERT INTO domain_stability (domain, is_stable, success_rate_7d, success_rate_30d, total_attempts, successful_attempts)
VALUES 
    ('habr.com', true, 88.24, 85.67, 17, 15),
    ('lenta.ru', true, 80.00, 78.95, 15, 12),
    ('ria.ru', true, 94.74, 92.31, 19, 18),
    ('tass.ru', true, 100.00, 95.45, 20, 20),
    ('rbc.ru', false, 77.78, 75.00, 18, 14),
    ('interfax.ru', true, 84.62, 81.25, 13, 11),
    ('rt.com', false, 81.25, 79.31, 16, 13),
    ('gazeta.ru', false, 69.23, 70.00, 13, 9)
ON CONFLICT (domain) DO NOTHING;

-- Add table comments for documentation
COMMENT ON TABLE extraction_patterns IS 'Хранит изученные паттерны извлечения с метриками успешности';
COMMENT ON TABLE domain_stability IS 'Отслеживает стабильность извлечения по доменам для оптимизации AI кредитов';
COMMENT ON TABLE extraction_attempts IS 'Детальный лог всех попыток извлечения контента';
COMMENT ON TABLE ai_usage_tracking IS 'Отслеживает использование AI API и эффективность затрат';

-- Add column comments for important fields
COMMENT ON COLUMN extraction_patterns.success_rate IS 'Вычисляемый процент успешности паттерна';
COMMENT ON COLUMN extraction_patterns.discovered_by IS 'Источник обнаружения: manual, ai, heuristic';
COMMENT ON COLUMN domain_stability.ai_credits_saved IS 'Количество сэкономленных AI кредитов';
COMMENT ON COLUMN domain_stability.reanalysis_triggers IS 'JSON массив причин для переанализа';
COMMENT ON COLUMN ai_usage_tracking.cost_effectiveness IS 'Отношение успешных паттернов к стоимости';

-- Success message
DO $$
BEGIN
    RAISE NOTICE '✅ Migration 001: Extraction learning tables created successfully';
    RAISE NOTICE '📊 Created tables: extraction_patterns, domain_stability, extraction_attempts, ai_usage_tracking';
    RAISE NOTICE '📈 Created views: domain_extraction_stats, recent_extraction_performance, ai_usage_analytics, extraction_patterns_effectiveness';
    RAISE NOTICE '🎯 Inserted test data for % domains', (SELECT COUNT(DISTINCT domain) FROM extraction_patterns);
END $$;