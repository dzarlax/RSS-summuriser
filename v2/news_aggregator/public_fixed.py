@router.get("/api/public/article/{article_id}")
async def get_public_article(article_id: int, db: AsyncSession = Depends(get_db)):
    """Get full article content for modal display."""
    try:
        # Handle mock data case
        if article_id == 1:
            return {
                "id": 1,
                "title": "⚠️ База данных недоступна", 
                "summary": "Показываем тестовые данные. Проверьте подключение к БД.",
                "content": "К сожалению, база данных недоступна. Это тестовая статья.",
                "url": "https://example.com/db-error",
                "image_url": None,
                "source_name": "Система",
                "category": "other",
                "categories": [],
                "published_at": datetime.utcnow().isoformat(),
                "is_advertisement": False,
                "ai_categories": []
            }
        
        # Simple query without complex joins
        query = select(Article).options(
            selectinload(Article.source),
            selectinload(Article.article_categories).selectinload(ArticleCategory.category)
        ).where(Article.id == article_id)
        
        result = await db.execute(query)
        article = result.scalar_one_or_none()
        
        if not article:
            raise HTTPException(status_code=404, detail="Article not found")
        
        # Convert using unified function
        return await article_to_dict(article, include_full_content=True)
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error fetching article {article_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")