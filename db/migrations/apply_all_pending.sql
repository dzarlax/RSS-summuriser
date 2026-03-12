-- ============================================================================
-- COMBINED MIGRATION SCRIPT FOR PRODUCTION
-- Run this to apply all pending migrations
-- Date: 2024-12-02
-- ============================================================================

-- ============================================================================
-- MIGRATION 001: Extraction learning tables
-- ============================================================================

-- 1. Extraction patterns
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
    discovered_by VARCHAR(20) DEFAULT 'manual',
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

CREATE INDEX IF NOT EXISTS idx_extraction_patterns_domain ON extraction_patterns(domain);
CREATE INDEX IF NOT EXISTS idx_extraction_patterns_success_rate ON extraction_patterns(success_rate DESC);
CREATE INDEX IF NOT EXISTS idx_extraction_patterns_stable ON extraction_patterns(is_stable);

-- 2. Domain stability
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

CREATE INDEX IF NOT EXISTS idx_domain_stability_domain ON domain_stability(domain);
CREATE INDEX IF NOT EXISTS idx_domain_stability_stable ON domain_stability(is_stable);

-- 3. Extraction attempts
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

CREATE INDEX IF NOT EXISTS idx_extraction_attempts_domain ON extraction_attempts(domain);
CREATE INDEX IF NOT EXISTS idx_extraction_attempts_success ON extraction_attempts(success);
CREATE INDEX IF NOT EXISTS idx_extraction_attempts_created_at ON extraction_attempts(created_at DESC);

-- 4. AI usage tracking
CREATE TABLE IF NOT EXISTS ai_usage_tracking (
    id SERIAL PRIMARY KEY,
    domain VARCHAR(255) NOT NULL,
    analysis_type VARCHAR(50) NOT NULL,
    tokens_used INTEGER,
    credits_cost DECIMAL(10,4),
    analysis_result JSONB,
    patterns_discovered INTEGER DEFAULT 0,
    patterns_successful INTEGER DEFAULT 0,
    cost_effectiveness DECIMAL(5,2),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ai_usage_domain ON ai_usage_tracking(domain);

-- ============================================================================
-- MIGRATION 004: Categories and mappings
-- ============================================================================

-- 1. Category mapping table
CREATE TABLE IF NOT EXISTS category_mapping (
    id SERIAL PRIMARY KEY,
    ai_category VARCHAR(100) NOT NULL UNIQUE,
    fixed_category VARCHAR(50) NOT NULL,
    confidence_threshold FLOAT DEFAULT 0.0,
    description TEXT,
    created_by VARCHAR(100) DEFAULT 'system',
    usage_count INTEGER DEFAULT 0,
    last_used TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_category_mapping_ai_category ON category_mapping(ai_category);
CREATE INDEX IF NOT EXISTS idx_category_mapping_fixed_category ON category_mapping(fixed_category);
CREATE INDEX IF NOT EXISTS idx_category_mapping_is_active ON category_mapping(is_active);

-- 2. Populate 7 fixed categories
INSERT INTO categories (name, display_name, color) VALUES
  ('Serbia', 'Сербия', '#dc3545'),
  ('Tech', 'Технологии', '#0d6efd'),
  ('Business', 'Бизнес', '#198754'),
  ('Science', 'Наука', '#6610f2'),
  ('Politics', 'Политика', '#fd7e14'),
  ('International', 'Международные', '#20c997'),
  ('Other', 'Прочее', '#6c757d')
ON CONFLICT (name) DO UPDATE SET
  display_name = EXCLUDED.display_name,
  color = EXCLUDED.color;

-- 3. Populate category mappings
INSERT INTO category_mapping (ai_category, fixed_category, description, created_by) VALUES
  -- Military/Defense -> Politics
  ('Military', 'Politics', 'Military news', 'system'),
  ('Defense', 'Politics', 'Defense news', 'system'),
  ('War', 'Politics', 'War news', 'system'),
  ('Armed Forces', 'Politics', 'Armed Forces', 'system'),
  -- International
  ('International Relations', 'International', 'International relations', 'system'),
  ('Foreign Affairs', 'International', 'Foreign affairs', 'system'),
  ('Diplomacy', 'International', 'Diplomacy', 'system'),
  ('World', 'International', 'World news', 'system'),
  ('Global', 'International', 'Global news', 'system'),
  ('Russia', 'International', 'Russia news', 'system'),
  ('Europe', 'International', 'Europe news', 'system'),
  ('USA', 'International', 'USA news', 'system'),
  ('China', 'International', 'China news', 'system'),
  -- Health -> Science
  ('Health', 'Science', 'Health news', 'system'),
  ('Medical', 'Science', 'Medical news', 'system'),
  ('Medicine', 'Science', 'Medicine news', 'system'),
  ('Healthcare', 'Science', 'Healthcare news', 'system'),
  ('Research', 'Science', 'Research news', 'system'),
  -- Tech
  ('Technology', 'Tech', 'Technology', 'system'),
  ('AI', 'Tech', 'AI news', 'system'),
  ('Artificial Intelligence', 'Tech', 'AI news', 'system'),
  ('Software', 'Tech', 'Software news', 'system'),
  ('Hardware', 'Tech', 'Hardware news', 'system'),
  ('Cybersecurity', 'Tech', 'Cybersecurity', 'system'),
  ('Internet', 'Tech', 'Internet news', 'system'),
  -- Business
  ('Economy', 'Business', 'Economy news', 'system'),
  ('Finance', 'Business', 'Finance news', 'system'),
  ('Markets', 'Business', 'Markets news', 'system'),
  ('Investment', 'Business', 'Investment news', 'system'),
  ('Banking', 'Business', 'Banking news', 'system'),
  ('Crypto', 'Business', 'Crypto news', 'system'),
  ('Cryptocurrency', 'Business', 'Cryptocurrency', 'system'),
  -- Politics
  ('Government', 'Politics', 'Government news', 'system'),
  ('Law', 'Politics', 'Law news', 'system'),
  ('Legal', 'Politics', 'Legal news', 'system'),
  ('Elections', 'Politics', 'Elections news', 'system'),
  ('Security', 'Politics', 'Security news', 'system'),
  ('Human Rights', 'Politics', 'Human Rights', 'system'),
  -- Science
  ('Environment', 'Science', 'Environment news', 'system'),
  ('Climate', 'Science', 'Climate news', 'system'),
  ('Nature', 'Science', 'Nature news', 'system'),
  ('Ecology', 'Science', 'Ecology news', 'system'),
  ('Space', 'Science', 'Space news', 'system'),
  -- Other
  ('Culture', 'Other', 'Culture news', 'system'),
  ('Lifestyle', 'Other', 'Lifestyle news', 'system'),
  ('Entertainment', 'Other', 'Entertainment', 'system'),
  ('Sports', 'Other', 'Sports news', 'system'),
  ('Society', 'Other', 'Society news', 'system'),
  ('Events', 'Other', 'Events news', 'system'),
  ('News', 'Other', 'General news', 'system')
ON CONFLICT (ai_category) DO UPDATE SET
  fixed_category = EXCLUDED.fixed_category,
  updated_at = NOW();

-- ============================================================================
-- VERIFICATION
-- ============================================================================
DO $$
BEGIN
    RAISE NOTICE '✅ Migration complete!';
    RAISE NOTICE 'Categories: %', (SELECT COUNT(*) FROM categories);
    RAISE NOTICE 'Mappings: %', (SELECT COUNT(*) FROM category_mapping);
END $$;
