-- Migration: Add search optimization indexes
-- Description: Add indexes for full-text search performance

-- Create indexes for search functionality
CREATE INDEX IF NOT EXISTS idx_articles_title_search ON articles USING GIN (to_tsvector('russian', title));
CREATE INDEX IF NOT EXISTS idx_articles_summary_search ON articles USING GIN (to_tsvector('russian', summary));
CREATE INDEX IF NOT EXISTS idx_articles_content_search ON articles USING GIN (to_tsvector('russian', content));

-- Create compound search index for combined search
CREATE INDEX IF NOT EXISTS idx_articles_full_text_search ON articles USING GIN (
    to_tsvector('russian', coalesce(title, '') || ' ' || coalesce(summary, '') || ' ' || coalesce(content, ''))
);

-- Create B-tree indexes for ILIKE searches (fallback for non-PostgreSQL)
CREATE INDEX IF NOT EXISTS idx_articles_title_ilike ON articles (lower(title) text_pattern_ops);
CREATE INDEX IF NOT EXISTS idx_articles_summary_ilike ON articles (lower(summary) text_pattern_ops);

-- Index for search with category filtering
CREATE INDEX IF NOT EXISTS idx_articles_search_category ON articles (published_at DESC, is_advertisement);

-- Add comment explaining the search optimization
COMMENT ON INDEX idx_articles_title_search IS 'Full-text search index for article titles (Russian language)';
COMMENT ON INDEX idx_articles_summary_search IS 'Full-text search index for article summaries (Russian language)';
COMMENT ON INDEX idx_articles_content_search IS 'Full-text search index for article content (Russian language)';
COMMENT ON INDEX idx_articles_full_text_search IS 'Combined full-text search index for all text fields';

