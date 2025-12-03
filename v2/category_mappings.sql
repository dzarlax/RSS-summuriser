-- Category Mappings for newsdb (production)
-- Map AI-generated categories to fixed categories

-- Clear existing mappings (optional - comment out if you want to keep existing)
-- DELETE FROM category_mapping;

-- Insert category mappings
INSERT INTO category_mapping (ai_category, fixed_category, confidence_threshold, description, created_by, is_active)
VALUES
    -- Business mappings
    ('business', 'Business', 0.7, 'Business and economy news', 'admin', true),
    ('economy', 'Business', 0.7, 'Economic news and analysis', 'admin', true),
    ('finance', 'Business', 0.7, 'Financial news and markets', 'admin', true),
    ('corporate', 'Business', 0.7, 'Corporate news and updates', 'admin', true),
    ('бизнес', 'Business', 0.7, 'Бизнес новости', 'admin', true),
    ('экономика', 'Business', 0.7, 'Экономические новости', 'admin', true),

    -- Tech mappings
    ('technology', 'Tech', 0.7, 'Technology news and updates', 'admin', true),
    ('tech', 'Tech', 0.7, 'Tech industry news', 'admin', true),
    ('software', 'Tech', 0.7, 'Software development and tools', 'admin', true),
    ('hardware', 'Tech', 0.7, 'Hardware and devices', 'admin', true),
    ('ai', 'Tech', 0.7, 'Artificial intelligence news', 'admin', true),
    ('технологии', 'Tech', 0.7, 'Технологические новости', 'admin', true),
    ('it', 'Tech', 0.7, 'IT новости', 'admin', true),

    -- Science mappings
    ('science', 'Science', 0.7, 'Scientific research and discoveries', 'admin', true),
    ('research', 'Science', 0.7, 'Research news and papers', 'admin', true),
    ('medicine', 'Science', 0.7, 'Medical research and health', 'admin', true),
    ('health', 'Science', 0.7, 'Health and wellness news', 'admin', true),
    ('наука', 'Science', 0.7, 'Научные новости', 'admin', true),
    ('исследования', 'Science', 0.7, 'Исследовательские новости', 'admin', true),

    -- Nature mappings
    ('nature', 'Nature', 0.7, 'Nature and wildlife news', 'admin', true),
    ('environment', 'Nature', 0.7, 'Environmental news and climate', 'admin', true),
    ('climate', 'Nature', 0.7, 'Climate change and weather', 'admin', true),
    ('ecology', 'Nature', 0.7, 'Ecological news and conservation', 'admin', true),
    ('природа', 'Nature', 0.7, 'Новости о природе', 'admin', true),
    ('экология', 'Nature', 0.7, 'Экологические новости', 'admin', true),

    -- Serbia mappings
    ('serbia', 'Serbia', 0.7, 'News about Serbia', 'admin', true),
    ('serbian', 'Serbia', 0.7, 'Serbian news and culture', 'admin', true),
    ('belgrade', 'Serbia', 0.7, 'News from Belgrade', 'admin', true),
    ('сербия', 'Serbia', 0.7, 'Новости о Сербии', 'admin', true),
    ('балканы', 'Serbia', 0.7, 'Балканские новости', 'admin', true),

    -- Marketing mappings
    ('marketing', 'Marketing', 0.7, 'Marketing and advertising news', 'admin', true),
    ('advertising', 'Marketing', 0.7, 'Advertising industry news', 'admin', true),
    ('branding', 'Marketing', 0.7, 'Brand management and strategy', 'admin', true),
    ('digital_marketing', 'Marketing', 0.7, 'Digital marketing trends', 'admin', true),
    ('маркетинг', 'Marketing', 0.7, 'Маркетинговые новости', 'admin', true),
    ('реклама', 'Marketing', 0.7, 'Рекламные новости', 'admin', true),

    -- Media mappings
    ('media', 'Media', 0.7, 'Media industry news', 'admin', true),
    ('journalism', 'Media', 0.7, 'Journalism and news industry', 'admin', true),
    ('entertainment', 'Media', 0.7, 'Entertainment news', 'admin', true),
    ('publishing', 'Media', 0.7, 'Publishing industry news', 'admin', true),
    ('медиа', 'Media', 0.7, 'Медиа новости', 'admin', true),
    ('журналистика', 'Media', 0.7, 'Новости журналистики', 'admin', true)
ON DUPLICATE KEY UPDATE
    fixed_category = VALUES(fixed_category),
    confidence_threshold = VALUES(confidence_threshold),
    description = VALUES(description),
    is_active = VALUES(is_active),
    updated_at = CURRENT_TIMESTAMP;

-- Verify mappings
SELECT COUNT(*) as total_mappings FROM category_mapping;
SELECT fixed_category, COUNT(*) as count FROM category_mapping GROUP BY fixed_category;
