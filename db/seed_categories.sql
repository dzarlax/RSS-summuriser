-- Seed categories table with main categories
-- These are the fixed categories that news articles will be assigned to

-- Insert main categories
INSERT INTO categories (name, display_name, color, description)
VALUES
    ('Business', 'Бизнес', '#2E7D32', 'Business and economy news'),
    ('Tech', 'Технологии', '#1976D2', 'Technology and IT news'),
    ('Science', 'Наука', '#7B1FA2', 'Scientific research and discoveries'),
    ('Nature', 'Природа и экология', '#4CAF50', 'Nature, environment and climate'),
    ('Serbia', 'Сербия', '#C62828', 'News about Serbia and Balkans'),
    ('Marketing', 'Маркетинг', '#F57C00', 'Marketing and advertising'),
    ('Media', 'Медиа', '#5E35B1', 'Media industry and journalism'),
    ('Other', 'Другое', '#757575', 'Other news and uncategorized')
ON DUPLICATE KEY UPDATE
    display_name = VALUES(display_name),
    color = VALUES(color),
    description = VALUES(description);

-- Verify categories
SELECT id, name, display_name, color, description FROM categories ORDER BY name;
