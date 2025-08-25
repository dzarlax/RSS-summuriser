-- Migration: Add support for multiple media files
-- Description: Add media_files JSON column to articles table for storing multiple media files

-- Add media_files column to articles table
ALTER TABLE articles ADD COLUMN IF NOT EXISTS media_files JSON DEFAULT '[]';

-- Add comment to explain the structure
COMMENT ON COLUMN articles.media_files IS 'List of media files: [{"url": "...", "type": "image|video|document", "thumbnail": "..."}]';

-- Create index for media_files queries (optional, for performance)
-- CREATE INDEX IF NOT EXISTS idx_articles_media_files ON articles USING GIN (media_files);
