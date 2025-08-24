-- Migration: Add support for multiple categories per article
-- Date: 2025-08-24
-- Description: Create article_categories junction table and categories table

-- Create categories table to store all available categories
CREATE TABLE IF NOT EXISTS categories (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE,
    display_name VARCHAR(100) NOT NULL,
    description TEXT,
    color VARCHAR(7) DEFAULT '#6c757d', -- Hex color for UI
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create junction table for many-to-many relationship
CREATE TABLE IF NOT EXISTS article_categories (
    id SERIAL PRIMARY KEY,
    article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    confidence FLOAT DEFAULT 1.0, -- AI confidence for this categorization
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(article_id, category_id)
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_article_categories_article_id ON article_categories(article_id);
CREATE INDEX IF NOT EXISTS idx_article_categories_category_id ON article_categories(category_id);
CREATE INDEX IF NOT EXISTS idx_article_categories_confidence ON article_categories(confidence);

-- Insert default categories
INSERT INTO categories (name, display_name, description, color) VALUES
    ('Business', 'Бизнес', 'Экономика, финансы, компании, инвестиции', '#28a745'),
    ('Tech', 'Технологии', 'IT, софтвер, инновации, стартапы', '#007bff'),
    ('Science', 'Наука', 'Исследования, медицина, открытия', '#6f42c1'),
    ('Serbia', 'Сербия', 'Новости Сербии, политика, общество', '#dc3545'),
    ('Other', 'Прочее', 'Остальные новости', '#6c757d')
ON CONFLICT (name) DO NOTHING;

-- Migrate existing single categories to new system
-- This handles simple categories first, composite categories are handled by separate script
INSERT INTO article_categories (article_id, category_id, confidence)
SELECT 
    a.id as article_id,
    c.id as category_id,
    1.0 as confidence
FROM articles a
JOIN categories c ON c.name = a.category
WHERE a.category IS NOT NULL
  AND a.category NOT LIKE '%|%'  -- Skip composite categories
  AND a.category NOT LIKE '%/%'  -- Skip composite categories  
  AND a.category NOT LIKE '%,%'  -- Skip composite categories
  AND a.category NOT LIKE '% and %'  -- Skip composite categories
  AND a.category NOT LIKE '% & %'  -- Skip composite categories
ON CONFLICT (article_id, category_id) DO NOTHING;

-- Add comment to explain the migration
COMMENT ON TABLE article_categories IS 'Junction table for many-to-many relationship between articles and categories';
COMMENT ON COLUMN article_categories.confidence IS 'AI confidence score for this category assignment (0.0-1.0)';

-- Note: Composite categories (Business|Tech, Serbia/Business, etc.) should be migrated 
-- using the separate script: scripts/migrate_composite_categories.py
