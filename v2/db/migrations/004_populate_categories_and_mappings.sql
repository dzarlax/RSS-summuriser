-- Migration: 004_populate_categories_and_mappings
-- Description: Populate categories table and create category_mapping table with default mappings
-- Date: 2024-12-02

-- ============================================================================
-- 1. Create category_mapping table if not exists
-- ============================================================================
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

-- ============================================================================
-- 2. Populate 7 fixed categories
-- ============================================================================
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

-- ============================================================================
-- 3. Populate category mappings (AI category -> Fixed category)
-- ============================================================================

-- Military/Defense -> Politics
INSERT INTO category_mapping (ai_category, fixed_category, description, created_by) VALUES
  ('Military', 'Politics', 'Military news maps to Politics', 'system'),
  ('Defense', 'Politics', 'Defense news maps to Politics', 'system'),
  ('War', 'Politics', 'War news maps to Politics', 'system'),
  ('Armed Forces', 'Politics', 'Armed Forces maps to Politics', 'system')
ON CONFLICT (ai_category) DO UPDATE SET
  fixed_category = EXCLUDED.fixed_category,
  description = EXCLUDED.description,
  updated_at = NOW();

-- International Relations -> International
INSERT INTO category_mapping (ai_category, fixed_category, description, created_by) VALUES
  ('International Relations', 'International', 'International relations maps to International', 'system'),
  ('Foreign Affairs', 'International', 'Foreign affairs maps to International', 'system'),
  ('Diplomacy', 'International', 'Diplomacy maps to International', 'system'),
  ('World', 'International', 'World news maps to International', 'system'),
  ('Global', 'International', 'Global news maps to International', 'system'),
  ('Russia', 'International', 'Russia news maps to International', 'system'),
  ('Europe', 'International', 'Europe news maps to International', 'system'),
  ('USA', 'International', 'USA news maps to International', 'system'),
  ('China', 'International', 'China news maps to International', 'system')
ON CONFLICT (ai_category) DO UPDATE SET
  fixed_category = EXCLUDED.fixed_category,
  description = EXCLUDED.description,
  updated_at = NOW();

-- Health/Medical -> Science
INSERT INTO category_mapping (ai_category, fixed_category, description, created_by) VALUES
  ('Health', 'Science', 'Health news maps to Science', 'system'),
  ('Medical', 'Science', 'Medical news maps to Science', 'system'),
  ('Medicine', 'Science', 'Medicine news maps to Science', 'system'),
  ('Healthcare', 'Science', 'Healthcare news maps to Science', 'system'),
  ('Research', 'Science', 'Research news maps to Science', 'system')
ON CONFLICT (ai_category) DO UPDATE SET
  fixed_category = EXCLUDED.fixed_category,
  description = EXCLUDED.description,
  updated_at = NOW();

-- Technology -> Tech
INSERT INTO category_mapping (ai_category, fixed_category, description, created_by) VALUES
  ('Technology', 'Tech', 'Technology maps to Tech', 'system'),
  ('AI', 'Tech', 'AI news maps to Tech', 'system'),
  ('Artificial Intelligence', 'Tech', 'AI news maps to Tech', 'system'),
  ('Software', 'Tech', 'Software news maps to Tech', 'system'),
  ('Hardware', 'Tech', 'Hardware news maps to Tech', 'system'),
  ('Cybersecurity', 'Tech', 'Cybersecurity maps to Tech', 'system'),
  ('Internet', 'Tech', 'Internet news maps to Tech', 'system')
ON CONFLICT (ai_category) DO UPDATE SET
  fixed_category = EXCLUDED.fixed_category,
  description = EXCLUDED.description,
  updated_at = NOW();

-- Economy/Finance -> Business
INSERT INTO category_mapping (ai_category, fixed_category, description, created_by) VALUES
  ('Economy', 'Business', 'Economy news maps to Business', 'system'),
  ('Finance', 'Business', 'Finance news maps to Business', 'system'),
  ('Markets', 'Business', 'Markets news maps to Business', 'system'),
  ('Investment', 'Business', 'Investment news maps to Business', 'system'),
  ('Banking', 'Business', 'Banking news maps to Business', 'system'),
  ('Crypto', 'Business', 'Crypto news maps to Business', 'system'),
  ('Cryptocurrency', 'Business', 'Cryptocurrency news maps to Business', 'system')
ON CONFLICT (ai_category) DO UPDATE SET
  fixed_category = EXCLUDED.fixed_category,
  description = EXCLUDED.description,
  updated_at = NOW();

-- Government/Law -> Politics
INSERT INTO category_mapping (ai_category, fixed_category, description, created_by) VALUES
  ('Government', 'Politics', 'Government news maps to Politics', 'system'),
  ('Law', 'Politics', 'Law news maps to Politics', 'system'),
  ('Legal', 'Politics', 'Legal news maps to Politics', 'system'),
  ('Elections', 'Politics', 'Elections news maps to Politics', 'system'),
  ('Security', 'Politics', 'Security news maps to Politics', 'system'),
  ('Human Rights', 'Politics', 'Human Rights maps to Politics', 'system')
ON CONFLICT (ai_category) DO UPDATE SET
  fixed_category = EXCLUDED.fixed_category,
  description = EXCLUDED.description,
  updated_at = NOW();

-- Environment -> Science
INSERT INTO category_mapping (ai_category, fixed_category, description, created_by) VALUES
  ('Environment', 'Science', 'Environment news maps to Science', 'system'),
  ('Climate', 'Science', 'Climate news maps to Science', 'system'),
  ('Nature', 'Science', 'Nature news maps to Science', 'system'),
  ('Ecology', 'Science', 'Ecology news maps to Science', 'system'),
  ('Space', 'Science', 'Space news maps to Science', 'system')
ON CONFLICT (ai_category) DO UPDATE SET
  fixed_category = EXCLUDED.fixed_category,
  description = EXCLUDED.description,
  updated_at = NOW();

-- Lifestyle/Culture -> Other
INSERT INTO category_mapping (ai_category, fixed_category, description, created_by) VALUES
  ('Culture', 'Other', 'Culture news maps to Other', 'system'),
  ('Lifestyle', 'Other', 'Lifestyle news maps to Other', 'system'),
  ('Entertainment', 'Other', 'Entertainment news maps to Other', 'system'),
  ('Sports', 'Other', 'Sports news maps to Other', 'system'),
  ('Society', 'Other', 'Society news maps to Other', 'system'),
  ('Events', 'Other', 'Events news maps to Other', 'system'),
  ('News', 'Other', 'General news maps to Other', 'system')
ON CONFLICT (ai_category) DO UPDATE SET
  fixed_category = EXCLUDED.fixed_category,
  description = EXCLUDED.description,
  updated_at = NOW();

-- ============================================================================
-- 4. Verification queries (optional - for manual check)
-- ============================================================================
-- SELECT COUNT(*) as categories_count FROM categories;
-- SELECT COUNT(*) as mappings_count FROM category_mapping;
-- SELECT fixed_category, COUNT(*) as count FROM category_mapping GROUP BY fixed_category ORDER BY count DESC;
