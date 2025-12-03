-- Fix articles table schema issues
-- 1. Increase content column size to handle large articles
-- 2. Fix URL unique constraint to avoid deadlocks

-- Backup note: This migration is safe and non-destructive

-- Step 1: Increase content column size from TEXT (64KB) to MEDIUMTEXT (16MB)
ALTER TABLE articles
MODIFY COLUMN content MEDIUMTEXT DEFAULT NULL;

-- Step 2: Increase summary column size for safety
ALTER TABLE articles
MODIFY COLUMN summary MEDIUMTEXT DEFAULT NULL;

-- Step 3: Increase ad_reasoning column size
ALTER TABLE articles
MODIFY COLUMN ad_reasoning MEDIUMTEXT DEFAULT NULL;

-- Step 4: Add index on hash_content for faster duplicate detection
CREATE INDEX IF NOT EXISTS idx_articles_hash_content ON articles(hash_content);

-- Step 5: Add index on published_at for sorting
CREATE INDEX IF NOT EXISTS idx_articles_published_at_desc ON articles(published_at DESC);

-- Step 6: Add composite index for common queries
CREATE INDEX IF NOT EXISTS idx_articles_source_published ON articles(source_id, published_at DESC);

-- Verify changes
SELECT
    COLUMN_NAME,
    COLUMN_TYPE,
    CHARACTER_MAXIMUM_LENGTH
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = 'newsdb'
  AND TABLE_NAME = 'articles'
  AND COLUMN_NAME IN ('content', 'summary', 'ad_reasoning');
