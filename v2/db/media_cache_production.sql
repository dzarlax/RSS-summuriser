-- ================================================================
-- МЕДИА КЕШ ДЛЯ ПРОДАКШЕНА
-- Команды PostgreSQL для создания таблицы кеширования медиа файлов
-- ================================================================

-- Создание основной таблицы media_files_cache
CREATE TABLE IF NOT EXISTS media_files_cache (
    id SERIAL PRIMARY KEY,
    article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    
    -- Original media data
    original_url TEXT NOT NULL,
    media_type VARCHAR(20) NOT NULL,
    filename VARCHAR(255),
    mime_type VARCHAR(100),
    file_size INTEGER,
    
    -- Cached file paths (relative to media_cache_dir)
    cached_original_path VARCHAR(500),
    cached_thumbnail_path VARCHAR(500),
    cached_optimized_path VARCHAR(500),
    
    -- Media metadata
    width INTEGER,
    height INTEGER,
    duration REAL,
    
    -- Cache status and error tracking
    cache_status VARCHAR(20) DEFAULT 'pending' NOT NULL,
    cache_attempts INTEGER DEFAULT 0,
    last_cache_attempt TIMESTAMP,
    cache_error TEXT,
    
    -- Usage tracking for LRU cleanup
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- ================================================================
-- ИНДЕКСЫ ДЛЯ ПРОИЗВОДИТЕЛЬНОСТИ
-- ================================================================

-- Основные индексы
CREATE INDEX IF NOT EXISTS idx_media_files_cache_article_id ON media_files_cache(article_id);
CREATE INDEX IF NOT EXISTS idx_media_files_cache_original_url ON media_files_cache(original_url);
CREATE INDEX IF NOT EXISTS idx_media_files_cache_media_type ON media_files_cache(media_type);
CREATE INDEX IF NOT EXISTS idx_media_files_cache_status ON media_files_cache(cache_status);

-- Индексы для времени (для LRU очистки и статистики)
CREATE INDEX IF NOT EXISTS idx_media_files_cache_created_at ON media_files_cache(created_at);
CREATE INDEX IF NOT EXISTS idx_media_files_cache_accessed_at ON media_files_cache(accessed_at);

-- Составной индекс для быстрого поиска по URL + статусу
CREATE INDEX IF NOT EXISTS idx_media_files_cache_url_status ON media_files_cache(original_url, cache_status);

-- ================================================================
-- КОММЕНТАРИИ ДЛЯ ДОКУМЕНТАЦИИ
-- ================================================================

COMMENT ON TABLE media_files_cache IS 'Cache table for media files with optimized versions';
COMMENT ON COLUMN media_files_cache.cache_status IS 'Status: pending, processing, cached, failed';
COMMENT ON COLUMN media_files_cache.media_type IS 'Type: image, video, document';
COMMENT ON COLUMN media_files_cache.cached_original_path IS 'Path relative to media_cache_dir';
COMMENT ON COLUMN media_files_cache.accessed_at IS 'Last access time for LRU cleanup';

-- ================================================================
-- ПРОВЕРКА СОЗДАНИЯ
-- ================================================================

-- Проверить созданную таблицу
SELECT 
    table_name, 
    column_name, 
    data_type, 
    is_nullable,
    column_default
FROM information_schema.columns 
WHERE table_name = 'media_files_cache' 
ORDER BY ordinal_position;

-- Проверить индексы
SELECT 
    indexname, 
    indexdef 
FROM pg_indexes 
WHERE tablename = 'media_files_cache';

-- ================================================================
-- ДОПОЛНИТЕЛЬНЫЕ КОМАНДЫ ДЛЯ МОНИТОРИНГА
-- ================================================================

-- Посмотреть размер таблицы
SELECT pg_size_pretty(pg_total_relation_size('media_files_cache')) as table_size;

-- Статистика по типам медиа
SELECT 
    media_type, 
    cache_status, 
    COUNT(*) as count,
    AVG(file_size) as avg_size,
    MIN(created_at) as first_cached,
    MAX(accessed_at) as last_accessed
FROM media_files_cache 
GROUP BY media_type, cache_status
ORDER BY media_type, cache_status;

-- ================================================================
-- КОМАНДЫ ДЛЯ ОЧИСТКИ (НЕ ВЫПОЛНЯТЬ АВТОМАТИЧЕСКИ!)
-- ================================================================

/*
-- Удалить старые неиспользуемые записи (старше 30 дней, не обращались)
DELETE FROM media_files_cache 
WHERE accessed_at < CURRENT_TIMESTAMP - INTERVAL '30 days'
AND cache_status = 'cached';

-- Удалить failed записи старше 7 дней  
DELETE FROM media_files_cache 
WHERE created_at < CURRENT_TIMESTAMP - INTERVAL '7 days'
AND cache_status = 'failed';

-- Полная очистка таблицы (ОСТОРОЖНО!)
-- TRUNCATE TABLE media_files_cache;
*/