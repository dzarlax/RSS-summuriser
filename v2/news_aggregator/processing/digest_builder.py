"""Digest builder for creating combined daily news digests."""

import datetime
from typing import List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..models import DailySummary


class DigestBuilder:
    """Handles building daily news digests from category summaries."""
    
    def __init__(self):
        self.telegram_limit = 3600  # Safe limit considering Telegraph button overhead (~200 chars)
    
    async def create_combined_digest(self, db: AsyncSession, date: datetime.date) -> str:
        """Create digest by combining ready category summaries (no AI needed)."""
        try:
            # Get all category summaries for today
            result = await db.execute(
                select(DailySummary).where(DailySummary.date == date)
                .order_by(DailySummary.articles_count.desc())  # Order by importance
            )
            summaries = result.scalars().all()
            
            if not summaries:
                return "Сводки новостей пока не готовы."
            
            # Calculate total articles
            total_articles = sum(s.articles_count for s in summaries)
            categories_count = len(summaries)
            
            # Build header
            header = f"<b>Сводка новостей за {date.strftime('%d.%m.%Y')}</b>"
            digest_parts = [header, ""]
            
            # Add category summaries  
            for summary in summaries:
                category_block = f"<b>{summary.category}</b>\n{summary.summary_text.strip()}\n"
                digest_parts.append(category_block)
            
            # Add footer with stats
            footer = f"\n📊 Всего: {total_articles} новостей в {categories_count} категориях"
            digest_parts.append(footer)
            
            combined_digest = "\n".join(digest_parts)
            
            # Check length and return single message or flag for splitting
            if len(combined_digest) <= self.telegram_limit:
                return combined_digest  # Single message
            else:
                # Return special marker indicating splitting needed
                print(f"  📄 Digest too long ({len(combined_digest)} chars), needs splitting by categories")
                return "SPLIT_NEEDED"
                
        except Exception as e:
            print(f"  ❌ Error creating combined digest: {e}")
            return f"<b>Сводка новостей за {date.strftime('%d.%m.%Y')}</b>\n\nОшибка при создании сводки."
    
    def split_digest_into_parts(self, header: str, summaries, footer: str, 
                               total_articles: int, categories_count: int) -> List[str]:
        """Split digest into multiple parts that fit Telegram limits."""
        try:
            parts = []
            
            # Split summaries into groups that fit telegram limit
            current_part_categories = []
            current_part_length = len(header) + 2  # header + empty line
            
            for i, summary in enumerate(summaries):
                category_block = f"<b>{summary.category}</b>\n{summary.summary_text.strip()}\n\n"
                
                # Check if adding this category would exceed limit
                estimated_footer = f"\n📊 Часть {len(parts)+1} • {len(current_part_categories)+1} категорий"
                
                if current_part_length + len(category_block) + len(estimated_footer) + 50 <= self.telegram_limit:
                    # Fits in current part
                    current_part_categories.append(summary)
                    current_part_length += len(category_block)
                else:
                    # Start new part
                    if current_part_categories:
                        # Save current part
                        parts.append(self._build_digest_part(
                            header, current_part_categories, total_articles, 
                            categories_count, len(parts) + 1, 
                            is_final=False
                        ))
                        
                        # Start new part
                        current_part_categories = [summary]
                        current_part_length = len(header) + 2 + len(category_block)
                    else:
                        # Single category too long - include anyway
                        current_part_categories = [summary]
                        current_part_length = len(header) + 2 + len(category_block)
            
            # Add final part
            if current_part_categories:
                parts.append(self._build_digest_part(
                    header, current_part_categories, total_articles,
                    categories_count, len(parts) + 1,
                    is_final=True, footer=footer
                ))
            
            print(f"  📄 Split digest into {len(parts)} parts")
            return parts
            
        except Exception as e:
            print(f"  ❌ Error splitting digest: {e}")
            # Fallback to single part with truncation
            fallback = header + "\n\n" + summaries[0].summary_text[:3000] + "...\n" + footer
            return [fallback]
    
    def _build_digest_part(self, header: str, categories, total_articles: int, 
                          total_categories: int, part_number: int, 
                          is_final: bool = False, footer: str = "") -> str:
        """Build a single digest part."""
        part_content = [header, ""]
        
        # Add categories
        for summary in categories:
            category_block = f"<b>{summary.category}</b>\n{summary.summary_text.strip()}\n"
            part_content.append(category_block)
        
        # Add appropriate footer
        if is_final:
            part_content.append(footer)
        else:
            part_footer = f"\n📊 Часть {part_number} • {len(categories)} из {total_categories} категорий"
            part_content.append(part_footer) 
            part_content.append("\n💬 Продолжение следует...")
        
        return "\n".join(part_content)
    
    async def generate_and_save_daily_summaries(self, db: AsyncSession, date: datetime.date, categories: Dict[str, List]):
        """Generate and save daily summaries by category."""
        from ..services.ai_client import get_ai_client
        
        ai_client = get_ai_client()
        
        for category, articles in categories.items():
            if not articles:
                continue
            
            print(f"  📝 Generating summary for {category} category ({len(articles)} articles)...")
            
            # Prepare article content for AI
            articles_text = []
            for article in articles[:10]:  # Limit to 10 most recent articles
                article_text = f"Заголовок: {article.title}\nСодержание: {(article.summary or article.content or '')[:500]}"
                articles_text.append(article_text)
            
            combined_content = "\n\n---\n\n".join(articles_text)
            
            try:
                # Generate category summary using AI
                summary_prompt = f"""Создай краткую сводку новостей для категории "{category}" на русском языке.
                
Статьи:
{combined_content}

Требования:
- Максимум 3-4 предложения
- Сосредоточься на главных событиях
- Используй деловой стиль
- Начинай с "В сфере {category.lower()}..."
- Не повторяй одну и ту же информацию
Requirements:
- End with a complete sentence
- Do not cut words
- Avoid trailing ellipsis"""
                
                summary_text = await ai_client._call_summary_llm(summary_prompt, max_tokens=1500)
                if summary_text:
                    summary_text = ai_client._clean_summary_text(summary_text)
                
                # Save or update daily summary
                existing_result = await db.execute(
                    select(DailySummary).where(
                        DailySummary.date == date,
                        DailySummary.category == category
                    )
                )
                existing_summary = existing_result.scalar_one_or_none()
                
                if existing_summary:
                    # Update existing
                    existing_summary.summary_text = summary_text
                    existing_summary.articles_count = len(articles)
                    print(f"  ✅ Updated summary for {category}")
                else:
                    # Create new
                    new_summary = DailySummary(
                        date=date,
                        category=category,
                        summary_text=summary_text,
                        articles_count=len(articles)
                    )
                    db.add(new_summary)
                    print(f"  ✅ Created summary for {category}")
                    
            except Exception as e:
                print(f"  ❌ Error generating summary for {category}: {e}")
                # Create fallback summary
                fallback_text = f"В сфере {category.lower()} произошли важные события. Обработано {len(articles)} новостей."
                
                existing_result = await db.execute(
                    select(DailySummary).where(
                        DailySummary.date == date,
                        DailySummary.category == category
                    )
                )
                existing_summary = existing_result.scalar_one_or_none()
                
                if not existing_summary:
                    fallback_summary = DailySummary(
                        date=date,
                        category=category,
                        summary_text=fallback_text,
                        articles_count=len(articles)
                    )
                    db.add(fallback_summary)
        
        await db.commit()
        print(f"  ✅ Daily summaries saved for {date}")
