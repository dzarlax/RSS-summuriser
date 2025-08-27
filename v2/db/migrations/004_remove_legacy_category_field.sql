-- Remove legacy category field from articles table
-- All category data is now stored in the categories/article_categories tables

-- Drop the legacy category column from articles table
ALTER TABLE articles DROP COLUMN IF EXISTS category;

-- Add a comment to the table explaining the change
COMMENT ON TABLE articles IS 'Articles table - categories now stored in article_categories relationship';